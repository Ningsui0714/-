"""五核状态：默认投影、知识状态机、投影读取包。

知识状态机（确定性，见 docs/ARCHITECTURE_AUTHORITY.md 第 5 节）：
- untested           无任何证据
- candidate          有候选/错误/跳过/辅助/含糊证据，但无独立掌握证据
- verified_once      >=1 道不同题独立正确（且近期未被错误推翻）
- stable             >=2 道不同题独立正确（且错误模式不显著）
"""

from __future__ import annotations

from typing import Any

from backend.learner_discovery.models import (
    EvidenceEvent,
    KernelProjection,
    Scope,
    scope_key,
)
from backend.learner_discovery.registry import KERNELS

KERNEL_NAMES = {
    "structure": "structure（位置与进度）",
    "knowledge": "knowledge（概念掌握）",
    "human": "human（教学适配）",
    "value": "value（目标与动机）",
    "practice": "practice（独立实践）",
}


def default_kernel_state(kernel: str) -> dict[str, Any]:
    if kernel == "structure":
        return {
            "position": {
                "session_status": "not_started",
                "phase": "",
                "question_index": 0,
                "total_questions": 0,
            },
            "seen_question_ids": [],
            "recovery_anchor": {},
        }
    if kernel == "knowledge":
        return {"kcs": {}}
    if kernel == "human":
        return {"preferences": [], "load_signals": []}
    if kernel == "value":
        return {
            "goal_candidates": [],
            "confirmed_goal": None,
            "confirmed_outcome": None,
            "confirmed_goal_label": None,
        }
    if kernel == "practice":
        return {"independence": {}}
    return {}


def default_kc_state(kc_id: str) -> dict[str, Any]:
    return {
        "kc_id": kc_id,
        "status": "untested",
        "confidence": 0.0,
        "evidence": {
            "distinct_independent_correct": 0,
            "wrong": 0,
            "skipped": 0,
            "hazy": 0,
            "assisted": 0,
            "explained_ok": 0,
            "need_review": 0,
            "distinct_question_ids": [],
        },
        "misconception_candidates": [],
        "corrected_event_ids": [],
        "last_graded_correct": None,
        "last_evidence_at": "",
    }


def compute_kc_status(state: dict[str, Any], policy: dict[str, Any] | None = None) -> str:
    """根据证据计数确定 KC 状态（确定性）。

    规则：
    1. 错误模式显著（>=2 次）-> candidate（误解置信度上升）
    2. 独立正确 >= stable_threshold 且错误 == 0 -> stable
    3. 独立正确 >= stable_threshold 且错误 == 1 -> verified_once（单次失误降一级）
    4. 独立正确 >= verified_threshold -> verified_once；最近判题为错误 -> candidate（近期证据推翻）
    5. 有任何非独立证据（错误/含糊/辅助/待复查）-> candidate
    6. 跳过不改变状态（记录未作答，不视为知识错误）
    """
    evidence = state.get("evidence", {})
    independent = int(evidence.get("distinct_independent_correct", 0) or 0)
    wrong = int(evidence.get("wrong", 0) or 0)
    stable_threshold = int((policy or {}).get("stable_threshold", 2))
    verified_threshold = int((policy or {}).get("verified_threshold", 1))
    last_correct = state.get("last_graded_correct")

    if wrong >= 2:
        return "candidate"
    if independent >= stable_threshold:
        if wrong == 0:
            return "stable"
        return "verified_once"
    if independent >= verified_threshold:
        if last_correct is False:
            return "candidate"
        return "verified_once"
    if independent == 0:
        if (
            wrong > 0
            or int(evidence.get("hazy", 0) or 0) > 0
            or int(evidence.get("assisted", 0) or 0) > 0
            or int(evidence.get("need_review", 0) or 0) > 0
        ):
            return "candidate"
        return "untested"
    return "candidate"


def compute_kc_confidence(state: dict[str, Any]) -> float:
    evidence = state.get("evidence", {})
    independent = int(evidence.get("distinct_independent_correct", 0) or 0)
    wrong = int(evidence.get("wrong", 0) or 0)
    hazy = int(evidence.get("hazy", 0) or 0)
    explained = int(evidence.get("explained_ok", 0) or 0)
    confidence = 0.5 + 0.15 * independent + 0.08 * explained - 0.2 * wrong - 0.1 * hazy
    return max(0.05, min(0.95, confidence))


def touch_kc(state: dict[str, Any], kc_id: str, at: str) -> dict[str, Any]:
    kcs = state.setdefault("kcs", {})
    if kc_id not in kcs:
        kcs[kc_id] = default_kc_state(kc_id)
    kcs[kc_id]["last_evidence_at"] = at
    return state


def empty_projection(scope: Scope) -> KernelProjection:
    return KernelProjection(
        scope=scope,
        kernels={kernel: default_kernel_state(kernel) for kernel in KERNELS},
        versions={kernel: 0 for kernel in KERNELS},
        recent_evidence=[],
    )


def assemble_projection(
    scope: Scope,
    states: dict[str, dict[str, Any]],
    versions: dict[str, int],
    recent_evidence: list[dict[str, Any]],
) -> KernelProjection:
    kernels: dict[str, dict[str, Any]] = {}
    final_versions: dict[str, int] = {}
    for kernel in KERNELS:
        state = states.get(kernel)
        if state is None:
            state = default_kernel_state(kernel)
        if kernel == "knowledge":
            # 确保所有 KC 有显式默认状态
            state = dict(state)
            state["kcs"] = {k: dict(v) for k, v in state.get("kcs", {}).items()}
        kernels[kernel] = state
        final_versions[kernel] = int(versions.get(kernel, 0) or 0)
    return KernelProjection(
        scope=scope,
        kernels=kernels,
        versions=final_versions,
        recent_evidence=recent_evidence,
    )


def projection_for(scope: Scope, states: dict[str, dict[str, Any]],
                   versions: dict[str, int], recent_evidence: list[dict[str, Any]]) -> KernelProjection:
    return assemble_projection(scope, states, versions, recent_evidence)


def subject_of(event: EvidenceEvent) -> str:
    """事件的主要 subject（KC / goal / session / preference），供 mutation 使用。"""
    payload = event.payload or {}
    return str(
        payload.get("knowledge_point_id")
        or payload.get("kc_id")
        or payload.get("goal_id")
        or payload.get("subject")
        or "session"
    )


def target_scopes(event: EvidenceEvent) -> dict[str, Scope]:
    """事件各 Kernel 目标持久化 scope（knowledge/practice/human/value 项目级，structure 会话级）。"""
    return {
        kernel: Scope(
            learner_id=event.scope.learner_id,
            project_id=event.scope.project_id,
            checkpoint_id=event.scope.checkpoint_id,
            session_id=event.scope.session_id,
        )
        for kernel in event.kernel_targets
    }
