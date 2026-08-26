from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text, select, func, Integer
from pathlib import Path
import os
import shutil
import sqlite3

from app.core.config import settings

engine = create_async_engine(settings.database_url, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()


# Lightweight migrations: columns added to existing models after the table
# was created. create_all() does not alter existing tables, so we add them
# explicitly (SQLite ADD COLUMN).
EXTRA_COLUMNS = {
    "projects": [
        ("learner_id", "INTEGER"),
    ],
    "learners": [
        ("user_id", "INTEGER"),
    ],
    "auth_sessions": [
        ("is_dev_login", "BOOLEAN DEFAULT 0"),
    ],
    "checkpoints": [
        ("brief", "TEXT"),        # CheckpointBrief handoff contract (T2)
        ("archived", "BOOLEAN"), # T10: removed-but-kept checkpoints
        ("progress", "TEXT"),    # T10: learning progress stats
        ("learning_status", "TEXT"),
        ("legacy_completed", "BOOLEAN"),
        ("learning_contract", "TEXT"),
    ],
    "sources": [
        ("role", "TEXT"),        # T10: main | auxiliary
    ],
    "lectures": [
        ("plan", "TEXT"),        # T10: persisted section plan (resume stability)
        ("concept_graph", "TEXT"),  # concept map {nodes, edges}
        ("version", "INTEGER DEFAULT 1"),
    ],
    "exercises": [
        ("files", "TEXT"),        # project-mode: [{name, content, read_only}]
        ("entrypoint", "TEXT"),   # main file to run
        ("requirements", "TEXT"), # ["torch", "scikit-learn"]
        ("judge_mode", "TEXT"),  # test_cases | stdout_check
        ("judge_config", "TEXT"),# {pattern, min_accuracy} for stdout_check
        ("assessment_meta", "TEXT"),
    ],
    "concept_questions": [
        ("assessment_meta", "TEXT"),
    ],
    "tasks": [
        ("agent_action_id", "INTEGER"),
        ("learner_id", "INTEGER"),
    ],
    "agent_messages": [
        ("idempotency_key", "TEXT"),
    ],
    "evidence_events": [
        ("occurred_at", "DATETIME"),
        ("learner_seq", "INTEGER"),
        ("actor_type", "TEXT"),
    ],
    "learning_attempts": [
        ("remediation_case_id", "INTEGER"),
        ("attempt_role", "TEXT DEFAULT 'original'"),
        ("client_submission_id", "TEXT"),
    ],
    "process_animations": [
        ("kind", "TEXT"),         # animation | static（表已存在时补列）
    ],
    "lecture_versions": [
        ("source_version", "INTEGER DEFAULT 1"),
        ("idempotency_key", "TEXT"),
    ],
}

FIVE_KERNEL_MIGRATION = "v2-five-kernel-tutor"
PROJECT_PROPOSAL_MIGRATION = "v3-evolving-project-proposals"
USER_ISOLATION_MIGRATION = "v4-user-isolation-profile-badges"
MEMORY_GRAPH_MIGRATION = "v5-inspectable-memory-graph"
DESKTOP_WORKSPACE_MIGRATION = "v6-desktop-workspace"
CHECKPOINT_TUTOR_MIGRATION = "v7-checkpoint-tutor-sessions"
MANAGED_ARTIFACT_MIGRATION = "v8-managed-learning-artifacts"
LOCAL_AGENT_BROKER_MIGRATION = "v9-local-agent-broker"
REVIEW_WORKBENCH_MIGRATION = "v10-review-workbench"


def _sqlite_path() -> Path | None:
    prefix = "sqlite+aiosqlite:///"
    if not settings.database_url.startswith(prefix):
        return None
    raw = settings.database_url[len(prefix):]
    return Path(raw).expanduser().resolve()


def _migration_applied(path: Path, version: str) -> bool:
    if not path.exists() or path.stat().st_size == 0:
        return False
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            has_table = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
            ).fetchone()
            if not has_table:
                return False
            return conn.execute(
                "SELECT 1 FROM schema_migrations WHERE version=?", (version,)
            ).fetchone() is not None
        finally:
            conn.close()
    except sqlite3.Error:
        return False


