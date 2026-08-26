"""目标驱动引擎：口语化目标归一化 + 目标 -> 知识点路径生成。

MVP 采用规则版（关键词匹配），未匹配返回 None 由调用方走 OOV 兜底；
后续可平滑替换为 LLM 归一化，接口保持不变。
"""

from __future__ import annotations

from typing import Any

try:
    from backend.data.goal_graph import DEPENDENCIES, GOALS, KNOWLEDGE_POINTS
except ModuleNotFoundError:
    from data.goal_graph import DEPENDENCIES, GOALS, KNOWLEDGE_POINTS


def list_goals() -> list[dict[str, Any]]:
    """图谱内全部可选目标（供前端目标选择 UI 使用）。"""
    return [
        {
            "goal_id": goal["goal_id"],
            "goal_type": goal.get("goal_type", "course"),
            "goal_name": goal["goal_name"],
            "goal_description": goal.get("goal_description", ""),
        }
        for goal in GOALS.values()
    ]


def _goal_payload(goal_id: str) -> dict[str, Any]:
    goal = GOALS[goal_id]
    return {
        "goal_id": goal["goal_id"],
        "goal_type": goal.get("goal_type", "course"),
        "goal_name": goal["goal_name"],
        "goal_description": goal.get("goal_description", ""),
    }


def normalize_goal(text: str) -> dict[str, Any] | None:
    """把口语化目标文本归一化到图谱目标；无法匹配返回 None（OOV 兜底）。"""
    if not text:
        return None
    lowered = str(text).strip().lower().replace("_", "-")
    for goal_id, goal in GOALS.items():
        if lowered == goal["goal_id"].lower() or lowered == str(goal["goal_name"]).lower():
            return _goal_payload(goal_id)
    for goal_id, goal in GOALS.items():
        for keyword in goal.get("keywords", []):
            if keyword.lower() in lowered:
                return _goal_payload(goal_id)
    return None


def resolve_learning_goal(learning_goal: dict[str, Any] | None) -> dict[str, Any] | None:
    """按 goal_id / goal_name / 口语化文本依次尝试归一化。"""
    learning_goal = learning_goal or {}
    for candidate in (
        str(learning_goal.get("goal_id") or "").strip(),
        str(learning_goal.get("goal_name") or "").strip(),
    ):
        if not candidate:
            continue
        matched = normalize_goal(candidate)
        if matched:
            return matched
    return None


def _topological_order(goal_id: str) -> list[str]:
    """按依赖关系拓扑排序；声明顺序作为同级稳定序。"""
    declared = list(GOALS[goal_id]["knowledge_points"])
    valid = set(declared)
    order: list[str] = []
    visited: set[str] = set()
    visiting: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in visited:
            return
        if node_id in visiting:
            return  # 依赖成环属数据错误，跳过避免死循环
        visiting.add(node_id)
        for prerequisite in DEPENDENCIES.get(node_id, []):
            if prerequisite in valid:
                visit(prerequisite)
        visiting.discard(node_id)
        visited.add(node_id)
        order.append(node_id)

    for node_id in declared:
        visit(node_id)
    return order if len(order) == len(declared) else declared


def build_learning_path(goal_id: str) -> dict[str, Any]:
    """按目标生成学习路径（依赖排序），首节点标记为 current。"""
    goal = GOALS[goal_id]
    items = []
    for index, point_id in enumerate(_topological_order(goal_id), start=1):
        point = KNOWLEDGE_POINTS[point_id]
        items.append(
            {
                "knowledge_point_id": point_id,
                "knowledge_point_name": point["knowledge_point_name"],
                "knowledge_type": point.get("knowledge_type", "conceptual"),
                "prerequisites": [
                    prerequisite
                    for prerequisite in DEPENDENCIES.get(point_id, [])
                    if prerequisite in GOALS[goal_id]["knowledge_points"]
                ],
                "mastery": 0,
                "status": "current" if index == 1 else "pending",
                "recommended_order": index,
                "goal_id": goal["goal_id"],
            }
        )
    return {
        "goal_id": goal["goal_id"],
        "goal_name": goal["goal_name"],
        "items": items,
        "progress": 0,
    }


def path_for_learning_goal(
    learning_goal: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """学习目标 -> 学习路径；目标不在图谱内返回 None。"""
    goal = resolve_learning_goal(learning_goal)
    if not goal:
        return None
    return build_learning_path(goal["goal_id"])
