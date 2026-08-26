"""Learning Map：从项目学习路径确定性投影只读学习地图。

不修改 `goal_graph` 或 `learning_path`；未评估的掌握度必须表示为 `None`，
绝不强制为 0。推荐语义：
- `current_recommended_kc` 最多一个，优先级：需补强 → 进行中 → 未开始 → 稳定。
- 排序使用 `recommended_order` 与拓扑深度，绝不使用随机或哈希顺序。
- `locked_nodes`：前置知识点尚未稳定（未达到已掌握）的节点，不应被推荐。
"""

from __future__ import annotations

from typing import Any

KNOWN_STATUSES = frozenset({"supported", "verified_once"})
REVIEW_STATUSES = frozenset({"needs_support", "developing"})
CANDIDATE_STATUSES = frozenset({"candidate"})

try:
    from backend.data.goal_graph import DEPENDENCIES
except ModuleNotFoundError:
    from data.goal_graph import DEPENDENCIES


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _str(value: Any) -> str:
    return "" if value is None else str(value)


def _path_items(state: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item
        for item in _as_list(_as_dict(state.get("learning_path")).get("items"))
        if isinstance(item, dict) and str(item.get("knowledge_point_id") or "")
    ]


def _sort_key(item: dict[str, Any], depth: dict[str, int]) -> tuple[int, int, str]:
    order = int(item.get("recommended_order") or 0) or 0
    point_id = str(item.get("knowledge_point_id") or "")
    return (order, depth.get(point_id, 0), point_id)


def node_status(path_item: dict[str, Any]) -> str:
    """根据正式证据与路径状态派生节点学习状态。"""
    source_event_ids = [
        str(event_id)
        for event_id in _as_list(path_item.get("source_event_ids"))
        if str(event_id)
    ]
    evidence_status = _str(path_item.get("evidence_status") or "unassessed")
    if source_event_ids and evidence_status in KNOWN_STATUSES:
        return "mastered"
    if source_event_ids and evidence_status in REVIEW_STATUSES:
        return "weak"
    if source_event_ids and evidence_status in CANDIDATE_STATUSES:
        return "candidate"
    if _str(path_item.get("status") or "pending") == "current":
        return "learning"
    if _str(path_item.get("status") or "") == "completed":
        return "mastered"
    return "unknown"


def build_learning_map(state: dict[str, Any]) -> dict[str, Any]:
    """构建只读学习地图投影（不影响底层图谱与持久化状态）。"""
    items = _path_items(state)
    if not items:
        return {
            "status": "empty",
            "project": str(_as_dict(state.get("goal")).get("goal_name") or ""),
            "nodes": [],
            "edges": [],
            "current_recommended_kc": None,
            "recommended_candidates": [],
            "locked_nodes": [],
            "active_path": [],
        }

    by_id: dict[str, dict[str, Any]] = {}
    for item in items:
        point_id = str(item.get("knowledge_point_id") or "")
        if point_id:
            by_id[point_id] = item

    # 依赖：优先节点自带 prerequisites，其次能力图谱 DEPENDENCIES；仅保留路径内节点
    deps: dict[str, list[str]] = {}
    for point_id in by_id:
        declared = [
            str(prereq) for prereq in _as_list(by_id[point_id].get("prerequisites"))
            if str(prereq)
        ]
        graph_deps = [
            str(prereq) for prereq in _as_list(DEPENDENCIES.get(point_id))
            if str(prereq)
        ]
        candidates = declared or graph_deps
        deps[point_id] = [prereq for prereq in candidates if prereq in by_id]

    # 拓扑深度（前置链长度），用于稳定排序
    depth: dict[str, int] = {}

    def _depth(point_id: str) -> int:
        if point_id in depth:
            return depth[point_id]
        prereq_depths = [_depth(prereq) for prereq in deps.get(point_id, [])]
        depth[point_id] = 1 + max(prereq_depths, default=0)
        return depth[point_id]

    for point_id in by_id:
        _depth(point_id)

    nodes: list[dict[str, Any]] = []
    for item in sorted(items, key=lambda i: _sort_key(i, depth)):
        point_id = str(item.get("knowledge_point_id") or "")
        status = node_status(item)
        mastery_value = item.get("mastery")
        nodes.append({
            "id": point_id,
            "name": str(item.get("knowledge_point_name") or point_id),
            "knowledge_type": str(item.get("knowledge_type") or "conceptual"),
            "mastery": mastery_value if mastery_value is not None else None,
            "confidence": item.get("confidence"),
            "status": status,
            "prerequisites": list(deps.get(point_id, [])),
            "recommended_order": int(item.get("recommended_order") or 0) or 0,
            "source_event_ids": [
                str(event_id) for event_id in _as_list(item.get("source_event_ids"))
                if str(event_id)
            ],
        })

    # locked：前置未达到已掌握
    locked_set: set[str] = set()
    for node in nodes:
        if node["status"] == "mastered":
            continue
        if any(
            by_prereq.get("status") != "mastered"
            for by_prereq in (
                next((n for n in nodes if n["id"] == prereq), None)
                for prereq in node["prerequisites"]
            )
            if by_prereq
        ):
            locked_set.add(node["id"])

    edges: list[dict[str, Any]] = []
    for source, targets in deps.items():
        for target in targets:
            if target in by_id:
                edges.append({
                    "source": source,
                    "target": target,
                    "relation": "prerequisite",
                })

    # 推荐：需补强 → 进行中 → 未开始 → 稳定；各档内按 recommended_order + 拓扑深度
    def _candidate_key(item: dict[str, Any]) -> tuple[int, tuple[int, int, str]]:
        priority = {
            "weak": 0,
            "candidate": 1,
            "learning": 2,
            "unknown": 3,
            "mastered": 4,
        }.get(item["status"], 4)
        return (priority, _sort_key(item, depth))

    ordered = sorted(
        (node for node in nodes if node["id"] not in locked_set),
        key=_candidate_key,
    )
    current_recommended: str | None = None
    for node in ordered:
        if node["status"] in {"weak", "candidate", "learning", "unknown"}:
            current_recommended = node["id"]
            break

    candidates: list[str] = []
    for node in ordered:
        if node["id"] == current_recommended:
            continue
        if node["status"] in {"weak", "candidate", "learning", "unknown"}:
            candidates.append(node["id"])
        if len(candidates) >= 3:
            break

    # active_path：从当前推荐沿 DAG 走到一个目标叶子
    active_path: list[str] = []
    if current_recommended:
        active_path.append(current_recommended)
        seen: set[str] = {current_recommended}
        current = current_recommended
        while True:
            children = [
                node["id"] for node in nodes
                if current in node["prerequisites"] and node["id"] not in seen
            ]
            if not children:
                break
            child = min(
                children,
                key=lambda node_id: _sort_key(by_id.get(node_id, {}), depth),
            )
            active_path.append(child)
            seen.add(child)
            current = child

    return {
        "status": "ok",
        "project": str(_as_dict(state.get("goal")).get("goal_name") or ""),
        "nodes": nodes,
        "edges": edges,
        "current_recommended_kc": current_recommended,
        "recommended_candidates": candidates,
        "locked_nodes": sorted(locked_set),
        "active_path": active_path,
    }