def _backup_before_five_kernel_migration():
    path = _sqlite_path()
    if not path or not path.exists() or path.stat().st_size == 0 or _migration_applied(path, FIVE_KERNEL_MIGRATION):
        return
    backup_dir = path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"{path.stem}-pre-five-kernel-v2{path.suffix}"
    if backup_path.exists():
        return
    required = path.stat().st_size + 64 * 1024 * 1024
    if shutil.disk_usage(path.parent).free < required:
        raise RuntimeError(
            f"数据库迁移需要至少 {required // (1024 * 1024)}MB 可用空间来创建安全备份"
        )
    temp_path = backup_path.with_suffix(backup_path.suffix + ".tmp")
    temp_path.unlink(missing_ok=True)
    source = sqlite3.connect(path)
    destination = sqlite3.connect(temp_path)
    try:
        source.backup(destination)
        check = destination.execute("PRAGMA quick_check").fetchone()
        if not check or check[0] != "ok":
            raise RuntimeError("数据库迁移备份完整性检查失败")
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
    finally:
        destination.close()
        source.close()
    os.replace(temp_path, backup_path)
    print(f"[migrate] backup created: {backup_path}")


def _backup_before_project_proposal_migration():
    path = _sqlite_path()
    if not path or not path.exists() or path.stat().st_size == 0:
        return
    if _migration_applied(path, PROJECT_PROPOSAL_MIGRATION):
        return
    backup_dir = path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"{path.stem}-pre-project-proposals-v3{path.suffix}"
    if backup_path.exists():
        return
    required = path.stat().st_size + 64 * 1024 * 1024
    if shutil.disk_usage(path.parent).free < required:
        raise RuntimeError(
            f"数据库迁移需要至少 {required // (1024 * 1024)}MB 可用空间来创建安全备份"
        )
    temp_path = backup_path.with_suffix(backup_path.suffix + ".tmp")
    temp_path.unlink(missing_ok=True)
    source = sqlite3.connect(path)
    destination = sqlite3.connect(temp_path)
    try:
        source.backup(destination)
        check = destination.execute("PRAGMA quick_check").fetchone()
        if not check or check[0] != "ok":
            raise RuntimeError("数据库迁移备份完整性检查失败")
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
    finally:
        destination.close()
        source.close()
    os.replace(temp_path, backup_path)
    print(f"[migrate] backup created: {backup_path}")


def _backup_before_user_isolation_migration():
    path = _sqlite_path()
    if not path or not path.exists() or path.stat().st_size == 0:
        return
    if _migration_applied(path, USER_ISOLATION_MIGRATION):
        return
    backup_dir = path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"{path.stem}-pre-user-isolation-v4{path.suffix}"
    if backup_path.exists():
        return
    required = path.stat().st_size + 64 * 1024 * 1024
    if shutil.disk_usage(path.parent).free < required:
        raise RuntimeError(
            f"数据库迁移需要至少 {required // (1024 * 1024)}MB 可用空间来创建安全备份"
        )
    temp_path = backup_path.with_suffix(backup_path.suffix + ".tmp")
    temp_path.unlink(missing_ok=True)
    source = sqlite3.connect(path)
    destination = sqlite3.connect(temp_path)
    try:
        source.backup(destination)
        check = destination.execute("PRAGMA quick_check").fetchone()
        if not check or check[0] != "ok":
            raise RuntimeError("数据库迁移备份完整性检查失败")
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
    finally:
        destination.close()
        source.close()
    os.replace(temp_path, backup_path)
    print(f"[migrate] backup created: {backup_path}")


def _backup_before_memory_graph_migration():
    path = _sqlite_path()
    if not path or not path.exists() or path.stat().st_size == 0:
        return
    if _migration_applied(path, MEMORY_GRAPH_MIGRATION):
        return
    backup_dir = path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"{path.stem}-pre-memory-graph-v5{path.suffix}"
    if backup_path.exists():
        return
    required = path.stat().st_size + 64 * 1024 * 1024
    if shutil.disk_usage(path.parent).free < required:
        raise RuntimeError(
            f"数据库迁移需要至少 {required // (1024 * 1024)}MB 可用空间来创建安全备份"
        )
    temp_path = backup_path.with_suffix(backup_path.suffix + ".tmp")
    temp_path.unlink(missing_ok=True)
    source = sqlite3.connect(path)
    destination = sqlite3.connect(temp_path)
    try:
        source.backup(destination)
        check = destination.execute("PRAGMA quick_check").fetchone()
        if not check or check[0] != "ok":
            raise RuntimeError("数据库迁移备份完整性检查失败")
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
    finally:
        destination.close()
        source.close()
    os.replace(temp_path, backup_path)
    print(f"[migrate] backup created: {backup_path}")


