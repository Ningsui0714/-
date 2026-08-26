"""five_kernel_reducer：EvidenceEvent -> KernelMutation（确定性、纯函数）。

规则注册于 docs/ARCHITECTURE_AUTHORITY.md 与 backend/learner_discovery/registry.py。
- 处理器签名：handler(event, states, policy)，states 为 {kernel: state_dict}；
- 只修改事件契约允许的 Kernel；保留 before/after、reason、evidence ref；
- 版本号由持久化层（session._record_event）替换为真实版本。
"""

from __future__ import annotations

import copy
from typing import Any

from backend.learner_discovery.models import (
    EvidenceEvent,
    stable_id,
    utc_now,
)
from backend.learner_discovery.kernels import (
    compute_kc_confidence,
    compute_kc_status,
    default_kc_state,
    default_kernel_state,
)


def _now() -> str:
    return utc_now()


def _mutation(
    event: EvidenceEvent,
    kernel: str,
    subject: str,
    mutation_type: str,
    before: dict[str, Any],
    after: dict[str, Any],
    reason: str,
    version: int = 0,
) -> dict[str, Any]:
    return {
        "mutation_id": stable_id("MUT", event.event_id, kernel, subject, mutation_type),
        "kernel": kernel,
        "subject": subject,
        "mutation_type": mutation_type,
        "before": before,
        "after": after,
        "reason": reason,
        "evidence_ref": event.event_id,
        "version": version,
    }


def _knowledge(states: dict[str, Any]) -> dict[str, Any]:
    return states.setdefault("knowledge", default_kernel_state("knowledge"))


def _structure(states: dict[str, Any]) -> dict[str, Any]:
    return states.setdefault("structure", default_kernel_state("structure"))


def _practice(states: dict[str, Any]) -> dict[str, Any]:
    return states.setdefault("practice", default_kernel_state("practice"))


def _value(states: dict[str, Any]) -> dict[str, Any]:
    return states.setdefault("value", default_kernel_state("value"))


def _kc_state(state: dict[str, Any], kc_id: str) -> dict[str, Any]:
    kcs = state.setdefault("kcs", {})
    if kc_id not in kcs:
        kcs[kc_id] = default_kc_state(kc_id)
    return kcs[kc_id]


# ---------------------------------------------------------------------------
# value 目标
# ---------------------------------------------------------------------------

def _reduce_goal_candidate_stated(
    event: EvidenceEvent, states: dict[str, Any], policy: dict[str, Any]
) -> list[dict[str, Any]]:
    state = _value(states)
    text = str(event.payload.get("text") or event.payload.get("goal_candidate") or "").strip()
    desired_outcome = str(event.payload.get("desired_outcome") or "").strip()
    before = dict(state)
    candidates = state.setdefault("goal_candidates", [])
    existing = next((c for c in candidates if str(c.get("text", "")).strip() == text), None)
    if existing is None:
        candidates.append({
            "text": text,
            "confirmed": False,
            "desired_outcome": desired_outcome,
            "events": [event.event_id],
        })
    else:
        existing["desired_outcome"] = desired_outcome or existing.get("desired_outcome", "")
        events = list(existing.setdefault("events", []))
        if event.event_id not in events:
            events.append(event.event_id)
        existing["events"] = events
    return [_mutation(
        event, "value", text or "goal", "value_goal_candidate", before, state,
        f"学习者自述目标候选：{text or '(空)'}",
    )]


def _reduce_goal_clarified(
    event: EvidenceEvent, states: dict[str, Any], policy: dict[str, Any]
) -> list[dict[str, Any]]:
    state = _value(states)
    text = str(event.payload.get("text") or event.payload.get("goal_candidate") or "").strip()
    desired_outcome = str(event.payload.get("desired_outcome") or "").strip()
    before = dict(state)
    candidates = state.setdefault("goal_candidates", [])
    if not candidates and text:
        candidates.append({
            "text": text, "confirmed": False,
            "desired_outcome": desired_outcome, "events": [event.event_id],
        })
    else:
        candidate = candidates[-1] if candidates else {}
        if desired_outcome:
            candidate["desired_outcome"] = desired_outcome
        if text and str(candidate.get("text", "")).strip() != text:
            candidate["text"] = text
        events = list(candidate.setdefault("events", []))
        if event.event_id not in events:
            events.append(event.event_id)
        candidate["events"] = events
    return [_mutation(
        event, "value", text or "goal", "value_goal_clarified", before, state,
        f"目标澄清：desired_outcome={desired_outcome or '(未提供)'}",
    )]


