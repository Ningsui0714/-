"""下一轮交互选择器：基于五核投影的证据缺口做确定性决策。

决策逻辑（可记录、可解释）：
1. 目标未确认 -> clarification（先确认目标与期望产物，成本最低）
2. 有未完成的追问预算且存在待追问 -> reasoning_probe / prerequisite_probe
3. 无待追问 -> 按知识核不确定性优先级选题（untested > candidate > verified_once > stable）
4. 预算耗尽 / 连续跳过 / 证据已足够 -> complete（提前结束）
"""

from __future__ import annotations

import random
from typing import Any

from backend.learner_discovery.models import (
    KernelProjection,
    NextInteraction,
)
from backend.learner_discovery import bank

try:  # 包方式
    from backend.data.goal_graph import DEPENDENCIES
except Exception:  # 脚本方式
    from data.goal_graph import DEPENDENCIES

KC_PRIORITY = {
    "untested": 1.0,
    "candidate": 0.8,
    "verified_once": 0.6,
    "stable": 0.2,
}


def _kc_priority(kc_id: str, knowledge: dict[str, Any]) -> float:
    kc = knowledge.get("kcs", {}).get(kc_id) or {}
    status = kc.get("status", "untested")
    priority = KC_PRIORITY.get(status, 0.5)
    if kc.get("misconception_candidates"):
        priority = max(priority, 0.9)
    return priority


def _rank_kcs(kc_ids: list[str], knowledge: dict[str, Any], seed: int) -> list[str]:
    ranked = sorted(
        kc_ids,
        key=lambda kc: (-_kc_priority(kc, knowledge), kc),
    )
    # 同优先级内种子化稳定打散（确定性）
    rng = random.Random(f"rank:{seed}")
    buckets: dict[float, list[str]] = {}
    for kc in ranked:
        buckets.setdefault(_kc_priority(kc, knowledge), []).append(kc)
    result: list[str] = []
    for priority in sorted(buckets, reverse=True):
        bucket = list(buckets[priority])
        rng.shuffle(bucket)
        result.extend(bucket)
    return result


def select_next_question(
    projection: KernelProjection,
    goal_id: str | None,
    seen_ids: list[str],
    seed: int,
    exclude: set[str] | None = None,
) -> tuple[NextInteraction | None, str | None]:
    """选择下一道题：返回 (interaction, 被选中 KC)。无可用题返回 (None, None)。"""
    knowledge = projection.kernels.get("knowledge", {})
    kc_ids = bank.list_knowledge_point_ids(goal_id)
    ranked = _rank_kcs(kc_ids, knowledge, seed)
    for kc_id in ranked:
        question = bank.pick_question(kc_id, goal_id, seen_ids, seed, exclude=exclude)
        if question is None:
            continue
        kc = knowledge.get("kcs", {}).get(kc_id) or {}
        status = kc.get("status", "untested")
        reason = {
            "untested": "该知识点尚无评分证据，优先级最高",
            "candidate": "该知识点已有候选/错误证据，需要进一步确认",
            "verified_once": "该知识点仅单次独立正确，需要巩固验证",
            "stable": "该知识点已较稳定，本轮不再重点追问",
        }.get(status, "常规选题")
        if kc.get("misconception_candidates"):
            reason = "该知识点存在误解候选，需要再次验证"
        content = {
            "question_id": str(question.get("id") or question.get("question_id") or ""),
            "knowledge_point_id": kc_id,
            "knowledge_point_name": bank.knowledge_point_name(kc_id),
            "title": question.get("title", ""),
            "options": question.get("options", {}),
            "difficulty": question.get("difficulty", 1),
            "question_version": "v1",
        }
        interaction = NextInteraction(
            kind="question",
            purpose=f"{reason}；本问用于确认或排除对 {bank.knowledge_point_name(kc_id)} 的掌握",
            content=content,
        )
        return interaction, kc_id
    return None, None