def _backup_before_desktop_workspace_migration():
    path = _sqlite_path()
    if not path or not path.exists() or path.stat().st_size == 0:
        return
    if _migration_applied(path, DESKTOP_WORKSPACE_MIGRATION):
        return
    backup_dir = path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"{path.stem}-pre-desktop-workspace-v6{path.suffix}"
    if backup_path.exists():
        return
    required = path.stat().st_size + 64 * 1024 * 1024
    if shutil.disk_usage(path.parent).free < required:
        raise RuntimeError(
            f"数据库迁移需要至少 {required // (1024 * 1024)}MB 可用空间来创建安全备份"
        )
    temp_path = backup_path.with_suffix(backup_path.suffix + ".tmp")
    temp_path.unlink(missing_ok=True)
    source = sqlite3.connect(path)
    destination = sqlite3.connect(temp_path)
    try:
        source.backup(destination)
        check = destination.execute("PRAGMA quick_check").fetchone()
        if not check or check[0] != "ok":
            raise RuntimeError("数据库迁移备份完整性检查失败")
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
    finally:
        destination.close()
        source.close()
    os.replace(temp_path, backup_path)
    print(f"[migrate] backup created: {backup_path}")


def _backup_before_checkpoint_tutor_migration():
    path = _sqlite_path()
    if (
        not path or not path.exists() or path.stat().st_size == 0
        or _migration_applied(path, CHECKPOINT_TUTOR_MIGRATION)
    ):
        return
    backup_dir = path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"{path.stem}-pre-checkpoint-tutor-v7{path.suffix}"
    if backup_path.exists():
        return
    required = path.stat().st_size + 64 * 1024 * 1024
    if shutil.disk_usage(path.parent).free < required:
        raise RuntimeError(
            f"数据库迁移需要至少 {required // (1024 * 1024)}MB 可用空间来创建安全备份"
        )
    temp_path = backup_path.with_suffix(backup_path.suffix + ".tmp")
    temp_path.unlink(missing_ok=True)
    source = sqlite3.connect(path)
    destination = sqlite3.connect(temp_path)
    try:
        source.backup(destination)
        check = destination.execute("PRAGMA quick_check").fetchone()
        if not check or check[0] != "ok":
            raise RuntimeError("数据库迁移备份完整性检查失败")
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
    finally:
        destination.close()
        source.close()
    os.replace(temp_path, backup_path)
    print(f"[migrate] backup created: {backup_path}")


def _backup_before_managed_artifact_migration():
    path = _sqlite_path()
    if (
        not path or not path.exists() or path.stat().st_size == 0
        or _migration_applied(path, MANAGED_ARTIFACT_MIGRATION)
    ):
        return
    backup_dir = path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"{path.stem}-pre-managed-artifacts-v8{path.suffix}"
    if backup_path.exists():
        return
    required = path.stat().st_size + 64 * 1024 * 1024
    if shutil.disk_usage(path.parent).free < required:
        raise RuntimeError(
            f"数据库迁移需要至少 {required // (1024 * 1024)}MB 可用空间来创建安全备份"
        )
    temp_path = backup_path.with_suffix(backup_path.suffix + ".tmp")
    temp_path.unlink(missing_ok=True)
    source = sqlite3.connect(path)
    destination = sqlite3.connect(temp_path)
    try:
        source.backup(destination)
        check = destination.execute("PRAGMA quick_check").fetchone()
        if not check or check[0] != "ok":
            raise RuntimeError("数据库迁移备份完整性检查失败")
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
    finally:
        destination.close()
        source.close()
    os.replace(temp_path, backup_path)
    print(f"[migrate] backup created: {backup_path}")