def _reduce_goal_confirmed(
    event: EvidenceEvent, states: dict[str, Any], policy: dict[str, Any]
) -> list[dict[str, Any]]:
    value = _value(states)
    goal_id = str(event.payload.get("goal_id") or "").strip()
    label = str(event.payload.get("goal_label") or goal_id or "").strip()
    text = str(event.payload.get("text") or "").strip()
    desired_outcome = str(event.payload.get("desired_outcome") or "").strip()
    before_value = dict(value)
    value["confirmed_goal"] = goal_id or None
    value["confirmed_goal_label"] = label or None
    value["confirmed_outcome"] = desired_outcome or None
    candidates = value.setdefault("goal_candidates", [])
    if text and not any(str(c.get("text", "")).strip() == text for c in candidates):
        candidates.append({
            "text": text, "confirmed": True,
            "desired_outcome": desired_outcome, "events": [event.event_id],
        })
    for candidate in candidates:
        if text and str(candidate.get("text", "")).strip() == text:
            candidate["confirmed"] = True
            candidate["goal_id"] = goal_id
    mutations = [_mutation(
        event, "value", goal_id or "goal", "value_goal_confirmed", before_value, value,
        f"学习者确认目标：{label or goal_id or '(自由输入)'}",
    )]
    structure = _structure(states)
    before_structure = dict(structure)
    position = structure.setdefault("position", {})
    position["phase"] = "diagnosing"
    structure["recovery_anchor"] = {
        "project_id": event.scope.project_id or "",
        "checkpoint_id": event.scope.checkpoint_id or "",
        "session_id": event.scope.session_id or "",
    }
    mutations.append(_mutation(
        event, "structure", "session", "structure_position", before_structure, structure,
        "目标确认后进入诊断阶段，锚定 project/checkpoint",
    ))
    return mutations


# ---------------------------------------------------------------------------
# structure 位置
# ---------------------------------------------------------------------------

def _reduce_discovery_session_started(
    event: EvidenceEvent, states: dict[str, Any], policy: dict[str, Any]
) -> list[dict[str, Any]]:
    state = _structure(states)
    before = dict(state)
    position = state.setdefault("position", {})
    position["session_status"] = "started"
    position["phase"] = str(event.payload.get("phase") or "goal_clarification")
    state["recovery_anchor"] = {
        "project_id": event.scope.project_id or "",
        "checkpoint_id": event.scope.checkpoint_id or "",
        "session_id": event.scope.session_id or "",
    }
    return [_mutation(
        event, "structure", "session", "structure_position", before, state,
        "发现会话开始，记录恢复锚点",
    )]


def _reduce_question_presented(
    event: EvidenceEvent, states: dict[str, Any], policy: dict[str, Any]
) -> list[dict[str, Any]]:
    state = _structure(states)
    before = dict(state)
    question_id = str(event.payload.get("question_id") or "").strip()
    seen = state.setdefault("seen_question_ids", [])
    if question_id and question_id not in seen:
        seen.append(question_id)
    position = state.setdefault("position", {})
    position["question_index"] = int(event.payload.get("question_index", position.get("question_index", 0)))
    position["total_questions"] = int(event.payload.get("total_questions", position.get("total_questions", 0)))
    position["phase"] = str(event.payload.get("phase") or position.get("phase") or "diagnosing")
    return [_mutation(
        event, "structure", "session", "structure_question_seen", before, state,
        f"展示题目 {question_id or '(无)'}",
    )]


