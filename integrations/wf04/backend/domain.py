from __future__ import annotations

import hashlib
import json
import re
import secrets
import sqlite3
import threading
import uuid
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from backend.data.error_cards import variant_practice_for
except ModuleNotFoundError:
    from data.error_cards import variant_practice_for


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12].upper()}"


class StudentModelCache:
    """SQLite-backed student model cache with event-based refresh tracking."""

    REFRESH_INTERVAL = 5

    def __init__(self, database_path: Path):
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=15)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._lock, closing(self._connect()) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS student_model (
                    student_id TEXT PRIMARY KEY,
                    model_json TEXT NOT NULL,
                    strategy_json TEXT NOT NULL,
                    generated_at TEXT NOT NULL,
                    event_count INTEGER NOT NULL DEFAULT 0,
                    profile_event_count INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(student_model)").fetchall()
            }
            if "profile_event_count" not in columns:
                connection.execute(
                    "ALTER TABLE student_model ADD COLUMN profile_event_count INTEGER NOT NULL DEFAULT 0"
                )
            connection.commit()

    def _ensure_row(self, connection: sqlite3.Connection, student_id: str) -> None:
        connection.execute(
            """
            INSERT OR IGNORE INTO student_model(
                student_id, model_json, strategy_json, generated_at,
                event_count, profile_event_count
            ) VALUES (?, '{}', '{}', '', 0, 0)
            """,
            (student_id,),
        )

    @staticmethod
    def _decode_object(value: Any) -> dict[str, Any]:
        try:
            decoded = json.loads(str(value))
        except (TypeError, json.JSONDecodeError):
            return {}
        return decoded if isinstance(decoded, dict) else {}

    def get_model(self, student_id: str) -> dict[str, Any] | None:
        with self._lock, closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT model_json, strategy_json, generated_at,
                       event_count, profile_event_count
                FROM student_model WHERE student_id = ?
                """,
                (student_id,),
            ).fetchone()
        if not row or not str(row["generated_at"]):
            return None
        model = self._decode_object(row["model_json"])
        if not model:
            return None
        return {
            "student_model": model,
            "strategy_defaults": self._decode_object(row["strategy_json"]),
            "generated_at": str(row["generated_at"]),
            "based_on_event_count": int(row["profile_event_count"] or 0),
            "event_count": int(row["event_count"] or 0),
        }

    def event_count(self, student_id: str) -> int:
        with self._lock, closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT event_count FROM student_model WHERE student_id = ?",
                (student_id,),
            ).fetchone()
        return int(row["event_count"] or 0) if row else 0

    def increment_event(self, student_id: str) -> int:
        with self._lock, closing(self._connect()) as connection:
            self._ensure_row(connection, student_id)
            connection.execute(
                "UPDATE student_model SET event_count = event_count + 1 WHERE student_id = ?",
                (student_id,),
            )
            row = connection.execute(
                "SELECT event_count FROM student_model WHERE student_id = ?",
                (student_id,),
            ).fetchone()
            connection.commit()
        return int(row["event_count"] or 0) if row else 0

    def save_model(
        self,
        student_id: str,
        model: dict[str, Any],
        strategy: dict[str, Any],
        based_on_event_count: int | None = None,
    ) -> None:
        now = utc_now()
        with self._lock, closing(self._connect()) as connection:
            self._ensure_row(connection, student_id)
            row = connection.execute(
                "SELECT event_count FROM student_model WHERE student_id = ?",
                (student_id,),
            ).fetchone()
            current_count = int(row["event_count"] or 0) if row else 0
            profile_count = (
                current_count
                if based_on_event_count is None
                else max(0, min(int(based_on_event_count), current_count))
            )
            connection.execute(
                """
                UPDATE student_model SET
                    model_json = ?, strategy_json = ?, generated_at = ?,
                    profile_event_count = ?
                WHERE student_id = ?
                """,
                (json_text(model), json_text(strategy), now, profile_count, student_id),
            )
            connection.commit()

    def should_refresh(self, student_id: str) -> bool:
        status = self.status(student_id)
        return bool(status["needs_refresh"])

    def status(self, student_id: str) -> dict[str, Any]:
        with self._lock, closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT model_json, generated_at, event_count, profile_event_count
                FROM student_model WHERE student_id = ?
                """,
                (student_id,),
            ).fetchone()
        if not row:
            return {
                "has_profile": False,
                "generated_at": "",
                "event_count": 0,
                "events_since_profile": 0,
                "needs_refresh": True,
            }
        has_profile = bool(str(row["generated_at"])) and bool(
            self._decode_object(row["model_json"])
        )
        event_count = int(row["event_count"] or 0)
        profile_count = int(row["profile_event_count"] or 0)
        events_since_profile = max(0, event_count - profile_count)
        return {
            "has_profile": has_profile,
            "generated_at": str(row["generated_at"]),
            "event_count": event_count,
            "events_since_profile": events_since_profile,
            "needs_refresh": not has_profile or events_since_profile >= self.REFRESH_INTERVAL,
        }


