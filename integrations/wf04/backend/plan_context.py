"""PlanContext：学习计划自适应上下文（生成前构建，注入学习计划）。

从项目 state 确定性构建，不暴露 mastery 原始值 / reason_code / policy JSON；
只输出计划生成需要的高层结论（known / candidate / unknown / review / background / style）。

分类规则：
- `evidence_status in {supported, verified_once}` 且有正式 `source_event_ids` → known。
- `evidence_status in {needs_support, developing}` 且有正式 `source_event_ids` → review。
- `evidence_status = candidate` 且有正式 `source_event_ids` → candidate（待验证）。
- 没有正式 `source_event_ids` → unknown。
- 学习者自评、计划步骤完成、AI 讲解完成不得进入 known/review。
"""

from __future__ import annotations

from typing import Any

KNOWN_STATUSES = frozenset({"supported", "verified_once"})
REVIEW_STATUSES = frozenset({"needs_support", "developing"})
CANDIDATE_STATUSES = frozenset({"candidate"})

# 与 _goal_duration / _goal_intake_daily_minutes 解析出的约束键保持一致
_SELF_REPORT_CONSTRAINT_KEYS = (
    ("goal_intake_career_stage", "career_stage"),
    ("goal_intake_tech_stack", "tech_stack"),
    ("goal_intake_help_focus", "help_focus"),
)


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _str(value: Any) -> str:
    return "" if value is None else str(value)


def _path_item_map(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("knowledge_point_id") or ""): item
        for item in _as_list(
            _as_dict(state.get("learning_path")).get("items")
        )
        if isinstance(item, dict) and str(item.get("knowledge_point_id") or "")
    }


def classify_knowledge_points(state: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """按正式证据把目标知识范围分为 known / review / candidate / unknown。

    known/review 只接受带 `source_event_ids` 的正式测评证据；自评、计划完成、
    讲解完成都不能进入这些正式证据分类。返回四类点列表，每个点含
    knowledge_point_id / knowledge_point_name / source_event_ids / evidence_status。
    """
    by_id = _path_item_map(state)
    known: list[dict[str, Any]] = []
    unknown: list[dict[str, Any]] = []
    review: list[dict[str, Any]] = []
    candidate: list[dict[str, Any]] = []
    for raw_point in _as_list(state.get("goal_knowledge_points")):
        point = _as_dict(raw_point)
        point_id = str(point.get("knowledge_point_id") or "").strip()
        if not point_id:
            continue
        path_item = _as_dict(by_id.get(point_id))
        source_event_ids = [
            str(event_id)
            for event_id in _as_list(path_item.get("source_event_ids"))
            if str(event_id)
        ]
        item = {
            "knowledge_point_id": point_id,
            "knowledge_point_name": str(
                point.get("knowledge_point_name") or point_id
            ),
            "source_event_ids": source_event_ids,
        }
        evidence_status = str(path_item.get("evidence_status") or "unassessed")
        if source_event_ids and evidence_status in KNOWN_STATUSES:
            known.append({**item, "evidence_status": evidence_status})
        elif source_event_ids and evidence_status in REVIEW_STATUSES:
            review.append({**item, "evidence_status": evidence_status})
        elif source_event_ids and evidence_status in CANDIDATE_STATUSES:
            candidate.append({**item, "evidence_status": evidence_status})
        else:
            unknown.append(item)
    return {
        "known": known,
        "candidate": candidate,
        "unknown": unknown,
        "review": review,
    }


def _background_facts(state: dict[str, Any]) -> list[str]:
    """把用户显式目标约束整理为人类可读背景，不进入掌握度结论。"""
    facts: list[str] = []
    goal = _as_dict(state.get("goal"))
    constraints = _as_dict(goal.get("constraints"))
    for _report_type, constraint_key in _SELF_REPORT_CONSTRAINT_KEYS:
        value = _str(constraints.get(constraint_key)).strip()
        if value:
            facts.append(value)
    current_level = _str(constraints.get("current_level")).strip()
    if current_level:
        facts.append(f"当前水平自述：{current_level}")
    preferred_style = _str(constraints.get("preferred_teaching_style")).strip()
    if preferred_style:
        facts.append(f"偏好讲解方式：{preferred_style}")
    return facts[:6]


def build_plan_context(state: dict[str, Any]) -> dict[str, Any]:
    """构建 PlanContext（只含必要信息，不塞整份 Learner Model / 项目 state）。"""
    classified = classify_knowledge_points(state)
    goal = _as_dict(state.get("goal"))
    constraints = _as_dict(goal.get("constraints"))
    preferences = _as_dict(state.get("learner_preferences"))

    daily_minutes = int(
        preferences.get("daily_minutes")
        or constraints.get("daily_minutes")
        or 0
    ) or None
    duration_days = int(constraints.get("estimated_days") or 0) or None

    preferred_style = str(
        preferences.get("preferred_teaching_style")
        or constraints.get("preferred_teaching_style")
        or ""
    ).strip()
    preferred_delivery = str(
        preferences.get("preferred_delivery_mode") or ""
    ).strip()

    background = _background_facts(state)
    source_policy = (
        "仅使用正式测评的 source_event_ids 归类；学习者自评、计划完成、"
        "讲解完成不构成掌握度。"
    )

    return {
        **classified,
        # 兼容现有 API 命名：known/candidate/unknown/review 已由 classify 返回
        "known_points": classified["known"],
        "candidate_points": classified["candidate"],
        "unknown_points": classified["unknown"],
        "review_points": classified["review"],
        "background": background,
        "preferred_style": preferred_style,
        "preferred_delivery": preferred_delivery,
        "daily_minutes": daily_minutes,
        "duration_days": duration_days,
        "source_policy": source_policy,
        "last_assessment_id": str(
            _as_dict(state.get("current_profile")).get("assessment_id") or ""
        ),
    }