def _reduce_discovery_session_completed(
    event: EvidenceEvent, states: dict[str, Any], policy: dict[str, Any]
) -> list[dict[str, Any]]:
    state = _structure(states)
    before = dict(state)
    position = state.setdefault("position", {})
    position["session_status"] = str(event.payload.get("status") or "completed")
    position["phase"] = "done"
    return [_mutation(
        event, "structure", "session", "structure_position", before, state,
        f"发现会话结束：{position['session_status']}",
    )]

# ---------------------------------------------------------------------------
# knowledge 掌握
# ---------------------------------------------------------------------------

def _apply_answer_to_kc(
    event: EvidenceEvent, state: dict[str, Any], policy: dict[str, Any]
) -> dict[str, Any]:
    payload = event.payload or {}
    kc_id = str(payload.get("knowledge_point_id") or "").strip()
    question_id = str(payload.get("question_id") or "").strip()
    correct = bool(payload.get("correct"))
    assisted = bool(payload.get("assisted"))
    kc = _kc_state(state, kc_id)
    evidence = kc.setdefault("evidence", {})
    distinct = list(evidence.setdefault("distinct_question_ids", []))
    if question_id and question_id not in distinct:
        distinct.append(question_id)
    evidence["distinct_question_ids"] = distinct
    if correct and not assisted:
        correct_ids = list(evidence.setdefault("correct_question_ids", []))
        if question_id and question_id not in correct_ids:
            correct_ids.append(question_id)
        evidence["correct_question_ids"] = correct_ids
        evidence["distinct_independent_correct"] = len(correct_ids)
        kc["last_graded_correct"] = True
    elif correct and assisted:
        evidence["assisted"] = int(evidence.get("assisted", 0) or 0) + 1
        kc["last_graded_correct"] = True
    else:
        evidence["wrong"] = int(evidence.get("wrong", 0) or 0) + 1
        kc["last_graded_correct"] = False
        misconception_id = str(payload.get("misconception_id") or "").strip()
        if misconception_id:
            candidates = kc.setdefault("misconception_candidates", [])
            existing = next(
                (c for c in candidates if str(c.get("misconception_id", "")) == misconception_id),
                None,
            )
            if existing is None:
                candidates.append({
                    "misconception_id": misconception_id,
                    "count": 1,
                    "events": [event.event_id],
                })
            else:
                existing["count"] = int(existing.get("count", 0) or 0) + 1
                events = list(existing.setdefault("events", []))
                if event.event_id not in events:
                    events.append(event.event_id)
                existing["events"] = events
    kc["status"] = compute_kc_status(kc, policy)
    kc["confidence"] = round(compute_kc_confidence(kc), 3)
    kc["last_evidence_at"] = _now()
    return kc


def _reduce_answer_submitted(
    event: EvidenceEvent, states: dict[str, Any], policy: dict[str, Any]
) -> list[dict[str, Any]]:
    payload = event.payload or {}
    kc_id = str(payload.get("knowledge_point_id") or "").strip()
    knowledge = _knowledge(states)
    kc = _kc_state(knowledge, kc_id)
    before = dict(kc)
    kc = _apply_answer_to_kc(event, knowledge, policy)
    knowledge.setdefault("kcs", {})[kc_id] = kc
    correct = bool(payload.get("correct"))
    assisted = bool(payload.get("assisted"))
    outcome = "辅助答对" if (correct and assisted) else ("独立答对" if correct else "答错")
    reason = f"{outcome}：{payload.get('question_id', '')} -> {before.get('status')} -> {kc.get('status')}"
    mutations = [_mutation(
        event, "knowledge", kc_id, "knowledge_answer_graded", before, kc, reason,
    )]
    mutations.extend(_reduce_practice_for_answer(event, states, policy))
    return mutations


