"""基于显式知识点依赖图编排学习路径。

该实现借鉴 EduAgents 的 ConceptSpec / prerequisite DAG 方法：阶段用于分组，
前置关系只来自节点显式声明，不能由阶段顺序推断。
"""

from __future__ import annotations

from typing import Any


STAGES = (
    ("foundation", 1),
    ("core", 2),
    ("application", 3),
)
_STAGE_ORDER = {stage_id: order for stage_id, order in STAGES}
_STAGE_BY_ORDER = {order: stage_id for stage_id, order in STAGES}
_APPLICATION_TYPES = frozenset({"practice", "project", "assessment"})


def build_daily_schedule(
    plan: dict[str, Any],
    *,
    duration_days: int | None,
    daily_minutes: int | None,
) -> list[dict[str, Any]]:
    """Derive a budget-safe daily schedule from validated plan steps.

    The schedule is presentation data, not a second source of path order: it
    preserves the plan's flattened order and never adds dependencies.
    """
    if not duration_days or not daily_minutes:
        return []

    steps = [
        step
        for stage in plan.get("stages") or []
        if isinstance(stage, dict)
        for step in stage.get("steps") or []
        if isinstance(step, dict)
    ]
    remaining = [
        {
            "step": step,
            "minutes": max(0, int(step.get("estimated_minutes") or 0)),
        }
        for step in steps
    ]
    schedule: list[dict[str, Any]] = []
    step_index = 0
    for day in range(1, duration_days + 1):
        available = daily_minutes
        tasks: list[dict[str, Any]] = []
        while available and step_index < len(remaining):
            current = remaining[step_index]
            if current["minutes"] < 1:
                step_index += 1
                continue
            allocated = min(available, current["minutes"])
            step = current["step"]
            name = str(step.get("knowledge_point_name") or "当前知识点")
            objective = str(step.get("learning_objective") or "完成本步骤的学习目标")
            tasks.append(
                {
                    "step_id": str(step.get("step_id") or ""),
                    "knowledge_point_id": str(step.get("knowledge_point_id") or ""),
                    "knowledge_point_name": name,
                    "minutes": allocated,
                    "learning_task": f"学习：{name}",
                    "practice_task": (
                        f"完成与“{name}”直接相关的最小成果"
                        if step.get("is_target")
                        else f"完成“{name}”的最小示例或应用记录"
                    ),
                    "check": objective,
                }
            )
            current["minutes"] -= allocated
            available -= allocated
            if current["minutes"] < 1:
                step_index += 1
        schedule.append(
            {
                "day": day,
                "planned_minutes": daily_minutes - available,
                "tasks": tasks,
                "focus": (
                    "完成当天学习、实践与检查任务。"
                    if tasks
                    else "预留为复盘、补缺或休息；不新增未经验证的学习内容。"
                ),
            }
        )
    return schedule


def validate_plan_delivery(plan: dict[str, Any]) -> list[str]:
    """Validate executable-plan invariants beyond graph well-formedness."""
    errors: list[str] = []
    stages = [stage for stage in plan.get("stages") or [] if isinstance(stage, dict)]
    steps = [
        step
        for stage in stages
        for step in stage.get("steps") or []
        if isinstance(step, dict)
    ]
    by_point: dict[str, dict[str, Any]] = {}
    global_order: dict[str, int] = {}
    for index, step in enumerate(steps, start=1):
        point_id = str(step.get("knowledge_point_id") or "").strip()
        if not point_id:
            errors.append("计划步骤缺少 knowledge_point_id")
            continue
        if point_id in by_point:
            errors.append(f"计划知识点重复：{point_id}")
            continue
        by_point[point_id] = step
        global_order[point_id] = index
        if len(str(step.get("learning_objective") or "").strip()) < 6:
            errors.append(f"计划步骤缺少可检查学习目标：{point_id}")

    target_ids = {
        str(point_id).strip()
        for point_id in plan.get("target_knowledge_point_ids") or []
        if str(point_id).strip()
    }
    if target_ids and not target_ids.issubset(by_point):
        errors.append("目标知识点未进入学习计划")
    if not target_ids and steps and not any(step.get("is_target") for step in steps):
        errors.append("学习路径未标记目标知识点")

    for point_id, step in by_point.items():
        for prerequisite in step.get("prerequisites") or []:
            prerequisite_id = str(prerequisite).strip()
            prerequisite_step = by_point.get(prerequisite_id)
            if not prerequisite_step:
                continue
            if global_order[prerequisite_id] >= global_order[point_id]:
                errors.append(f"前置知识未排在目标知识点之前：{point_id}")
            if int(prerequisite_step.get("stage_order") or 0) > int(
                step.get("stage_order") or 0
            ):
                errors.append(f"前置知识阶段晚于目标知识点：{point_id}")

    budget = plan.get("time_budget") or {}
    if budget.get("constraint_applied"):
        duration_days = int(budget.get("duration_days") or 0)
        daily_minutes = int(budget.get("daily_minutes") or 0)
        schedule = plan.get("daily_schedule") or []
        if duration_days < 1 or daily_minutes < 1:
            errors.append("时间预算缺少有效的周期或每日时长")
        elif len(schedule) != duration_days:
            errors.append("每日学习安排未覆盖完整学习周期")
        else:
            scheduled_minutes: dict[str, int] = {point_id: 0 for point_id in by_point}
            for expected_day, day in enumerate(schedule, start=1):
                if not isinstance(day, dict) or int(day.get("day") or 0) != expected_day:
                    errors.append("每日学习安排的日期不连续")
                    break
                tasks = [task for task in day.get("tasks") or [] if isinstance(task, dict)]
                planned = sum(max(0, int(task.get("minutes") or 0)) for task in tasks)
                if planned != int(day.get("planned_minutes") or 0):
                    errors.append(f"第 {expected_day} 天的任务时长汇总不一致")
                if planned > daily_minutes:
                    errors.append(f"第 {expected_day} 天的任务超过每日时间预算")
                for task in tasks:
                    point_id = str(task.get("knowledge_point_id") or "")
                    if point_id in scheduled_minutes:
                        scheduled_minutes[point_id] += max(0, int(task.get("minutes") or 0))
            for point_id, step in by_point.items():
                if scheduled_minutes[point_id] != int(step.get("estimated_minutes") or 0):
                    errors.append(f"知识点未被完整排入每日学习安排：{point_id}")
    return errors