class LearningDomainStore:
    DEFAULT_SETTINGS = {
        "preferred_delivery_mode": "text",
        "explanation_depth": "guided",
        "reduced_motion": False,
        "auto_play_video": False,
    }

    def __init__(self, database_path: Path):
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._lock, closing(self._connect()) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS student_profiles (
                    student_id TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    program_name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS training_cycles (
                    training_cycle_id TEXT PRIMARY KEY,
                    student_id TEXT NOT NULL,
                    goal_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_cycles_student
                    ON training_cycles(student_id, updated_at DESC);
                CREATE TABLE IF NOT EXISTS learning_tasks (
                    learning_task_id TEXT PRIMARY KEY,
                    training_cycle_id TEXT NOT NULL,
                    knowledge_point_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    sequence_number INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_task_cycle_knowledge
                    ON learning_tasks(training_cycle_id, knowledge_point_id);
                CREATE TABLE IF NOT EXISTS task_instances (
                    task_instance_id TEXT PRIMARY KEY,
                    learning_task_id TEXT NOT NULL,
                    student_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_task_instances_student
                    ON task_instances(student_id, updated_at DESC);
                CREATE TABLE IF NOT EXISTS question_instances (
                    question_instance_id TEXT PRIMARY KEY,
                    student_id TEXT NOT NULL,
                    task_instance_id TEXT NOT NULL,
                    source_question_id TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    knowledge_point_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    answer_schema_json TEXT NOT NULL,
                    expected_answer TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_questions_student
                    ON question_instances(student_id, updated_at DESC);
                CREATE TABLE IF NOT EXISTS attempts (
                    attempt_id TEXT PRIMARY KEY,
                    question_instance_id TEXT NOT NULL,
                    student_id TEXT NOT NULL,
                    answer_text TEXT NOT NULL,
                    evaluation_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_attempts_student
                    ON attempts(student_id, created_at DESC);
                CREATE TABLE IF NOT EXISTS wrongbook_events (
                    event_id TEXT PRIMARY KEY, student_id TEXT NOT NULL,
                    project_id TEXT NOT NULL, root_question_instance_id TEXT NOT NULL,
                    event_json TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS wrongbook_items (
                    student_id TEXT NOT NULL, project_id TEXT NOT NULL,
                    root_question_instance_id TEXT NOT NULL, knowledge_point_id TEXT NOT NULL,
                    status TEXT NOT NULL, last_error_json TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL,
                    PRIMARY KEY(student_id, project_id, root_question_instance_id)
                );
                CREATE TABLE IF NOT EXISTS explanation_sessions (
                    explanation_session_id TEXT PRIMARY KEY,
                    student_id TEXT NOT NULL,
                    task_instance_id TEXT NOT NULL,
                    question_instance_id TEXT NOT NULL,
                    attempt_id TEXT NOT NULL,
                    scene TEXT NOT NULL,
                    explanation_type TEXT NOT NULL,
                    explanation_mode TEXT NOT NULL,
                    delivery_mode TEXT NOT NULL,
                    source_explanation_session_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_explanations_student
                    ON explanation_sessions(student_id, created_at DESC);
                CREATE TABLE IF NOT EXISTS explanation_turns (
                    explanation_turn_id TEXT PRIMARY KEY,
                    explanation_session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS source_references (
                    source_reference_id TEXT PRIMARY KEY,
                    explanation_session_id TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    locator TEXT NOT NULL,
                    quote_text TEXT NOT NULL,
                    url TEXT NOT NULL,
                    verification_state TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_sources_explanation
                    ON source_references(explanation_session_id, created_at);
                CREATE TABLE IF NOT EXISTS resume_tokens (
                    token_hash TEXT PRIMARY KEY,
                    student_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    context_json TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    used_at TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS student_settings (
                    student_id TEXT PRIMARY KEY,
                    settings_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS student_favorites (
                    student_id TEXT NOT NULL,
                    knowledge_point_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(student_id, knowledge_point_id)
                );
                CREATE TABLE IF NOT EXISTS notifications (
                    notification_id TEXT PRIMARY KEY,
                    student_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    message TEXT NOT NULL,
                    read_at TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_notifications_student
                    ON notifications(student_id, created_at DESC);
                CREATE TABLE IF NOT EXISTS knowledge_entries (
                    rowid INTEGER PRIMARY KEY AUTOINCREMENT,
                    entry_id TEXT NOT NULL UNIQUE,
                    knowledge_point_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    category TEXT NOT NULL,
                    content TEXT NOT NULL,
                    source TEXT NOT NULL,
                    source_type TEXT NOT NULL DEFAULT 'document',
                    document_id TEXT NOT NULL DEFAULT '',
                    locator TEXT NOT NULL DEFAULT '',
                    safety INTEGER NOT NULL DEFAULT 0,
                    job_role TEXT NOT NULL DEFAULT '',
                    action TEXT NOT NULL DEFAULT '',
                    keywords TEXT NOT NULL DEFAULT '',
                    published_at TEXT NOT NULL DEFAULT '',
                    fetched_at TEXT NOT NULL DEFAULT '',
                    authority TEXT NOT NULL DEFAULT '',
                    valid_year TEXT NOT NULL DEFAULT '',
                    region TEXT NOT NULL DEFAULT '',
                    content_hash TEXT NOT NULL DEFAULT '',
                    review_status TEXT NOT NULL DEFAULT 'approved',
                    reviewed_at TEXT NOT NULL DEFAULT '',
                    reviewed_by TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_knowledge_point
                    ON knowledge_entries(knowledge_point_id, category);
                CREATE TABLE IF NOT EXISTS source_documents (
                    document_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_url TEXT NOT NULL DEFAULT '',
                    published_at TEXT NOT NULL DEFAULT '',
                    fetched_at TEXT NOT NULL DEFAULT '',
                    authority TEXT NOT NULL DEFAULT '',
                    valid_year TEXT NOT NULL DEFAULT '',
                    region TEXT NOT NULL DEFAULT '',
                    content_hash TEXT NOT NULL DEFAULT '',
                    review_status TEXT NOT NULL DEFAULT 'pending'
                        CHECK(review_status IN ('pending', 'approved', 'rejected', 'needs_update')),
                    reviewed_at TEXT NOT NULL DEFAULT '',
                    reviewed_by TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_source_documents_review
                    ON source_documents(review_status, updated_at DESC);
                CREATE TABLE IF NOT EXISTS knowledge_candidates (
                    candidate_id TEXT PRIMARY KEY,
                    knowledge_point_id TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL,
                    category TEXT NOT NULL,
                    content TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    locator TEXT NOT NULL DEFAULT '',
                    content_hash TEXT NOT NULL DEFAULT '',
                    ai_generated INTEGER NOT NULL DEFAULT 0
                        CHECK(ai_generated IN (0, 1)),
                    review_status TEXT NOT NULL DEFAULT 'pending'
                        CHECK(review_status IN ('pending', 'approved', 'rejected', 'needs_update')),
                    review_note TEXT NOT NULL DEFAULT '',
                    reviewed_at TEXT NOT NULL DEFAULT '',
                    reviewed_by TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(document_id) REFERENCES source_documents(document_id)
                );
                CREATE INDEX IF NOT EXISTS idx_knowledge_candidates_review
                    ON knowledge_candidates(review_status, updated_at DESC);
                CREATE TABLE IF NOT EXISTS generated_questions (
                    question_id TEXT PRIMARY KEY,
                    knowledge_point_id TEXT NOT NULL,
                    knowledge_point_name TEXT NOT NULL,
                    difficulty INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    options_json TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    question_type TEXT NOT NULL DEFAULT 'choice',
                    accepted_answers_json TEXT NOT NULL DEFAULT '[]',
                    grading_mode TEXT NOT NULL DEFAULT '',
                    explanation TEXT NOT NULL,
                    source TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_generated_questions_kp
                    ON generated_questions(knowledge_point_id, created_at DESC);
                """
            )
            resume_token_columns = {
                str(row["name"])
                for row in connection.execute(
                    "PRAGMA table_info(resume_tokens)"
                ).fetchall()
            }
            if "student_id" not in resume_token_columns:
                connection.execute(
                    "ALTER TABLE resume_tokens "
                    "ADD COLUMN student_id TEXT NOT NULL DEFAULT ''"
                )
            if "session_id" not in resume_token_columns:
                connection.execute(
                    "ALTER TABLE resume_tokens "
                    "ADD COLUMN session_id TEXT NOT NULL DEFAULT ''"
                )
            knowledge_columns = {
                str(row["name"])
                for row in connection.execute(
                    "PRAGMA table_info(knowledge_entries)"
                ).fetchall()
            }
            knowledge_migrations = {
                "published_at": "TEXT NOT NULL DEFAULT ''",
                "fetched_at": "TEXT NOT NULL DEFAULT ''",
                "authority": "TEXT NOT NULL DEFAULT ''",
                "valid_year": "TEXT NOT NULL DEFAULT ''",
                "region": "TEXT NOT NULL DEFAULT ''",
                "content_hash": "TEXT NOT NULL DEFAULT ''",
                "review_status": "TEXT NOT NULL DEFAULT 'approved'",
                "reviewed_at": "TEXT NOT NULL DEFAULT ''",
                "reviewed_by": "TEXT NOT NULL DEFAULT ''",
            }
            for column_name, column_definition in knowledge_migrations.items():
                if column_name not in knowledge_columns:
                    connection.execute(
                        f"ALTER TABLE knowledge_entries ADD COLUMN {column_name} "
                        f"{column_definition}"
                    )
            generated_question_columns = {
                str(row["name"])
                for row in connection.execute(
                    "PRAGMA table_info(generated_questions)"
                ).fetchall()
            }
            generated_question_migrations = {
                "question_type": "TEXT NOT NULL DEFAULT 'choice'",
                "accepted_answers_json": "TEXT NOT NULL DEFAULT '[]'",
                "grading_mode": "TEXT NOT NULL DEFAULT ''",
            }
            for column_name, column_definition in generated_question_migrations.items():
                if column_name not in generated_question_columns:
                    connection.execute(
                        f"ALTER TABLE generated_questions ADD COLUMN {column_name} "
                        f"{column_definition}"
                    )
            question_columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(question_instances)").fetchall()
            }
            question_migrations = {
                "source_question_instance_id": "TEXT NOT NULL DEFAULT ''",
                "root_question_instance_id": "TEXT NOT NULL DEFAULT ''",
                "question_spec_json": "TEXT NOT NULL DEFAULT ''",
                "question_template_id": "TEXT NOT NULL DEFAULT ''",
                "question_role": "TEXT NOT NULL DEFAULT ''",
                "assessment_mode": "TEXT NOT NULL DEFAULT ''",
                "generation_request_id": "TEXT NOT NULL DEFAULT ''",
                "generation_provider": "TEXT NOT NULL DEFAULT ''",
                "project_id": "TEXT NOT NULL DEFAULT ''",
            }
            for column_name, column_definition in question_migrations.items():
                if column_name not in question_columns:
                    connection.execute(
                        f"ALTER TABLE question_instances ADD COLUMN {column_name} {column_definition}"
                    )
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_questions_generation_request "
                "ON question_instances(student_id, generation_request_id) "
                "WHERE generation_request_id <> ''"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_knowledge_review_status "
                "ON knowledge_entries(review_status, knowledge_point_id)"
            )
            self._initialize_knowledge(connection)
            self._publish_approved_knowledge_candidates(connection)
            connection.commit()

    def ensure_profile(self, student_id: str) -> dict[str, Any]:
        now = utc_now()
        with self._lock, closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO student_profiles(
                    student_id, display_name, program_name, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (student_id, "林同学", "Java 面向对象程序设计实训", now, now),
            )
            row = connection.execute(
                "SELECT * FROM student_profiles WHERE student_id = ?", (student_id,)
            ).fetchone()
            connection.commit()
        return dict(row) if row else {}

    def ingest_context(self, payload: dict[str, Any]) -> dict[str, str]:
        student_id = str(payload.get("student_id", "")).strip()
        session_id = str(payload.get("session_id", "")).strip()
        if not student_id or not session_id:
            return {}
        self.ensure_profile(student_id)
        goal = as_dict(payload.get("learning_goal"))
        goal_id = str(goal.get("goal_id") or "GOAL-CURRENT")
        title = str(goal.get("goal_name") or "当前学习目标")
        now = utc_now()
        with self._lock, closing(self._connect()) as connection:
            cycle_id = str(payload.get("training_cycle_id", "")).strip()
            if not cycle_id:
                row = connection.execute(
                    """
                    SELECT training_cycle_id FROM training_cycles
                    WHERE student_id = ? AND goal_id = ? AND status = 'active'
                    ORDER BY updated_at DESC LIMIT 1
                    """,
                    (student_id, goal_id),
                ).fetchone()
                cycle_id = str(row[0]) if row else new_id("CYCLE")
            connection.execute(
                """
                INSERT INTO training_cycles(
                    training_cycle_id, student_id, goal_id, title, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'active', ?, ?)
                ON CONFLICT(training_cycle_id) DO UPDATE SET
                    title = excluded.title,
                    updated_at = excluded.updated_at
                """,
                (cycle_id, student_id, goal_id, title, now, now),
            )

            diagnostic = as_dict(payload.get("diagnostic_result"))
            weak_points = [item for item in as_list(diagnostic.get("weak_points")) if isinstance(item, dict)]
            current = as_dict(payload.get("current_knowledge_point"))
            if current and not any(
                str(item.get("knowledge_point_id", "")) == str(current.get("knowledge_point_id", ""))
                for item in weak_points
            ):
                weak_points.append(current)
            if not weak_points:
                weak_points = [{
                    "knowledge_point_id": "KN_CURRENT",
                    "knowledge_point_name": "当前知识点",
                    "recommended_order": 1,
                }]

            current_id = str(current.get("knowledge_point_id") or weak_points[0].get("knowledge_point_id") or "KN_CURRENT")
            task_id = ""
            for index, item in enumerate(weak_points, start=1):
                knowledge_id = str(item.get("knowledge_point_id") or f"KN-{index}")
                existing = connection.execute(
                    """
                    SELECT learning_task_id FROM learning_tasks
                    WHERE training_cycle_id = ? AND knowledge_point_id = ?
                    """,
                    (cycle_id, knowledge_id),
                ).fetchone()
                item_task_id = str(existing[0]) if existing else new_id("TASK")
                status = "current" if knowledge_id == current_id else (
                    "completed" if int(item.get("mastery", 0) or 0) >= 80 else "pending"
                )
                connection.execute(
                    """
                    INSERT INTO learning_tasks(
                        learning_task_id, training_cycle_id, knowledge_point_id, title,
                        sequence_number, status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(learning_task_id) DO UPDATE SET
                        title = excluded.title,
                        sequence_number = excluded.sequence_number,
                        status = excluded.status,
                        updated_at = excluded.updated_at
                    """,
                    (
                        item_task_id,
                        cycle_id,
                        knowledge_id,
                        str(item.get("knowledge_point_name") or knowledge_id),
                        int(item.get("recommended_order", index) or index),
                        status,
                        now,
                        now,
                    ),
                )
                if knowledge_id == current_id:
                    task_id = item_task_id
            if not task_id:
                row = connection.execute(
                    """
                    SELECT learning_task_id FROM learning_tasks
                    WHERE training_cycle_id = ? ORDER BY sequence_number LIMIT 1
                    """,
                    (cycle_id,),
                ).fetchone()
                task_id = str(row[0])

            task_instance_id = str(payload.get("task_instance_id", "")).strip()
            if not task_instance_id:
                row = connection.execute(
                    """
                    SELECT task_instance_id FROM task_instances
                    WHERE student_id = ? AND session_id = ? AND learning_task_id = ?
                    ORDER BY updated_at DESC LIMIT 1
                    """,
                    (student_id, session_id, task_id),
                ).fetchone()
                task_instance_id = str(row[0]) if row else new_id("TASKINST")
            connection.execute(
                """
                INSERT INTO task_instances(
                    task_instance_id, learning_task_id, student_id, session_id,
                    status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'active', ?, ?)
                ON CONFLICT(task_instance_id) DO UPDATE SET updated_at = excluded.updated_at
                """,
                (task_instance_id, task_id, student_id, session_id, now, now),
            )

            question = as_dict(payload.get("question_snapshot"))
            question_instance_id = str(payload.get("question_instance_id", "")).strip()
            source_question_id = str(question.get("question_id", "")).strip()
            if source_question_id and not question_instance_id:
                row = connection.execute(
                    """
                    SELECT question_instance_id FROM question_instances
                    WHERE student_id = ? AND source_question_id = ? AND mode = 'assessment'
                    ORDER BY updated_at DESC LIMIT 1
                    """,
                    (student_id, source_question_id),
                ).fetchone()
                question_instance_id = str(row[0]) if row else new_id("QUESTION")
            if source_question_id:
                prompt = str(question.get("question_text") or "待补充题目描述")
                connection.execute(
                    """
                    INSERT INTO question_instances(
                        question_instance_id, student_id, task_instance_id, source_question_id,
                        mode, knowledge_point_id, title, prompt, answer_schema_json,
                        expected_answer, status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, 'assessment', ?, ?, ?, ?, '', 'reviewed', ?, ?)
                    ON CONFLICT(question_instance_id) DO UPDATE SET
                        prompt = excluded.prompt,
                        updated_at = excluded.updated_at
                    """,
                    (
                        question_instance_id,
                        student_id,
                        task_instance_id,
                        source_question_id,
                        current_id,
                        str(current.get("knowledge_point_name") or "测验题目"),
                        prompt,
                        json_text({"type": "text", "label": "作答"}),
                        now,
                        now,
                    ),
                )

            attempt_id = str(payload.get("attempt_id", "")).strip()
            attempt = as_dict(payload.get("current_attempt"))
            if question_instance_id and attempt_id and attempt:
                evaluation = as_dict(payload.get("validated_evaluation"))
                connection.execute(
                    """
                    INSERT OR IGNORE INTO attempts(
                        attempt_id, question_instance_id, student_id, answer_text,
                        evaluation_json, status, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        attempt_id,
                        question_instance_id,
                        student_id,
                        str(attempt.get("student_answer", "")),
                        json_text(evaluation),
                        str(evaluation.get("evaluation_status") or "submitted"),
                        now,
                    ),
                )
            connection.commit()
        return {
            "training_cycle_id": cycle_id,
            "learning_task_id": task_id,
            "task_instance_id": task_instance_id,
            "question_instance_id": question_instance_id,
            "attempt_id": str(payload.get("attempt_id", "")),
        }

    def create_resume_token(
        self,
        context: dict[str, Any],
        student_id: str,
        session_id: str,
        ttl_minutes: int = 15,
    ) -> str:
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        now = datetime.now(timezone.utc)
        with self._lock, closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO resume_tokens(
                    token_hash, student_id, session_id, context_json,
                    expires_at, used_at, created_at
                ) VALUES (?, ?, ?, ?, ?, '', ?)
                """,
                (
                    token_hash,
                    student_id,
                    session_id,
                    json_text(context),
                    (now + timedelta(minutes=ttl_minutes)).isoformat(timespec="seconds"),
                    now.isoformat(timespec="seconds"),
                ),
            )
            connection.commit()
        return "resume." + token

    def consume_resume_token(
        self, token: str, student_id: str, session_id: str
    ) -> dict[str, Any]:
        if not token.startswith("resume."):
            return {}
        raw_token = token[7:]
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        now = datetime.now(timezone.utc)
        with self._lock, closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT context_json, expires_at, used_at FROM resume_tokens
                WHERE token_hash = ? AND student_id = ? AND session_id = ?
                """,
                (token_hash, student_id, session_id),
            ).fetchone()
            if not row or row["used_at"]:
                return {}
            try:
                expires_at = datetime.fromisoformat(str(row["expires_at"]))
            except ValueError:
                return {}
            if expires_at <= now:
                return {}
            cursor = connection.execute(
                """
                UPDATE resume_tokens SET used_at = ?
                WHERE token_hash = ? AND student_id = ? AND session_id = ? AND used_at = ''
                """,
                (
                    now.isoformat(timespec="seconds"),
                    token_hash,
                    student_id,
                    session_id,
                ),
            )
            connection.commit()
            if cursor.rowcount <= 0:
                return {}
        try:
            parsed = json.loads(str(row["context_json"]))
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def record_explanation(
        self,
        student_id: str,
        scene: str,
        context: dict[str, Any],
        result: dict[str, Any],
    ) -> dict[str, Any]:
        session_id = str(result.get("explanation_session_id") or new_id("EXPLAIN"))
        strategy = as_dict(result.get("teaching_strategy")) or as_dict(result.get("teaching_plan"))
        explanation_type = str(
            result.get("explanation_type")
            or strategy.get("strategy_code")
            or ("concept_guidance" if scene == "learn" else "evidence_contrast")
        )
        explanation_mode = str(result.get("explanation_mode") or explanation_type)
        delivery_mode = str(
            result.get("delivery_mode")
            or strategy.get("delivery_mode")
            or strategy.get("primary_mode")
            or "interactive_document"
        )
        identifiers = {
            "task_instance_id": str(context.get("task_instance_id", "")),
            "question_instance_id": str(context.get("question_instance_id", "")),
            "attempt_id": str(context.get("attempt_id", "")),
        }
        references = self._build_source_references(session_id, result)
        enriched = {
            **result,
            **identifiers,
            "explanation_session_id": session_id,
            "scene": scene,
            "explanation_type": explanation_type,
            "explanation_mode": explanation_mode,
            "delivery_mode": delivery_mode,
            "source_references": references,
        }
        now = utc_now()
        with self._lock, closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO explanation_sessions(
                    explanation_session_id, student_id, task_instance_id,
                    question_instance_id, attempt_id, scene, explanation_type,
                    explanation_mode, delivery_mode, source_explanation_session_id,
                    status, result_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    student_id,
                    identifiers["task_instance_id"],
                    identifiers["question_instance_id"],
                    identifiers["attempt_id"],
                    scene,
                    explanation_type,
                    explanation_mode,
                    delivery_mode,
                    str(context.get("source_explanation_session_id", "")),
                    str(result.get("status", "unknown")),
                    json_text(enriched),
                    now,
                ),
            )
            connection.execute(
                """
                INSERT OR REPLACE INTO explanation_turns(
                    explanation_turn_id, explanation_session_id, role, content_json, created_at
                ) VALUES (?, ?, 'assistant', ?, ?)
                """,
                (new_id("TURN"), session_id, json_text(enriched), now),
            )
            connection.execute(
                "DELETE FROM source_references WHERE explanation_session_id = ?", (session_id,)
            )
            for reference in references:
                connection.execute(
                    """
                    INSERT INTO source_references(
                        source_reference_id, explanation_session_id, source_type,
                        title, document_id, locator, quote_text, url,
                        verification_state, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        reference["source_reference_id"],
                        session_id,
                        reference["source_type"],
                        reference["title"],
                        reference["document_id"],
                        reference["locator"],
                        reference["quote_text"],
                        reference["url"],
                        reference["verification_state"],
                        now,
                    ),
                )
            connection.commit()
        return enriched

    def _build_source_references(
        self, explanation_session_id: str, result: dict[str, Any]
    ) -> list[dict[str, str]]:
        candidates: list[dict[str, str]] = []
        for source in as_list(result.get("sources")):
            if isinstance(source, dict):
                candidates.append({
                    "source_type": str(source.get("type") or "document"),
                    "title": str(source.get("title") or source.get("source") or "课程资料"),
                    "document_id": str(source.get("document_id") or ""),
                    "locator": str(source.get("locator") or source.get("page") or ""),
                    "quote_text": str(source.get("quote") or ""),
                    "url": str(source.get("url") or ""),
                    "verification_state": str(source.get("verification_state") or "provided"),
                })
            elif str(source).strip():
                candidates.append({
                    "source_type": "document",
                    "title": str(source).strip(),
                    "document_id": "",
                    "locator": "",
                    "quote_text": "",
                    "url": "",
                    "verification_state": "provided",
                })
        for block in as_list(result.get("content_blocks")):
            if isinstance(block, dict) and str(block.get("source", "")).strip():
                candidates.append({
                    "source_type": "document",
                    "title": str(block["source"]).strip(),
                    "document_id": "",
                    "locator": str(block.get("locator") or ""),
                    "quote_text": str(block.get("content") or "")[:280],
                    "url": "",
                    "verification_state": "provided",
                })
        for resource in as_list(result.get("resources")):
            if isinstance(resource, dict):
                candidates.append({
                    "source_type": str(resource.get("type") or "resource"),
                    "title": str(resource.get("title") or resource.get("source") or "学习资源"),
                    "document_id": str(resource.get("document_id") or ""),
                    "locator": str(resource.get("segment") or ""),
                    "quote_text": str(resource.get("reason") or resource.get("description") or "")[:280],
                    "url": str(resource.get("url") or ""),
                    "verification_state": "verified" if resource.get("url") else "provided",
                })
        target = as_dict(result.get("target_error"))
        if target:
            candidates.append({
                "source_type": "diagnosis",
                "title": f"错误诊断 {target.get('error_id') or '上游测验'}",
                "document_id": str(target.get("error_id") or ""),
                "locator": str(target.get("knowledge_point_id") or ""),
                "quote_text": str(target.get("diagnosis") or target.get("student_evidence") or "")[:280],
                "url": "",
                "verification_state": "validated",
            })
        unique: list[dict[str, str]] = []
        seen: set[tuple[str, str, str]] = set()
        for candidate in candidates:
            key = (candidate["title"], candidate["locator"], candidate["url"])
            if key in seen:
                continue
            seen.add(key)
            unique.append({
                "source_reference_id": new_id("SOURCE"),
                "explanation_session_id": explanation_session_id,
                **candidate,
            })
        return unique

    ACTION_CATEGORIES: dict[str, tuple[str, ...]] = {
        "concept": ("concept", "standard"),
        "steps": ("steps",),
        "example": ("example",),
        "warning": ("warning", "safety"),
        "workplace": ("workplace",),
        "maintenance": ("maintenance",),
        "review": ("warning", "safety", "workplace"),
        "standard": ("standard",),
    }
    REVIEW_STATUSES = {"pending", "approved", "rejected", "needs_update"}
    REVIEW_TRANSITIONS = {
        "pending": {"approved", "rejected"},
        "approved": {"needs_update"},
        "needs_update": {"approved", "rejected"},
        "rejected": {"pending"},
    }

    def _initialize_knowledge(self, connection: sqlite3.Connection) -> None:
        try:
            connection.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5("
                "title, category, content, source, safety, job_role, "
                "knowledge_point_id, keywords, "
                "content='knowledge_entries', content_rowid='rowid')"
            )
        except sqlite3.OperationalError:
            pass
        try:
            from backend.data.knowledge_seed import KNOWLEDGE_ENTRIES
        except ModuleNotFoundError:
            try:
                from data.knowledge_seed import KNOWLEDGE_ENTRIES
            except (ImportError, ModuleNotFoundError):
                return
        now = utc_now()
        for entry in KNOWLEDGE_ENTRIES:
            connection.execute(
                """
                INSERT OR IGNORE INTO knowledge_entries(
                    entry_id, knowledge_point_id, title, category, content, source,
                    source_type, document_id, locator, safety, job_role, action,
                    keywords, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(entry.get("entry_id", "")),
                    str(entry.get("knowledge_point_id", "")),
                    str(entry.get("title", "")),
                    str(entry.get("category", "")),
                    str(entry.get("content", "")),
                    str(entry.get("source", "")),
                    str(entry.get("source_type", "document")),
                    str(entry.get("document_id", "")),
                    str(entry.get("locator", "")),
                    1 if entry.get("safety") else 0,
                    str(entry.get("job_role", "")),
                    str(entry.get("action", "")),
                    str(entry.get("keywords", "")),
                    now,
                ),
            )
        try:
            connection.execute(
                "INSERT INTO knowledge_fts(knowledge_fts) VALUES('rebuild')"
            )
        except sqlite3.OperationalError:
            pass

    def knowledge_count(self) -> int:
        with self._lock, closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS n FROM knowledge_entries "
                "WHERE review_status = 'approved'"
            ).fetchone()
        return int(row["n"] or 0) if row else 0

    @staticmethod
    def _candidate_entry_id(candidate_id: str) -> str:
        return f"KN-CAND-{candidate_id}"

    @staticmethod
    def _rebuild_knowledge_fts(connection: sqlite3.Connection) -> None:
        try:
            connection.execute(
                "INSERT INTO knowledge_fts(knowledge_fts) VALUES('rebuild')"
            )
        except sqlite3.OperationalError:
            pass

    def _publish_candidate_row(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
        reviewed_at: str = "",
        reviewed_by: str = "",
    ) -> str:
        candidate_id = str(row["candidate_id"])
        entry_id = self._candidate_entry_id(candidate_id)
        category = str(row["category"])
        reviewed_at = str(reviewed_at or row["reviewed_at"] or utc_now())
        reviewed_by = str(reviewed_by or row["reviewed_by"])
        connection.execute(
            """
            INSERT INTO knowledge_entries(
                entry_id, knowledge_point_id, title, category, content, source,
                source_type, document_id, locator, safety, job_role, action,
                keywords, published_at, fetched_at, authority, valid_year,
                region, content_hash, review_status, reviewed_at, reviewed_by,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', '', '', ?, ?, ?, ?, ?, ?,
                      'approved', ?, ?, ?)
            ON CONFLICT(entry_id) DO UPDATE SET
                knowledge_point_id = excluded.knowledge_point_id,
                title = excluded.title,
                category = excluded.category,
                content = excluded.content,
                source = excluded.source,
                source_type = excluded.source_type,
                document_id = excluded.document_id,
                locator = excluded.locator,
                safety = excluded.safety,
                published_at = excluded.published_at,
                fetched_at = excluded.fetched_at,
                authority = excluded.authority,
                valid_year = excluded.valid_year,
                region = excluded.region,
                content_hash = excluded.content_hash,
                review_status = 'approved',
                reviewed_at = excluded.reviewed_at,
                reviewed_by = excluded.reviewed_by
            """,
            (
                entry_id,
                str(row["knowledge_point_id"]),
                str(row["title"]),
                category,
                str(row["content"]),
                str(row["source_title"]),
                str(row["source_type"]),
                str(row["document_id"]),
                str(row["locator"]),
                1 if category == "safety" else 0,
                str(row["source_published_at"]),
                str(row["source_fetched_at"]),
                str(row["source_authority"]),
                str(row["source_valid_year"]),
                str(row["source_region"]),
                str(row["content_hash"]),
                reviewed_at,
                reviewed_by,
                reviewed_at,
            ),
        )
        return entry_id

    def _publish_approved_knowledge_candidates(
        self, connection: sqlite3.Connection
    ) -> None:
        rows = connection.execute(
            """
            SELECT c.*, d.title AS source_title,
                   d.source_type AS source_type,
                   d.published_at AS source_published_at,
                   d.fetched_at AS source_fetched_at,
                   d.authority AS source_authority,
                   d.valid_year AS source_valid_year,
                   d.region AS source_region
            FROM knowledge_candidates c
            JOIN source_documents d ON d.document_id = c.document_id
            WHERE c.review_status = 'approved'
              AND c.ai_generated = 0
              AND d.review_status = 'approved'
            """
        ).fetchall()
        for row in rows:
            self._publish_candidate_row(connection, row)
        if rows:
            self._rebuild_knowledge_fts(connection)

    @staticmethod
    def _mark_published_document_needs_update(
        connection: sqlite3.Connection, document_id: str
    ) -> None:
        connection.execute(
            """
            UPDATE knowledge_entries
            SET review_status = 'needs_update', reviewed_at = '', reviewed_by = ''
            WHERE document_id = ? AND entry_id LIKE 'KN-CAND-%'
              AND review_status = 'approved'
            """,
            (document_id,),
        )

    def stage_source_document(self, document: dict[str, Any]) -> dict[str, Any]:
        document_id = str(document.get("document_id") or "").strip()
        title = str(document.get("title") or "").strip()
        source_type = str(document.get("source_type") or "").strip()
        content_hash = str(document.get("content_hash") or "").strip().lower()
        if not document_id or not title or not source_type or not content_hash:
            raise ValueError("document_id、title、source_type 和 content_hash 均不能为空")
        if not re.fullmatch(r"[0-9a-f]{64}", content_hash):
            raise ValueError("content_hash 必须是 SHA-256 十六进制摘要")
        now = utc_now()
        with self._lock, closing(self._connect()) as connection:
            existing = connection.execute(
                "SELECT content_hash, review_status FROM source_documents "
                "WHERE document_id = ?",
                (document_id,),
            ).fetchone()
            content_changed = bool(
                existing and str(existing["content_hash"]) != content_hash
            )
            connection.execute(
                """
                INSERT INTO source_documents(
                    document_id, title, source_type, source_url, published_at,
                    fetched_at, authority, valid_year, region, content_hash,
                    review_status, reviewed_at, reviewed_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', '', '', ?, ?)
                ON CONFLICT(document_id) DO UPDATE SET
                    title = excluded.title,
                    source_type = excluded.source_type,
                    source_url = excluded.source_url,
                    published_at = excluded.published_at,
                    fetched_at = excluded.fetched_at,
                    authority = excluded.authority,
                    valid_year = excluded.valid_year,
                    region = excluded.region,
                    content_hash = excluded.content_hash,
                    review_status = CASE
                        WHEN source_documents.content_hash <> excluded.content_hash
                         AND source_documents.review_status = 'approved'
                        THEN 'needs_update'
                        WHEN source_documents.content_hash <> excluded.content_hash
                         AND source_documents.review_status = 'rejected'
                        THEN 'pending'
                        ELSE source_documents.review_status
                    END,
                    reviewed_at = CASE
                        WHEN source_documents.content_hash <> excluded.content_hash
                        THEN '' ELSE source_documents.reviewed_at
                    END,
                    reviewed_by = CASE
                        WHEN source_documents.content_hash <> excluded.content_hash
                        THEN '' ELSE source_documents.reviewed_by
                    END,
                    updated_at = excluded.updated_at
                """,
                (
                    document_id,
                    title,
                    source_type,
                    str(document.get("source_url") or "").strip(),
                    str(document.get("published_at") or "").strip(),
                    str(document.get("fetched_at") or now).strip(),
                    str(document.get("authority") or "").strip(),
                    str(document.get("valid_year") or "").strip(),
                    str(document.get("region") or "").strip(),
                    content_hash,
                    now,
                    now,
                ),
            )
            if content_changed:
                connection.execute(
                    """
                    UPDATE knowledge_candidates
                    SET review_status = 'needs_update',
                        review_note = '来源文档内容已变化，需重新审核',
                        reviewed_at = '', reviewed_by = '', updated_at = ?
                    WHERE document_id = ? AND review_status = 'approved'
                    """,
                    (now, document_id),
                )
                self._mark_published_document_needs_update(
                    connection, document_id
                )
            row = connection.execute(
                "SELECT * FROM source_documents WHERE document_id = ?",
                (document_id,),
            ).fetchone()
            connection.commit()
        return self._source_document_row_to_dict(row)

    def review_source_document(
        self,
        document_id: str,
        review_status: str,
        reviewed_by: str,
    ) -> dict[str, Any]:
        document_id = str(document_id or "").strip()
        review_status = str(review_status or "").strip()
        reviewed_by = str(reviewed_by or "").strip()
        if not reviewed_by:
            raise ValueError("reviewed_by 不能为空")
        with self._lock, closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM source_documents WHERE document_id = ?",
                (document_id,),
            ).fetchone()
            if not row:
                raise KeyError(document_id)
            self._validate_review_transition(str(row["review_status"]), review_status)
            now = utc_now()
            connection.execute(
                "UPDATE source_documents SET review_status = ?, reviewed_at = ?, "
                "reviewed_by = ?, updated_at = ? "
                "WHERE document_id = ?",
                (review_status, now, reviewed_by, now, document_id),
            )
            if review_status == "needs_update":
                connection.execute(
                    """
                    UPDATE knowledge_candidates
                    SET review_status = 'needs_update',
                        review_note = '来源文档被标记为需更新',
                        reviewed_at = '', reviewed_by = '', updated_at = ?
                    WHERE document_id = ? AND review_status = 'approved'
                    """,
                    (now, document_id),
                )
                self._mark_published_document_needs_update(
                    connection, document_id
                )
            updated = connection.execute(
                "SELECT * FROM source_documents WHERE document_id = ?",
                (document_id,),
            ).fetchone()
            connection.commit()
        return self._source_document_row_to_dict(updated)

    def stage_knowledge_candidate(
        self, candidate: dict[str, Any]
    ) -> dict[str, Any]:
        title = str(candidate.get("title") or "").strip()
        category = str(candidate.get("category") or "").strip()
        content = str(candidate.get("content") or "").strip()
        document_id = str(candidate.get("document_id") or "").strip()
        if not title or not category or not content or not document_id:
            raise ValueError("title、category、content 和 document_id 均不能为空")
        candidate_id = str(candidate.get("candidate_id") or new_id("CANDIDATE")).strip()
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        now = utc_now()
        with self._lock, closing(self._connect()) as connection:
            source = connection.execute(
                "SELECT document_id FROM source_documents WHERE document_id = ?",
                (document_id,),
            ).fetchone()
            if not source:
                raise ValueError("候选资料必须关联已登记的来源文档")
            connection.execute(
                """
                INSERT INTO knowledge_candidates(
                    candidate_id, knowledge_point_id, title, category, content,
                    document_id, locator, content_hash, ai_generated,
                    review_status, review_note, reviewed_at, reviewed_by,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', '', '', '', ?, ?)
                """,
                (
                    candidate_id,
                    str(candidate.get("knowledge_point_id") or "").strip(),
                    title,
                    category,
                    content,
                    document_id,
                    str(candidate.get("locator") or "").strip(),
                    content_hash,
                    1 if candidate.get("ai_generated") else 0,
                    now,
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM knowledge_candidates WHERE candidate_id = ?",
                (candidate_id,),
            ).fetchone()
            connection.commit()
        return self._knowledge_candidate_row_to_dict(row)

    def list_knowledge_candidates(
        self, review_status: str = "", limit: int = 50
    ) -> list[dict[str, Any]]:
        review_status = str(review_status or "").strip()
        if review_status and review_status not in self.REVIEW_STATUSES:
            raise ValueError(f"未知审核状态：{review_status}")
        try:
            limit = max(1, min(int(limit), 200))
        except (TypeError, ValueError):
            limit = 50
        sql = "SELECT * FROM knowledge_candidates"
        params: list[Any] = []
        if review_status:
            sql += " WHERE review_status = ?"
            params.append(review_status)
        sql += " ORDER BY updated_at DESC, candidate_id LIMIT ?"
        params.append(limit)
        with self._lock, closing(self._connect()) as connection:
            rows = connection.execute(sql, params).fetchall()
        return [self._knowledge_candidate_row_to_dict(row) for row in rows]

    def review_knowledge_candidate(
        self,
        candidate_id: str,
        review_status: str,
        reviewed_by: str,
        review_note: str = "",
    ) -> dict[str, Any]:
        candidate_id = str(candidate_id or "").strip()
        review_status = str(review_status or "").strip()
        reviewed_by = str(reviewed_by or "").strip()
        if not reviewed_by:
            raise ValueError("reviewed_by 不能为空")
        with self._lock, closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT c.*, d.review_status AS source_review_status,
                       d.title AS source_title,
                       d.source_type AS source_type,
                       d.published_at AS source_published_at,
                       d.fetched_at AS source_fetched_at,
                       d.authority AS source_authority,
                       d.valid_year AS source_valid_year,
                       d.region AS source_region
                FROM knowledge_candidates c
                JOIN source_documents d ON d.document_id = c.document_id
                WHERE c.candidate_id = ?
                """,
                (candidate_id,),
            ).fetchone()
            if not row:
                raise KeyError(candidate_id)
            self._validate_review_transition(str(row["review_status"]), review_status)
            if review_status == "approved" and bool(row["ai_generated"]):
                raise ValueError("AI 生成候选不得进入正式知识审核通过状态")
            if review_status == "approved" and str(row["source_review_status"]) != "approved":
                raise ValueError("来源文档审核通过后才能批准候选资料")
            now = utc_now()
            connection.execute(
                """
                UPDATE knowledge_candidates
                SET review_status = ?, review_note = ?, reviewed_at = ?,
                    reviewed_by = ?, updated_at = ?
                WHERE candidate_id = ?
                """,
                (
                    review_status,
                    str(review_note or "").strip(),
                    now,
                    reviewed_by,
                    now,
                    candidate_id,
                ),
            )
            entry_id = self._candidate_entry_id(candidate_id)
            if review_status == "approved":
                self._publish_candidate_row(
                    connection, row, reviewed_at=now, reviewed_by=reviewed_by
                )
                self._rebuild_knowledge_fts(connection)
            else:
                connection.execute(
                    """
                    UPDATE knowledge_entries
                    SET review_status = ?, reviewed_at = ?, reviewed_by = ?
                    WHERE entry_id = ?
                    """,
                    (review_status, now, reviewed_by, entry_id),
                )
            updated = connection.execute(
                "SELECT * FROM knowledge_candidates WHERE candidate_id = ?",
                (candidate_id,),
            ).fetchone()
            connection.commit()
        return self._knowledge_candidate_row_to_dict(updated)

    @classmethod
    def _validate_review_transition(cls, current: str, target: str) -> None:
        if target not in cls.REVIEW_STATUSES:
            raise ValueError(f"未知审核状态：{target}")
        if target == current:
            return
        if target not in cls.REVIEW_TRANSITIONS.get(current, set()):
            raise ValueError(f"不允许的审核状态转换：{current} -> {target}")

    @staticmethod
    def _source_document_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            key: row[key]
            for key in (
                "document_id", "title", "source_type", "source_url",
                "published_at", "fetched_at", "authority", "valid_year",
                "region", "content_hash", "review_status", "reviewed_at",
                "reviewed_by", "created_at", "updated_at",
            )
        }

    @staticmethod
    def _knowledge_candidate_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        result = {
            key: row[key]
            for key in (
                "candidate_id", "knowledge_point_id", "title", "category",
                "content", "document_id", "locator", "content_hash",
                "review_status", "review_note", "reviewed_at", "reviewed_by",
                "created_at", "updated_at",
            )
        }
        result["ai_generated"] = bool(row["ai_generated"])
        return result

    def search_knowledge(
        self,
        query: str = "",
        knowledge_point_id: str = "",
        action: str = "",
        category: str = "",
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        query = str(query or "").strip()
        knowledge_point_id = str(knowledge_point_id or "").strip()
        action = str(action or "").strip()
        category = str(category or "").strip()
        try:
            limit = max(1, min(int(limit), 20))
        except (TypeError, ValueError):
            limit = 5
        where: list[str] = ["k.review_status = 'approved'"]
        params: list[Any] = []
        if knowledge_point_id:
            where.append("k.knowledge_point_id = ?")
            params.append(knowledge_point_id)
        if category:
            where.append("k.category = ?")
            params.append(category)
        elif action and action in self.ACTION_CATEGORIES:
            categories = self.ACTION_CATEGORIES[action]
            where.append("k.category IN ({})".format(",".join("?" * len(categories))))
            params.extend(categories)
        base_where = " AND ".join(where) if where else "1=1"
        rows: list[sqlite3.Row] = []
        with self._lock, closing(self._connect()) as connection:
            if query:
                fts_query = '"' + query.replace('"', '""') + '"'
                try:
                    rows = connection.execute(
                        "SELECT k.* FROM knowledge_entries k "
                        "JOIN knowledge_fts ON knowledge_fts.rowid = k.rowid "
                        f"WHERE {base_where} AND knowledge_fts MATCH ? "
                        "ORDER BY bm25(knowledge_fts) LIMIT ?",
                        params + [fts_query, limit],
                    ).fetchall()
                except sqlite3.OperationalError:
                    rows = []
                if not rows:
                    like = f"%{query}%"
                    rows = connection.execute(
                        "SELECT k.* FROM knowledge_entries k "
                        f"WHERE {base_where} AND (k.title LIKE ? OR k.content LIKE ? "
                        "OR k.keywords LIKE ? OR k.source LIKE ?) "
                        "ORDER BY k.entry_id LIMIT ?",
                        params + [like, like, like, like, limit],
                    ).fetchall()
                if not rows:
                    # 提问式 query 清洗：先剔除疑问词/停用词，再按标点分词逐 token 检索；
                    # 中文长句整句命中失败时，回退为 2 字滑动窗口关键词。
                    stop_words = {"什么", "如何", "为什么", "怎么", "请", "解释", "一下", "是", "的", "吗", "呢", "有", "没有", "能", "可以", "讲", "说", "什么是", "请解释", "是什么意思"}
                    cleaned = query
                    for word in stop_words:
                        cleaned = cleaned.replace(word, "")
                    tokens = [
                        token
                        for token in re.split(r"[\s/、,，;；|？?！!。.：:]+", cleaned)
                        if len(token) >= 2
                    ]
                    for token in tokens:
                        like = f"%{token}%"
                        rows = connection.execute(
                            "SELECT k.* FROM knowledge_entries k "
                            f"WHERE {base_where} AND (k.title LIKE ? OR k.content LIKE ? "
                            "OR k.keywords LIKE ? OR k.source LIKE ?) "
                            "ORDER BY k.entry_id LIMIT ?",
                            params + [like, like, like, like, limit],
                        ).fetchall()
                        if rows:
                            break
                    if not rows and cleaned:
                        # 2 字滑动窗口（去重、按出现顺序），提高中文长句命中率
                        seen: set[str] = set()
                        window_tokens: list[str] = []
                        for i in range(len(cleaned) - 1):
                            piece = cleaned[i:i + 2]
                            if piece not in seen:
                                seen.add(piece)
                                window_tokens.append(piece)
                        for token in window_tokens:
                            like = f"%{token}%"
                            rows = connection.execute(
                                "SELECT k.* FROM knowledge_entries k "
                                f"WHERE {base_where} AND (k.title LIKE ? OR k.content LIKE ? "
                                "OR k.keywords LIKE ? OR k.source LIKE ?) "
                                "ORDER BY k.entry_id LIMIT ?",
                                params + [like, like, like, like, limit],
                            ).fetchall()
                            if rows:
                                break
            else:
                rows = connection.execute(
                    "SELECT k.* FROM knowledge_entries k "
                    f"WHERE {base_where} "
                    "ORDER BY k.category, k.entry_id LIMIT ?",
                    params + [limit],
                ).fetchall()
        return [self._knowledge_row_to_dict(row) for row in rows]

    @staticmethod
    def _knowledge_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "entry_id": str(row["entry_id"]),
            "knowledge_point_id": str(row["knowledge_point_id"]),
            "title": str(row["title"]),
            "category": str(row["category"]),
            "content": str(row["content"]),
            "source": str(row["source"]),
            "source_type": str(row["source_type"]),
            "document_id": str(row["document_id"]),
            "locator": str(row["locator"]),
            "safety": bool(row["safety"]),
            "job_role": str(row["job_role"]),
            "action": str(row["action"]),
            "keywords": str(row["keywords"]),
            "published_at": str(row["published_at"]),
            "fetched_at": str(row["fetched_at"]),
            "authority": str(row["authority"]),
            "valid_year": str(row["valid_year"]),
            "region": str(row["region"]),
            "content_hash": str(row["content_hash"]),
            "review_status": str(row["review_status"]),
            "reviewed_at": str(row["reviewed_at"]),
            "reviewed_by": str(row["reviewed_by"]),
            "url": "",
        }

    def get_sources(self, explanation_session_id: str, student_id: str) -> list[dict[str, Any]]:
        with self._lock, closing(self._connect()) as connection:
            owner = connection.execute(
                """
                SELECT 1 FROM explanation_sessions
                WHERE explanation_session_id = ? AND student_id = ?
                """,
                (explanation_session_id, student_id),
            ).fetchone()
            if not owner:
                return []
            rows = connection.execute(
                """
                SELECT source_reference_id, source_type, title, document_id,
                       locator, quote_text, url, verification_state, created_at
                FROM source_references WHERE explanation_session_id = ?
                ORDER BY created_at, source_reference_id
                """,
                (explanation_session_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def explanation_context(self, explanation_session_id: str, student_id: str) -> dict[str, Any]:
        with self._lock, closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT result_json FROM explanation_sessions
                WHERE explanation_session_id = ? AND student_id = ?
                """,
                (explanation_session_id, student_id),
            ).fetchone()
        if not row:
            return {}
        try:
            value = json.loads(str(row["result_json"]))
        except json.JSONDecodeError:
            return {}
        return value if isinstance(value, dict) else {}
        return value if isinstance(value, dict) else {}

    def add_explanation_turn(
        self,
        explanation_session_id: str,
        student_id: str,
        role: str,
        content: dict[str, Any],
    ) -> dict[str, Any]:
        """Persist a user or assistant turn for a follow-up conversation."""
        with self._lock, closing(self._connect()) as connection:
            owner = connection.execute(
                """
                SELECT 1 FROM explanation_sessions
                WHERE explanation_session_id = ? AND student_id = ?
                """,
                (explanation_session_id, student_id),
            ).fetchone()
            if not owner:
                raise LookupError("explanation_session_id")
            connection.execute(
                """
                INSERT INTO explanation_turns(
                    explanation_turn_id, explanation_session_id, role, content_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (new_id("TURN"), explanation_session_id, role, json_text(content), utc_now()),
            )
            connection.commit()
        return content

    def explanation_sessions_for(self, student_id: str) -> list[dict[str, Any]]:
        """Compact activity list (created_at, scene, knowledge_point_id) for a student."""
        with self._lock, closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT scene, created_at, result_json FROM explanation_sessions
                WHERE student_id = ?
                ORDER BY created_at ASC
                """,
                (student_id,),
            ).fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            knowledge_point_id = ""
            try:
                result = json.loads(str(row["result_json"]))
            except json.JSONDecodeError:
                result = {}
            if isinstance(result, dict):
                knowledge_point_id = str(
                    result.get("knowledge_point_id")
                    or as_dict(result.get("learning_target")).get("knowledge_point_id")
                    or ""
                )
            items.append(
                {
                    "scene": str(row["scene"]),
                    "created_at": str(row["created_at"]),
                    "knowledge_point_id": knowledge_point_id,
                }
            )
        return items
    def profile(self, student_id: str) -> dict[str, Any]:
        return {"status": "ok", "profile": self.ensure_profile(student_id)}

    def settings(self, student_id: str) -> dict[str, Any]:
        with self._lock, closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT settings_json, updated_at FROM student_settings WHERE student_id = ?",
                (student_id,),
            ).fetchone()
        values = dict(self.DEFAULT_SETTINGS)
        if row:
            try:
                stored = json.loads(str(row["settings_json"]))
            except json.JSONDecodeError:
                stored = {}
            if isinstance(stored, dict):
                values.update(stored)
        return {"status": "ok", "student_id": student_id, "settings": values}

    def save_settings(self, student_id: str, incoming: dict[str, Any]) -> dict[str, Any]:
        values = self.settings(student_id)["settings"]
        allowed = set(self.DEFAULT_SETTINGS)
        values.update({key: value for key, value in incoming.items() if key in allowed})
        now = utc_now()
        with self._lock, closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO student_settings(student_id, settings_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(student_id) DO UPDATE SET
                    settings_json = excluded.settings_json,
                    updated_at = excluded.updated_at
                """,
                (student_id, json_text(values), now),
            )
            connection.commit()
        return {"status": "ok", "student_id": student_id, "settings": values, "updated_at": now}

    def toggle_favorite(
        self, student_id: str, knowledge_point_id: str, title: str, favorite: bool
    ) -> dict[str, Any]:
        with self._lock, closing(self._connect()) as connection:
            if favorite:
                connection.execute(
                    """
                    INSERT INTO student_favorites(student_id, knowledge_point_id, title, created_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(student_id, knowledge_point_id) DO UPDATE SET title = excluded.title
                    """,
                    (student_id, knowledge_point_id, title, utc_now()),
                )
            else:
                connection.execute(
                    "DELETE FROM student_favorites WHERE student_id = ? AND knowledge_point_id = ?",
                    (student_id, knowledge_point_id),
                )
            connection.commit()
        return {
            "status": "ok",
            "student_id": student_id,
            "knowledge_point_id": knowledge_point_id,
            "favorite": favorite,
        }

    def is_favorite(self, student_id: str, knowledge_point_id: str) -> bool:
        with self._lock, closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT 1 FROM student_favorites
                WHERE student_id = ? AND knowledge_point_id = ?
                """,
                (student_id, knowledge_point_id),
            ).fetchone()
        return bool(row)

    def _ensure_notifications(self, student_id: str) -> None:
        with self._lock, closing(self._connect()) as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM notifications WHERE student_id = ?", (student_id,)
            ).fetchone()[0]
            if count == 0:
                now = utc_now()
                messages = [
                    ("学习路径已更新", "系统已根据最近测验把“平均分统计口径”设为当前节点。"),
                    ("错题讲解已生成", "第 3 题的错误证据、正确要求和重做检查点已经准备完成。"),
                ]
                for title, message in messages:
                    connection.execute(
                        """
                        INSERT INTO notifications(
                            notification_id, student_id, title, message, read_at, created_at
                        ) VALUES (?, ?, ?, ?, '', ?)
                        """,
                        (new_id("NOTICE"), student_id, title, message, now),
                    )
                connection.commit()

    def notifications(self, student_id: str) -> dict[str, Any]:
        self._ensure_notifications(student_id)
        with self._lock, closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT notification_id, title, message, read_at, created_at
                FROM notifications WHERE student_id = ?
                ORDER BY created_at DESC, notification_id DESC LIMIT 20
                """,
                (student_id,),
            ).fetchall()
        items = [dict(row) for row in rows]
        return {
            "status": "ok",
            "items": items,
            "unread_count": sum(1 for item in items if not item["read_at"]),
        }

    def mark_notification_read(self, student_id: str, notification_id: str) -> dict[str, Any]:
        with self._lock, closing(self._connect()) as connection:
            cursor = connection.execute(
                """
                UPDATE notifications SET read_at = ?
                WHERE notification_id = ? AND student_id = ?
                """,
                (utc_now(), notification_id, student_id),
            )
            connection.commit()
        return {"status": "ok", "updated": cursor.rowcount == 1}

    def records(self, student_id: str) -> dict[str, Any]:
        with self._lock, closing(self._connect()) as connection:
            explanation_rows = connection.execute(
                """
                SELECT explanation_session_id, scene, explanation_type, delivery_mode,
                       status, question_instance_id, attempt_id, created_at
                FROM explanation_sessions WHERE student_id = ?
                ORDER BY created_at DESC LIMIT 30
                """,
                (student_id,),
            ).fetchall()
            attempt_rows = connection.execute(
                """
                SELECT a.attempt_id, a.question_instance_id, a.status, a.created_at,
                       q.title, q.mode, q.source_question_id, q.knowledge_point_id
                FROM attempts a JOIN question_instances q
                  ON q.question_instance_id = a.question_instance_id
                WHERE a.student_id = ? ORDER BY a.created_at DESC LIMIT 30
                """,
                (student_id,),
            ).fetchall()
        return {
            "status": "ok",
            "explanations": [dict(row) for row in explanation_rows],
            "attempts": [dict(row) for row in attempt_rows],
        }

    def save_generated_questions(self, questions: list[dict[str, Any]]) -> int:
        """生成式题库：工作流出题并通过本地校验的题目入库（幂等）。

        返回实际写入条数；同 question_id 重复写入被忽略。
        """
        if not questions:
            return 0
        now = utc_now()
        saved = 0
        with self._lock, closing(self._connect()) as connection:
            for q in questions:
                question_id = str(q.get("question_id") or "").strip() or new_id("GEN")
                try:
                    cursor = connection.execute(
                        """
                        INSERT OR IGNORE INTO generated_questions(
                            question_id, knowledge_point_id, knowledge_point_name,
                            difficulty, title, options_json, answer, question_type,
                            accepted_answers_json, grading_mode, explanation, source,
                            created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            question_id,
                            str(q.get("knowledge_point_id") or ""),
                            str(q.get("knowledge_point_name") or ""),
                            int(q.get("difficulty", 1) or 1),
                            str(q.get("title") or ""),
                            json_text(as_dict(q.get("options"))),
                            str(q.get("answer") or ""),
                            str(q.get("question_type") or "choice"),
                            json_text(as_list(q.get("accepted_answers"))),
                            str(q.get("grading_mode") or ""),
                            str(q.get("explanation") or ""),
                            str(q.get("source") or "工作流生成（本地校验通过）"),
                            now,
                        ),
                    )
                    saved += cursor.rowcount
                except (sqlite3.Error, ValueError):
                    continue
            connection.commit()
        return saved

    def recent_generated_questions(
        self, knowledge_point_id: str = "", limit: int = 10
    ) -> list[dict[str, Any]]:
        """最近生成并入库的题目（可按知识点过滤），供诊断复用。"""
        with self._lock, closing(self._connect()) as connection:
            if knowledge_point_id:
                rows = connection.execute(
                    """
                    SELECT * FROM generated_questions
                    WHERE knowledge_point_id = ?
                    ORDER BY created_at DESC LIMIT ?
                    """,
                    (knowledge_point_id, limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT * FROM generated_questions
                    ORDER BY created_at DESC LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        questions = []
        for row in rows:
            q = dict(row)
            try:
                q["options"] = json.loads(q.pop("options_json"))
            except (json.JSONDecodeError, KeyError):
                q["options"] = {}
            try:
                q["accepted_answers"] = json.loads(
                    q.pop("accepted_answers_json")
                )
            except (json.JSONDecodeError, KeyError):
                q["accepted_answers"] = []
            questions.append(q)
        return questions

    def knowledge_evidence_stats(self, student_id: str) -> dict[str, dict[str, Any]]:
        """按知识点统计作答证据（真实 attempts）：次数与最近作答时间。

        用于画像 knowledge 节点的 evidence_count / last_evidence_at；
        无作答记录的知识点不出现（调用方按 null 缺省，不虚构）。
        """
        with self._lock, closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT q.knowledge_point_id, COUNT(*) AS count,
                       MAX(a.created_at) AS last_at
                FROM attempts a JOIN question_instances q
                  ON q.question_instance_id = a.question_instance_id
                WHERE a.student_id = ?
                GROUP BY q.knowledge_point_id
                """,
                (student_id,),
            ).fetchall()
        stats: dict[str, dict[str, Any]] = {}
        for row in rows:
            kp_id = str(row["knowledge_point_id"] or "").strip()
            if not kp_id:
                continue
            stats[kp_id] = {
                "count": int(row["count"] or 0),
                "last_at": str(row["last_at"] or ""),
            }
        return stats

    def record_choice_attempt(
        self,
        student_id: str,
        source_question_id: str,
        mode: str,
        knowledge_point_id: str,
        knowledge_point_name: str,
        title: str,
        prompt: str,
        options: dict[str, Any],
        expected: str,
        selected: str,
        explanation: str = "",
        project_id: str = "",
        correct_override: bool | None = None,
    ) -> dict[str, Any]:
        """选择题作答落库：按 (student, mode, source_question_id) 复用题目实例，
        每次作答写入 attempts，返回判题结果与 attempt 信息。

        供题库刷题 / 学情诊断 / 阶段检查三类选择题共用，保证练习-归因-讲解-画像
        主闭环可溯源（E-2）。
        """
        expected_key = str(expected).strip().lower()
        selected_key = str(selected).strip().lower()
        # 选择题之外的题型已由调用方按其确定性规则完成判分；不得在此处
        # 用字符串相等覆盖多选、填空或实操题的结果。
        correct = (
            bool(correct_override)
            if correct_override is not None
            else bool(expected_key) and selected_key == expected_key
        )
        attempt_id = new_id("ATTEMPT")
        now = utc_now()
        with self._lock, closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT question_instance_id FROM question_instances
                WHERE student_id = ? AND mode = ? AND source_question_id = ?
                ORDER BY created_at DESC LIMIT 1
                """,
                (student_id, mode, source_question_id),
            ).fetchone()
            if row:
                question_instance_id = str(row["question_instance_id"])
            else:
                question_instance_id = new_id("QUESTION")
                task_instance_id = new_id("TASKINST")
                connection.execute(
                    """
                    INSERT INTO question_instances(
                        question_instance_id, student_id, task_instance_id, source_question_id,
                        mode, knowledge_point_id, title, prompt, answer_schema_json,
                        expected_answer, status, created_at, updated_at,
                        source_question_instance_id, root_question_instance_id, project_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ready', ?, ?, '', ?, ?)
                    """,
                    (
                        question_instance_id,
                        student_id,
                        task_instance_id,
                        source_question_id,
                        mode,
                        knowledge_point_id,
                        title,
                        prompt,
                        json_text({
                            "type": "choice",
                            "label": "选择答案",
                            "options": options,
                            "expected": expected,
                        }),
                        expected,
                        now,
                        now,
                        question_instance_id,
                        project_id,
                    ),
                )
            evaluation = {
                "validation_passed": True,
                "evaluation_status": "correct" if correct else "incorrect",
                "score": 1 if correct else 0,
                "max_score": 1,
                "explanation": explanation,
                "error_points": [] if correct else [{
                    "error_id": "CHOICE_ANSWER_INCORRECT",
                    "knowledge_point_id": knowledge_point_id,
                    "knowledge_point_name": knowledge_point_name or title,
                    "error_type": "practice",
                    "student_evidence": selected,
                    "expected_behavior": expected,
                    "diagnosis": "选择题作答与正确答案不一致",
                    "root_cause": "关键规则尚未稳定掌握",
                    "severity": "medium",
                    "confidence": 1.0,
                }],
            }
            connection.execute(
                """
                INSERT INTO attempts(
                    attempt_id, question_instance_id, student_id, answer_text,
                    evaluation_json, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    attempt_id,
                    question_instance_id,
                    student_id,
                    selected,
                    json_text(evaluation),
                    evaluation["evaluation_status"],
                    now,
                ),
            )
            connection.execute(
                "UPDATE question_instances SET status = 'submitted', updated_at = ? WHERE question_instance_id = ?",
                (now, question_instance_id),
            )
            # 正式项目测评的选择题同样由宿主后端按确定性结果投影到错题本。
            # 非项目题库/临时自测不传 project_id，不会冒充项目错题证据。
            if project_id:
                root_row = connection.execute(
                    "SELECT root_question_instance_id FROM question_instances WHERE question_instance_id = ?",
                    (question_instance_id,),
                ).fetchone()
                root_id = str(root_row["root_question_instance_id"] or question_instance_id) if root_row else question_instance_id
                existing_item = connection.execute(
                    "SELECT status FROM wrongbook_items WHERE student_id = ? AND project_id = ? AND root_question_instance_id = ?",
                    (student_id, project_id, root_id),
                ).fetchone()
                if not correct:
                    event_id = "WB-" + hashlib.sha256(f"{attempt_id}:incorrect".encode("utf-8")).hexdigest()[:16].upper()
                    connection.execute(
                        "INSERT OR IGNORE INTO wrongbook_events(event_id, student_id, project_id, root_question_instance_id, event_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                        (event_id, student_id, project_id, root_id, json_text({"event_id": event_id, "projection_instruction": "upsert_needs_review", "attempt_id": attempt_id, "knowledge_point_id": knowledge_point_id}), now),
                    )
                    connection.execute(
                        "INSERT INTO wrongbook_items(student_id, project_id, root_question_instance_id, knowledge_point_id, status, last_error_json, attempt_count, updated_at) VALUES (?, ?, ?, ?, 'needs_review', ?, 1, ?) ON CONFLICT(student_id, project_id, root_question_instance_id) DO UPDATE SET status = 'needs_review', last_error_json = excluded.last_error_json, attempt_count = wrongbook_items.attempt_count + 1, updated_at = excluded.updated_at",
                        (student_id, project_id, root_id, knowledge_point_id, json_text(evaluation["error_points"]), now),
                    )
                elif existing_item:
                    connection.execute(
                        "UPDATE wrongbook_items SET status = 'improved_not_deleted', attempt_count = attempt_count + 1, updated_at = ? WHERE student_id = ? AND project_id = ? AND root_question_instance_id = ?",
                        (now, student_id, project_id, root_id),
                    )
            connection.commit()
        return {
            "status": "ok",
            "attempt_id": attempt_id,
            "question_instance_id": question_instance_id,
            "correct": correct,
            "evaluation": evaluation,
        }

    def project_wrongbook_result(
        self,
        student_id: str,
        project_id: str,
        assessment_id: str,
        question: dict[str, Any],
        correct: bool,
    ) -> None:
        """Idempotently restore an assessment result into a project's wrongbook.

        This is for completed low-stakes assessment sessions created before
        attempts were persisted. It intentionally creates no fabricated answer
        or formal evidence.
        """
        if correct or not project_id:
            return
        source_question_id = str(question.get("question_id", "")).strip()
        knowledge_point_id = str(question.get("knowledge_point_id", "")).strip()
        if not source_question_id or not knowledge_point_id:
            return
        now = utc_now()
        with self._lock, closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT question_instance_id, root_question_instance_id FROM question_instances "
                "WHERE student_id = ? AND source_question_id = ? ORDER BY created_at DESC LIMIT 1",
                (student_id, source_question_id),
            ).fetchone()
            if row:
                root_id = str(row["root_question_instance_id"] or row["question_instance_id"])
            else:
                root_id = new_id("QUESTION")
                connection.execute(
                    """INSERT INTO question_instances(
                        question_instance_id, student_id, task_instance_id, source_question_id,
                        mode, knowledge_point_id, title, prompt, answer_schema_json,
                        expected_answer, status, created_at, updated_at,
                        source_question_instance_id, root_question_instance_id, project_id
                    ) VALUES (?, ?, '', ?, 'assessment_projection', ?, ?, ?, '{}', '', 'submitted', ?, ?, '', ?, ?)""",
                    (
                        root_id, student_id, source_question_id, knowledge_point_id,
                        str(question.get("title") or knowledge_point_id),
                        str(question.get("title") or ""), now, now, root_id, project_id,
                    ),
                )
            event_id = "WB-ASSESS-" + hashlib.sha256(
                f"{assessment_id}:{project_id}:{source_question_id}".encode("utf-8")
            ).hexdigest()[:16].upper()
            event = {
                "event_id": event_id,
                "projection_instruction": "upsert_needs_review",
                "assessment_id": assessment_id,
                "knowledge_point_id": knowledge_point_id,
                "source": "assessment_session_backfill",
            }
            inserted_event = connection.execute(
                "INSERT OR IGNORE INTO wrongbook_events(event_id, student_id, project_id, root_question_instance_id, event_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (event_id, student_id, project_id, root_id, json_text(event), now),
            )
            existing_item = connection.execute(
                "SELECT 1 FROM wrongbook_items WHERE student_id = ? AND project_id = ? "
                "AND root_question_instance_id = ?",
                (student_id, project_id, root_id),
            ).fetchone()
            if inserted_event.rowcount or not existing_item:
                connection.execute(
                    """INSERT INTO wrongbook_items(
                        student_id, project_id, root_question_instance_id, knowledge_point_id,
                        status, last_error_json, attempt_count, updated_at
                    ) VALUES (?, ?, ?, ?, 'needs_review', ?, 1, ?)
                    ON CONFLICT(student_id, project_id, root_question_instance_id) DO UPDATE SET
                        status = 'needs_review', last_error_json = excluded.last_error_json,
                        updated_at = excluded.updated_at""",
                    (
                        student_id, project_id, root_id, knowledge_point_id,
                        json_text([{
                            "error_id": "ASSESSMENT_ANSWER_INCORRECT",
                            "knowledge_point_id": knowledge_point_id,
                            "knowledge_point_name": str(question.get("knowledge_point_name") or knowledge_point_id),
                            "error_type": "assessment",
                            "diagnosis": "该题在项目测评中答错，建议回顾对应知识点。",
                        }]), now,
                    ),
                )
            connection.commit()

    def create_practice(self, student_id: str, incoming: dict[str, Any]) -> dict[str, Any]:
        mode = str(incoming.get("mode") or "retry_original")
        if mode not in {"retry_original", "variant"}:
            raise ValueError("mode 必须是 retry_original 或 variant")
        task_instance_id = str(incoming.get("task_instance_id", ""))
        source_question_id = str(incoming.get("source_question_instance_id", ""))
        knowledge_id = str(incoming.get("knowledge_point_id") or "KN_JAVA_ENCAPSULATION")
        source = self.question(source_question_id, student_id) if source_question_id else {}
        project_id = str(incoming.get("project_id") or source.get("project_id") or "")
        root_question_id = str(
            source.get("root_question_instance_id") or source_question_id or ""
        )
        if not task_instance_id:
            task_instance_id = str(source.get("task_instance_id", ""))

        if mode == "retry_original" and source:
            title = str(source.get("title") or "重做原题")
            prompt = str(source.get("prompt") or "请重新完成原题。")
            schema = as_dict(source.get("answer_schema")) or {"type": "text", "label": "你的答案"}
            expected = str(source.get("expected_answer", ""))
        else:
            # 变式练习模板来自错误卡配置（P1-3），新知识点加配置即可
            template = variant_practice_for(knowledge_id)
            title = str(template.get("title") or "同知识点变式题")
            prompt = str(template.get("prompt") or "请用自己的话说明当前知识点的核心规则，并给出一个应用例子。")
            schema = as_dict(template.get("schema")) or {"type": "text", "label": "你的答案"}
            expected = str(template.get("expected_answer") or "")

        question_instance_id = new_id("QUESTION")
        now = utc_now()
        with self._lock, closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO question_instances(
                    question_instance_id, student_id, task_instance_id, source_question_id,
                    mode, knowledge_point_id, title, prompt, answer_schema_json,
                    expected_answer, status, created_at, updated_at,
                    source_question_instance_id, root_question_instance_id, project_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ready', ?, ?, ?, ?, ?)
                """,
                (
                    question_instance_id,
                    student_id,
                    task_instance_id,
                    source_question_id,
                    mode,
                    knowledge_id,
                    title,
                    prompt,
                    json_text(schema),
                    expected,
                    now,
                    now,
                    source_question_id,
                    root_question_id or question_instance_id,
                    project_id,
                ),
            )
            connection.commit()
        return {
            "status": "ok",
            "question": {
                "question_instance_id": question_instance_id,
                "task_instance_id": task_instance_id,
                "source_question_instance_id": source_question_id,
                "mode": mode,
                "knowledge_point_id": knowledge_id,
                "title": title,
                "prompt": prompt,
                "answer_schema": schema,
            },
        }

    def question(self, question_instance_id: str, student_id: str) -> dict[str, Any]:
        if not question_instance_id:
            return {}
        with self._lock, closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT * FROM question_instances
                WHERE question_instance_id = ? AND student_id = ?
                """,
                (question_instance_id, student_id),
            ).fetchone()
        if not row:
            return {}
        result = dict(row)
        try:
            result["answer_schema"] = json.loads(result.pop("answer_schema_json"))
        except json.JSONDecodeError:
            result["answer_schema"] = {"type": "text", "label": "你的答案"}
        return result

    def create_wf04_question(
        self, student_id: str, project_id: str, task_instance_id: str,
        request_id: str, question_spec: dict[str, Any], public_question: dict[str, Any],
        assessment_mode: str,
    ) -> dict[str, Any]:
        """Persist the private WF04 specification while returning only public fields."""
        now = utc_now()
        with self._lock, closing(self._connect()) as connection:
            existing = connection.execute(
                "SELECT * FROM question_instances WHERE student_id = ? AND generation_request_id = ?",
                (student_id, request_id),
            ).fetchone()
            if existing:
                question_id = str(existing["question_instance_id"])
            else:
                question_id = new_id("QUESTION")
                source_id = str(question_spec.get("source_question_instance_id", ""))
                root_id = source_id or question_id
                if source_id:
                    source_row = connection.execute(
                        "SELECT root_question_instance_id FROM question_instances WHERE question_instance_id = ? AND student_id = ?",
                        (source_id, student_id),
                    ).fetchone()
                    if source_row and source_row["root_question_instance_id"]:
                        root_id = str(source_row["root_question_instance_id"])
                connection.execute(
                    """
                    INSERT INTO question_instances(
                        question_instance_id, student_id, task_instance_id, source_question_id,
                        mode, knowledge_point_id, title, prompt, answer_schema_json,
                        expected_answer, status, created_at, updated_at,
                        source_question_instance_id, root_question_instance_id, question_spec_json,
                        question_template_id, question_role, assessment_mode,
                        generation_request_id, generation_provider, project_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ready', ?, ?, ?, ?, ?, ?, ?, ?, ?, 'wf04', ?)
                    """,
                    (question_id, student_id, task_instance_id, source_id,
                     str(question_spec.get("question_role", "recommended")),
                     str(question_spec.get("knowledge_point_id", "")),
                     str(question_spec.get("title", "当前知识点练习")),
                     str(question_spec.get("prompt", "")), json_text(as_dict(question_spec.get("answer_schema"))),
                     str(question_spec.get("expected_answer", "")), now, now, source_id, root_id,
                     json_text(question_spec), str(question_spec.get("question_template_id", "")),
                     str(question_spec.get("question_role", "recommended")), assessment_mode,
                     request_id, project_id),
                )
            connection.commit()
            row = connection.execute("SELECT * FROM question_instances WHERE question_instance_id = ?", (question_id,)).fetchone()
        safe = {
            "question_instance_id": question_id, "task_instance_id": task_instance_id,
            "source_question_instance_id": str(row["source_question_instance_id"]),
            "mode": str(row["mode"]), "knowledge_point_id": str(row["knowledge_point_id"]),
            "title": str(public_question.get("title") or row["title"]),
            "prompt": str(public_question.get("prompt") or row["prompt"]),
            "question_type": str(public_question.get("question_type") or question_spec.get("question_type", "text")),
            "answer_schema": as_dict(public_question.get("answer_schema")) or as_dict(question_spec.get("answer_schema")),
        }
        return {"status": "ok", "question": safe}

    @staticmethod
    def _normalize_wrongbook_error(error_point: Any) -> dict[str, Any] | None:
        """兼容旧版字符串错因，并避免把无限长历史文本继续传入出题上下文。"""
        if isinstance(error_point, dict):
            return dict(error_point)
        if isinstance(error_point, str) and error_point.strip():
            return {
                "error_type": "legacy",
                "root_cause": error_point.strip()[:240],
            }
        return None

    @staticmethod
    def _wrongbook_error_key(error_point: dict[str, Any]) -> str:
        """返回可跨次作答稳定合并的错因键。"""
        explicit = str(error_point.get("error_id") or "").strip()
        if explicit:
            return explicit
        fingerprint = "|".join(
            str(error_point.get(key) or "").strip()
            for key in ("knowledge_point_id", "concept_id", "criterion_id", "error_type", "root_cause")
        )
        return "ERR-" + hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:16].upper()

    @classmethod
    def _merge_wrongbook_errors(
        cls, prior_errors: list[Any], attempt_errors: list[Any]
    ) -> list[dict[str, Any]]:
        """按 error_id 合并本次错因，不覆盖同题下仍未解决的其他错因。"""
        merged: dict[str, dict[str, Any]] = {}
        order: list[str] = []
        for raw in [*prior_errors, *attempt_errors]:
            item = cls._normalize_wrongbook_error(raw)
            if not item:
                continue
            key = cls._wrongbook_error_key(item)
            item["error_id"] = key
            if key not in merged:
                order.append(key)
            merged[key] = item
        return [merged[key] for key in order]

    @classmethod
    def _remove_wrongbook_errors(
        cls, prior_errors: list[Any], resolved_error_ids: list[Any]
    ) -> list[dict[str, Any]]:
        """只移除本次独立验证实际覆盖的错因，保留未提及错因。"""
        resolved = {str(value or "").strip() for value in resolved_error_ids if str(value or "").strip()}
        result: list[dict[str, Any]] = []
        for raw in prior_errors:
            item = cls._normalize_wrongbook_error(raw)
            if not item:
                continue
            key = cls._wrongbook_error_key(item)
            item["error_id"] = key
            if key not in resolved:
                result.append(item)
        return result

    def submit_wf04_attempt(
        self, student_id: str, question_instance_id: str, answer: str,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        question = self.question(question_instance_id, student_id)
        if not question:
            raise LookupError("题目实例不存在")
        evaluation = as_dict(result.get("validated_evaluation"))
        wrongbook_event = as_dict(result.get("wrongbook_event"))
        attempt_id = str(result.get("attempt_id", ""))
        if not attempt_id or not evaluation:
            raise ValueError("WF04 评价结果不完整")
        now = utc_now()
        with self._lock, closing(self._connect()) as connection:
            existing = connection.execute("SELECT attempt_id FROM attempts WHERE attempt_id = ?", (attempt_id,)).fetchone()
            if not existing:
                connection.execute(
                    "INSERT INTO attempts(attempt_id, question_instance_id, student_id, answer_text, evaluation_json, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (attempt_id, question_instance_id, student_id, answer, json_text(evaluation), str(evaluation.get("evaluation_status", "invalid")), now),
                )
                connection.execute("UPDATE question_instances SET status = 'submitted', updated_at = ? WHERE question_instance_id = ?", (now, question_instance_id))
            event_id = str(wrongbook_event.get("event_id", ""))
            if event_id:
                event_exists = connection.execute("SELECT 1 FROM wrongbook_events WHERE event_id = ?", (event_id,)).fetchone()
                if not event_exists:
                    root_id = str(wrongbook_event.get("root_question_instance_id") or question.get("root_question_instance_id") or question_instance_id)
                    project_id = str(wrongbook_event.get("project_id") or question.get("project_id", ""))
                    connection.execute("INSERT INTO wrongbook_events(event_id, student_id, project_id, root_question_instance_id, event_json, created_at) VALUES (?, ?, ?, ?, ?, ?)", (event_id, student_id, project_id, root_id, json_text(wrongbook_event), now))
                    prior = connection.execute("SELECT status, attempt_count, last_error_json FROM wrongbook_items WHERE student_id = ? AND project_id = ? AND root_question_instance_id = ?", (student_id, project_id, root_id)).fetchone()
                    instruction = str(wrongbook_event.get("projection_instruction", ""))
                    prior_errors: list[Any] = []
                    if prior:
                        try:
                            decoded = json.loads(str(prior["last_error_json"] or "[]"))
                            prior_errors = decoded if isinstance(decoded, list) else []
                        except json.JSONDecodeError:
                            prior_errors = []
                    if instruction == "upsert_needs_review":
                        attempt_errors = as_list(wrongbook_event.get("attempt_error_points")) or as_list(evaluation.get("error_points"))
                        merged_errors = self._merge_wrongbook_errors(prior_errors, attempt_errors)
                        connection.execute("INSERT INTO wrongbook_items(student_id, project_id, root_question_instance_id, knowledge_point_id, status, last_error_json, attempt_count, updated_at) VALUES (?, ?, ?, ?, 'needs_review', ?, 1, ?) ON CONFLICT(student_id, project_id, root_question_instance_id) DO UPDATE SET status = 'needs_review', last_error_json = excluded.last_error_json, attempt_count = wrongbook_items.attempt_count + 1, updated_at = excluded.updated_at", (student_id, project_id, root_id, str(wrongbook_event.get("knowledge_point_id", "")), json_text(merged_errors), now))
                    elif prior:
                        status = str(prior["status"])
                        remaining_errors = self._merge_wrongbook_errors([], prior_errors)
                        if instruction == "mark_improved_not_deleted_if_prior_wrong" and bool(evaluation.get("independent_evidence")):
                            resolved_ids = as_list(wrongbook_event.get("candidate_resolved_error_point_ids"))
                            if resolved_ids:
                                remaining_errors = self._remove_wrongbook_errors(prior_errors, resolved_ids)
                                status = "improved_not_deleted" if not remaining_errors else "needs_review"
                            else:
                                # 兼容非错题专项的原题独立重做：该题全部错因可视为已改善。
                                remaining_errors = []
                                status = "improved_not_deleted"
                        connection.execute("UPDATE wrongbook_items SET status = ?, last_error_json = ?, attempt_count = attempt_count + 1, updated_at = ? WHERE student_id = ? AND project_id = ? AND root_question_instance_id = ?", (status, json_text(remaining_errors), now, student_id, project_id, root_id))
            connection.commit()
        return {"status": "ok", "attempt_id": attempt_id, "question_instance_id": question_instance_id, "correct": str(evaluation.get("evaluation_status")) == "correct", "evaluation": evaluation, "adaptive_policy": as_dict(result.get("adaptive_policy")), "explanation_input": {"question_instance_id": question_instance_id, "task_instance_id": str(question.get("task_instance_id", "")), "attempt_id": attempt_id, "question_snapshot": {"question_id": question_instance_id, "question_text": str(question.get("prompt", ""))}, "current_attempt": {"student_answer": answer}, "validated_evaluation": evaluation}}

    def wrongbook(
        self,
        student_id: str,
        project_id: str,
        status: str = "all",
        query: str = "",
        knowledge_point_id: str = "",
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Return a compact, searchable project wrongbook page and its totals."""
        allowed_statuses = {"all", "needs_review", "improved_not_deleted"}
        status = status if status in allowed_statuses else "all"
        limit = max(1, min(int(limit or 20), 100))
        offset = max(0, int(offset or 0))
        clauses = ["student_id = ?", "project_id = ?"]
        values: list[Any] = [student_id, project_id]
        if status != "all":
            clauses.append("status = ?")
            values.append(status)
        if knowledge_point_id:
            clauses.append("knowledge_point_id = ?")
            values.append(knowledge_point_id)
        if query:
            clauses.append("(knowledge_point_id LIKE ? OR last_error_json LIKE ?)")
            needle = f"%{query.strip()}%"
            values.extend([needle, needle])
        where = " AND ".join(clauses)
        with self._lock, closing(self._connect()) as connection:
            counts = {
                str(row["status"]): int(row["count"])
                for row in connection.execute(
                    "SELECT status, COUNT(*) AS count FROM wrongbook_items "
                    "WHERE student_id = ? AND project_id = ? GROUP BY status",
                    (student_id, project_id),
                ).fetchall()
            }
            knowledge_points = [
                dict(row)
                for row in connection.execute(
                    "SELECT knowledge_point_id, COUNT(*) AS count FROM wrongbook_items "
                    "WHERE student_id = ? AND project_id = ? GROUP BY knowledge_point_id "
                    "ORDER BY count DESC, knowledge_point_id",
                    (student_id, project_id),
                ).fetchall()
            ]
            total = int(connection.execute(
                f"SELECT COUNT(*) FROM wrongbook_items WHERE {where}", values
            ).fetchone()[0])
            rows = connection.execute(
                f"SELECT * FROM wrongbook_items WHERE {where} "
                "ORDER BY CASE status WHEN 'needs_review' THEN 0 ELSE 1 END, updated_at DESC "
                "LIMIT ? OFFSET ?",
                [*values, limit, offset],
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            try:
                decoded = json.loads(str(item.pop("last_error_json")))
                raw_errors = decoded if isinstance(decoded, list) else []
            except json.JSONDecodeError:
                raw_errors = []
            item["last_error_points"] = self._merge_wrongbook_errors([], raw_errors)
            source = self.question(str(item.get("root_question_instance_id") or ""), student_id)
            schema = as_dict(source.get("answer_schema"))
            item["task_instance_id"] = str(source.get("task_instance_id") or "")
            item["original_question_title"] = str(source.get("title") or "")
            item["original_question_prompt"] = str(source.get("prompt") or "")
            item["question_type"] = str(schema.get("type") or "text")
            item["can_retry_original"] = bool(
                source and str(source.get("prompt") or "").strip()
                and str(source.get("expected_answer") or "").strip()
            )
            result.append(item)
        return {
            "items": result,
            "total": total,
            "counts": {
                "needs_review": counts.get("needs_review", 0),
                "improved_not_deleted": counts.get("improved_not_deleted", 0),
                "all": sum(counts.values()),
            },
            "knowledge_points": knowledge_points,
            "limit": limit,
            "offset": offset,
        }

    def wrongbook_focus(
        self,
        student_id: str,
        project_id: str,
        knowledge_point_id: str = "",
        limit: int = 3,
    ) -> dict[str, Any]:
        """从后端错题投影中选出一个可直接传给 WF04 的未解决错因焦点。"""
        limit = max(1, min(int(limit or 3), 10))
        clauses = ["wi.student_id = ?", "wi.project_id = ?", "wi.status = 'needs_review'"]
        values: list[Any] = [student_id, project_id]
        if knowledge_point_id:
            clauses.append("wi.knowledge_point_id = ?")
            values.append(knowledge_point_id)
        where = " AND ".join(clauses)
        with self._lock, closing(self._connect()) as connection:
            active_count = int(connection.execute(
                f"SELECT COUNT(*) FROM wrongbook_items wi WHERE {where}", values
            ).fetchone()[0])
            rows = connection.execute(
                f"""SELECT wi.*, qi.title AS original_question_title,
                            qi.prompt AS original_question_prompt
                     FROM wrongbook_items wi
                     LEFT JOIN question_instances qi
                       ON qi.question_instance_id = wi.root_question_instance_id
                     WHERE {where}
                     ORDER BY wi.attempt_count DESC, wi.updated_at DESC
                     LIMIT ?""",
                [*values, limit],
            ).fetchall()
        for row in rows:
            item = dict(row)
            try:
                decoded = json.loads(str(item.get("last_error_json") or "[]"))
                raw_errors = decoded if isinstance(decoded, list) else []
            except json.JSONDecodeError:
                raw_errors = []
            target_errors = self._merge_wrongbook_errors([], raw_errors)[:3]
            if not target_errors:
                continue
            safe_errors = [
                {
                    key: error.get(key)
                    for key in (
                        "error_id", "concept_id", "criterion_id", "error_type",
                        "expected_behavior", "root_cause", "severity", "confidence",
                    )
                    if error.get(key) not in (None, "")
                }
                for error in target_errors
            ]
            target_concepts = list(dict.fromkeys(
                str(error.get("concept_id") or "").strip()
                for error in target_errors
                if str(error.get("concept_id") or "").strip()
            ))
            root_id = str(item.get("root_question_instance_id") or "")
            return {
                "focus_source": "wrongbook",
                "active_wrongbook_count": active_count,
                "wrongbook_entry_id": root_id,
                "status": "needs_review",
                "knowledge_point_id": str(item.get("knowledge_point_id") or ""),
                "source_question_instance_id": root_id,
                "root_question_instance_id": root_id,
                "original_question_title": str(item.get("original_question_title") or ""),
                "original_question_prompt": str(item.get("original_question_prompt") or ""),
                "target_error_points": safe_errors,
                "target_concept_ids": target_concepts,
                "attempt_count": int(item.get("attempt_count") or 0),
            }
        return {}

    def submit_attempt(
        self, student_id: str, question_instance_id: str, answer: str
    ) -> dict[str, Any]:
        question = self.question(question_instance_id, student_id)
        if not question:
            raise LookupError("题目实例不存在")
        answer = answer.strip()
        if not answer:
            raise ValueError("答案不能为空")
        expected = str(question.get("expected_answer", "")).strip()
        schema_type = str(as_dict(question.get("answer_schema")).get("type", "text"))
        if schema_type == "number":
            try:
                correct = abs(float(answer) - float(expected)) < 1e-9
            except ValueError:
                correct = False
        elif schema_type in {"choice", "single_choice", "radio", "judgment"}:
            correct = bool(expected) and answer.casefold() == expected.casefold()
        elif schema_type in {"multiple_choice", "multi_choice", "checkbox"}:
            selected_values = {value.strip().casefold() for value in answer.split(",") if value.strip()}
            expected_values = {value.strip().casefold() for value in expected.split(",") if value.strip()}
            correct = bool(expected_values) and selected_values == expected_values
        elif question.get("mode") == "retry_original" and not expected:
            # 无答案标准的 retry 题不得乱判对（历史上曾硬编码 Python 题魔术串）
            correct = False
        else:
            # 语义短语 any 命中；token 长度 ≥3 排除"75/有效"这类泛词误判
            expected_tokens = [
                token for token in expected.replace("或", " ").split() if len(token) >= 3
            ]
            correct = bool(expected_tokens) and any(token in answer for token in expected_tokens)

        attempt_id = new_id("ATTEMPT")
        knowledge_id = str(question.get("knowledge_point_id", ""))
        evaluation = {
            "validation_passed": True,
            "evaluation_status": "correct" if correct else "incorrect",
            "score": 1 if correct else 0,
            "max_score": 1,
            "error_points": [] if correct else [{
                "error_id": "PRACTICE_ANSWER_INCORRECT",
                "knowledge_point_id": knowledge_id,
                "knowledge_point_name": str(question.get("title") or "当前知识点"),
                "error_type": "practice",
                "student_evidence": answer,
                "expected_behavior": expected or "按照题目要求给出完整答案",
                "diagnosis": "本次练习答案与预期要求不一致",
                "root_cause": "关键规则尚未稳定迁移到新题情境",
                "severity": "medium",
                "confidence": 1.0,
            }],
        }
        now = utc_now()
        with self._lock, closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO attempts(
                    attempt_id, question_instance_id, student_id, answer_text,
                    evaluation_json, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    attempt_id,
                    question_instance_id,
                    student_id,
                    answer,
                    json_text(evaluation),
                    evaluation["evaluation_status"],
                    now,
                ),
            )
            connection.execute(
                "UPDATE question_instances SET status = 'submitted', updated_at = ? WHERE question_instance_id = ?",
                (now, question_instance_id),
            )
            project_id = str(question.get("project_id") or "")
            root_id = str(
                question.get("root_question_instance_id")
                or question.get("source_question_instance_id")
                or question_instance_id
            )
            if project_id:
                prior = connection.execute(
                    "SELECT status, last_error_json FROM wrongbook_items "
                    "WHERE student_id = ? AND project_id = ? AND root_question_instance_id = ?",
                    (student_id, project_id, root_id),
                ).fetchone()
                event_id = "WB-" + hashlib.sha256(
                    f"{attempt_id}:{'correct' if correct else 'incorrect'}".encode("utf-8")
                ).hexdigest()[:16].upper()
                instruction = (
                    "mark_improved_not_deleted_if_prior_wrong"
                    if correct else "upsert_needs_review"
                )
                connection.execute(
                    "INSERT OR IGNORE INTO wrongbook_events(event_id, student_id, project_id, "
                    "root_question_instance_id, event_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        event_id,
                        student_id,
                        project_id,
                        root_id,
                        json_text({
                            "event_id": event_id,
                            "projection_instruction": instruction,
                            "attempt_id": attempt_id,
                            "knowledge_point_id": knowledge_id,
                        }),
                        now,
                    ),
                )
                if correct and prior:
                    connection.execute(
                        "UPDATE wrongbook_items SET status = 'improved_not_deleted', "
                        "last_error_json = '[]', attempt_count = attempt_count + 1, updated_at = ? "
                        "WHERE student_id = ? AND project_id = ? AND root_question_instance_id = ?",
                        (now, student_id, project_id, root_id),
                    )
                elif not correct:
                    prior_errors: list[Any] = []
                    if prior:
                        try:
                            decoded = json.loads(str(prior["last_error_json"] or "[]"))
                            prior_errors = decoded if isinstance(decoded, list) else []
                        except json.JSONDecodeError:
                            prior_errors = []
                    merged_errors = self._merge_wrongbook_errors(
                        prior_errors, evaluation["error_points"]
                    )
                    connection.execute(
                        "INSERT INTO wrongbook_items(student_id, project_id, root_question_instance_id, "
                        "knowledge_point_id, status, last_error_json, attempt_count, updated_at) "
                        "VALUES (?, ?, ?, ?, 'needs_review', ?, 1, ?) "
                        "ON CONFLICT(student_id, project_id, root_question_instance_id) DO UPDATE SET "
                        "status = 'needs_review', last_error_json = excluded.last_error_json, "
                        "attempt_count = wrongbook_items.attempt_count + 1, updated_at = excluded.updated_at",
                        (
                            student_id,
                            project_id,
                            root_id,
                            knowledge_id,
                            json_text(merged_errors),
                            now,
                        ),
                    )
            connection.commit()
        return {
            "status": "ok",
            "attempt_id": attempt_id,
            "question_instance_id": question_instance_id,
            "correct": correct,
            "feedback": "回答正确，可以继续下一项学习。" if correct else "答案尚未满足要求，已准备针对性讲解。",
            "evaluation": evaluation,
            "explanation_input": {
                "question_instance_id": question_instance_id,
                "task_instance_id": str(question.get("task_instance_id", "")),
                "attempt_id": attempt_id,
                "question_snapshot": {
                    "question_id": question_instance_id,
                    "question_text": str(question.get("prompt", "")),
                },
                "current_attempt": {"student_answer": answer},
                "validated_evaluation": evaluation,
            },
        }
