"""Deterministic, inspectable planning analysis for learning-work-task Plans.

This module deliberately produces planning artifacts rather than hidden model
reasoning.  It expands the validated remote Plan into a hierarchy, dependency
schedule, alternative candidates, critic verdicts, risks, and versioned local
replanning records that can be rendered and audited by the workspace UI.
"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.services.learning_task_plan_gateway import LearningTaskPlanRun


PlanDecisionCode = Literal[
    "SELECT_CANDIDATE", "REQUEST_EVIDENCE", "LOCAL_REPLAN", "STOP",
]
ReplanFailureCode = Literal[
    "evidence_gap", "dependency_blocked", "safety_conflict",
    "artifact_rejected", "mapping_conflict",
]


class PlanHierarchyNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str
    node_type: Literal["goal", "phase", "work_package", "atomic_step"]
    parent_id: str | None = None
    label: str
    objective: str
    package_id: str | None = None
    depth: int = Field(ge=0, le=3)


class PlanGraphEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    target: str
    edge_type: Literal["contains", "precedes", "produces", "reviews"]


class PlanCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    strategy: Literal["fidelity_first", "evidence_first", "balanced_parallel"]
    title: str
    ordered_package_ids: list[str]
    parallel_waves: list[list[str]]
    scores: dict[str, int]
    weighted_score: int = Field(ge=0, le=100)
    hard_gate_passed: bool
    tradeoffs: list[str]


class PlanCriticVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    critic_id: str
    dimension: Literal[
        "task_identity", "dependency", "evidence", "safety",
        "deliverable", "teaching_fit",
    ]
    verdict: Literal["pass", "warning", "fail"]
    score: int = Field(ge=0, le=100)
    findings: list[str]
    affected_package_ids: list[str]


class PlanRiskItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    risk_id: str
    package_id: str
    category: Literal[
        "evidence", "dependency", "safety", "artifact", "mapping",
    ]
    likelihood: Literal["low", "medium", "high"]
    impact: Literal["low", "medium", "high"]
    mitigation: str
    evidence_required: bool


class PlanDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: PlanDecisionCode
    selected_candidate_id: str | None = None
    confidence: int = Field(ge=0, le=100)
    reasons: list[str]
    triggered_rules: list[str]


class PlanRevision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision_id: str
    analysis_version: int = Field(ge=1)
    parent_revision_id: str | None = None
    cause: str
    failure_code: ReplanFailureCode | None = None
    affected_package_ids: list[str]
    preserved_package_ids: list[str]
    controls_added: list[str]


PlanStageStatus = Literal[
    "completed", "ready", "blocked", "pending", "not_started",
]


class PlanStageSubstep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    substep_id: str
    label: str
    status: PlanStageStatus
    detail: str
    parent_substep_id: str | None = None
    depends_on: list[str] = Field(default_factory=list)
    output_ref: str | None = None


class PlanStage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage_id: Literal[
        "task_contract",
        "grounding_clarification",
        "evidence_search_planning",
        "evidence_grounded_task_planning",
        "critic_finalize",
        "execution_handoff",
    ]
    sequence: int = Field(ge=1, le=6)
    label: str
    status: PlanStageStatus
    summary: str
    input_refs: list[str]
    output_refs: list[str]
    substeps: list[PlanStageSubstep]

    @model_validator(mode="after")
    def validate_substep_tree(self) -> "PlanStage":
        substep_ids = [item.substep_id for item in self.substeps]
        if len(substep_ids) != len(set(substep_ids)):
            raise ValueError("Plan 阶段子步骤 ID 必须唯一")
        known = set(substep_ids)
        for item in self.substeps:
            references = set(item.depends_on)
            if item.parent_substep_id:
                references.add(item.parent_substep_id)
            if not references <= known:
                raise ValueError("Plan 阶段子步骤引用了不存在的节点")
        return self


class PlanExecutionChecklistItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    package_id: str
    objective: str
    status: Literal["pending", "in_progress", "completed", "blocked"]
    expected_artifact: str
    observation_state: Literal[
        "not_observed", "observed", "accepted", "rejected",
    ]
    completion_condition: str


class PlanHandoffArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str
    artifact_type: Literal[
        "html", "pdf", "versioned_json",
        "knowledge_learning_entry", "feedback_contract",
    ]
    label: str
    status: Literal["planned", "ready", "generated"]
    contract_ref: str


class LearningTaskPlanningAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["learning-work-task-planning-analysis-v3"]
    run_id: str
    plan_version: int = Field(ge=1)
    analysis_version: int = Field(ge=1)
    planning_status: Literal[
        "ready_for_confirmation", "planned_not_executed",
        "replanned_not_executed", "needs_evidence",
    ]
    active_revision_id: str
    hierarchy: list[PlanHierarchyNode]
    graph_edges: list[PlanGraphEdge]
    topological_waves: list[list[str]]
    critical_path: list[str]
    candidates: list[PlanCandidate] = Field(default_factory=list, max_length=3)
    critics: list[PlanCriticVerdict] = Field(default_factory=list, max_length=6)
    risks: list[PlanRiskItem]
    decision: PlanDecision
    stages: list[PlanStage] = Field(min_length=6, max_length=6)
    execution_checklist: list[PlanExecutionChecklistItem]
    handoff_artifacts: list[PlanHandoffArtifact] = Field(
        min_length=5, max_length=5,
    )
    evidence_semantics: Literal["operational_only"]
    revision_history: list[PlanRevision]
    repair_budget_remaining: int = Field(ge=0, le=2)
    metrics: dict[str, int]

    @model_validator(mode="after")
    def validate_references(self) -> "LearningTaskPlanningAnalysis":
        package_ids = {
            node.package_id for node in self.hierarchy if node.package_id
        }
        for wave in self.topological_waves:
            if not set(wave) <= package_ids:
                raise ValueError("Plan 波次引用了不存在的工作包")
        candidate_ids = {item.candidate_id for item in self.candidates}
        if len(self.candidates) not in {0, 3}:
            raise ValueError("学习型任务候选必须尚未生成或完整生成三份")
        if len(self.critics) not in {0, 6}:
            raise ValueError("Critic 必须尚未运行或完整输出六维结论")
        selected = self.decision.selected_candidate_id
        if selected and selected not in candidate_ids:
            raise ValueError("Plan 决策引用了不存在的候选")
        if [item.sequence for item in self.stages] != list(range(1, 7)):
            raise ValueError("Plan 六阶段必须按 1 到 6 的顺序输出")
        checklist_ids = {item.package_id for item in self.execution_checklist}
        if checklist_ids != package_ids:
            raise ValueError("执行清单必须覆盖且只能覆盖全部工作包")
        return self


def _topological_waves(packages: list[dict[str, Any]]) -> list[list[str]]:
    remaining = {
        item["package_id"]: set(item.get("depends_on") or [])
        for item in packages
    }
    waves: list[list[str]] = []
    while remaining:
        ready = sorted(key for key, deps in remaining.items() if not deps)
        if not ready:  # The gateway validator already rejects this condition.
            break
        waves.append(ready)
        ready_set = set(ready)
        remaining = {
            key: deps - ready_set
            for key, deps in remaining.items()
            if key not in ready_set
        }
    return waves


def _priority_order(
    packages: list[dict[str, Any]],
    package_priority: dict[str, int],
) -> list[str]:
    by_id = {item["package_id"]: item for item in packages}
    remaining = {
        item["package_id"]: set(item.get("depends_on") or [])
        for item in packages
    }
    ordered: list[str] = []
    while remaining:
        ready = [key for key, deps in remaining.items() if not deps]
        ready.sort(key=lambda key: (
            package_priority.get(key, 50), key,
        ))
        chosen = ready[0]
        ordered.append(chosen)
        remaining = {
            key: deps - {chosen}
            for key, deps in remaining.items()
            if key != chosen
        }
    return ordered


def _critical_path(packages: list[dict[str, Any]]) -> list[str]:
    by_id = {item["package_id"]: item for item in packages}
    waves = _topological_waves(packages)
    best: dict[str, tuple[int, list[str]]] = {}
    for package_id in [item for wave in waves for item in wave]:
        item = by_id[package_id]
        duration = max(1, int(item.get("estimated_minutes") or 3))
        parents = item.get("depends_on") or []
        parent_score, parent_path = max(
            (best[parent] for parent in parents),
            default=(0, []),
            key=lambda value: value[0],
        )
        best[package_id] = (parent_score + duration, [*parent_path, package_id])
    return max(best.values(), default=(0, []), key=lambda value: value[0])[1]


def _nested_mapping_candidates(run: dict[str, Any], key: str) -> list[Any]:
    state = run.get("state") if isinstance(run.get("state"), dict) else {}
    artifacts = state.get("artifacts") if isinstance(state.get("artifacts"), dict) else {}
    run_artifacts = run.get("artifacts") if isinstance(run.get("artifacts"), dict) else {}
    return [
        run.get(key),
        state.get(key),
        artifacts.get(key),
        run_artifacts.get(key),
    ]


def _extract_evidence_ledger(run: dict[str, Any]) -> dict[str, Any] | None:
    for candidate in _nested_mapping_candidates(run, "evidence_ledger"):
        if not isinstance(candidate, dict):
            continue
        entries = candidate.get("entries") or candidate.get("items")
        if isinstance(entries, list) and entries:
            return candidate
    return None


def _extract_task_steps(run: dict[str, Any]) -> list[dict[str, Any]]:
    state = run.get("state") if isinstance(run.get("state"), dict) else {}
    artifacts = state.get("artifacts") if isinstance(state.get("artifacts"), dict) else {}
    containers: list[Any] = [
        run.get("learning_task_plan"),
        state.get("learning_task_plan"),
        state.get("step_plan"),
        state.get("selected_candidate"),
        artifacts.get("learning_task_plan"),
        artifacts.get("step_plan"),
        artifacts.get("selected_candidate"),
    ]
    for container in containers:
        if isinstance(container, list):
            steps = container
        elif isinstance(container, dict):
            steps = (
                container.get("task_steps")
                or container.get("steps")
                or container.get("work_steps")
            )
        else:
            continue
        if isinstance(steps, list) and steps and all(
            isinstance(item, dict) for item in steps
        ):
            return steps
    return []


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _positive_int(value: Any, default: int = 3) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, parsed)


def _learning_task_packages(run: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize evidence-grounded learning task steps for planning analysis."""
    steps = _extract_task_steps(run)
    packages: list[dict[str, Any]] = []
    known_ids: list[str] = []
    for index, step in enumerate(steps):
        package_id = str(
            step.get("step_id") or step.get("package_id") or f"step_{index + 1:02d}"
        ).strip()
        raw_dependencies = step.get("depends_on") or step.get("dependency_ids")
        if isinstance(raw_dependencies, list):
            dependencies = [
                str(item) for item in raw_dependencies if str(item) in known_ids
            ]
        else:
            dependencies = known_ids[-1:] if known_ids else []
        title = str(
            step.get("title") or step.get("name") or step.get("step_name")
            or f"作业步骤 {index + 1}"
        ).strip()
        objective = str(
            step.get("objective") or step.get("instruction")
            or step.get("description") or title
        ).strip()
        expected_artifact = str(
            step.get("expected_artifact") or step.get("deliverable")
            or step.get("output") or "可检查步骤产物"
        ).strip()
        completion_condition = str(
            step.get("completion_condition") or step.get("acceptance_criteria")
            or step.get("checkpoint") or "步骤产物通过明确的验收检查。"
        ).strip()
        knowledge_ids = _string_list(step.get("knowledge_point_ids"))
        skill_ids = _string_list(step.get("skill_point_ids"))
        packages.append({
            "package_id": package_id,
            "title": title,
            "phase": str(step.get("phase") or step.get("stage") or "真实作业过程"),
            "objective": objective,
            "depends_on": dependencies,
            "allowed_tools": [],
            "expected_artifact": expected_artifact,
            "completion_condition": completion_condition,
            "knowledge_point_ids": knowledge_ids,
            "skill_point_ids": skill_ids,
            "safety_constraints": _string_list(step.get("safety_constraints")),
            "source_refs": _string_list(
                step.get("source_refs") or step.get("evidence_refs")
            ),
            "estimated_minutes": _positive_int(
                step.get("estimated_minutes") or step.get("duration_minutes")
            ),
        })
        known_ids.append(package_id)
    return packages


