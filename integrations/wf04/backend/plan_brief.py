"""PlanBrief：确定性解释“为什么这样安排学习计划”。

完全由后端规则 + 正式证据构建，不调用大模型；只解释系统规则与证据，
不暴露内部 ID、reason code 或原始 JSON。未评估知识点属于 unassessed_skills，
绝不等于掌握度 0（UNKNOWN ≠ skill gap）。
"""

from __future__ import annotations

from typing import Any

try:
    from backend.data.goal_graph import DEPENDENCIES
except ModuleNotFoundError:
    from data.goal_graph import DEPENDENCIES
try:
    from backend.plan_context import build_plan_context
except ModuleNotFoundError:
    from plan_context import build_plan_context


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _str(value: Any) -> str:
    return "" if value is None else str(value)


def _path_item_map(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("knowledge_point_id") or ""): item
        for item in _as_list(_as_dict(state.get("learning_path")).get("items"))
        if isinstance(item, dict) and str(item.get("knowledge_point_id") or "")
    }


def _plan_steps(state: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        step
        for stage in _as_list(
            _as_dict(state.get("learning_plan")).get("stages")
        )
        if isinstance(stage, dict)
        for step in _as_list(stage.get("steps"))
        if isinstance(step, dict)
    ]


def _dependencies(state: dict[str, Any]) -> dict[str, list[str]]:
    """构建计划内依赖 DAG：优先节点自带 prerequisites，其次能力图谱。"""
    path_by_id = _path_item_map(state)
    deps: dict[str, list[str]] = {}
    for point_id in path_by_id:
        declared = [
            str(prereq)
            for prereq in _as_list(path_by_id[point_id].get("prerequisites"))
            if str(prereq)
        ]
        graph_deps = [
            str(prereq) for prereq in _as_list(DEPENDENCIES.get(point_id))
            if str(prereq)
        ]
        candidates = declared or graph_deps
        deps[point_id] = [prereq for prereq in candidates if prereq in path_by_id]
    return deps


def _critical_path(state: dict[str, Any], name_of: dict[str, str]) -> list[str]:
    """真实 DAG 最长路径（Kahn 拓扑序 + DP），不取列表前 N 个节点。"""
    deps = _dependencies(state)
    nodes = list(deps.keys())
    if not nodes:
        return []
    children: dict[str, list[str]] = {k: [] for k in nodes}
    indegree: dict[str, int] = {k: 0 for k in nodes}
    for source, targets in deps.items():
        for target in targets:
            children[source].append(target)
            indegree[target] += 1
    order: list[str] = []
    queue = [k for k, indeg in indegree.items() if indeg == 0]
    while queue:
        node = queue.pop(0)
        order.append(node)
        for child in children.get(node, []):
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)
    if len(order) != len(nodes):
        order = nodes

    dist: dict[str, int] = {}
    parent: dict[str, str | None] = {}
    for node in order:
        best = 0
        best_parent: str | None = None
        for prereq in deps.get(node, []):
            if dist.get(prereq, 0) + 1 > best:
                best = dist.get(prereq, 0) + 1
                best_parent = prereq
        dist[node] = best
        parent[node] = best_parent
    if not order:
        return []
    end = max(order, key=lambda k: dist.get(k, 0))
    path_ids: list[str] = []
    current: str | None = end
    while current is not None:
        path_ids.append(current)
        current = parent.get(current)
    path_ids.reverse()
    # 只返回人类可读名称，不暴露内部 ID
    return [name_of.get(point_id, point_id) for point_id in path_ids[:8]]