def _backup_before_review_workbench_migration():
    path = _sqlite_path()
    if (
        not path or not path.exists() or path.stat().st_size == 0
        or _migration_applied(path, REVIEW_WORKBENCH_MIGRATION)
    ):
        return
    backup_dir = path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = path.parent / "backups" / f"{path.stem}-pre-review-v10{path.suffix}"
    if backup_path.exists():
        return
    required = path.stat().st_size + 64 * 1024 * 1024
    if shutil.disk_usage(path.parent).free < required:
        raise RuntimeError(
            f"数据库迁移需要至少 {required // (1024 * 1024)}MB 可用空间来创建安全备份"
        )
    temp_path = backup_path.with_suffix(backup_path.suffix + ".tmp")
    temp_path.unlink(missing_ok=True)
    source = sqlite3.connect(path)
    destination = sqlite3.connect(temp_path)
    try:
        source.backup(destination)
        check = destination.execute("PRAGMA quick_check").fetchone()
        if not check or check[0] != "ok":
            raise RuntimeError("数据库迁移备份完整性检查失败")
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
    finally:
        destination.close()
        source.close()
    os.replace(temp_path, backup_path)
    print(f"[migrate] backup created: {backup_path}")


async def _ensure_columns():
    async with engine.begin() as conn:
        for table, cols in EXTRA_COLUMNS.items():
            result = await conn.execute(text(f"PRAGMA table_info({table})"))
            existing = {row[1] for row in result.fetchall()}
            for col, coltype in cols:
                if col not in existing:
                    await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {coltype}"))
                    print(f"[migrate] added column {table}.{col} ({coltype})")

        indexes = [
            ("ix_projects_learner_id", "projects", "learner_id"),
            ("ix_learners_user_id", "learners", "user_id"),
            ("ix_checkpoints_learning_status", "checkpoints", "learning_status"),
            ("ix_tasks_agent_action_id", "tasks", "agent_action_id"),
            ("ix_tasks_learner_id", "tasks", "learner_id"),
            ("ix_agent_messages_idempotency_key", "agent_messages", "idempotency_key"),
            ("ix_evidence_events_occurred_at", "evidence_events", "occurred_at"),
            ("ix_evidence_events_learner_seq", "evidence_events", "learner_seq"),
            ("ix_evidence_events_actor_type", "evidence_events", "actor_type"),
            ("ix_learning_attempts_remediation_case_id", "learning_attempts", "remediation_case_id"),
            ("ix_learning_attempts_attempt_role", "learning_attempts", "attempt_role"),
            ("ix_learning_attempts_client_submission_id", "learning_attempts", "client_submission_id"),
            ("ix_lecture_versions_idempotency_key", "lecture_versions", "idempotency_key"),
        ]
        for name, table, column in indexes:
            unique = "UNIQUE " if name in {
                "ix_agent_messages_idempotency_key",
                "ix_learning_attempts_client_submission_id",
                "ix_lecture_versions_idempotency_key",
            } else ""
            await conn.execute(text(
                f"CREATE {unique}INDEX IF NOT EXISTS {name} ON {table} ({column})"
            ))

        await conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_evidence_learner_seq_idx "
            "ON evidence_events (learner_id, learner_seq)"
        ))
        await conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_session_checkpoint_scope_idx "
            "ON agent_sessions (learner_id, project_id, checkpoint_id) "
            "WHERE session_type = 'checkpoint' AND status = 'active'"
        ))


