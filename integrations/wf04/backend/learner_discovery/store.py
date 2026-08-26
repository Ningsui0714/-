"""Discovery 持久化：Evidence Ledger / KernelState / KernelMutations / MemoryGraph / Sessions。

所有表与现有学习主库（backend/server.py StateStore 的 database_path）共用同一 SQLite 文件，
但通过独立前缀表名隔离；模块不建立与 Evidence Ledger、KernelState 并列的长期事实权威。
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import closing
from pathlib import Path
from typing import Any

from backend.learner_discovery.models import (
    EvidenceEvent,
    Scope,
    SessionPolicy,
    scope_key,
    utc_now,
)
from backend.learner_discovery.registry import KERNELS


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {}
    return {}


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except (json.JSONDecodeError, TypeError):
            return []
    return []


class DiscoveryStore:
    """发现模块持久化存储（线程安全，幂等建表）。"""

    def __init__(self, database_path: Path | str):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.database_path), timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _init_schema(self) -> None:
        with self._lock, closing(self._connect()) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS ld_evidence_events (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    learner_id TEXT NOT NULL,
                    project_id TEXT NOT NULL DEFAULT '',
                    checkpoint_id TEXT NOT NULL DEFAULT '',
                    session_id TEXT NOT NULL DEFAULT '',
                    client_event_id TEXT NOT NULL,
                    kernel_targets_json TEXT NOT NULL,
                    evidence_role TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    payload_json TEXT NOT NULL,
                    artifact_refs_json TEXT NOT NULL,
                    provenance_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE (learner_id, client_event_id)
                );
                CREATE INDEX IF NOT EXISTS idx_ld_events_learner
                    ON ld_evidence_events(learner_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_ld_events_session
                    ON ld_evidence_events(learner_id, session_id, created_at);

                CREATE TABLE IF NOT EXISTS ld_kernel_state (
                    scope_key TEXT NOT NULL,
                    kernel TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (scope_key, kernel)
                );

                CREATE TABLE IF NOT EXISTS ld_kernel_mutations (
                    mutation_id TEXT PRIMARY KEY,
                    scope_key TEXT NOT NULL,
                    kernel TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    mutation_type TEXT NOT NULL,
                    before_json TEXT NOT NULL,
                    after_json TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    evidence_event_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_ld_mutations_event
                    ON ld_kernel_mutations(evidence_event_id);

                CREATE TABLE IF NOT EXISTS ld_memory_facts (
                    fact_id TEXT PRIMARY KEY,
                    scope_key TEXT NOT NULL,
                    kernel TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    claim TEXT NOT NULL,
                    status TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    evidence_refs_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    archived INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_ld_facts_scope
                    ON ld_memory_facts(scope_key, kernel);

                CREATE TABLE IF NOT EXISTS ld_memory_modules (
                    module_id TEXT PRIMARY KEY,
                    scope_key TEXT NOT NULL,
                    kernel TEXT NOT NULL,
                    summary_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS ld_memory_claims (
                    claim_id TEXT PRIMARY KEY,
                    scope_key TEXT NOT NULL,
                    kernel TEXT NOT NULL,
                    statement TEXT NOT NULL,
                    status TEXT NOT NULL,
                    fact_ids_json TEXT NOT NULL,
                    evidence_trace_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    archived INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS ld_discovery_sessions (
                    session_id TEXT PRIMARY KEY,
                    learner_id TEXT NOT NULL,
                    project_id TEXT NOT NULL DEFAULT '',
                    checkpoint_id TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    seed INTEGER NOT NULL,
                    policy_json TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_ld_sessions_learner
                    ON ld_discovery_sessions(learner_id, updated_at DESC);
                """
            )
            connection.commit()

    # ------------------------------------------------------------------
    # Evidence Ledger
    # ------------------------------------------------------------------

    def save_event(self, event: EvidenceEvent) -> bool:
        """写入事件；同一 (learner_id, client_event_id) 重复时返回 False（幂等）。"""
        with self._lock, closing(self._connect()) as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO ld_evidence_events(
                        event_id, event_type, learner_id, project_id, checkpoint_id,
                        session_id, client_event_id, kernel_targets_json, evidence_role,
                        confidence, payload_json, artifact_refs_json, provenance_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.event_id,
                        event.event_type,
                        str(event.scope.learner_id or ""),
                        str(event.scope.project_id or ""),
                        str(event.scope.checkpoint_id or ""),
                        str(event.scope.session_id or ""),
                        event.client_event_id,
                        _json_text(event.kernel_targets),
                        event.evidence_role,
                        float(event.confidence),
                        _json_text(event.payload),
                        _json_text(event.artifact_refs),
                        _json_text(event.provenance),
                        event.created_at,
                    ),
                )
                connection.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def get_event(self, event_id: str) -> dict[str, Any] | None:
        with self._lock, closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM ld_evidence_events WHERE event_id = ?", (event_id,)
            ).fetchone()
        return self._row_to_event(row) if row else None

    def get_event_by_client_id(self, learner_id: str, client_event_id: str) -> dict[str, Any] | None:
        with self._lock, closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM ld_evidence_events WHERE learner_id = ? AND client_event_id = ?",
                (learner_id, client_event_id),
            ).fetchone()
        return self._row_to_event(row) if row else None

    def list_events(
        self,
        learner_id: str,
        session_id: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        with self._lock, closing(self._connect()) as connection:
            if session_id:
                rows = connection.execute(
                    "SELECT * FROM ld_evidence_events WHERE learner_id = ? AND session_id = ? "
                    "ORDER BY created_at, event_id LIMIT ?",
                    (learner_id, session_id, limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM ld_evidence_events WHERE learner_id = ? "
                    "ORDER BY created_at, event_id LIMIT ?",
                    (learner_id, limit),
                ).fetchall()
        return [self._row_to_event(row) for row in rows if row]

    def recent_events(
        self, learner_id: str, project_id: str | None, limit: int = 20
    ) -> list[dict[str, Any]]:
        project = project_id or ""
        with self._lock, closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM ld_evidence_events WHERE learner_id = ? AND project_id = ? "
                "ORDER BY created_at DESC, event_id DESC LIMIT ?",
                (learner_id, project, limit),
            ).fetchall()
        return [self._row_to_event(row) for row in rows if row]

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "event_id": str(row["event_id"]),
            "event_type": str(row["event_type"]),
            "scope": {
                "learner_id": str(row["learner_id"]),
                "project_id": str(row["project_id"]) or None,
                "checkpoint_id": str(row["checkpoint_id"]) or None,
                "session_id": str(row["session_id"]) or None,
            },
            "client_event_id": str(row["client_event_id"]),
            "kernel_targets": _as_list(row["kernel_targets_json"]),
            "evidence_role": str(row["evidence_role"]),
            "confidence": float(row["confidence"]),
            "payload": _as_dict(row["payload_json"]),
            "artifact_refs": _as_list(row["artifact_refs_json"]),
            "provenance": _as_dict(row["provenance_json"]),
            "created_at": str(row["created_at"]),
        }

    # ------------------------------------------------------------------
    # KernelState
    # ------------------------------------------------------------------

    def load_kernel_state(self, scope: Scope, kernel: str) -> tuple[dict[str, Any], int]:
        key = scope_key(scope)
        with self._lock, closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT state_json, version FROM ld_kernel_state WHERE scope_key = ? AND kernel = ?",
                (key, kernel),
            ).fetchone()
        if row:
            return _as_dict(row["state_json"]), int(row["version"])
        return {}, 0

    def save_kernel_state(
        self, scope: Scope, kernel: str, state: dict[str, Any], version: int
    ) -> None:
        key = scope_key(scope)
        now = utc_now()
        with self._lock, closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO ld_kernel_state(scope_key, kernel, state_json, version, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(scope_key, kernel)
                DO UPDATE SET state_json = excluded.state_json,
                              version = excluded.version,
                              updated_at = excluded.updated_at
                """,
                (key, kernel, _json_text(state), int(version), now),
            )
            connection.commit()

    def load_all_kernel_state(self, scope: Scope) -> dict[str, tuple[dict[str, Any], int]]:
        key = scope_key(scope)
        with self._lock, closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT kernel, state_json, version FROM ld_kernel_state WHERE scope_key = ?",
                (key,),
            ).fetchall()
        return {str(row["kernel"]): (_as_dict(row["state_json"]), int(row["version"])) for row in rows}

    def append_mutation(self, mutation: dict[str, Any], scope: Scope) -> None:
        key = scope_key(scope)
        now = utc_now()
        with self._lock, closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO ld_kernel_mutations(
                    mutation_id, scope_key, kernel, subject, mutation_type,
                    before_json, after_json, reason, evidence_event_id, version, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(mutation.get("mutation_id", "")),
                    key,
                    str(mutation.get("kernel", "")),
                    str(mutation.get("subject", "")),
                    str(mutation.get("mutation_type", "")),
                    _json_text(mutation.get("before", {})),
                    _json_text(mutation.get("after", {})),
                    str(mutation.get("reason", "")),
                    str(mutation.get("evidence_ref", "")),
                    int(mutation.get("version", 0)),
                    now,
                ),
            )
            connection.commit()

    def list_mutations_for_event(self, event_id: str) -> list[dict[str, Any]]:
        with self._lock, closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM ld_kernel_mutations WHERE evidence_event_id = ? ORDER BY created_at",
                (event_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # Memory Graph（派生视图）
    # ------------------------------------------------------------------

    def replace_memory_for_scope(self, scope: Scope, facts: list[dict[str, Any]],
                                 modules: list[dict[str, Any]], claims: list[dict[str, Any]]) -> None:
        key = scope_key(scope)
        now = utc_now()
        with self._lock, closing(self._connect()) as connection:
            connection.execute(
                "DELETE FROM ld_memory_facts WHERE scope_key = ?", (key,)
            )
            connection.execute(
                "DELETE FROM ld_memory_modules WHERE scope_key = ?", (key,)
            )
            connection.execute(
                "DELETE FROM ld_memory_claims WHERE scope_key = ?", (key,)
            )
            for fact in facts:
                connection.execute(
                    """
                    INSERT INTO ld_memory_facts(
                        fact_id, scope_key, kernel, subject, claim, status, confidence,
                        evidence_refs_json, created_at, updated_at, archived
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                    """,
                    (
                        fact["fact_id"], key, fact["kernel"], fact["subject"], fact["claim"],
                        fact["status"], float(fact["confidence"]),
                        _json_text(fact.get("evidence_refs", [])), now, now,
                    ),
                )
            for module in modules:
                connection.execute(
                    """
                    INSERT INTO ld_memory_modules(module_id, scope_key, kernel, summary_json, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (module["module_id"], key, module["kernel"], _json_text(module.get("summary", {})), now),
                )
            for claim in claims:
                connection.execute(
                    """
                    INSERT INTO ld_memory_claims(
                        claim_id, scope_key, kernel, statement, status, fact_ids_json,
                        evidence_trace_json, created_at, updated_at, archived
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                    """,
                    (
                        claim["claim_id"], key, claim["kernel"], claim["statement"],
                        claim["status"], _json_text(claim.get("fact_ids", [])),
                        _json_text(claim.get("evidence_trace", [])), now, now,
                    ),
                )
            connection.commit()

    def load_memory_graph(self, scope: Scope) -> dict[str, Any]:
        key = scope_key(scope)
        with self._lock, closing(self._connect()) as connection:
            facts = connection.execute(
                "SELECT * FROM ld_memory_facts WHERE scope_key = ? ORDER BY confidence DESC",
                (key,),
            ).fetchall()
            modules = connection.execute(
                "SELECT * FROM ld_memory_modules WHERE scope_key = ?", (key,)
            ).fetchall()
            claims = connection.execute(
                "SELECT * FROM ld_memory_claims WHERE scope_key = ?", (key,)
            ).fetchall()
        return {
            "facts": [dict(row) for row in facts],
            "modules": [dict(row) for row in modules],
            "claims": [dict(row) for row in claims],
        }

    # ------------------------------------------------------------------
    # Discovery Sessions
    # ------------------------------------------------------------------

    def save_session(self, session: dict[str, Any]) -> None:
        now = utc_now()
        with self._lock, closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO ld_discovery_sessions(
                    session_id, learner_id, project_id, checkpoint_id, status, seed,
                    policy_json, state_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    status = excluded.status,
                    policy_json = excluded.policy_json,
                    state_json = excluded.state_json,
                    updated_at = excluded.updated_at
                """,
                (
                    session["session_id"],
                    session["learner_id"],
                    session.get("project_id") or "",
                    session.get("checkpoint_id") or "",
                    session["status"],
                    int(session.get("seed", 20260811)),
                    _json_text(session.get("policy", {})),
                    _json_text(session.get("state", {})),
                    session.get("created_at") or now,
                    now,
                ),
            )
            connection.commit()

    def load_session(self, session_id: str) -> dict[str, Any] | None:
        with self._lock, closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM ld_discovery_sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
        if not row:
            return None
        return {
            "session_id": str(row["session_id"]),
            "learner_id": str(row["learner_id"]),
            "project_id": str(row["project_id"]) or None,
            "checkpoint_id": str(row["checkpoint_id"]) or None,
            "status": str(row["status"]),
            "seed": int(row["seed"]),
            "policy": _as_dict(row["policy_json"]),
            "state": _as_dict(row["state_json"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }

    def list_sessions(self, learner_id: str, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock, closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM ld_discovery_sessions WHERE learner_id = ? "
                "ORDER BY updated_at DESC LIMIT ?",
                (learner_id, limit),
            ).fetchall()
        return [
            {
                "session_id": str(row["session_id"]),
                "learner_id": str(row["learner_id"]),
                "project_id": str(row["project_id"]) or None,
                "status": str(row["status"]),
                "seed": int(row["seed"]),
                "created_at": str(row["created_at"]),
                "updated_at": str(row["updated_at"]),
            }
            for row in rows
        ]