def compile_learning_path(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return a stable topological path with explicit stage metadata."""
    by_id: dict[str, dict[str, Any]] = {}
    original_order: dict[str, int] = {}
    for index, raw_item in enumerate(items, start=1):
        item = dict(raw_item)
        point_id = str(item.get("knowledge_point_id") or "").strip()
        if not point_id or point_id in by_id:
            raise ValueError("学习路径包含空或重复的知识点 ID")
        by_id[point_id] = item
        original_order[point_id] = int(item.get("recommended_order") or index)

    dependencies: dict[str, list[str]] = {}
    for point_id, item in by_id.items():
        prerequisites: list[str] = []
        for raw_prerequisite in item.get("prerequisites") or []:
            prerequisite = str(raw_prerequisite or "").strip()
            if not prerequisite:
                continue
            if prerequisite == point_id or prerequisite not in by_id:
                raise ValueError(f"知识点前置依赖无效：{point_id}")
            if prerequisite not in prerequisites:
                prerequisites.append(prerequisite)
        dependencies[point_id] = prerequisites

    remaining = set(by_id)
    ordered_ids: list[str] = []
    while remaining:
        ready = sorted(
            (
                point_id
                for point_id in remaining
                if not any(prerequisite in remaining for prerequisite in dependencies[point_id])
            ),
            key=lambda point_id: (original_order[point_id], point_id),
        )
        if not ready:
            raise ValueError("学习路径前置依赖存在环路")
        point_id = ready[0]
        ordered_ids.append(point_id)
        remaining.remove(point_id)

    children: dict[str, list[str]] = {point_id: [] for point_id in by_id}
    for point_id, prerequisites in dependencies.items():
        for prerequisite in prerequisites:
            children[prerequisite].append(point_id)

    depth: dict[str, int] = {}
    for point_id in ordered_ids:
        depth[point_id] = 1 + max(
            (depth[prerequisite] for prerequisite in dependencies[point_id]),
            default=0,
        )

    stage_by_id: dict[str, str] = {}
    for point_id in ordered_ids:
        knowledge_type = str(by_id[point_id].get("knowledge_type") or "").lower()
        if not dependencies[point_id]:
            stage_by_id[point_id] = "foundation"
        elif knowledge_type in _APPLICATION_TYPES or not children[point_id]:
            stage_by_id[point_id] = "application"
        else:
            stage_by_id[point_id] = "core"

    def lift_dependent_stages() -> None:
        for point_id in ordered_ids:
            prerequisite_order = max(
                (_STAGE_ORDER[stage_by_id[prerequisite]] for prerequisite in dependencies[point_id]),
                default=1,
            )
            current_order = _STAGE_ORDER[stage_by_id[point_id]]
            if current_order < prerequisite_order:
                stage_by_id[point_id] = _STAGE_BY_ORDER[prerequisite_order]

    lift_dependent_stages()
    if "core" not in stage_by_id.values() and len(ordered_ids) >= 3:
        core_candidate = next(
            (
                point_id
                for point_id in ordered_ids[1:]
                if all(
                    _STAGE_ORDER[stage_by_id[prerequisite]] <= 1
                    for prerequisite in dependencies[point_id]
                )
            ),
            ordered_ids[len(ordered_ids) // 2],
        )
        stage_by_id[core_candidate] = "core"
    if "application" not in stage_by_id.values() and ordered_ids:
        stage_by_id[ordered_ids[-1]] = "application"
    if "foundation" not in stage_by_id.values() and ordered_ids:
        stage_by_id[ordered_ids[0]] = "foundation"
    lift_dependent_stages()

    compiled: list[dict[str, Any]] = []
    for index, point_id in enumerate(ordered_ids, start=1):
        item = dict(by_id[point_id])
        stage_id = stage_by_id[point_id]
        item.update(
            {
                "prerequisites": dependencies[point_id],
                "recommended_order": index,
                "stage_id": stage_id,
                "stage_order": _STAGE_ORDER[stage_id],
                "is_target": bool(
                    item.get("is_target")
                    or str(item.get("knowledge_type") or "").lower()
                    in {"project", "assessment"}
                    or (not children[point_id] and bool(dependencies[point_id]))
                ),
            }
        )
        compiled.append(item)
    return compiled