async def _backfill_five_kernel():
    from app.models.project import Project, Roadmap, Checkpoint, Lecture
    from app.models.learning import (
        Learner, EvidenceEvent, KernelState, AgentSession, AgentMessage,
        SchemaMigration,
    )

    async with async_session() as db:
        applied = (await db.execute(
            select(SchemaMigration).where(SchemaMigration.version == FIVE_KERNEL_MIGRATION)
        )).scalar_one_or_none()
        if applied:
            return

        learner = (await db.execute(
            select(Learner).where(Learner.key == "local-default")
        )).scalar_one_or_none()
        if not learner:
            learner = Learner(key="local-default", display_name="本地学习者")
            db.add(learner)
            await db.flush()

        projects = (await db.execute(select(Project))).scalars().all()
        migration_event_ids = set((await db.execute(
            select(EvidenceEvent.client_event_id).where(
                EvidenceEvent.client_event_id.like("migration:%")
            )
        )).scalars().all())
        for project in projects:
            project.learner_id = learner.id
            event_id = f"migration:project:{project.id}"
            if event_id not in migration_event_ids:
                db.add(EvidenceEvent(
                    learner_id=learner.id,
                    project_id=project.id,
                    event_type="project_imported",
                    source="migration",
                    context_id=f"project:{project.id}",
                    payload={"name": project.name, "description": project.description or ""},
                    confidence=1.0,
                    provenance={"migration": FIVE_KERNEL_MIGRATION},
                    client_event_id=event_id,
                    created_at=project.created_at,
                ))

        existing_kernels = set((await db.execute(
            select(KernelState.kernel_name).where(KernelState.learner_id == learner.id)
        )).scalars().all())
        for kernel_name in ("structure", "knowledge", "human", "value", "practice"):
            if kernel_name not in existing_kernels:
                db.add(KernelState(
                    learner_id=learner.id,
                    kernel_name=kernel_name,
                    short_term={}, long_term={}, action_chain=[], evidence_refs=[], confidence=0.0,
                ))

        lectures = set((await db.execute(select(Lecture.checkpoint_id))).scalars().all())
        checkpoints = (await db.execute(select(Checkpoint))).scalars().all()
        for cp in checkpoints:
            progress = dict(cp.progress or {})
            if not cp.learning_status:
                if cp.completed:
                    cp.learning_status = "verification_due"
                elif cp.id in lectures or progress:
                    cp.learning_status = "in_progress"
                else:
                    cp.learning_status = "not_started"
            if cp.legacy_completed is None:
                cp.legacy_completed = bool(cp.completed)

            brief = dict(cp.brief or {})
            concepts = brief.get("key_concepts") or brief.get("concepts") or []
            if not cp.learning_contract:
                cp.learning_contract = {
                    "concept_ids": concepts,
                    "knowledge_target": {"checkpoint_id": cp.id},
                    "practice_target": {"requires_generation": True},
                    "exit_criteria": ["knowledge_verified", "independent_practice"],
                    "source": "migration",
                }
            roadmap = await db.get(Roadmap, cp.roadmap_id)
            project_id = roadmap.project_id if roadmap else None
            event_id = f"migration:checkpoint:{cp.id}"
            if event_id not in migration_event_ids:
                db.add(EvidenceEvent(
                    learner_id=learner.id,
                    project_id=project_id,
                    checkpoint_id=cp.id,
                    event_type="checkpoint_imported",
                    source="migration",
                    context_id=f"project:{project_id}/checkpoint:{cp.id}",
                    payload={
                        "title": cp.title,
                        "legacy_completed": bool(cp.completed),
                        "has_lecture": cp.id in lectures,
                        "aggregate_progress": progress,
                    },
                    confidence=0.4 if cp.completed else 0.8,
                    provenance={"migration": FIVE_KERNEL_MIGRATION, "aggregate_only": True},
                    client_event_id=event_id,
                    created_at=cp.created_at,
                ))

        global_session = (await db.execute(select(AgentSession).where(
            AgentSession.learner_id == learner.id,
            AgentSession.session_type == "global",
            AgentSession.project_id.is_(None),
        ).limit(1))).scalar_one_or_none()
        if not global_session:
            db.add(AgentSession(
                learner_id=learner.id,
                session_type="global",
                title="学习 Tutor",
                status="active",
            ))

        roadmaps = (await db.execute(select(Roadmap))).scalars().all()
        imported_sessions = (await db.execute(select(AgentSession).where(
            AgentSession.learner_id == learner.id,
            AgentSession.session_type == "project",
        ))).scalars().all()
        imported_project_ids = {
            session.project_id for session in imported_sessions
            if (session.context_summary or {}).get("imported_from") == "roadmap.conversation_history"
        }
        for roadmap in roadmaps:
            history = list(roadmap.conversation_history or [])
            if not history or roadmap.project_id in imported_project_ids:
                continue
            session = AgentSession(
                learner_id=learner.id,
                session_type="project",
                project_id=roadmap.project_id,
                title="项目 Tutor",
                status="active",
                context_summary={"imported_from": "roadmap.conversation_history"},
            )
            db.add(session)
            await db.flush()
            for message in history:
                role = message.get("role") if isinstance(message, dict) else "assistant"
                content = message.get("content", "") if isinstance(message, dict) else str(message)
                if content:
                    db.add(AgentMessage(
                        session_id=session.id,
                        role=role if role in ("user", "assistant") else "assistant",
                        content=content,
                        meta_data={"provenance": "legacy_roadmap_history"},
                    ))

        db.add(SchemaMigration(version=FIVE_KERNEL_MIGRATION))
        await db.commit()
        print(f"[migrate] applied {FIVE_KERNEL_MIGRATION}")


