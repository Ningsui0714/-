"""Learner State Discovery 核心数据模型。

本模块使用 stdlib 即可运行（无第三方依赖），保证离线 seeded 模式可跑。
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def scope_key(scope: "Scope") -> str:
    """稳定 scope 键：learner|project|checkpoint|session（空串表示无）。"""
    return "|".join(
        [
            str(scope.learner_id or ""),
            str(scope.project_id or ""),
            str(scope.checkpoint_id or ""),
            str(scope.session_id or ""),
        ]
    )


def scope_key_for(kernel: str, scope: "Scope") -> str:
    """各核的持久化 scope：
    - knowledge / practice / human / value：项目级（跨会话累积证据）
    - structure：会话级（位置与进度）
    """
    if kernel == "structure":
        return "|".join(
            [str(scope.learner_id or ""), str(scope.project_id or ""), str(scope.checkpoint_id or ""), str(scope.session_id or "")]
        )
    return "|".join([str(scope.learner_id or ""), str(scope.project_id or ""), "", ""])


def stable_id(prefix: str, *parts: str) -> str:
    raw = "|".join(parts)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


@dataclass
class Scope:
    learner_id: str
    project_id: str | None = None
    checkpoint_id: str | None = None
    session_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "learner_id": self.learner_id,
            "project_id": self.project_id,
            "checkpoint_id": self.checkpoint_id,
            "session_id": self.session_id,
        }


@dataclass
class EvidenceEvent:
    """规范化证据事件（唯一合法的状态变化输入）。"""

    event_type: str
    scope: Scope
    payload: dict[str, Any]
    kernel_targets: list[str]
    evidence_role: str
    confidence: float
    client_event_id: str
    event_id: str = ""
    artifact_refs: list[str] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.event_id:
            self.event_id = new_id("EV")
        if not self.created_at:
            self.created_at = utc_now()

    def as_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "scope": self.scope.as_dict(),
            "payload": self.payload,
            "kernel_targets": list(self.kernel_targets),
            "evidence_role": self.evidence_role,
            "confidence": self.confidence,
            "client_event_id": self.client_event_id,
            "artifact_refs": list(self.artifact_refs),
            "provenance": self.provenance,
            "created_at": self.created_at,
        }


@dataclass
class KernelMutation:
    """Reducer 输出：对某个 Kernel 的一个确定性变更。"""

    kernel: str
    subject: str
    mutation_type: str
    before: dict[str, Any]
    after: dict[str, Any]
    reason: str
    evidence_ref: str  # evidence event_id
    version: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "kernel": self.kernel,
            "subject": self.subject,
            "mutation_type": self.mutation_type,
            "before": self.before,
            "after": self.after,
            "reason": self.reason,
            "evidence_ref": self.evidence_ref,
            "version": self.version,
        }


@dataclass
class Observation:
    """对外输出的观察：本次交互实际支持的有限、可追溯观察。"""

    kernel: str
    subject: str
    claim: str
    status: str  # candidate | supported | verified_once | unknown
    confidence: float
    evidence_refs: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "kernel": self.kernel,
            "subject": self.subject,
            "claim": self.claim,
            "status": self.status,
            "confidence": round(float(self.confidence), 3),
            "evidence_refs": list(self.evidence_refs),
        }


@dataclass
class NextInteraction:
    """下一轮交互建议（对外语义，不是 Kernel patch）。"""

    kind: str  # clarification | question | reasoning_probe | prerequisite_probe | state_check | complete
    purpose: str
    content: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "purpose": self.purpose,
            "content": self.content,
        }


@dataclass
class KernelProjection:
    """有 scope 的五核投影（读取包）。"""

    scope: Scope
    kernels: dict[str, dict[str, Any]] = field(default_factory=dict)
    versions: dict[str, int] = field(default_factory=dict)
    recent_evidence: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "scope": self.scope.as_dict(),
            "kernels": self.kernels,
            "versions": self.versions,
            "recent_evidence": self.recent_evidence,
        }


@dataclass
class SessionPolicy:
    """运行时策略（确定性可重放）。"""

    seed: int = 20260811
    interaction_budget: int = 8
    followup_budget: int = 2
    skip_limit: int = 2
    stable_threshold: int = 2  # 同一 KC ≥2 道不同题独立正确 -> stable
    verified_threshold: int = 1  # 同一 KC ≥1 道题独立正确 -> verified_once
    complete_coverage: float = 0.5  # 已验证 KC 覆盖率达到该比例 -> 提前结束
    time_budget_seconds: int = 180
    offline_mode: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "interaction_budget": self.interaction_budget,
            "followup_budget": self.followup_budget,
            "skip_limit": self.skip_limit,
            "stable_threshold": self.stable_threshold,
            "verified_threshold": self.verified_threshold,
            "complete_coverage": self.complete_coverage,
            "time_budget_seconds": self.time_budget_seconds,
            "offline_mode": self.offline_mode,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "SessionPolicy":
        return cls(
            seed=int(raw.get("seed", 20260811)),
            interaction_budget=int(raw.get("interaction_budget", 8)),
            followup_budget=int(raw.get("followup_budget", 2)),
            skip_limit=int(raw.get("skip_limit", 2)),
            stable_threshold=int(raw.get("stable_threshold", 2)),
            verified_threshold=int(raw.get("verified_threshold", 1)),
            complete_coverage=float(raw.get("complete_coverage", 0.5)),
            time_budget_seconds=int(raw.get("time_budget_seconds", 180)),
            offline_mode=bool(raw.get("offline_mode", True)),
        )