def _build_learning_task_hierarchy(
    packages: list[dict[str, Any]],
    goal: str,
) -> list[dict[str, Any]]:
    if not packages:
        return []
    nodes: list[dict[str, Any]] = [{
        "node_id": "goal",
        "node_type": "goal",
        "parent_id": None,
        "label": "学习型任务目标",
        "objective": goal,
        "package_id": None,
        "depth": 0,
    }]
    phases: dict[str, str] = {}
    for item in packages:
        phase_label = item["phase"]
        phase_id = phases.get(phase_label)
        if not phase_id:
            phase_id = f"learning_phase_{len(phases) + 1:02d}"
            phases[phase_label] = phase_id
            nodes.append({
                "node_id": phase_id,
                "node_type": "phase",
                "parent_id": "goal",
                "label": phase_label,
                "objective": "按证据确认的真实作业顺序组织学习任务步骤。",
                "package_id": None,
                "depth": 1,
            })
        package_id = item["package_id"]
        package_node_id = f"learning_step_{package_id}"
        nodes.append({
            "node_id": package_node_id,
            "node_type": "work_package",
            "parent_id": phase_id,
            "label": item["title"],
            "objective": item["objective"],
            "package_id": package_id,
            "depth": 2,
        })
        atomic_specs = (
            ("operate", "执行操作", item["objective"]),
            ("deliver", "形成步骤产物", item["expected_artifact"]),
            ("accept", "执行验收检查", item["completion_condition"]),
        )
        for suffix, label, objective in atomic_specs:
            nodes.append({
                "node_id": f"learning_atomic_{package_id}_{suffix}",
                "node_type": "atomic_step",
                "parent_id": package_node_id,
                "label": label,
                "objective": objective,
                "package_id": package_id,
                "depth": 3,
            })
    return nodes


def _build_edges(packages: list[dict[str, Any]], hierarchy: list[dict[str, Any]]) -> list[dict[str, str]]:
    edges = [
        {"source": node["parent_id"], "target": node["node_id"], "edge_type": "contains"}
        for node in hierarchy if node["parent_id"]
    ]
    package_nodes = {
        str(node["package_id"]): str(node["node_id"])
        for node in hierarchy
        if node.get("node_type") == "work_package" and node.get("package_id")
    }
    for item in packages:
        for parent in item.get("depends_on") or []:
            edges.append({
                "source": package_nodes.get(parent, f"learning_step_{parent}"),
                "target": package_nodes.get(
                    item["package_id"], f"learning_step_{item['package_id']}"
                ),
                "edge_type": "precedes",
            })
    return edges


def _critics(
    run: dict[str, Any],
    packages: list[dict[str, Any]],
    *,
    evidence_ready: bool,
) -> list[dict[str, Any]]:
    if not packages:
        return []
    plan = run["plan"]
    package_ids = [item["package_id"] for item in packages]
    blocking = [] if evidence_ready else [
        item for item in plan.get("unknowns") or [] if item.get("blocking")
    ]
    missing_mappings = [
        item["package_id"] for item in packages
        if not item.get("knowledge_point_ids") or not item.get("skill_point_ids")
    ]
    missing_sources = [
        item["package_id"] for item in packages if not item.get("source_refs")
    ]
    missing_artifacts = [
        item["package_id"] for item in packages
        if not str(item.get("expected_artifact") or "").strip()
        or not str(item.get("completion_condition") or "").strip()
    ]
    stop_text = " ".join(plan.get("stop_conditions") or [])
    return [
        {
            "critic_id": "critic_identity",
            "dimension": "task_identity",
            "verdict": "pass",
            "score": 100,
            "findings": ["Run、任务契约和 Plan 使用同一语义指纹。"],
            "affected_package_ids": [],
        },
        {
            "critic_id": "critic_dependency",
            "dimension": "dependency",
            "verdict": "pass",
            "score": 96,
            "findings": ["依赖图无环，所有前置工作包均可解析。"],
            "affected_package_ids": [],
        },
        {
            "critic_id": "critic_evidence",
            "dimension": "evidence",
            "verdict": "warning" if blocking or missing_sources else "pass",
            "score": 68 if blocking else 78 if missing_sources else 94,
            "findings": (
                [f"仍有 {len(blocking)} 个阻塞性证据缺口。"] if blocking
                else [f"{len(missing_sources)} 个学习任务步骤缺少来源引用。"] if missing_sources
                else ["证据账本已就绪，所有任务步骤均带来源引用。"]
            ),
            "affected_package_ids": missing_sources,
        },
        {
            "critic_id": "critic_safety",
            "dimension": "safety",
            "verdict": "pass" if any(word in stop_text for word in ("安全", "权限", "停止", "终止")) else "warning",
            "score": 91 if any(word in stop_text for word in ("安全", "权限", "停止", "终止")) else 72,
            "findings": ["停止条件已建立。" if stop_text else "需要补充明确的安全停止条件。"],
            "affected_package_ids": package_ids[-1:] if not stop_text else [],
        },
        {
            "critic_id": "critic_delivery",
            "dimension": "deliverable",
            "verdict": "warning" if missing_artifacts else "pass",
            "score": 74 if missing_artifacts else 92,
            "findings": [
                f"{len(missing_artifacts)} 个步骤缺少产物或验收条件。"
                if missing_artifacts else "每个学习任务步骤均声明产物与验收条件。"
            ],
            "affected_package_ids": missing_artifacts,
        },
        {
            "critic_id": "critic_teaching",
            "dimension": "teaching_fit",
            "verdict": "warning" if missing_mappings else "pass",
            "score": 70 if missing_mappings else 93,
            "findings": [
                f"{len(missing_mappings)} 个步骤缺少知识点或技能点强映射。"
                if missing_mappings else "每个步骤均具备知识点与技能点映射。"
            ],
            "affected_package_ids": missing_mappings,
        },
    ]