async def _mark_project_proposal_migration():
    from app.models.learning import SchemaMigration

    async with async_session() as db:
        applied = (await db.execute(
            select(SchemaMigration).where(
                SchemaMigration.version == PROJECT_PROPOSAL_MIGRATION
            )
        )).scalar_one_or_none()
        if applied:
            return
        db.add(SchemaMigration(version=PROJECT_PROPOSAL_MIGRATION))
        await db.commit()
        print(f"[migrate] applied {PROJECT_PROPOSAL_MIGRATION}")


async def _backfill_user_isolation():
    from app.models.learning import (
        EvidenceEvent, Learner, UserAccount, LearnerProfile, LearningLifeEvent,
        LearnerBadge, LearningProjectProposal, SchemaMigration,
    )
    from app.models.project import Project, Roadmap, Checkpoint, Task

    async with async_session() as db:
        applied = (await db.execute(select(SchemaMigration).where(
            SchemaMigration.version == USER_ISOLATION_MIGRATION
        ))).scalar_one_or_none()
        if applied:
            return

        legacy_learner = (await db.execute(
            select(Learner).where(Learner.key == "local-default")
        )).scalar_one_or_none()
        legacy_account = (await db.execute(
            select(UserAccount).where(UserAccount.username_normalized == "legacy-demo")
        )).scalar_one_or_none()
        if not legacy_account:
            legacy_account = UserAccount(
                username="legacy-demo",
                username_normalized="legacy-demo",
                password_hash=None,
                is_legacy_demo=True,
            )
            db.add(legacy_account)
            await db.flush()
        if not legacy_learner:
            legacy_learner = Learner(
                user_id=legacy_account.id,
                key="local-default",
                display_name="现有学习者",
            )
            db.add(legacy_learner)
            await db.flush()
        else:
            legacy_learner.user_id = legacy_account.id
            if legacy_learner.display_name == "本地学习者":
                legacy_learner.display_name = "现有学习者"

        orphan_learners = (await db.execute(select(Learner).where(
            Learner.user_id.is_(None), Learner.id != legacy_learner.id,
        ))).scalars().all()
        for learner in orphan_learners:
            normalized = f"legacy-learner-{learner.id}"
            account = (await db.execute(select(UserAccount).where(
                UserAccount.username_normalized == normalized,
            ))).scalar_one_or_none()
            if not account:
                account = UserAccount(
                    username=normalized,
                    username_normalized=normalized,
                    password_hash=None,
                    is_legacy_demo=True,
                )
                db.add(account)
                await db.flush()
            learner.user_id = account.id
            if not await db.get(LearnerProfile, learner.id):
                db.add(LearnerProfile(
                    learner_id=learner.id,
                    education_stage="other",
                    background="由 LearnFlow 单用户版本迁移",
                    focus_areas=[],
                    weekly_hours=5,
                    preferred_modes=["explanation", "project", "practice"],
                    career_goal="",
                    career_goal_status="exploring",
                ))

        profile = await db.get(LearnerProfile, legacy_learner.id)
        if not profile:
            project_names = list((await db.execute(
                select(Project.name).where(Project.learner_id == legacy_learner.id).limit(5)
            )).scalars().all())
            db.add(LearnerProfile(
                learner_id=legacy_learner.id,
                education_stage="other",
                background="由 LearnFlow 单用户版本迁移",
                focus_areas=project_names or ["自主学习"],
                weekly_hours=5,
                preferred_modes=["explanation", "project", "practice"],
                career_goal="",
                career_goal_status="exploring",
            ))

        projects = (await db.execute(select(Project))).scalars().all()
        for project in projects:
            if project.learner_id is None:
                project.learner_id = legacy_learner.id

        tasks = (await db.execute(select(Task))).scalars().all()
        proposals_by_task = {
            item.source_task_id: item.learner_id
            for item in (await db.execute(select(LearningProjectProposal))).scalars().all()
            if item.source_task_id
        }
        project_owner = {project.id: project.learner_id for project in projects}
        for task in tasks:
            if task.learner_id:
                continue
            task.learner_id = project_owner.get(task.project_id) or proposals_by_task.get(task.id) or legacy_learner.id

        for project in projects:
            counts = (await db.execute(
                select(
                    func.count(Checkpoint.id),
                    func.sum((Checkpoint.learning_status == "completed").cast(Integer)),
                )
                .select_from(Roadmap)
                .join(Checkpoint, Checkpoint.roadmap_id == Roadmap.id)
                .where(Roadmap.project_id == project.id, Checkpoint.archived.is_(False))
            )).one()
            total, completed = counts[0] or 0, counts[1] or 0
            if total == 0 or completed != total:
                continue
            dedupe_key = f"project:{project.id}:completed"
            life_event = (await db.execute(select(LearningLifeEvent).where(
                LearningLifeEvent.learner_id == project.learner_id,
                LearningLifeEvent.dedupe_key == dedupe_key,
            ))).scalar_one_or_none()
            if not life_event:
                evidence_key = f"{project.learner_id}:migration:v4:project:{project.id}:completed"
                evidence = (await db.execute(select(EvidenceEvent).where(
                    EvidenceEvent.learner_id == project.learner_id,
                    EvidenceEvent.client_event_id == evidence_key,
                ))).scalar_one_or_none()
                if not evidence:
                    evidence = EvidenceEvent(
                        learner_id=project.learner_id,
                        project_id=project.id,
                        event_type="project_completed",
                        source="migration",
                        context_id=f"project:{project.id}",
                        payload={"project_id": project.id, "name": project.name, "migrated": True},
                        confidence=0.6,
                        provenance={"migration": USER_ISOLATION_MIGRATION},
                        client_event_id=evidence_key,
                    )
                    db.add(evidence)
                    await db.flush()
                life_event = LearningLifeEvent(
                    learner_id=project.learner_id,
                    event_type="project_completed",
                    title=f"完成学习项目：{project.name}",
                    summary="由多用户迁移根据已验证检查点补记",
                    payload={"project_id": project.id, "migrated": True},
                    project_id=project.id,
                    source_event_id=evidence.id,
                    confidence=1.0,
                    dedupe_key=dedupe_key,
                )
                db.add(life_event)
                await db.flush()
            existing_badge = (await db.execute(select(LearnerBadge).where(
                LearnerBadge.learner_id == project.learner_id,
                LearnerBadge.award_key == dedupe_key,
            ))).scalar_one_or_none()
            if not existing_badge:
                db.add(LearnerBadge(
                    learner_id=project.learner_id,
                    badge_type="project_completed",
                    title=f"完成「{project.name}」",
                    description="完成项目中的全部独立验证",
                    icon_key="trophy",
                    color_token="emerald",
                    award_key=dedupe_key,
                    life_event_id=life_event.id,
                    project_id=project.id,
                    meta_data={"migrated": True},
                ))

        db.add(SchemaMigration(version=USER_ISOLATION_MIGRATION))
        await db.commit()
        print(f"[migrate] applied {USER_ISOLATION_MIGRATION}")