def _reduce_answer_skipped(
    event: EvidenceEvent, states: dict[str, Any], policy: dict[str, Any]
) -> list[dict[str, Any]]:
    payload = event.payload or {}
    kc_id = str(payload.get("knowledge_point_id") or "").strip()
    knowledge = _knowledge(states)
    kc = _kc_state(knowledge, kc_id)
    before = dict(kc)
    evidence = kc.setdefault("evidence", {})
    evidence["skipped"] = int(evidence.get("skipped", 0) or 0) + 1
    kc["status"] = compute_kc_status(kc, policy)
    kc["last_evidence_at"] = _now()
    knowledge.setdefault("kcs", {})[kc_id] = kc
    mutations = [_mutation(
        event, "knowledge", kc_id, "knowledge_skipped", before, kc,
        "跳过本题：记录未作答，不视为知识错误",
    )]
    structure = _structure(states)
    before_s = dict(structure)
    position = structure.setdefault("position", {})
    position["question_index"] = int(payload.get("question_index", 0) or 0) + 1
    position["phase"] = "diagnosing"
    mutations.append(_mutation(
        event, "structure", "session", "structure_position", before_s, structure,
        "跳过：位置推进",
    ))
    return mutations


def _reduce_answer_hazy(
    event: EvidenceEvent, states: dict[str, Any], policy: dict[str, Any]
) -> list[dict[str, Any]]:
    payload = event.payload or {}
    kc_id = str(payload.get("knowledge_point_id") or "").strip()
    knowledge = _knowledge(states)
    kc = _kc_state(knowledge, kc_id)
    before = dict(kc)
    evidence = kc.setdefault("evidence", {})
    evidence["hazy"] = int(evidence.get("hazy", 0) or 0) + 1
    kc["status"] = compute_kc_status(kc, policy)
    kc["last_evidence_at"] = _now()
    knowledge.setdefault("kcs", {})[kc_id] = kc
    return [_mutation(
        event, "knowledge", kc_id, "knowledge_hazy", before, kc,
        "含糊回答：标记不确定性，等待澄清",
    )]


def _reduce_reasoning_explained(
    event: EvidenceEvent, states: dict[str, Any], policy: dict[str, Any]
) -> list[dict[str, Any]]:
    payload = event.payload or {}
    kc_id = str(payload.get("knowledge_point_id") or "").strip()
    matches = payload.get("matches_rubric")
    knowledge = _knowledge(states)
    kc = _kc_state(knowledge, kc_id)
    before = dict(kc)
    evidence = kc.setdefault("evidence", {})
    if matches is True:
        evidence["explained_ok"] = int(evidence.get("explained_ok", 0) or 0) + 1
        reason = "解释与 Rubric 匹配：支持该 KC 的理解证据"
    else:
        evidence["need_review"] = int(evidence.get("need_review", 0) or 0) + 1
        reason = "解释无法可靠判定或与 Rubric 不符：保留原始回答待复查"
    kc["status"] = compute_kc_status(kc, policy)
    kc["confidence"] = round(compute_kc_confidence(kc), 3)
    kc["last_evidence_at"] = _now()
    knowledge.setdefault("kcs", {})[kc_id] = kc
    return [_mutation(
        event, "knowledge", kc_id, "knowledge_reasoning", before, kc, reason,
    )]