def build_plan_brief(
    state: dict[str, Any], context: dict[str, Any] | None = None
) -> dict[str, Any]:
    """确定性构建 PlanBrief；context 缺省时由正式证据重新构建。"""
    plan_context = context or build_plan_context(state)
    goal = _as_dict(state.get("goal"))
    constraints = _as_dict(goal.get("constraints"))
    plan = _as_dict(state.get("learning_plan"))
    stages = _as_list(plan.get("stages"))
    steps = [
        step for stage in stages for step in _as_list(_as_dict(stage).get("steps"))
        if isinstance(step, dict)
    ]
    path_by_id = _path_item_map(state)
    name_of = {
        point_id: str(item.get("knowledge_point_name") or point_id)
        for point_id, item in path_by_id.items()
    }
    for step in steps:
        point_id = str(step.get("knowledge_point_id") or "")
        if point_id and point_id not in name_of:
            name_of[point_id] = str(step.get("knowledge_point_name") or point_id)

    known_names = [
        str(item.get("knowledge_point_name") or item.get("knowledge_point_id") or "")
        for item in _as_list(plan_context.get("known_points"))
    ]
    gap_names = [
        str(item.get("knowledge_point_name") or item.get("knowledge_point_id") or "")
        for item in _as_list(plan_context.get("review_points"))
    ]
    candidate_names = [
        str(item.get("knowledge_point_name") or item.get("knowledge_point_id") or "")
        for item in _as_list(plan_context.get("candidate_points"))
    ]
    unassessed_names = [
        str(item.get("knowledge_point_name") or item.get("knowledge_point_id") or "")
        for item in _as_list(plan_context.get("unknown_points"))
    ]

    stage_overview: list[dict[str, Any]] = []
    stage_titles = {
        "foundation": "基础准备",
        "core": "核心学习",
        "application": "综合应用",
    }
    for index, stage in enumerate(stages, start=1):
        stage_steps = [
            step for step in _as_list(_as_dict(stage).get("steps"))
            if isinstance(step, dict)
        ]
        stage_id = str(_as_dict(stage).get("stage_id") or f"stage-{index}")
        stage_overview.append(
            {
                "stage_id": stage_id,
                "title": str(_as_dict(stage).get("title") or stage_titles.get(stage_id, f"阶段 {index}")),
                "objective": str(_as_dict(stage).get("description") or ""),
                "order": index,
                "kc_count": len(stage_steps),
            }
        )

    difficulty_hotspots = [
        str(step.get("knowledge_point_name") or step.get("knowledge_point_id") or "")
        for step in steps
        if int(step.get("difficulty") or 0) >= 3
    ][:5]

    goal_name = str(goal.get("goal_name") or "")
    target_outcome = str(constraints.get("target_outcome") or "").strip()

    why: list[str] = [f"目标：{goal_name}"]
    if known_names:
        why.append("已掌握：" + "、".join(known_names[:4]))
    if gap_names:
        why.append("建议加强：" + "、".join(gap_names[:4]))
    if candidate_names:
        why.append("待验证：" + "、".join(candidate_names[:4]))

    adaptation_rules = [
        "只有正式测评证据（source_event_ids）才会更新掌握度；"
        "计划步骤完成、讲解完成只推进计划进度。",
        "如果后续测评显示某个知识点已经掌握，系统会减少该点的重复基础内容。",
        "如果某个前置知识点仍需加强，系统会调整推荐顺序并重新生成计划版本。",
    ]

    daily_minutes = int(plan_context.get("daily_minutes") or 0) or None
    duration_days = int(plan_context.get("duration_days") or 0) or None
    time_budget = (
        f"{duration_days} 天 · 每天 {daily_minutes} 分钟"
        if duration_days and daily_minutes
        else ""
    )

    return {
        "goal": goal_name,
        "target_outcome": target_outcome,
        "why_this_plan": why,
        "known_skills": known_names[:8],
        "skill_gaps": gap_names[:8],
        "candidate_skills": candidate_names[:8],
        "unassessed_skills": unassessed_names[:8],
        "critical_path": _critical_path(state, name_of),
        "difficulty_hotspots": difficulty_hotspots,
        "adaptation_rules": adaptation_rules,
        "stage_overview": stage_overview,
        "time_budget": time_budget,
    }