async def _backfill_inspectable_memory_graph():
    from app.models.learning import SchemaMigration
    from app.services.memory_graph import backfill_memory_graph

    async with async_session() as db:
        applied = (await db.execute(select(SchemaMigration).where(
            SchemaMigration.version == MEMORY_GRAPH_MIGRATION
        ))).scalar_one_or_none()
        if applied:
            return
        counts = await backfill_memory_graph(db)
        db.add(SchemaMigration(version=MEMORY_GRAPH_MIGRATION))
        await db.commit()
        print(f"[migrate] applied {MEMORY_GRAPH_MIGRATION}: {counts}")


async def _mark_desktop_workspace_migration():
    from app.models.learning import SchemaMigration

    async with async_session() as db:
        applied = (await db.execute(select(SchemaMigration).where(
            SchemaMigration.version == DESKTOP_WORKSPACE_MIGRATION
        ))).scalar_one_or_none()
        if applied:
            return
        db.add(SchemaMigration(version=DESKTOP_WORKSPACE_MIGRATION))
        await db.commit()
        print(f"[migrate] applied {DESKTOP_WORKSPACE_MIGRATION}")


async def _mark_checkpoint_tutor_migration():
    from app.models.learning import SchemaMigration

    async with async_session() as db:
        applied = (await db.execute(select(SchemaMigration).where(
            SchemaMigration.version == CHECKPOINT_TUTOR_MIGRATION
        ))).scalar_one_or_none()
        if applied:
            return
        db.add(SchemaMigration(version=CHECKPOINT_TUTOR_MIGRATION))
        await db.commit()
        print(f"[migrate] applied {CHECKPOINT_TUTOR_MIGRATION}")