def decide_next(
    projection: KernelProjection,
    session_state: dict[str, Any],
    policy: dict[str, Any],
    goal_id: str | None,
) -> NextInteraction:
    """会话主决策：返回下一轮交互。session_state 需含 budget/followup/pending 等。"""
    value = projection.kernels.get("value", {})
    knowledge = projection.kernels.get("knowledge", {})

    # 1) 目标未确认
    if not value.get("confirmed_goal") and session_state.get("phase") in (
        "goal_clarification", "created", "clarifying", ""
    ):
        candidates = value.get("goal_candidates", [])
        candidate_text = ""
        if candidates:
            candidate_text = str(candidates[-1].get("text", "") or "")
        return NextInteraction(
            kind="clarification",
            purpose="确认学习目标与期望产物：目标决定了本轮要降低哪部分不确定性",
            content={
                "candidate": candidate_text,
                "desired_outcome": session_state.get("desired_outcome") or "",
                "prompt": "请确认：你想学什么、期望达到什么结果？（可补充难度/节奏偏好）",
            },
        )

    # 2) 待追问（答错后的理由追问 / 前置追问），受 followup 预算约束
    pending = session_state.get("pending_followup")
    followup_used = int(session_state.get("followup_used", 0) or 0)
    followup_budget = int(policy.get("followup_budget", 2))
    if pending and followup_used < followup_budget:
        kind = str(pending.get("kind") or "reasoning_probe")
        question = pending.get("question") or {}
        content = {
            "question_id": str(question.get("id") or question.get("question_id") or ""),
            "knowledge_point_id": str(question.get("knowledge_point_id") or ""),
            "knowledge_point_name": bank.knowledge_point_name(
                str(question.get("knowledge_point_id") or "")
            ),
            "title": question.get("title", ""),
            "options": question.get("options", {}),
            "followup": True,
            "prompt": (
                "这道题你选错了。能说说你的思考过程吗？"
                if kind == "reasoning_probe"
                else "这道题可能依赖前置知识。你觉得自己是哪里卡住了？"
            ),
        }
        return NextInteraction(kind=kind, purpose="区分误解与前置缺口，降低知识核不确定性", content=content)

    # 3) 停止条件
    if int(session_state.get("interaction_count", 0) or 0) >= int(
        policy.get("interaction_budget", 8)
    ):
        return NextInteraction(
            kind="complete",
            purpose="交互预算已耗尽",
            content={"status": "insufficient_evidence", "reason": "interaction_budget_exhausted"},
        )
    if int(session_state.get("consecutive_skips", 0) or 0) >= int(
        policy.get("skip_limit", 2)
    ):
        return NextInteraction(
            kind="complete",
            purpose="连续跳过达到阈值，继续追问收益低于用户成本",
            content={"status": "insufficient_evidence", "reason": "skip_limit_reached"},
        )

    # 4) 证据已足够 -> 提前结束（收益低于用户成本）
    kc_ids = bank.list_knowledge_point_ids(goal_id)
    coverage = _evidence_coverage(knowledge, kc_ids)
    complete_coverage = float(policy.get("complete_coverage", 0.5))
    if coverage >= complete_coverage:
        return NextInteraction(
            kind="complete",
            purpose=f"已验证知识点覆盖率达到 {coverage:.0%}，继续提问收益低于用户成本",
            content={"status": "completed", "reason": "evidence_sufficient", "coverage": round(coverage, 3)},
        )

    # 5) 选题
    seen_ids = list(session_state.get("seen_question_ids", []))
    interaction, _ = select_next_question(
        projection, goal_id, seen_ids, int(policy.get("seed", 20260811)),
    )
    if interaction is not None:
        return interaction

    # 6) 无题可用 -> 检查证据是否足够
    kc_ids = bank.list_knowledge_point_ids(goal_id)
    evidence_coverage = _evidence_coverage(knowledge, kc_ids)
    if evidence_coverage >= complete_coverage:
        return NextInteraction(
            kind="complete",
            purpose="题库已用尽且已有可用证据",
            content={"status": "completed", "reason": "bank_exhausted"},
        )
    return NextInteraction(
        kind="complete",
        purpose="题库已用尽且证据不足",
        content={"status": "insufficient_evidence", "reason": "bank_exhausted"},
    )


def _evidence_coverage(knowledge: dict[str, Any], kc_ids: list[str]) -> float:
    if not kc_ids:
        return 0.0
    covered = 0
    for kc_id in kc_ids:
        kc = knowledge.get("kcs", {}).get(kc_id) or {}
        if kc.get("status") in ("verified_once", "stable"):
            covered += 1
    return covered / len(kc_ids)


def recommended_action(status: str, projection: KernelProjection) -> str:
    """从结束状态推导 recommended_next_action（可检查原因）。"""
    knowledge = projection.kernels.get("knowledge", {})
    misconceptions = [
        kc for kc in knowledge.get("kcs", {}).values() if kc.get("misconception_candidates")
    ]
    if status == "completed":
        if misconceptions:
            return "start_remediation"
        return "begin_learning"
    if status == "insufficient_evidence":
        return "continue_discovery"
    if status == "stopped":
        return "request_confirmation"
    return "continue_discovery"
