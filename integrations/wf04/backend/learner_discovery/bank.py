"""题目源适配：复用现有本地题库 / 目标图谱，并支持种子化确定性取样。

离线 seeded 模式不依赖外部模型；远程模式可把本模块的候选交给工作流生成，
但生成结果必须经过 validator.validate_question 才能入库展示。
"""

from __future__ import annotations

import random
from typing import Any

try:  # 以包方式运行
    from backend.data.diagnosis_bank import DIAGNOSIS_BANK, DIAGNOSIS_GOALS
    from backend.data.goal_graph import GOALS, KNOWLEDGE_POINTS
    from backend.data.error_cards import ERROR_CARDS
except Exception:  # 直接以脚本方式运行
    from data.diagnosis_bank import DIAGNOSIS_BANK, DIAGNOSIS_GOALS
    from data.goal_graph import GOALS, KNOWLEDGE_POINTS
    from data.error_cards import ERROR_CARDS

from backend.learner_discovery.validator import validate_question


def goal_key_for(goal_id: str | None) -> str:
    """项目目标 id -> 诊断取样键（缺省 daily）。"""
    if not goal_id:
        return "daily"
    mapping = {
        "GOAL-JAVA-001": "daily",
        "GOAL-JAVA-COMPETITION": "competition",
        "GOAL-JAVA-CERT": "certification",
        "GOAL-JAVA-DAILY": "daily",
    }
    return mapping.get(goal_id, "daily")


def goal_label_for(goal_id: str | None) -> str:
    goal = GOALS.get(goal_id or "")
    if goal:
        return str(goal.get("goal_name") or goal.get("name") or goal.get("label") or goal_id or "")
    return goal_id or ""


def knowledge_point_name(kc_id: str) -> str:
    kp = KNOWLEDGE_POINTS.get(kc_id) or {}
    return str(kp.get("knowledge_point_name") or kc_id)


def list_knowledge_point_ids(goal_id: str | None) -> list[str]:
    """目标覆盖的知识点（有题可用的）按图谱顺序返回。"""
    goal_key = goal_key_for(goal_id)
    ordered: list[str] = []
    for question in DIAGNOSIS_BANK:
        goals = question.get("goals")
        if goals and goal_key not in goals:
            continue
        kc = str(question.get("knowledge_point_id") or "").strip()
        if kc and kc not in ordered:
            ordered.append(kc)
    return ordered


def questions_for_goal(goal_id: str | None) -> list[dict[str, Any]]:
    goal_key = goal_key_for(goal_id)
    questions: list[dict[str, Any]] = []
    for question in DIAGNOSIS_BANK:
        goals = question.get("goals")
        if goals and goal_key not in goals:
            continue
        valid, _ = validate_question(question)
        if valid:
            questions.append(dict(question))
    return questions


def pick_question(
    kc_id: str,
    goal_id: str | None,
    seen_ids: list[str],
    seed: int,
    exclude: set[str] | None = None,
) -> dict[str, Any] | None:
    """按 KC 与已见题，种子化确定性取题（候选必须通过校验）。"""
    exclude = exclude or set()
    goal_key = goal_key_for(goal_id)
    pool: list[dict[str, Any]] = []
    for question in DIAGNOSIS_BANK:
        goals = question.get("goals")
        if goals and goal_key not in goals:
            continue
        qid = str(question.get("id") or question.get("question_id") or "")
        if str(question.get("knowledge_point_id") or "") != kc_id:
            continue
        if qid in seen_ids or qid in exclude:
            continue
        valid, _ = validate_question(question)
        if valid:
            pool.append(question)
    if not pool:
        return None
    rng = random.Random(f"{seed}:{kc_id}")
    rng.shuffle(pool)
    pool.sort(key=lambda q: int(q.get("difficulty", 2) or 2))
    return pool[0]


def misconception_id_for(kc_id: str, wrong_selected: str, expected: str) -> str:
    """答错时映射错误卡（确定性）：优先命中与错误选项语义一致的卡片，否则 generic。"""
    cards = ERROR_CARDS.get(kc_id) or []
    if cards:
        card = cards[0]
        return str(card.get("error_id") or f"GENERIC_{kc_id}")
    return f"GENERIC_{kc_id}"


def question_public(question: dict[str, Any]) -> dict[str, Any]:
    """剔除 answer/explanation 的对外展示版本。"""
    return {k: v for k, v in question.items() if k not in ("answer", "explanation")}


def question_by_id(question_id: str) -> dict[str, Any] | None:
    """按稳定 id 查找题目（供演示/测试拿到答案进行回放）。"""
    for question in DIAGNOSIS_BANK:
        if str(question.get("id") or question.get("question_id") or "") == question_id:
            valid, _ = validate_question(question)
            if valid:
                return dict(question)
    return None