def _reduce_evidence_correction(
    event: EvidenceEvent, states: dict[str, Any], policy: dict[str, Any]
) -> list[dict[str, Any]]:
    payload = event.payload or {}
    kc_id = str(payload.get("knowledge_point_id") or "").strip()
    recomputed = payload.get("recomputed") or {}
    knowledge = _knowledge(states)
    kc = _kc_state(knowledge, kc_id)
    before = dict(kc)
    if recomputed:
        kc.clear()
        kc.update(copy.deepcopy(recomputed))
    corrected = list(kc.setdefault("corrected_event_ids", []))
    target = str(payload.get("target_event_id") or "")
    if target and target not in corrected:
        corrected.append(target)
    kc["corrected_event_ids"] = corrected
    kc["status"] = compute_kc_status(kc, policy)
    kc["confidence"] = round(compute_kc_confidence(kc), 3)
    kc["last_evidence_at"] = _now()
    knowledge.setdefault("kcs", {})[kc_id] = kc
    mutations = [_mutation(
        event, "knowledge", kc_id, "knowledge_corrected", before, kc,
        f"用户纠正/归档证据 {target or '(无)'}：状态重算 -> {kc.get('status')}",
    )]
    # practice 同步降级
    practice = _practice(states)
    entry = dict(practice.get("independence", {}).get(kc_id) or {
        "level": "untested", "assisted_events": [], "independent_events": [], "transfer_events": [],
    })
    before_p = dict(entry)
    independent = int(recomputed.get("evidence", {}).get("distinct_independent_correct", 0) or 0)
    assisted = int(recomputed.get("evidence", {}).get("assisted", 0) or 0)
    if independent >= 1:
        entry["level"] = "applied"
    elif assisted >= 1:
        entry["level"] = "assisted"
    else:
        entry["level"] = "untested"
    practice.setdefault("independence", {})[kc_id] = entry
    mutations.append(_mutation(
        event, "practice", kc_id, "practice_independence", before_p, entry,
        f"纠正后独立性 -> {entry.get('level')}",
    ))
    return mutations


# ---------------------------------------------------------------------------
# practice 独立实践
# ---------------------------------------------------------------------------

def _reduce_practice_for_answer(
    event: EvidenceEvent, states: dict[str, Any], policy: dict[str, Any]
) -> list[dict[str, Any]]:
    payload = event.payload or {}
    kc_id = str(payload.get("knowledge_point_id") or "").strip()
    correct = bool(payload.get("correct"))
    assisted = bool(payload.get("assisted"))
    transfer = bool(payload.get("transfer"))
    practice = _practice(states)
    independence = practice.setdefault("independence", {})
    entry = dict(independence.get(kc_id) or {
        "level": "untested", "assisted_events": [], "independent_events": [], "transfer_events": [],
    })
    before = dict(entry)
    if correct and assisted:
        entry["level"] = "assisted"
        events = list(entry.setdefault("assisted_events", []))
        if event.event_id not in events:
            events.append(event.event_id)
        entry["assisted_events"] = events
    elif correct and not assisted:
        events = list(entry.setdefault("independent_events", []))
        if event.event_id not in events:
            events.append(event.event_id)
        entry["independent_events"] = events
        if transfer:
            entry["level"] = "transferred"
            transfer_events = list(entry.setdefault("transfer_events", []))
            if event.event_id not in transfer_events:
                transfer_events.append(event.event_id)
            entry["transfer_events"] = transfer_events
        elif entry.get("level") in ("untested", "assisted"):
            entry["level"] = "applied"
    independence[kc_id] = entry
    return [_mutation(
        event, "practice", kc_id, "practice_independence", before, entry,
        f"独立性更新 -> {entry.get('level')}",
    )]


def _reduce_assisted_success(
    event: EvidenceEvent, states: dict[str, Any], policy: dict[str, Any]
) -> list[dict[str, Any]]:
    payload = event.payload or {}
    kc_id = str(payload.get("knowledge_point_id") or "").strip()
    knowledge = _knowledge(states)
    kc = _kc_state(knowledge, kc_id)
    before_kc = dict(kc)
    evidence = kc.setdefault("evidence", {})
    evidence["assisted"] = int(evidence.get("assisted", 0) or 0) + 1
    kc["status"] = compute_kc_status(kc, policy)
    kc["last_evidence_at"] = _now()
    knowledge.setdefault("kcs", {})[kc_id] = kc
    mutations = [_mutation(
        event, "knowledge", kc_id, "knowledge_assisted", before_kc, kc,
        "辅助后成功：支持'在帮助下可以完成'，不升级独立掌握",
    )]
    practice = _practice(states)
    entry = dict(practice.get("independence", {}).get(kc_id) or {
        "level": "untested", "assisted_events": [], "independent_events": [], "transfer_events": [],
    })
    before_p = dict(entry)
    entry["level"] = "assisted"
    events = list(entry.setdefault("assisted_events", []))
    if event.event_id not in events:
        events.append(event.event_id)
    entry["assisted_events"] = events
    practice.setdefault("independence", {})[kc_id] = entry
    mutations.append(_mutation(
        event, "practice", kc_id, "practice_independence", before_p, entry,
        "独立性 -> assisted",
    ))
    return mutations