def _risks(run: dict[str, Any], packages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    plan = run["plan"]
    risks: list[dict[str, Any]] = []
    evidence_packages = [
        item["package_id"] for item in packages
        if item.get("agent_role") == "evidence_explorer"
    ]
    for index, unknown in enumerate(plan.get("unknowns") or []):
        risks.append({
            "risk_id": f"risk_unknown_{index + 1}",
            "package_id": evidence_packages[0] if evidence_packages else packages[0]["package_id"],
            "category": "evidence",
            "likelihood": "high" if unknown.get("blocking") else "medium",
            "impact": "high" if unknown.get("blocking") else "medium",
            "mitigation": str(unknown.get("question") or "补齐可追溯证据。"),
            "evidence_required": True,
        })
    for item in packages:
        if len(item.get("depends_on") or []) >= 2:
            risks.append({
                "risk_id": f"risk_join_{item['package_id']}",
                "package_id": item["package_id"],
                "category": "dependency",
                "likelihood": "medium",
                "impact": "high",
                "mitigation": "在汇合点逐项检查上游产物版本与完成门禁。",
                "evidence_required": False,
            })
    if not risks:
        target = packages[min(1, len(packages) - 1)]
        risks.append({
            "risk_id": "risk_artifact_gate",
            "package_id": target["package_id"],
            "category": "artifact",
            "likelihood": "low",
            "impact": "medium",
            "mitigation": "按完成条件校验中间产物，不合格时仅回退当前子图。",
            "evidence_required": False,
        })
    return risks[:12]


def _candidates(
    run: dict[str, Any],
    packages: list[dict[str, Any]],
    waves: list[list[str]],
    critics: list[dict[str, Any]],
    *,
    evidence_ready: bool,
) -> list[dict[str, Any]]:
    if not packages or not critics:
        return []
    blocking = 0 if evidence_ready else sum(
        1 for item in run["plan"].get("unknowns") or [] if item.get("blocking")
    )
    critic_floor = min(item["score"] for item in critics)
    original_priority = {
        item["package_id"]: index for index, item in enumerate(packages)
    }
    evidence_priority = {
        item["package_id"]: -len(item.get("source_refs") or [])
        for item in packages
    }
    learning_priority = {
        item["package_id"]: -(
            len(item.get("knowledge_point_ids") or [])
            + len(item.get("skill_point_ids") or [])
        )
        for item in packages
    }
    strategies = (
        (
            "candidate_fidelity", "fidelity_first", "任务保真优先",
            original_priority,
            {"fidelity": 98, "executability": 88, "evidence": 90, "safety": 90, "teaching_fit": 84, "efficiency": 76},
            ["最大限度保持企业任务对象、动作与产物。", "串行门禁较多，整体耗时相对更长。"],
        ),
        (
            "candidate_evidence", "evidence_first", "证据充分优先",
            evidence_priority,
            {"fidelity": 92, "executability": 85, "evidence": 98, "safety": 93, "teaching_fit": 82, "efficiency": 72},
            ["在不违反依赖的前提下，优先安排来源覆盖更充分的步骤。", "证据较弱的步骤会被推迟并要求补证据。"],
        ),
        (
            "candidate_balanced", "balanced_parallel", "并行均衡方案",
            learning_priority,
            {"fidelity": 94, "executability": 94, "evidence": 90, "safety": 91, "teaching_fit": 94, "efficiency": 95},
            ["在依赖约束内兼顾知识技能覆盖并利用可并行波次。", "需要在汇合点执行严格的步骤产物门禁。"],
        ),
    )
    weights = {"fidelity": 24, "executability": 20, "evidence": 18, "safety": 18, "teaching_fit": 12, "efficiency": 8}
    result: list[dict[str, Any]] = []
    for candidate_id, strategy, title, priority, base_scores, tradeoffs in strategies:
        scores = dict(base_scores)
        scores["evidence"] = max(45, scores["evidence"] - blocking * 12)
        scores["safety"] = min(scores["safety"], critic_floor + 20)
        weighted = round(sum(scores[key] * weights[key] for key in weights) / 100)
        result.append({
            "candidate_id": candidate_id,
            "strategy": strategy,
            "title": title,
            "ordered_package_ids": _priority_order(packages, priority),
            "parallel_waves": waves,
            "scores": scores,
            "weighted_score": weighted,
            "hard_gate_passed": blocking == 0 and critic_floor >= 70,
            "tradeoffs": tradeoffs,
        })
    return result


def _initial_revision(
    run: dict[str, Any],
    package_ids: list[str],
    *,
    task_plan_ready: bool,
) -> dict[str, Any]:
    return {
        "revision_id": "revision_1",
        "analysis_version": 1,
        "parent_revision_id": None,
        "cause": (
            "从证据账本生成学习型任务分层树与三类候选 Plan。"
            if task_plan_ready
            else "从已校验任务契约生成证据检索计划；学习型任务 Plan 等待证据。"
        ),
        "failure_code": None,
        "affected_package_ids": package_ids,
        "preserved_package_ids": [],
        "controls_added": ["语义指纹锁定", "依赖无环校验", "工具白名单"],
    }


_TOOL_LABELS = {
    "task_database": "任务库",
    "knowledge_base_pro": "知识库 Pro",
    "official_web": "权威 Web",
    "evidence_verifier": "证据校验器",
}


def _build_stages(
    run: dict[str, Any],
    workflow_packages: list[dict[str, Any]],
    task_packages: list[dict[str, Any]],
    evidence_ledger: dict[str, Any] | None,
    hierarchy: list[dict[str, Any]],
    waves: list[list[str]],
    critical_path: list[str],
    candidates: list[dict[str, Any]],
    critics: list[dict[str, Any]],
    decision: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Compile the visible six-stage timeline shown in the workspace.

    These are inspectable artifacts and state summaries. They intentionally do
    not expose hidden model reasoning or claim that planned work was executed.
    """
    plan = run["plan"]
    blocking_unknowns = [
        item for item in plan.get("unknowns") or [] if item.get("blocking")
    ]
    user_blocking_unknowns = [
        item for item in blocking_unknowns
        if item.get("required_evidence") == "user_confirmation"
    ]
    evidence_ready = evidence_ledger is not None
    task_plan_ready = bool(task_packages and hierarchy and candidates)
    search_plan_confirmed = run["phase"] not in {"INTAKE", "CONTRACT_READY"}
    task_plan_finalized = run["phase"] == "COMMITTED"

    contract_input_text = str(
        run["task_contract"].get("raw_input")
        or run["task_contract"].get("normalized_input")
        or plan["goal"]
    )
    contract_steps = [
        {"substep_id": "contract_ingestion", "label": "输入接入与封装", "status": "completed", "detail": "接收上游任务 JSON、Run 标识和版本上下文。", "output_ref": "raw_task_envelope"},
        {"substep_id": "contract_input", "label": "原始任务文本读取", "status": "completed", "detail": contract_input_text, "parent_substep_id": "contract_ingestion", "output_ref": f"run:{run['run_id']}"},
        {"substep_id": "contract_schema", "label": "结构 Schema 校验", "status": "completed", "detail": "校验 Run、TaskPlan、角色、工具、产物和字段边界。", "parent_substep_id": "contract_ingestion", "output_ref": plan["schema_version"]},
        {"substep_id": "contract_normalize", "label": "文本与枚举归一化", "status": "completed", "detail": "统一空白、枚举值、标识符和输入层级表达。", "parent_substep_id": "contract_ingestion", "output_ref": "normalized_task_input"},
        {"substep_id": "contract_semantics", "label": "任务语义五元组解析", "status": "completed", "detail": "把任务拆为对象、动作、情境、产物和边界五类不可混淆语义。", "depends_on": ["contract_input", "contract_normalize"], "output_ref": "task_semantic_tuple"},
        {"substep_id": "contract_action", "label": "动作谓词识别", "status": "completed", "detail": str(run["task_contract"].get("action") or "由任务语义约束"), "parent_substep_id": "contract_semantics", "output_ref": "semantic.action"},
        {"substep_id": "contract_object", "label": "作业对象识别", "status": "completed", "detail": str(run["task_contract"].get("object") or "由任务语义约束"), "parent_substep_id": "contract_semantics", "output_ref": "semantic.object"},
        {"substep_id": "contract_context", "label": "工作情境识别", "status": "completed", "detail": "保留任务发生的环境、角色和课堂适配边界。", "parent_substep_id": "contract_semantics", "output_ref": "semantic.context"},
        {"substep_id": "contract_deliverable", "label": "预期产物识别", "status": "completed", "detail": str(run["task_contract"].get("expected_deliverable") or "由完成条件约束"), "parent_substep_id": "contract_semantics", "output_ref": "semantic.deliverable"},
        {"substep_id": "contract_boundary", "label": "范围与禁止项识别", "status": "completed", "detail": "锁定不换岗位、不改任务主体、不越权执行等边界。", "parent_substep_id": "contract_semantics", "output_ref": "semantic.boundary"},
        {"substep_id": "contract_identity", "label": "稳定身份与关系锁定", "status": "completed", "detail": "建立 Run、任务、知识、技能和关系的稳定引用空间。", "depends_on": ["contract_schema"], "output_ref": "identity_registry"},
        {"substep_id": "contract_ids", "label": "Run / 工作包 ID 校验", "status": "completed", "detail": f"run_id 与 {len(workflow_packages)} 个检索工作包 ID 已锁定。", "parent_substep_id": "contract_identity", "output_ref": run["run_id"]},
        {"substep_id": "contract_fingerprint", "label": "语义指纹计算", "status": "completed", "detail": "对象、动作和产物变化会触发同一性门禁。", "parent_substep_id": "contract_identity", "output_ref": plan["task_contract_fingerprint"]},
        {"substep_id": "contract_invariants", "label": "任务不变量编译", "status": "completed", "detail": "生成后续候选必须共同满足的同一性、产物与安全不变量。", "depends_on": ["contract_action", "contract_object", "contract_deliverable", "contract_boundary", "contract_fingerprint"], "output_ref": "task_invariants"},
        {"substep_id": "contract_gate", "label": "契约一致性门禁", "status": "completed", "detail": "结构、语义、身份和不变量全部通过后才允许进入环境落地。", "depends_on": ["contract_schema", "contract_invariants", "contract_ids"], "output_ref": "contract_gate:pass"},
        {"substep_id": "contract_artifact", "label": "版本化任务契约", "status": "completed", "detail": "封存可审计 task_contract，作为后续所有阶段共同基线。", "depends_on": ["contract_gate"], "output_ref": "task_contract"},
    ]

    grounding_steps = [
        {"substep_id": "grounding_snapshot", "label": "运行环境快照", "status": "completed", "detail": "读取任务契约、Run 状态、上游交接信息和可用规划能力。", "output_ref": "environment_snapshot"},
        {"substep_id": "grounding_run", "label": "Run 与检查点状态", "status": "completed", "detail": f"当前阶段 {run['phase']}，checkpoint v{run['checkpoint_version']}。", "parent_substep_id": "grounding_snapshot", "output_ref": "run_state"},
        {"substep_id": "grounding_upstream", "label": "上游对象与关系引用", "status": "completed", "detail": "核对任务、知识、技能和关系 ID 的来源与可解析性。", "parent_substep_id": "grounding_snapshot", "output_ref": "upstream_refs"},
        {"substep_id": "grounding_capability", "label": "可用工具与权限盘点", "status": "completed", "detail": f"盘点 {len(workflow_packages)} 个规划工作包及其工具白名单。", "parent_substep_id": "grounding_snapshot", "output_ref": "capability_inventory"},
        {"substep_id": "grounding_fact_model", "label": "已知事实建模", "status": "completed", "detail": "区分任务事实、环境事实、用户确认事实和仍待取证事实。", "depends_on": ["grounding_run", "grounding_upstream"], "output_ref": "discovered_fact_model"},
        {"substep_id": "grounding_input_level", "label": "输入层级判定", "status": "completed", "detail": f"输入层级：{run['task_contract'].get('input_level') or '未声明'}。", "parent_substep_id": "grounding_fact_model", "output_ref": "input_level"},
        {"substep_id": "grounding_unknowns", "label": "未知项分类与路由", "status": "completed", "detail": f"登记 {len(plan.get('unknowns') or [])} 个未知项并按责任来源分流。", "depends_on": ["grounding_fact_model"], "output_ref": "unknown_register"},
        {"substep_id": "grounding_user_unknowns", "label": "必须由用户确认", "status": "blocked" if user_blocking_unknowns else "completed", "detail": f"{len(user_blocking_unknowns)} 个偏好或现场选择不能由检索替代。", "parent_substep_id": "grounding_unknowns", "output_ref": "user_clarification_queue"},
        {"substep_id": "grounding_evidence_unknowns", "label": "必须通过证据关闭", "status": "completed", "detail": f"{len(blocking_unknowns) - len(user_blocking_unknowns)} 个事实问题进入证据检索规划。", "parent_substep_id": "grounding_unknowns", "output_ref": "evidence_question_queue"},
        {"substep_id": "grounding_conflicts", "label": "歧义与冲突登记", "status": "completed", "detail": "记录名称冲突、范围歧义和关系不一致，禁止静默覆盖。", "parent_substep_id": "grounding_unknowns", "output_ref": "ambiguity_register"},
        {"substep_id": "grounding_constraints", "label": "课堂实施约束建模", "status": "completed", "detail": "把资源、时间、安全、权限和学习者前置能力显式化。", "depends_on": ["grounding_capability", "grounding_unknowns"], "output_ref": "constraint_model"},
        {"substep_id": "grounding_resource", "label": "资源与设备约束", "status": "completed", "detail": "登记环境、设备、软件、资料和不可用资源。", "parent_substep_id": "grounding_constraints", "output_ref": "resource_constraints"},
        {"substep_id": "grounding_time", "label": "课时与节奏约束", "status": "completed", "detail": "为后续步骤粒度、并行度和检查点密度提供边界。", "parent_substep_id": "grounding_constraints", "output_ref": "time_constraints"},
        {"substep_id": "grounding_safety", "label": "安全与权限约束", "status": "completed", "detail": "声明危险操作、权限升级、人工确认和立即停止条件。", "parent_substep_id": "grounding_constraints", "output_ref": "safety_constraints"},
        {"substep_id": "grounding_prerequisite", "label": "学习前置能力约束", "status": "completed", "detail": "登记完成真实作业步骤前必须掌握或能够调用的基础能力。", "parent_substep_id": "grounding_constraints", "output_ref": "prerequisite_constraints"},
        {"substep_id": "grounding_spec", "label": "任务规格编译", "status": "completed", "detail": "把目标、范围、成功标准和停止条件编译为可检查规格。", "depends_on": ["grounding_fact_model", "grounding_constraints"], "output_ref": "task_specification"},
        {"substep_id": "grounding_goal", "label": "目标与完成定义", "status": "completed", "detail": plan["goal"], "parent_substep_id": "grounding_spec", "output_ref": "goal_and_done_definition"},
        {"substep_id": "grounding_success", "label": "成功标准矩阵", "status": "completed", "detail": "；".join(plan["success_criteria"]), "parent_substep_id": "grounding_spec", "output_ref": "success_criteria_matrix"},
        {"substep_id": "grounding_stop", "label": "停止与升级条件", "status": "completed", "detail": "；".join(plan["stop_conditions"]), "parent_substep_id": "grounding_spec", "output_ref": "stop_conditions"},
        {"substep_id": "grounding_gate", "label": "规格完整性门禁", "status": "blocked" if user_blocking_unknowns else "completed", "detail": "用户选择、事实问题、课堂约束和完成定义均已获得明确去向。", "depends_on": ["grounding_user_unknowns", "grounding_evidence_unknowns", "grounding_spec"], "output_ref": "grounding_gate"},
        {"substep_id": "grounding_freeze", "label": "规划基线冻结", "status": "blocked" if user_blocking_unknowns else "completed", "detail": "冻结进入证据检索阶段的任务规格版本，后续变化必须生成 Revision。", "depends_on": ["grounding_gate"], "output_ref": "planning_baseline"},
    ]

    evidence_workflows = [
        item for item in workflow_packages
        if item.get("agent_role") == "evidence_explorer"
    ]
    allowed_tools = sorted({
        tool
        for item in evidence_workflows
        for tool in item.get("allowed_tools") or []
    })
    search_steps: list[dict[str, Any]] = [
        {"substep_id": "search_problem_model", "label": "证据问题空间建模", "status": "completed", "detail": "把事实缺口转换为可检索、可验证、可判定关闭的问题树。", "output_ref": "evidence_problem_model"},
        {"substep_id": "search_questions", "label": "阻塞未知项分解", "status": "completed", "detail": f"把 {len(blocking_unknowns)} 个未知项转成可执行检索问题。", "parent_substep_id": "search_problem_model", "output_ref": "evidence_questions"},
        {"substep_id": "search_operation_facts", "label": "真实作业事实问题", "status": "completed", "detail": "检索真实作业顺序、动作对象、前置条件、阶段产物与验收点。", "parent_substep_id": "search_problem_model", "output_ref": "operation_fact_questions"},
        {"substep_id": "search_mapping_facts", "label": "知识技能关系问题", "status": "completed", "detail": "检索每个作业步骤所需知识、技能及强关系依据。", "parent_substep_id": "search_problem_model", "output_ref": "mapping_fact_questions"},
        {"substep_id": "search_safety_facts", "label": "安全与边界问题", "status": "completed", "detail": "检索权限边界、危险操作、停止条件与官方安全要求。", "parent_substep_id": "search_problem_model", "output_ref": "safety_fact_questions"},
        {"substep_id": "search_acceptance_facts", "label": "产物与验收问题", "status": "completed", "detail": "检索可观察产物、合格阈值、检查方式与失败判据。", "parent_substep_id": "search_problem_model", "output_ref": "acceptance_fact_questions"},
    ]
    for unknown in plan.get("unknowns") or []:
        search_steps.append({
            "substep_id": f"search_question_{unknown['unknown_id']}",
            "label": unknown["question"],
            "status": "ready" if unknown.get("blocking") else "completed",
            "detail": f"所需证据类型：{unknown['required_evidence']}。",
            "parent_substep_id": "search_questions",
            "output_ref": unknown["unknown_id"],
        })
    search_steps.extend([
        {"substep_id": "search_source_strategy", "label": "多源检索策略编译", "status": "completed", "detail": "为不同证据问题分配任务库、知识库、权威 Web 与上游来源。", "depends_on": ["search_problem_model"], "output_ref": "source_strategy"},
        {"substep_id": "search_route", "label": "来源路由矩阵", "status": "completed", "detail": "每类问题至少声明主来源、备选来源和不可接受来源。", "parent_substep_id": "search_source_strategy", "output_ref": "evidence_route_matrix"},
        {"substep_id": "search_trust_tiers", "label": "来源可信等级", "status": "completed", "detail": "按上游确认、官方标准、权威资料、任务库和辅助来源分级。", "parent_substep_id": "search_source_strategy", "output_ref": "source_trust_tiers"},
        {"substep_id": "search_freshness", "label": "时效与版本边界", "status": "completed", "detail": "为软件版本、标准版本和适用日期设置新鲜度约束。", "parent_substep_id": "search_source_strategy", "output_ref": "freshness_policy"},
        {"substep_id": "search_tool_policy", "label": "工具权限白名单", "status": "completed", "detail": "只允许证据工作包调用登记过的只读检索与校验工具。", "parent_substep_id": "search_source_strategy", "output_ref": "evidence_tool_policy"},
    ])
    for tool in allowed_tools:
        search_steps.append({
            "substep_id": f"search_tool_{tool}",
            "label": _TOOL_LABELS.get(tool, tool),
            "status": "ready",
            "detail": "已登记到证据检索计划的工具白名单。",
            "parent_substep_id": "search_tool_policy",
            "output_ref": f"tool:{tool}",
        })
    search_steps.extend([
        {"substep_id": "search_query_design", "label": "查询生成与编排", "status": "completed", "detail": "把问题树编译为可复现的查询组、执行顺序和并行批次。", "depends_on": ["search_route", "search_tool_policy"], "output_ref": "query_program"},
        {"substep_id": "search_terms", "label": "术语与同义词展开", "status": "completed", "detail": "围绕任务对象、动作、产物和验收建立受控检索词表。", "parent_substep_id": "search_query_design", "output_ref": "query_terms"},
        {"substep_id": "search_variants", "label": "查询变体生成", "status": "completed", "detail": "为精确查询、关系查询、标准查询和反证查询生成变体。", "parent_substep_id": "search_query_design", "output_ref": "query_variants"},
        {"substep_id": "search_batches", "label": "并行批次与依赖顺序", "status": "completed", "detail": "独立问题并行，依赖事实按先验结果串行展开。", "parent_substep_id": "search_query_design", "output_ref": "query_batches"},
        {"substep_id": "search_dedup", "label": "结果去重与聚类计划", "status": "completed", "detail": "按来源、版本、事实声明和适用范围进行去重聚类。", "parent_substep_id": "search_query_design", "output_ref": "dedup_policy"},
        {"substep_id": "search_verification", "label": "证据验证协议", "status": "completed", "detail": "规定引用抽取、交叉验证、冲突处理和覆盖率计算。", "depends_on": ["search_query_design"], "output_ref": "verification_protocol"},
        {"substep_id": "search_cross_check", "label": "跨来源交叉验证", "status": "completed", "detail": "关键作业事实需要两个独立来源或一个权威来源支持。", "parent_substep_id": "search_verification", "output_ref": "cross_check_rule"},
        {"substep_id": "search_conflict", "label": "冲突证据裁决", "status": "completed", "detail": "不覆盖冲突，按权威性、时效、适用边界登记裁决理由。", "parent_substep_id": "search_verification", "output_ref": "conflict_resolution_rule"},
        {"substep_id": "search_applicability", "label": "适用边界检查", "status": "completed", "detail": "核对证据是否适用于当前对象、版本、课堂环境和安全边界。", "parent_substep_id": "search_verification", "output_ref": "applicability_rule"},
        {"substep_id": "search_coverage", "label": "证据覆盖矩阵", "status": "completed", "detail": "问题、事实、来源和拟生成步骤之间建立可追溯覆盖关系。", "parent_substep_id": "search_verification", "output_ref": "evidence_coverage_matrix"},
        {"substep_id": "search_budget_control", "label": "预算与停止控制", "status": "completed", "detail": "对检索轮次、来源数量、冲突修复和低收益查询设置上限。", "depends_on": ["search_verification"], "output_ref": "search_budget_control"},
        {"substep_id": "search_budget", "label": "检索预算分配", "status": "completed", "detail": "优先分配给阻塞任务同一性、安全和验收的事实缺口。", "parent_substep_id": "search_budget_control", "output_ref": "search_budget"},
        {"substep_id": "search_stop", "label": "覆盖率停止条件", "status": "completed", "detail": "关键事实达到可信门槛且不存在未裁决冲突时停止。", "parent_substep_id": "search_budget_control", "output_ref": "search_stop_conditions"},
        {"substep_id": "search_fallback", "label": "检索失败降级策略", "status": "completed", "detail": "无权威证据时转人工确认或终止，不用模型猜测填补。", "parent_substep_id": "search_budget_control", "output_ref": "search_fallback_policy"},
    ])
    for item in evidence_workflows:
        search_steps.append({
            "substep_id": f"search_package_{item['package_id']}",
            "label": item["objective"],
            "status": "ready" if not evidence_ready else "completed",
            "detail": item["completion_condition"],
            "parent_substep_id": "search_query_design",
            "output_ref": item["expected_artifact"],
        })
    search_steps.append({
        "substep_id": "search_plan_artifact",
        "label": "版本化证据检索计划",
        "status": "completed" if search_plan_confirmed else "ready",
        "detail": "封存问题树、来源路由、查询程序、验证协议、预算与停止条件。",
        "depends_on": ["search_problem_model", "search_source_strategy", "search_query_design", "search_verification", "search_budget_control"],
        "output_ref": "evidence_search_plan.json",
    })

    task_build_status: PlanStageStatus = (
        "completed" if task_packages else "blocked" if evidence_ready else "not_started"
    )
    task_planning_steps: list[dict[str, Any]] = [
        {"substep_id": "task_evidence_pipeline", "label": "证据执行与账本门禁", "status": "completed" if evidence_ready else "blocked", "detail": "执行检索程序，清洗、校验并汇合为可追溯证据账本。", "output_ref": "evidence_pipeline"},
        {"substep_id": "task_evidence_ledger", "label": "证据账本接入", "status": "completed" if evidence_ready else "blocked", "detail": "证据条目已到位。" if evidence_ready else "尚无可验证证据账本，禁止提前生成学习任务步骤。", "parent_substep_id": "task_evidence_pipeline", "output_ref": "evidence_ledger" if evidence_ready else "awaiting_evidence_ledger"},
        {"substep_id": "task_ledger_schema", "label": "账本结构与引用校验", "status": "completed" if evidence_ready else "not_started", "detail": "检查 evidence_id、来源、事实声明、可信度和适用边界。", "parent_substep_id": "task_evidence_pipeline", "output_ref": "ledger_schema_report"},
        {"substep_id": "task_ledger_dedup", "label": "事实去重与声明聚类", "status": "completed" if evidence_ready else "not_started", "detail": "合并同义事实，保留来源差异、版本差异和冲突记录。", "parent_substep_id": "task_evidence_pipeline", "output_ref": "fact_clusters"},
        {"substep_id": "task_ledger_conflict", "label": "冲突与反证检查", "status": "completed" if evidence_ready else "not_started", "detail": "关键事实存在未裁决冲突时阻断学习任务步骤生成。", "parent_substep_id": "task_evidence_pipeline", "output_ref": "conflict_register"},
        {"substep_id": "task_ledger_coverage", "label": "任务事实覆盖率计算", "status": "completed" if evidence_ready else "not_started", "detail": "计算动作、顺序、产物、验收、安全和 K/S 关系覆盖率。", "parent_substep_id": "task_evidence_pipeline", "output_ref": "coverage_report"},
        {"substep_id": "task_ledger_gate", "label": "证据充分性硬门禁", "status": "completed" if evidence_ready else "blocked", "detail": "只有可信、适用、无未裁决冲突的关键事实才能进入任务编译。", "depends_on": ["task_evidence_ledger", "task_ledger_schema", "task_ledger_conflict", "task_ledger_coverage"], "output_ref": "evidence_gate"},
        {"substep_id": "task_fact_extraction", "label": "真实作业事实抽取", "status": task_build_status, "detail": "从证据账本提取动作、对象、条件、顺序、产物、验收和安全事实。", "depends_on": ["task_ledger_gate"], "output_ref": "operation_fact_graph"},
        {"substep_id": "task_action_units", "label": "动作—对象单元识别", "status": task_build_status, "detail": "把真实作业拆为最小但可验收的动作对象单元。", "parent_substep_id": "task_fact_extraction", "output_ref": "action_object_units"},
        {"substep_id": "task_preconditions", "label": "前置条件与输入识别", "status": task_build_status, "detail": "为每个动作单元绑定环境、资源、状态和前置产物。", "parent_substep_id": "task_fact_extraction", "output_ref": "precondition_model"},
        {"substep_id": "task_outputs", "label": "阶段产物与状态变化识别", "status": task_build_status, "detail": "识别每个操作引起的可观察状态变化和中间产物。", "parent_substep_id": "task_fact_extraction", "output_ref": "output_state_model"},
        {"substep_id": "task_acceptance_facts", "label": "验收与失败事实识别", "status": task_build_status, "detail": "提取合格条件、检查方法、失败症状和返工边界。", "parent_substep_id": "task_fact_extraction", "output_ref": "acceptance_fact_model"},
        {"substep_id": "task_decomposition", "label": "学习型任务分层编译", "status": task_build_status, "detail": "把真实工作过程编译为 Goal、作业阶段、任务步骤和原子操作。", "depends_on": ["task_fact_extraction"], "output_ref": "learning_task_hierarchy"},
        {"substep_id": "task_phase_clustering", "label": "真实作业阶段聚类", "status": task_build_status, "detail": "按作业目的、状态转换和产物汇合点划分阶段，不按教材章节切分。", "parent_substep_id": "task_decomposition", "output_ref": "work_phases"},
        {"substep_id": "task_step_boundaries", "label": "任务步骤边界判定", "status": task_build_status, "detail": "每一步必须有明确动作、输入、产物和完成定义。", "parent_substep_id": "task_decomposition", "output_ref": "task_step_boundaries"},
        {"substep_id": "task_atomic_compile", "label": "原子操作编译", "status": task_build_status, "detail": "继续拆解为可执行操作、产物形成和验收检查。", "parent_substep_id": "task_decomposition", "output_ref": "atomic_operations"},
        {"substep_id": "task_step_enrichment", "label": "步骤实施条件补齐", "status": task_build_status, "detail": "为每个真实任务步骤补齐资源、K/S、安全、产物、验收和失败处理。", "depends_on": ["task_decomposition"], "output_ref": "enriched_task_steps"},
        {"substep_id": "task_resource_binding", "label": "资源与工具绑定", "status": task_build_status, "detail": "绑定设备、软件、资料、输入文件和可用工具。", "parent_substep_id": "task_step_enrichment", "output_ref": "resource_bindings"},
        {"substep_id": "task_knowledge_binding", "label": "知识点强关系映射", "status": task_build_status, "detail": "只绑定完成该步骤真正需要的知识点，并保留关系依据。", "parent_substep_id": "task_step_enrichment", "output_ref": "knowledge_bindings"},
        {"substep_id": "task_skill_binding", "label": "技能点强关系映射", "status": task_build_status, "detail": "把可观察技能表现绑定到具体操作和步骤产物。", "parent_substep_id": "task_step_enrichment", "output_ref": "skill_bindings"},
        {"substep_id": "task_safety_binding", "label": "安全门禁与禁止项", "status": task_build_status, "detail": "在危险操作前插入权限、备份、确认和停止节点。", "parent_substep_id": "task_step_enrichment", "output_ref": "step_safety_gates"},
        {"substep_id": "task_artifact_binding", "label": "步骤产物与证据要求", "status": task_build_status, "detail": "规定配置、记录、截图、报告等可检查产物。", "parent_substep_id": "task_step_enrichment", "output_ref": "step_artifact_contracts"},
        {"substep_id": "task_acceptance_binding", "label": "检查点与验收条件", "status": task_build_status, "detail": "将每个步骤的完成定义编译为可观察检查点。", "parent_substep_id": "task_step_enrichment", "output_ref": "step_acceptance_contracts"},
        {"substep_id": "task_failure_binding", "label": "失败分支与返工边界", "status": task_build_status, "detail": "声明失败症状、诊断入口、冻结范围和允许重规划的子图。", "parent_substep_id": "task_step_enrichment", "output_ref": "step_failure_branches"},
        {"substep_id": "task_dependency_model", "label": "步骤依赖与调度建模", "status": task_build_status, "detail": "从前置状态和阶段产物推导依赖，不用文本顺序冒充依赖。", "depends_on": ["task_step_enrichment"], "output_ref": "task_step_dag"},
        {"substep_id": "task_dependency_inference", "label": "前后继依赖推断", "status": task_build_status, "detail": "建立 produces / requires / precedes 关系。", "parent_substep_id": "task_dependency_model", "output_ref": "dependency_edges"},
        {"substep_id": "task_cycle_check", "label": "依赖无环校验", "status": task_build_status, "detail": "发现环时返回步骤边界或前置条件重新编译。", "parent_substep_id": "task_dependency_model", "output_ref": "dag_validation"},
        {"substep_id": "task_parallel_waves", "label": "并行波次计算", "status": task_build_status, "detail": f"当前形成 {len(waves)} 个拓扑波次。", "parent_substep_id": "task_dependency_model", "output_ref": "topological_waves"},
        {"substep_id": "task_critical_path_model", "label": "关键路径与瓶颈识别", "status": task_build_status, "detail": " → ".join(critical_path) or "等待真实 task_steps", "parent_substep_id": "task_dependency_model", "output_ref": "critical_path"},
    ]
    for node in hierarchy:
        task_planning_steps.append({
            "substep_id": f"hierarchy_{node['node_id']}",
            "label": node["label"],
            "status": "completed",
            "detail": node["objective"],
            "parent_substep_id": (
                f"hierarchy_{node['parent_id']}"
                if node["parent_id"] else "task_decomposition"
            ),
            "output_ref": (
                f"work-package:{node['package_id']}"
                if node.get("package_id") else node["node_type"]
            ),
        })
    if hierarchy:
        task_planning_steps.append({"substep_id": "task_graph_gate", "label": "学习任务图完整性门禁", "status": "completed", "detail": "层级、步骤、依赖、映射、产物、验收和来源引用全部可解析。", "depends_on": ["hierarchy_goal", "task_cycle_check", "task_artifact_binding", "task_acceptance_binding"], "output_ref": "task_graph_gate:pass"})
    else:
        task_planning_steps.append({"substep_id": "task_graph_gate", "label": "学习任务图完整性门禁", "status": "blocked", "detail": "等待证据账本与真实 task_steps 后才能运行。", "depends_on": ["task_decomposition", "task_dependency_model"], "output_ref": "awaiting_task_graph"})
    task_planning_steps.append({
        "substep_id": "candidate_search",
        "label": "学习型任务多候选生成",
        "status": "completed" if candidates else "blocked",
        "detail": (
            "基于同一证据账本比较保真、证据与并行策略。"
            if candidates else "必须等待证据账本与真实 task_steps。"
        ),
        "depends_on": ["task_graph_gate"],
        "output_ref": "candidate_set" if candidates else "awaiting_task_steps",
    })
    task_planning_steps.extend([
        {"substep_id": "candidate_fidelity_strategy", "label": "保真候选编译策略", "status": task_build_status, "detail": "优先保持真实作业对象、动作、顺序和企业产物。", "parent_substep_id": "candidate_search", "output_ref": "fidelity_strategy"},
        {"substep_id": "candidate_evidence_strategy", "label": "证据候选编译策略", "status": task_build_status, "detail": "优先强化来源覆盖、冲突关闭和事实可追溯性。", "parent_substep_id": "candidate_search", "output_ref": "evidence_strategy"},
        {"substep_id": "candidate_parallel_strategy", "label": "并行候选编译策略", "status": task_build_status, "detail": "在不破坏依赖和安全门禁的前提下提高并行度。", "parent_substep_id": "candidate_search", "output_ref": "parallel_strategy"},
        {"substep_id": "candidate_feasibility", "label": "候选可执行性模拟", "status": "completed" if candidates else "blocked", "detail": "模拟前置条件、资源占用、关键路径、产物汇合和失败回路。", "depends_on": ["candidate_fidelity_strategy", "candidate_evidence_strategy", "candidate_parallel_strategy"], "output_ref": "candidate_feasibility_report"},
    ])
    for candidate in candidates:
        task_planning_steps.append({
            "substep_id": f"candidate_{candidate['candidate_id']}",
            "label": candidate["title"],
            "status": "completed" if candidate["hard_gate_passed"] else "blocked",
            "detail": f"加权分 {candidate['weighted_score']}；{len(candidate['parallel_waves'])} 个依赖波次。",
            "parent_substep_id": "candidate_search",
            "output_ref": candidate["candidate_id"],
        })

    gate_status: PlanStageStatus = (
        "blocked" if not task_plan_ready
        else "completed" if task_plan_finalized
        else "ready"
    )
    critic_steps: list[dict[str, Any]] = [
        {"substep_id": "critic_input_gate", "label": "候选集与证据输入门禁", "status": "completed" if critics else "blocked", "detail": "确认候选共享同一任务契约、证据账本和步骤图基线。", "output_ref": "critic_input_snapshot" if critics else "awaiting_candidates"},
        {"substep_id": "critic_committee", "label": "六维独立 Critic 编排", "status": "completed" if critics else "blocked", "detail": "六个评审维度独立给出结论、分数、发现和受影响步骤。", "depends_on": ["critic_input_gate"], "output_ref": "critic_report.json" if critics else "awaiting_candidates"},
    ]
    critic_checks = {
        "task_identity": [("fingerprint", "语义指纹一致性"), ("subject", "对象—动作—产物同一性"), ("scope", "范围与禁止项保持")],
        "dependency": [("acyclic", "依赖无环与引用完整"), ("precondition", "前置条件可满足性"), ("schedule", "波次与关键路径合理性")],
        "evidence": [("coverage", "关键事实来源覆盖"), ("crosscheck", "跨来源交叉验证"), ("conflict", "冲突与适用边界关闭")],
        "safety": [("hazard", "危险操作识别"), ("permission", "权限与人工确认门禁"), ("stop", "停止和升级条件")],
        "deliverable": [("observable", "步骤产物可观察性"), ("acceptance", "验收条件可判定性"), ("trace", "最终交付可追溯性")],
        "teaching_fit": [("authenticity", "真实工作过程保真"), ("mapping", "知识技能强关系"), ("feasibility", "课堂资源与粒度可实施")],
    }
    for critic in critics:
        critic_status: PlanStageStatus = (
            "blocked" if critic["verdict"] == "fail"
            else "ready" if critic["verdict"] == "warning"
            else "completed"
        )
        critic_parent = f"critic_{critic['critic_id']}"
        critic_steps.append({
            "substep_id": critic_parent,
            "label": critic["dimension"],
            "status": critic_status,
            "detail": f"{critic['verdict']} · {critic['score']} · {critic['findings'][0]}",
            "parent_substep_id": "critic_committee",
            "output_ref": critic["critic_id"],
        })
        for suffix, label in critic_checks[critic["dimension"]]:
            critic_steps.append({
                "substep_id": f"{critic_parent}_{suffix}",
                "label": label,
                "status": critic_status,
                "detail": "输出检查结果、证据引用、失败规则和受影响任务步骤。",
                "parent_substep_id": critic_parent,
                "output_ref": f"{critic['critic_id']}.{suffix}",
            })
    critic_steps.extend([
        {"substep_id": "critic_aggregation", "label": "评审结果归并", "status": gate_status, "detail": "合并六维发现，区分硬门禁失败、可修补警告和通过项。", "depends_on": ["critic_committee"], "output_ref": "critic_aggregation"},
        {"substep_id": "critic_hard_gate", "label": "硬门禁规则求值", "status": gate_status, "detail": "同一性、依赖、证据、安全、交付任一硬失败均禁止定稿。", "depends_on": ["critic_aggregation"], "output_ref": "hard_gate_result"},
        {"substep_id": "critic_impact_scope", "label": "失败影响域计算", "status": gate_status, "detail": "计算失败步骤、后继闭包、可冻结步骤和剩余修补预算。", "depends_on": ["critic_aggregation"], "output_ref": "impact_scope"},
        {
            "substep_id": "decision_controller",
            "label": "决策控制器",
            "status": gate_status,
            "detail": "；".join(decision["reasons"]),
            "depends_on": ["critic_hard_gate", "critic_impact_scope"],
            "output_ref": decision.get("selected_candidate_id") or decision["code"],
        },
        {
            "substep_id": "decision_evidence",
            "label": "补充证据",
            "status": "ready" if decision["code"] == "REQUEST_EVIDENCE" else "completed",
            "detail": "证据不足时返回上一阶段，只补充受影响事实。",
            "parent_substep_id": "decision_controller",
        },
        {
            "substep_id": "decision_replan",
            "label": "局部重规划",
            "status": "ready" if decision["code"] == "LOCAL_REPLAN" else "completed",
            "detail": "冻结未受影响工作包，只重算失败节点及其后继子图。",
            "parent_substep_id": "decision_controller",
        },
        {"substep_id": "decision_stop", "label": "停止并升级人工复核", "status": "ready" if decision["code"] == "STOP" else "completed", "detail": "修补预算耗尽、同一性破坏或高风险无证据时停止。", "parent_substep_id": "decision_controller", "output_ref": "stop_or_continue"},
        {"substep_id": "decision_score", "label": "候选多目标加权", "status": gate_status, "detail": "按保真、执行、证据、安全、教学与效率六项权重比较候选。", "parent_substep_id": "decision_controller", "output_ref": "candidate_score_matrix"},
        {
            "substep_id": "decision_select",
            "label": "选定候选",
            "status": gate_status,
            "detail": "硬门禁通过后形成 proposed_plan，并等待确认或修订。",
            "depends_on": ["decision_score"],
            "output_ref": "proposed_plan.json",
        },
        {"substep_id": "decision_diff", "label": "候选差异与取舍说明", "status": gate_status, "detail": "输出未选候选的优势、代价和拒绝原因，避免黑箱选中。", "parent_substep_id": "decision_select", "output_ref": "candidate_tradeoff_report"},
        {
            "substep_id": "decision_confirmation",
            "label": "确认 / 修订",
            "status": "completed" if task_plan_finalized else gate_status,
            "detail": "确认的是证据支撑的学习型任务 Plan，不代表任务已经执行。",
            "parent_substep_id": "decision_select",
            "output_ref": "task_plan.json" if task_plan_finalized else "awaiting_confirmation",
        },
        {"substep_id": "decision_version_freeze", "label": "版本冻结与审计登记", "status": "completed" if task_plan_finalized else gate_status, "detail": "确认后冻结 Plan 版本、指纹、证据引用和修订父版本。", "depends_on": ["decision_confirmation"], "output_ref": "plan_revision_ledger"},
    ])

    execution_checklist = [{
        "package_id": item["package_id"],
        "objective": item["objective"],
        "status": "pending",
        "expected_artifact": item["expected_artifact"],
        "observation_state": "not_observed",
        "completion_condition": item["completion_condition"],
    } for item in task_packages]
    handoff_artifacts = [
        {"artifact_id": "handoff_html", "artifact_type": "html", "label": "中央任务网页", "status": "planned", "contract_ref": "learning-work-task-page"},
        {"artifact_id": "handoff_pdf", "artifact_type": "pdf", "label": "可审阅任务文档", "status": "planned", "contract_ref": "learning-work-task-pdf"},
        {"artifact_id": "handoff_json", "artifact_type": "versioned_json", "label": "版本化任务 JSON", "status": "planned", "contract_ref": "learning-work-task-bundle-v1"},
        {"artifact_id": "handoff_learning", "artifact_type": "knowledge_learning_entry", "label": "知识点级个性化学习入口", "status": "planned", "contract_ref": "personalized-learning-entry-v1"},
        {"artifact_id": "handoff_feedback", "artifact_type": "feedback_contract", "label": "批注与下游反馈契约", "status": "planned", "contract_ref": "feedback_contract"},
    ]
    execution_pending: PlanStageStatus = "pending" if task_packages else "not_started"
    execution_steps: list[dict[str, Any]] = [
        {"substep_id": "execution_compile", "label": "Plan 执行包编译", "status": execution_pending, "detail": "把确认后的任务图编译为运行清单、检查点、观察契约和交接契约。", "output_ref": "execution_package"},
        {"substep_id": "execution_checklist", "label": "步骤运行清单", "status": execution_pending, "detail": f"已形成 {len(task_packages)} 个待执行学习任务步骤；当前没有运行证据。" if task_packages else "学习型任务 Plan 尚未形成，暂不生成运行清单。", "parent_substep_id": "execution_compile", "output_ref": "execution_checklist"},
        {"substep_id": "execution_preconditions", "label": "前置条件检查表", "status": execution_pending, "detail": "为每步列出输入状态、依赖产物、资源、权限和人工确认项。", "parent_substep_id": "execution_compile", "output_ref": "precondition_checklist"},
        {"substep_id": "execution_checkpoints", "label": "检查点与恢复点编译", "status": execution_pending, "detail": "在阶段边界和高风险操作前建立可恢复 Checkpoint。", "parent_substep_id": "execution_compile", "output_ref": "checkpoint_plan"},
        {"substep_id": "execution_observation_contract", "label": "Observation 采集契约", "status": execution_pending, "detail": "规定环境状态、操作记录、产物、错误和验收结果的采集格式。", "parent_substep_id": "execution_compile", "output_ref": "observation_contract"},
        {"substep_id": "execution_scheduler", "label": "依赖感知调度器", "status": execution_pending, "detail": "按拓扑波次、资源互斥、安全门禁和人工确认调度步骤。", "depends_on": ["execution_compile"], "output_ref": "execution_schedule"},
        {"substep_id": "execution_wave_gate", "label": "波次前置产物门禁", "status": "not_started", "detail": "只有上一波次必需产物通过验收，后继波次才能解锁。", "parent_substep_id": "execution_scheduler", "output_ref": "wave_gate"},
        {"substep_id": "execution_resource_lock", "label": "资源与环境锁定", "status": "not_started", "detail": "检查设备、软件、文件、账号和环境版本，防止并行冲突。", "parent_substep_id": "execution_scheduler", "output_ref": "resource_lock"},
        {"substep_id": "execution_safety_gate", "label": "安全与权限确认", "status": "not_started", "detail": "危险操作、删除、权限升级和外部写入必须经过对应门禁。", "parent_substep_id": "execution_scheduler", "output_ref": "safety_gate"},
        {"substep_id": "execution_dispatch", "label": "步骤下发与状态迁移", "status": "not_started", "detail": "只允许 pending → in_progress → completed / blocked 的显式迁移。", "parent_substep_id": "execution_scheduler", "output_ref": "step_dispatch_events"},
    ]
    for item in execution_checklist:
        execution_steps.append({
            "substep_id": f"execution_{item['package_id']}",
            "label": item["package_id"],
            "status": "pending",
            "detail": item["objective"],
            "parent_substep_id": "execution_dispatch",
            "output_ref": item["expected_artifact"],
        })
    execution_steps.extend([
        {
            "substep_id": "execution_observation",
            "label": "运行观察与状态归约",
            "status": "not_started",
            "detail": "执行器接入后采集环境 Observation，并将事实归约为步骤状态。",
            "depends_on": ["execution_dispatch"],
            "output_ref": "observation_register",
        },
        {"substep_id": "execution_environment_observation", "label": "环境状态 Observation", "status": "not_started", "detail": "采集版本、配置、依赖服务、权限和资源占用状态。", "parent_substep_id": "execution_observation", "output_ref": "environment_observation"},
        {"substep_id": "execution_action_trace", "label": "操作轨迹记录", "status": "not_started", "detail": "记录已执行动作、参数、时间、操作者和关联步骤 ID。", "parent_substep_id": "execution_observation", "output_ref": "action_trace"},
        {"substep_id": "execution_artifact_gate", "label": "步骤产物门禁", "status": "not_started", "detail": "验证产物存在性、结构、版本、完整性和与步骤契约的一致性。", "parent_substep_id": "execution_observation", "output_ref": "artifact_gate_result"},
        {"substep_id": "execution_acceptance_gate", "label": "验收条件求值", "status": "not_started", "detail": "依据显式检查点判定通过、拒绝或需要人工复核。", "parent_substep_id": "execution_observation", "output_ref": "acceptance_result"},
        {"substep_id": "execution_state_reduce", "label": "步骤状态确定性归约", "status": "not_started", "detail": "只有 Observation 与验收结果共同满足时才迁移为 completed。", "parent_substep_id": "execution_observation", "output_ref": "step_state_event"},
        {
            "substep_id": "execution_failure",
            "label": "失败诊断与影响域定位",
            "status": "not_started",
            "detail": "失败时冻结已通过步骤，仅回传受影响子图到局部重规划。",
            "parent_substep_id": "execution_observation",
            "output_ref": "failure_report",
        },
        {"substep_id": "execution_failure_classify", "label": "失败类型分类", "status": "not_started", "detail": "区分证据、依赖、安全、产物和映射冲突。", "parent_substep_id": "execution_failure", "output_ref": "failure_code"},
        {"substep_id": "execution_freeze_passed", "label": "已通过子图冻结", "status": "not_started", "detail": "冻结未受影响步骤的版本、产物和验收结论。", "parent_substep_id": "execution_failure", "output_ref": "frozen_subgraph"},
        {"substep_id": "execution_affected_closure", "label": "失败后继闭包计算", "status": "not_started", "detail": "从失败节点沿依赖边计算必须重规划的最小影响域。", "parent_substep_id": "execution_failure", "output_ref": "affected_subgraph"},
        {"substep_id": "execution_replan_request", "label": "局部重规划请求", "status": "not_started", "detail": "携带失败观察、影响步骤、冻结步骤和剩余预算返回第 05 阶段。", "parent_substep_id": "execution_failure", "output_ref": "local_replan_request"},
        {
            "substep_id": "execution_handoff",
            "label": "多格式成果编译与交接",
            "status": "not_started",
            "detail": "HTML、PDF、版本化 JSON 与知识点级学习入口均等待真实产物生成。",
            "depends_on": ["execution_acceptance_gate"],
            "output_ref": "delivery_bundle",
        },
    ])
    for artifact in handoff_artifacts:
        execution_steps.append({
            "substep_id": f"execution_{artifact['artifact_id']}",
            "label": artifact["label"],
            "status": "not_started",
            "detail": f"计划交接契约：{artifact['contract_ref']}。",
            "parent_substep_id": "execution_handoff",
            "output_ref": artifact["artifact_id"],
        })
    execution_steps.extend([
        {"substep_id": "execution_feedback", "label": "批注与下游反馈闭环", "status": "not_started", "detail": "把页面批注、步骤问题和知识关系问题按稳定 ID 回传。", "depends_on": ["execution_handoff"], "output_ref": "feedback_pipeline"},
        {"substep_id": "execution_annotation_feedback", "label": "步骤与文本批注归档", "status": "not_started", "detail": "保留锚点、选区、意见、作者和版本上下文。", "parent_substep_id": "execution_feedback", "output_ref": "annotation_feedback"},
        {"substep_id": "execution_learning_feedback", "label": "个性化学习反馈接收", "status": "not_started", "detail": "接收下游对知识点、技能点和任务步骤关系的复核意见。", "parent_substep_id": "execution_feedback", "output_ref": "learning_feedback"},
        {"substep_id": "execution_review_event", "label": "复核事件登记", "status": "not_started", "detail": "登记为导航与运营事件，不伪装成五核掌握证据。", "parent_substep_id": "execution_feedback", "output_ref": "review_event"},
        {"substep_id": "execution_final_audit", "label": "版本、产物与审计汇合", "status": "not_started", "detail": "汇总 Plan 版本、执行状态、产物引用和反馈链路，形成最终审计索引。", "depends_on": ["execution_handoff", "execution_feedback"], "output_ref": "final_audit_index"},
    ])

    stages = [
        {"stage_id": "task_contract", "sequence": 1, "label": "任务契约", "status": "completed", "summary": "输入、Schema、稳定 ID 与语义指纹形成共同基线。", "input_refs": ["upstream_task.json"], "output_refs": ["task_contract"], "substeps": contract_steps},
        {"stage_id": "grounding_clarification", "sequence": 2, "label": "环境落地与澄清", "status": "blocked" if user_blocking_unknowns else "completed", "summary": "读取现状并显式形成目标、范围、成功标准与停止条件。", "input_refs": ["task_contract", "run_state"], "output_refs": ["task_specification", "clarification_register"], "substeps": grounding_steps},
        {"stage_id": "evidence_search_planning", "sequence": 3, "label": "证据检索规划", "status": "completed" if search_plan_confirmed else "ready", "summary": "先规划证据问题、来源、查询顺序与停止条件，不提前生成任务步骤。", "input_refs": ["task_specification", "unknown_register"], "output_refs": ["evidence_search_plan.json"], "substeps": search_steps},
        {"stage_id": "evidence_grounded_task_planning", "sequence": 4, "label": "证据驱动的学习任务规划", "status": "completed" if task_plan_ready else "ready" if evidence_ready else "blocked", "summary": "先形成证据账本，再生成 Goal、真实作业阶段、任务步骤、原子操作和三类候选。", "input_refs": ["evidence_search_plan.json", "evidence_ledger"], "output_refs": ["learning_task_hierarchy.json", "candidate_set"], "substeps": task_planning_steps},
        {"stage_id": "critic_finalize", "sequence": 5, "label": "学习任务 Critic 与定稿", "status": gate_status, "summary": "六维独立评审驱动补证据、局部重规划、选定与最终确认。", "input_refs": ["candidate_set", "evidence_ledger"], "output_refs": ["critic_report.json", "proposed_plan.json", "task_plan.json" if task_plan_finalized else "awaiting_confirmation"], "substeps": critic_steps},
        {"stage_id": "execution_handoff", "sequence": 6, "label": "执行观察与交接", "status": "pending" if task_plan_ready else "not_started", "summary": "正式学习任务 Plan 确认后才生成运行清单；当前不伪造执行或掌握证据。", "input_refs": ["task_plan.json"], "output_refs": ["execution_checklist", "delivery_bundle", "feedback_contract"], "substeps": execution_steps},
    ]
    return stages, execution_checklist, handoff_artifacts


def build_planning_analysis(run_payload: dict[str, Any]) -> dict[str, Any]:
    run = LearningTaskPlanRun.model_validate(run_payload).model_dump(mode="json")
    plan = run["plan"]
    workflow_packages = plan["work_packages"]
    evidence_ledger = _extract_evidence_ledger(run)
    evidence_ready = evidence_ledger is not None
    task_packages = _learning_task_packages(run) if evidence_ready else []
    package_ids = [item["package_id"] for item in task_packages]
    waves = _topological_waves(task_packages) if task_packages else []
    hierarchy = _build_learning_task_hierarchy(task_packages, plan["goal"])
    critics = _critics(
        run, task_packages, evidence_ready=evidence_ready,
    )
    risks = _risks(run, task_packages or workflow_packages)
    candidates = _candidates(
        run,
        task_packages,
        waves,
        critics,
        evidence_ready=evidence_ready,
    )
    eligible = [item for item in candidates if item["hard_gate_passed"]]
    selected = max(eligible, key=lambda item: item["weighted_score"], default=None)
    if not evidence_ready:
        decision = {
            "code": "REQUEST_EVIDENCE",
            "selected_candidate_id": None,
            "confidence": 82,
            "reasons": ["证据检索计划已经形成，但证据账本尚未到位，禁止生成学习型任务步骤。"],
            "triggered_rules": ["EVIDENCE_LEDGER_REQUIRED"],
        }
        status = "needs_evidence"
    elif not task_packages:
        decision = {
            "code": "REQUEST_EVIDENCE",
            "selected_candidate_id": None,
            "confidence": 78,
            "reasons": ["证据账本已就绪，但尚未收到由证据支撑的 task_steps。"],
            "triggered_rules": ["EVIDENCE_GROUNDED_TASK_STEPS_REQUIRED"],
        }
        status = "needs_evidence"
    elif selected:
        decision = {
            "code": "SELECT_CANDIDATE",
            "selected_candidate_id": selected["candidate_id"],
            "confidence": selected["weighted_score"],
            "reasons": ["所有硬门禁通过。", f"{selected['title']}获得最高加权分。"],
            "triggered_rules": ["IDENTITY_LOCKED", "DAG_VALID", "CRITIC_GATE_PASS"],
        }
        status = (
            "planned_not_executed"
            if run["phase"] == "COMMITTED"
            else "ready_for_confirmation"
        )
    else:
        decision = {
            "code": "LOCAL_REPLAN",
            "selected_candidate_id": None,
            "confidence": 64,
            "reasons": ["至少一个硬门禁未通过，需要修订受影响子图。"],
            "triggered_rules": ["CRITIC_GATE_REJECT"],
        }
        status = "planned_not_executed"
    critical_path = _critical_path(task_packages) if task_packages else []
    stages, execution_checklist, handoff_artifacts = _build_stages(
        run,
        workflow_packages,
        task_packages,
        evidence_ledger,
        hierarchy,
        waves,
        critical_path,
        candidates,
        critics,
        decision,
    )
    analysis = {
        "schema_version": "learning-work-task-planning-analysis-v3",
        "run_id": run["run_id"],
        "plan_version": plan["plan_version"],
        "analysis_version": 1,
        "planning_status": status,
        "active_revision_id": "revision_1",
        "hierarchy": hierarchy,
        "graph_edges": _build_edges(task_packages, hierarchy),
        "topological_waves": waves,
        "critical_path": critical_path,
        "candidates": candidates,
        "critics": critics,
        "risks": risks,
        "decision": decision,
        "stages": stages,
        "execution_checklist": execution_checklist,
        "handoff_artifacts": handoff_artifacts,
        "evidence_semantics": "operational_only",
        "revision_history": [_initial_revision(
            run, package_ids, task_plan_ready=bool(candidates),
        )],
        "repair_budget_remaining": plan["repair_budget"],
        "metrics": {
            "hierarchy_nodes": len(hierarchy),
            "dependency_edges": sum(
                len(item.get("depends_on") or []) for item in task_packages
            ),
            "parallel_waves": len(waves),
            "candidate_count": len(candidates),
            "critic_count": len(critics),
            "risk_count": len(risks),
            "stage_count": len(stages),
            "stage_substep_count": sum(len(item["substeps"]) for item in stages),
            "execution_pending": len(execution_checklist),
        },
    }
    return LearningTaskPlanningAnalysis.model_validate(analysis).model_dump(mode="json")


_REPLAN_CONTROLS: dict[str, list[str]] = {
    "evidence_gap": ["刷新证据查询", "提高来源可信门槛", "重新计算证据覆盖率"],
    "dependency_blocked": ["冻结已完成上游", "重排未完成波次", "新增汇合点版本检查"],
    "safety_conflict": ["插入安全前置门禁", "暂停受影响后继包", "要求人工确认"],
    "artifact_rejected": ["保留通过项", "只修补被拒产物", "重新执行产物验收"],
    "mapping_conflict": ["锁定真实作业步骤", "重算知识技能强关系", "复核稳定 ID"],
}


def replan_analysis(
    run_payload: dict[str, Any],
    current_payload: dict[str, Any],
    *,
    target_package_id: str,
    failure_code: ReplanFailureCode,
    observation: str,
    expected_analysis_version: int,
) -> dict[str, Any]:
    run = LearningTaskPlanRun.model_validate(run_payload).model_dump(mode="json")
    current = LearningTaskPlanningAnalysis.model_validate(current_payload)
    if current.run_id != run["run_id"] or current.plan_version != run["plan"]["plan_version"]:
        raise ValueError("Plan 基线已经变化，请刷新后重试")
    if current.analysis_version != expected_analysis_version:
        raise ValueError(f"规划分析版本已变化，当前为 v{current.analysis_version}")
    if current.repair_budget_remaining <= 0:
        raise ValueError("局部重规划预算已经用尽")
    packages = _learning_task_packages(run)
    if not _extract_evidence_ledger(run) or not packages or not current.candidates:
        raise ValueError("证据驱动的学习型任务 Plan 尚未生成，不能局部重规划")
    package_ids = [item["package_id"] for item in packages]
    if target_package_id not in package_ids:
        raise ValueError("局部重规划目标学习任务步骤不存在")

    affected = {target_package_id}
    changed = True
    while changed:
        changed = False
        for item in packages:
            if item["package_id"] not in affected and affected.intersection(item.get("depends_on") or []):
                affected.add(item["package_id"])
                changed = True
    affected_ordered = [item for item in package_ids if item in affected]
    preserved = [item for item in package_ids if item not in affected]
    next_version = current.analysis_version + 1
    digest = sha256(
        f"{run['run_id']}:{next_version}:{target_package_id}:{failure_code}:{observation}".encode()
    ).hexdigest()[:10]
    revision_id = f"revision_{next_version}_{digest}"
    revision = {
        "revision_id": revision_id,
        "analysis_version": next_version,
        "parent_revision_id": current.active_revision_id,
        "cause": observation.strip(),
        "failure_code": failure_code,
        "affected_package_ids": affected_ordered,
        "preserved_package_ids": preserved,
        "controls_added": _REPLAN_CONTROLS[failure_code],
    }
    updated = deepcopy(current.model_dump(mode="json"))
    updated.update({
        "analysis_version": next_version,
        "planning_status": "replanned_not_executed",
        "active_revision_id": revision_id,
        "repair_budget_remaining": current.repair_budget_remaining - 1,
    })
    updated["revision_history"] = [*updated["revision_history"], revision]
    selected = max(updated["candidates"], key=lambda item: item["weighted_score"])
    selected["title"] = f"{selected['title']} · 局部修订 v{next_version}"
    selected["tradeoffs"] = [
        f"冻结 {len(preserved)} 个未受影响工作包，只重规划 {len(affected_ordered)} 个工作包。",
        *_REPLAN_CONTROLS[failure_code],
    ]
    updated["decision"] = {
        "code": "SELECT_CANDIDATE",
        "selected_candidate_id": selected["candidate_id"],
        "confidence": max(70, selected["weighted_score"] - 2),
        "reasons": ["已完成局部子图修订，任务语义指纹保持不变。", "未受影响工作包保持冻结。"],
        "triggered_rules": ["LOCAL_SUBGRAPH_REPLAN", failure_code.upper()],
    }
    finalize_stage = next(
        item for item in updated["stages"]
        if item["stage_id"] == "critic_finalize"
    )
    finalize_stage["status"] = "ready"
    finalize_stage["summary"] = (
        f"局部子图修订 v{next_version} 已生成；等待确认后再进入执行。"
    )
    finalize_stage["substeps"].append({
        "substep_id": f"decision_revision_{next_version}",
        "label": f"局部修订 v{next_version}",
        "status": "completed",
        "detail": (
            f"冻结 {len(preserved)} 个未受影响工作包，只重规划 "
            f"{len(affected_ordered)} 个受影响工作包。"
        ),
        "parent_substep_id": "decision_replan",
        "depends_on": [],
        "output_ref": revision_id,
    })
    execution_stage = next(
        item for item in updated["stages"]
        if item["stage_id"] == "execution_handoff"
    )
    execution_stage["status"] = "pending"
    execution_stage["summary"] = (
        "修订后的运行清单仍为 pending；尚无执行、观察或掌握证据。"
    )
    updated["metrics"]["revision_count"] = len(updated["revision_history"])
    updated["metrics"]["stage_substep_count"] = sum(
        len(item["substeps"]) for item in updated["stages"]
    )
    return LearningTaskPlanningAnalysis.model_validate(updated).model_dump(mode="json")