async def _migrate_managed_artifacts():
    from app.models.learning import SchemaMigration
    from app.models.project import ArtifactAnnotation, Checkpoint, Lecture, LectureNote, Project, Roadmap

    async with async_session() as db:
        applied = (await db.execute(select(SchemaMigration).where(
            SchemaMigration.version == MANAGED_ARTIFACT_MIGRATION
        ))).scalar_one_or_none()
        if applied:
            return
        legacy_notes = list((await db.execute(select(LectureNote))).scalars().all())
        for note in legacy_notes:
            existing = (await db.execute(select(ArtifactAnnotation).where(
                ArtifactAnnotation.legacy_note_id == note.id,
            ))).scalar_one_or_none()
            if existing:
                continue
            ownership = (await db.execute(
                select(Project.learner_id, Lecture.id, Lecture.version)
                .join(Roadmap, Roadmap.project_id == Project.id)
                .join(Checkpoint, Checkpoint.roadmap_id == Roadmap.id)
                .join(Lecture, Lecture.checkpoint_id == Checkpoint.id)
                .where(Checkpoint.id == note.checkpoint_id)
            )).one_or_none()
            if not ownership or ownership[0] is None:
                continue
            db.add(ArtifactAnnotation(
                learner_id=ownership[0], checkpoint_id=note.checkpoint_id,
                artifact_type="lecture", artifact_id=ownership[1],
                artifact_version=ownership[2] or 1,
                anchor={"section_index": note.section_index, "selection": note.selection or ""},
                body=note.note or "", status="anchored", legacy_note_id=note.id,
                created_at=note.created_at, updated_at=note.updated_at,
            ))
        db.add(SchemaMigration(version=MANAGED_ARTIFACT_MIGRATION))
        await db.commit()
        print(f"[migrate] applied {MANAGED_ARTIFACT_MIGRATION}: {len(legacy_notes)} legacy notes inspected")


async def _mark_local_agent_broker_migration():
    from app.models.learning import SchemaMigration

    async with async_session() as db:
        applied = (await db.execute(select(SchemaMigration).where(
            SchemaMigration.version == LOCAL_AGENT_BROKER_MIGRATION
        ))).scalar_one_or_none()
        if applied:
            return
        db.add(SchemaMigration(version=LOCAL_AGENT_BROKER_MIGRATION))
        await db.commit()
        print(f"[migrate] applied {LOCAL_AGENT_BROKER_MIGRATION}")


async def _backfill_review_workbench():
    from app.models.learning import SchemaMigration
    from app.services.review import rebuild_review_schedules

    async with async_session() as db:
        applied = (await db.execute(select(SchemaMigration).where(
            SchemaMigration.version == REVIEW_WORKBENCH_MIGRATION
        ))).scalar_one_or_none()
        if applied:
            return
        count = await rebuild_review_schedules(db)
        db.add(SchemaMigration(version=REVIEW_WORKBENCH_MIGRATION))
        await db.commit()
        print(f"[migrate] applied {REVIEW_WORKBENCH_MIGRATION}: {count} attempts projected")


async def init_db():
    _backup_before_five_kernel_migration()
    _backup_before_project_proposal_migration()
    _backup_before_user_isolation_migration()
    _backup_before_memory_graph_migration()
    _backup_before_desktop_workspace_migration()
    _backup_before_checkpoint_tutor_migration()
    _backup_before_managed_artifact_migration()
    _backup_before_review_workbench_migration()
    async with engine.begin() as conn:
        from app.models import project, learning  # noqa: F401
        await conn.run_sync(Base.metadata.create_all)
    await _ensure_columns()
    await _backfill_five_kernel()
    await _mark_project_proposal_migration()
    await _backfill_user_isolation()
    await _backfill_inspectable_memory_graph()
    await _mark_desktop_workspace_migration()
    await _mark_checkpoint_tutor_migration()
    await _migrate_managed_artifacts()
    await _mark_local_agent_broker_migration()
    await _backfill_review_workbench()