# ---------------------------------------------------------------------------
# human 教学适配
# ---------------------------------------------------------------------------

def _reduce_preference_stated(
    event: EvidenceEvent, states: dict[str, Any], policy: dict[str, Any]
) -> list[dict[str, Any]]:
    state = states.setdefault("human", default_kernel_state("human"))
    mode = str(event.payload.get("mode") or "").strip()
    kind = str(event.payload.get("kind") or "preference")
    before = dict(state)
    preferences = state.setdefault("preferences", [])
    existing = next((p for p in preferences if str(p.get("mode", "")) == mode), None)
    if existing is None:
        preferences.append({
            "mode": mode,
            "kind": kind,
            "status": "candidate",
            "events": [event.event_id],
        })
    else:
        existing["status"] = "candidate"
        events = list(existing.setdefault("events", []))
        if event.event_id not in events:
            events.append(event.event_id)
        existing["events"] = events
    return [_mutation(
        event, "human", mode or "preference", "human_preference", before, state,
        f"学习者明确偏好：{mode or '(未提供)'}",
    )]


# ---------------------------------------------------------------------------
# 分发
# ---------------------------------------------------------------------------

_HANDLERS: dict[str, Any] = {
    "goal_candidate_stated": _reduce_goal_candidate_stated,
    "goal_clarified": _reduce_goal_clarified,
    "goal_confirmed": _reduce_goal_confirmed,
    "discovery_session_started": _reduce_discovery_session_started,
    "question_presented": _reduce_question_presented,
    "answer_submitted": _reduce_answer_submitted,
    "answer_skipped": _reduce_answer_skipped,
    "answer_hazy": _reduce_answer_hazy,
    "reasoning_explained": _reduce_reasoning_explained,
    "assisted_success": _reduce_assisted_success,
    "preference_stated": _reduce_preference_stated,
    "discovery_session_completed": _reduce_discovery_session_completed,
    "evidence_correction": _reduce_evidence_correction,
}

_KERNEL_TARGETS: dict[str, tuple[str, ...]] = {
    "goal_candidate_stated": ("value",),
    "goal_clarified": ("value",),
    "goal_confirmed": ("value", "structure"),
    "discovery_session_started": ("structure",),
    "question_presented": ("structure",),
    "answer_submitted": ("knowledge", "practice"),
    "answer_skipped": ("knowledge", "structure"),
    "answer_hazy": ("knowledge",),
    "reasoning_explained": ("knowledge",),
    "assisted_success": ("knowledge", "practice"),
    "preference_stated": ("human",),
    "discovery_session_completed": ("structure",),
    "evidence_correction": ("knowledge", "practice"),
}


def reduce_event(
    event: EvidenceEvent,
    state_by_kernel: dict[str, dict[str, Any]],
    policy: dict[str, Any] | None = None,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """对事件应用确定性 Reducer。

    入参 state_by_kernel：事件各 target Kernel 当前状态（调用方按 target scope 加载）。
    返回 (new_state_by_kernel, mutations)。版本号由持久化层替换。
    """
    handler = _HANDLERS.get(event.event_type)
    if handler is None:
        raise KeyError(f"未登记的 Reducer 规则：{event.event_type}")
    policy = policy or {}
    new_states: dict[str, dict[str, Any]] = {}
    for kernel in _KERNEL_TARGETS.get(event.event_type, ()):
        base = state_by_kernel.get(kernel)
        if base is None:
            base = default_kernel_state(kernel)
        new_states[kernel] = copy.deepcopy(base)
    mutations = handler(event, new_states, policy)
    return new_states, mutations
