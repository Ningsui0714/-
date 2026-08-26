"""Executable architecture authority for LearnFlow.

This registry is deliberately boring: it does not route requests or let an
LLM select policy. It defines ownership and contracts so agents, tools,
workbenches and evidence events can be inspected and checked for drift.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Any

from app.services.action_board import ACTION_BOARD


REGISTRY_VERSION = "2026-08-25.1"
EVENT_SCHEMA_VERSION = "learnflow.evidence.v1"
KERNEL_NAMES = ("structure", "knowledge", "human", "value", "practice")

# This is the canonical allow-list used by Tutor semantic observations. The
# runtime imports it instead of maintaining a second copy.
SEMANTIC_MEMORY_KEYS = {
    "structure": {
        "path_position", "path_dependencies", "resume_anchor",
        "focus_transition", "deferred_threads", "navigation_blocker",
    },
    "knowledge": {
        "concept_understanding", "knowledge_gap", "pending_question",
        "misconceptions", "active_concepts", "recent_errors", "retention_status",
    },
    "human": {
        "affect", "cognitive_load", "attention", "frustration",
        "pace_preference", "format_preference", "support_need",
    },
    "value": {
        "current_priority", "current_motivation", "goal_candidate",
        "interest_signal", "relevance_reason",
    },
    "practice": {
        "current_attempt", "assistance_level", "artifact_state",
        "recent_feedback", "transfer_readiness", "review_history",
    },
}


@dataclass(frozen=True)
class AgentContract:
    id: str
    name: str
    plane: str
    components: tuple[str, ...]
    input_contract: tuple[str, ...]
    output_contract: tuple[str, ...]
    kernel_access: str
    must_not: tuple[str, ...]


@dataclass(frozen=True)
class KernelContract:
    id: str
    question: str
    short_term_keys: tuple[str, ...]
    long_term_rule: str
    writer: str = "five_kernel_reducer"


@dataclass(frozen=True)
class ToolContract:
    id: str
    name: str
    owner: str
    origin: str
    mode: str
    reads_kernels: tuple[str, ...] = ()
    writes_kernels: tuple[str, ...] = ()
    write_path: str = "none"


@dataclass(frozen=True)
class SkillContract:
    id: str
    name: str
    owner_agent: str
    tools: tuple[str, ...]
    output_contract: str
    strategy_authority: str
    origin: str = "learnflow"


@dataclass(frozen=True)
class WorkbenchContract:
    id: str
    name: str
    surface: str
    owner_agent: str
    capabilities: tuple[str, ...]
    origin: str = "learnflow"


@dataclass(frozen=True)
class EventContract:
    id: str
    owner_agent: str
    capability: str
    tool: str
    workbench: str
    kernel_targets: tuple[str, ...]
    evidence_role: str
    origin: str = "learnflow"


# Three primary contracts are responsibility families, not three competing
# chat personas. Concrete domain workers stay behind the corresponding
# structured interface.
AGENTS = {
    item.id: item for item in (
        AgentContract(
            "tutor_agent", "Tutor 控制 Agent", "control",
            ("global_main_agent", "project_tutor", "checkpoint_tutor"),
            ("current_learner", "page_context", "five_kernel_projection", "recent_evidence"),
            ("structured_intent", "reply", "action_proposal", "handoff_refs"),
            "read projections; emit events through Action Board",
            ("direct database writes", "claim mastery", "bypass confirmation policy"),
        ),
        AgentContract(
            "learning_design_agent", "学习设计 Agent", "capability",
            ("roadmap_agent", "lecture_agent", "concept_agent", "animation_agent"),
            ("project_brief", "processed_sources", "learner_projection", "provenance"),
            ("roadmap_proposal", "lecture_artifact", "assessment_spec", "visual_artifact"),
            "read scoped projections; artifacts never mutate mastery",
            ("apply roadmap without confirmation", "invent source provenance", "write kernels"),
        ),
        AgentContract(
            "practice_agent", "实践与验证 Agent", "capability",
            ("exercise_agent", "code_agent", "remediation_renderer"),
            ("assessment_spec", "submission", "test_result", "error_evidence"),
            ("practice_artifact", "feedback", "explanation_sections"),
            "read scoped projections; assessed events enter the reducer",
            ("choose remediation policy", "override deterministic grading", "write kernels"),
        ),
    )
}


KERNELS = {
    item.id: item for item in (
        KernelContract("structure", "学习者走到哪里，怎样离开与返回",
                       tuple(sorted(SEMANTIC_MEMORY_KEYS["structure"])),
                       "Only stable path patterns and confirmed project structure may consolidate."),
        KernelContract("knowledge", "对哪个知识点理解到什么程度",
                       tuple(sorted(SEMANTIC_MEMORY_KEYS["knowledge"])),
                       "Mastery and misconception require graded or explicitly correctable evidence."),
        KernelContract("human", "当前怎样教更合适",
                       tuple(sorted(SEMANTIC_MEMORY_KEYS["human"])),
                       "Preferences consolidate after explicit confirmation or cross-session evidence."),
        KernelContract("value", "为什么学，什么更值得投入",
                       tuple(sorted(SEMANTIC_MEMORY_KEYS["value"])),
                       "Long-term goals require explicit learner confirmation."),
        KernelContract("practice", "能否独立做出来",
                       tuple(sorted(SEMANTIC_MEMORY_KEYS["practice"])),
                       "Independent and transfer attempts outrank assisted completion."),
    )
}


TOOLS = {
    item.id: item for item in (
        ToolContract("action_board", "Action Board", "tutor_agent", "learnflow", "transaction",
                     KERNEL_NAMES, (), "EvidenceEvent"),
        ToolContract("tutor_context", "Tutor Context Assembler", "tutor_agent", "learnflow", "read",
                     KERNEL_NAMES),
        ToolContract("checkpoint_context", "Checkpoint Tutor Context Assembler", "tutor_agent", "learnflow", "read",
                     KERNEL_NAMES),
        ToolContract("source_ingestion", "Source Ingestion + Chunking", "learning_design_agent", "learnflow", "artifact"),
        ToolContract("repository_knowledge_domains", "Repository Knowledge Domain Context Builder", "learning_design_agent", "learnflow", "read"),
        ToolContract("hierarchical_rag", "Hierarchical RAG", "learning_design_agent", "learnflow", "read",
                     ("knowledge", "structure")),
        ToolContract("content_generation", "Roadmap/Lecture/Assessment Generation", "learning_design_agent", "learnflow", "artifact",
                     KERNEL_NAMES),
        ToolContract("process_animation", "Process Animation", "learning_design_agent", "learnflow", "artifact",
                     ("knowledge", "human")),
        ToolContract("code_executor", "Sandboxed Code Executor", "practice_agent", "learnflow", "assessment"),
        ToolContract("deterministic_assessment", "Deterministic Assessment", "practice_agent", "learnflow", "assessment"),
        ToolContract("deterministic_remediation", "RemediationStrategy", "practice_agent", "fused", "policy",
                     ("knowledge", "human", "practice"), (), "EvidenceEvent"),
        ToolContract("review_scheduler", "Deterministic Spaced Review Scheduler", "practice_agent", "learnflow", "projection",
                     ("knowledge", "practice"), (), "LearningAttempt/Event -> ReviewSchedule"),
        ToolContract("evidence_ledger", "Evidence Ledger Gateway", "tutor_agent", "learnflow", "event_gateway",
                     (), (), "append-only EvidenceEvent"),
        ToolContract("five_kernel_reducer", "Five-kernel Deterministic Reducer", "tutor_agent", "learnflow", "projection",
                     (), KERNEL_NAMES, "EvidenceEvent -> KernelMutation"),
        ToolContract("memory_graph", "Inspectable Memory Graph", "tutor_agent", "learnflow", "projection",
                     KERNEL_NAMES, (), "KernelMutation -> Fact -> Module -> Claim"),
        ToolContract("workflow_gateway", "Mock / Xingchen Workflow Gateway", "learning_design_agent", "companion", "optional_adapter",
                     KERNEL_NAMES, (), "validated artifact or EvidenceEvent only"),
        ToolContract("workflow_validator", "Workflow Builder + Validator", "learning_design_agent", "companion", "maintenance"),
        ToolContract(
            "learning_task_conversion_gateway",
            "岗位典型工作任务转化 Gateway",
            "learning_design_agent",
            "companion",
            "validated_artifact",
            (), (),
            "validated HTML/PDF/JSON artifact or zero-kernel operational event only",
        ),
        ToolContract("seeded_demo", "Seeded Competition Demo", "tutor_agent", "fused", "demo"),
        ToolContract("task_runtime", "Idempotent Background Task Runtime", "tutor_agent", "learnflow", "execution"),
        ToolContract("workspace_file_service", "Desktop Workspace File Service", "tutor_agent", "learnflow", "filesystem",
                     (), (), "confirmed WorkspaceOperation only"),
        ToolContract("managed_artifact_service", "Managed Learning Artifact Service", "tutor_agent", "learnflow", "artifact",
                     (), (), "versioned lecture/draft/annotation domain APIs"),
        ToolContract("local_agent_broker", "Local Agent Broker", "tutor_agent", "learnflow", "isolated_execution",
                     (), (), "two-confirmation WorkspaceOperation batch only"),
    )
}


SKILLS = {
    item.id: item for item in (
        SkillContract("intent_and_handoff", "意图理解与跨空间交接", "tutor_agent",
                      ("tutor_context", "action_board", "evidence_ledger"),
                      "structured intent + auditable action/handoff", "Action Board"),
        SkillContract("checkpoint_tutoring", "关卡内统一教学协作", "tutor_agent",
                      ("checkpoint_context", "hierarchical_rag", "workspace_file_service"),
                      "checkpoint-scoped Tutor reply + internal design/practice handoff",
                      "immutable checkpoint session scope"),
        SkillContract("learning_path_planning", "来源约束的学习路线规划", "learning_design_agent",
                      ("source_ingestion", "repository_knowledge_domains", "hierarchical_rag", "content_generation"),
                      "roadmap proposal with checkpoint dependencies and provenance", "confirmed proposal"),
        SkillContract("evidence_grounded_teaching", "有来源的讲义与概念教学", "learning_design_agent",
                      ("hierarchical_rag", "content_generation", "process_animation"),
                      "structured teaching artifact; never mastery evidence", "artifact contract"),
        SkillContract("practice_verification", "代码实践与确定性验证", "practice_agent",
                      ("code_executor", "deterministic_assessment", "evidence_ledger"),
                      "graded LearningAttempt + evidence", "test/grading rules"),
        SkillContract("remediation_loop", "答错—纠错—重做—变式—回写", "practice_agent",
                      ("deterministic_remediation", "deterministic_assessment", "evidence_ledger"),
                      "RemediationCase + ordered evidence chain", "RemediationStrategy", "fused"),
        SkillContract("spaced_review", "检索练习与可解释间隔复习", "practice_agent",
                      ("review_scheduler", "deterministic_assessment", "deterministic_remediation", "evidence_ledger"),
                      "QuestionLearningState + ReviewSchedule + graded review evidence",
                      "review-policy-v1"),
        SkillContract("learner_memory_synthesis", "五核画像与可检查记忆", "tutor_agent",
                      ("five_kernel_reducer", "memory_graph"),
                      "kernel projection + evidence-backed claims", "deterministic reducer", "fused"),
        SkillContract("external_workflow_rendering", "星辰/Mock 教学内容适配", "learning_design_agent",
                      ("workflow_gateway", "workflow_validator"),
                      "validated content artifact; no direct kernel mutation", "LearnFlow contract", "companion"),
        SkillContract(
            "learning_work_task_conversion",
            "岗位典型工作任务转化与复核",
            "learning_design_agent",
            ("learning_task_conversion_gateway", "evidence_ledger"),
            "versioned TaskPlan + task page + PDF + knowledge-scoped personalized-learning JSON + relation feedback",
            "task identity, evidence and relation gates",
            "companion",
        ),
        SkillContract("workspace_file_management", "受控本地项目文件管理", "tutor_agent",
                      ("workspace_file_service", "evidence_ledger"),
                      "hash-bound diff proposal + explicit confirmation + operational event",
                      "WorkspaceOperation state machine"),
        SkillContract("managed_learning_file_playback", "讲义与练习专用播放器", "tutor_agent",
                      ("managed_artifact_service", "deterministic_assessment", "evidence_ledger"),
                      "versioned lecture, personal draft, annotation and formal assessment",
                      "database learning-object authority"),
        SkillContract("local_agent_delegation", "本地代码 Agent 双确认委派", "tutor_agent",
                      ("local_agent_broker", "workspace_file_service", "evidence_ledger"),
                      "isolated run events + tests + risk + hash-bound diff",
                      "deterministic profile selector and two confirmations"),
    )
}


WORKBENCHES = {
    item.id: item for item in (
        WorkbenchContract("global_tutor", "Global Tutor", "/agent", "tutor_agent",
                          ("search_projects", "draft_learning_project", "create_project", "plan_learning_work_task", "generate_learning_work_task")),
        WorkbenchContract("project_tutor", "Project Tutor", "/projects/:projectId", "tutor_agent",
                          ("add_source", "plan_learning_path", "apply_learning_path", "navigate_checkpoint")),
        WorkbenchContract("lecture", "Checkpoint Tutor · Lecture", "/projects/:projectId/checkpoints/:checkpointId", "tutor_agent",
                          ("generate_lecture", "explain_selection", "generate_assessment")),
        WorkbenchContract("assessment", "Checkpoint Tutor · Assessment", "/projects/:projectId/checkpoints/:checkpointId/exercises", "tutor_agent",
                          ("evaluate_attempt", "retry_attempt", "evaluate_transfer_variant")),
        WorkbenchContract("remediation", "Remediation Panel", "RemediationPanel", "practice_agent",
                          ("request_remediation_explanation", "retry_attempt", "evaluate_transfer_variant"), "fused"),
        WorkbenchContract("review", "Global Review Workbench", "/review", "tutor_agent",
                          ("plan_review_queue", "evaluate_review_attempt", "manage_review_item")),
        WorkbenchContract("profile", "Learner Profile", "/profile", "tutor_agent", ()),
        WorkbenchContract("memory", "Inspectable Memory", "/memory", "tutor_agent", ()),
        WorkbenchContract("competition_demo", "Seeded Demo Entry", "/demo", "tutor_agent",
                          ("plan_review_queue", "evaluate_review_attempt", "manage_review_item",
                           "evaluate_attempt", "request_remediation_explanation", "retry_attempt",
                           "evaluate_transfer_variant"), "fused"),
        WorkbenchContract("desktop_workspace", "Desktop File Workspace", "tauri://workspace", "tutor_agent",
                          ("link_project_workspace", "inspect_workspace_files", "propose_workspace_change", "apply_workspace_change", "open_managed_learning_artifact", "edit_managed_lecture", "annotate_learning_artifact", "delegate_local_agent_task", "inspect_local_agent_run", "cancel_local_agent_run", "apply_local_agent_result")),
        WorkbenchContract("xingchen_studio", "Xingchen Workflow Studio", "external", "learning_design_agent",
                          ("generate_lecture", "request_remediation_explanation"), "companion"),
        WorkbenchContract(
            "learning_work_task_plan",
            "学习型工作任务 Plan",
            "/learning-task-plans/:runId",
            "learning_design_agent",
            ("plan_learning_work_task",),
            "companion",
        ),
        WorkbenchContract(
            "learning_work_task_review",
            "学习型工作任务网页与关系复核",
            "/wf03/tasks/:taskCardId",
            "learning_design_agent",
            (
                "generate_learning_work_task", "review_learning_work_task",
                "open_personalized_learning",
            ),
            "companion",
        ),
        WorkbenchContract(
            "personalized_learning_entry",
            "知识点个性化学习交接入口",
            "/personalized-learning/tasks/:taskCardId/knowledge/:knowledgeId",
            "learning_design_agent",
            ("open_personalized_learning",),
            "companion",
        ),
    )
}


CAPABILITY_OWNERS = {
    "search_projects": ("tutor_agent", "action_board", "global_tutor"),
    "draft_learning_project": ("tutor_agent", "action_board", "global_tutor"),
    "revise_learning_project_proposal": ("tutor_agent", "action_board", "global_tutor"),
    "search_learning_resources": ("tutor_agent", "action_board", "project_tutor"),
    "create_project": ("tutor_agent", "action_board", "global_tutor"),
    "bootstrap_project": ("tutor_agent", "action_board", "global_tutor"),
    "enter_project": ("tutor_agent", "action_board", "project_tutor"),
    "add_source": ("tutor_agent", "source_ingestion", "project_tutor"),
    "plan_learning_path": ("learning_design_agent", "content_generation", "project_tutor"),
    "apply_learning_path": ("tutor_agent", "action_board", "project_tutor"),
    "navigate_checkpoint": ("tutor_agent", "action_board", "project_tutor"),
    "generate_lecture": ("learning_design_agent", "content_generation", "lecture"),
    "generate_assessment": ("learning_design_agent", "content_generation", "assessment"),
    "plan_learning_work_task": (
        "learning_design_agent", "learning_task_conversion_gateway", "learning_work_task_plan",
    ),
    "generate_learning_work_task": (
        "learning_design_agent", "learning_task_conversion_gateway", "global_tutor",
    ),
    "review_learning_work_task": (
        "learning_design_agent", "learning_task_conversion_gateway", "learning_work_task_review",
    ),
    "open_personalized_learning": (
        "learning_design_agent", "learning_task_conversion_gateway", "personalized_learning_entry",
    ),
    "evaluate_attempt": ("practice_agent", "deterministic_assessment", "assessment"),
    "explain_selection": ("learning_design_agent", "content_generation", "lecture"),
    "advance_checkpoint": ("tutor_agent", "action_board", "assessment"),
    "request_remediation_explanation": ("practice_agent", "deterministic_remediation", "remediation"),
    "retry_attempt": ("practice_agent", "deterministic_assessment", "remediation"),
    "evaluate_transfer_variant": ("practice_agent", "deterministic_assessment", "remediation"),
    "plan_review_queue": ("tutor_agent", "review_scheduler", "review"),
    "evaluate_review_attempt": ("practice_agent", "deterministic_assessment", "review"),
    "manage_review_item": ("practice_agent", "review_scheduler", "review"),
    "record_task_outcome": ("tutor_agent", "task_runtime", "project_tutor"),
    "link_project_workspace": ("tutor_agent", "workspace_file_service", "desktop_workspace"),
    "inspect_workspace_files": ("tutor_agent", "workspace_file_service", "desktop_workspace"),
    "propose_workspace_change": ("tutor_agent", "workspace_file_service", "desktop_workspace"),
    "apply_workspace_change": ("tutor_agent", "workspace_file_service", "desktop_workspace"),
    "open_managed_learning_artifact": ("tutor_agent", "managed_artifact_service", "desktop_workspace"),
    "edit_managed_lecture": ("learning_design_agent", "managed_artifact_service", "desktop_workspace"),
    "annotate_learning_artifact": ("tutor_agent", "managed_artifact_service", "desktop_workspace"),
    "delegate_local_agent_task": ("tutor_agent", "local_agent_broker", "desktop_workspace"),
    "inspect_local_agent_run": ("tutor_agent", "local_agent_broker", "desktop_workspace"),
    "cancel_local_agent_run": ("tutor_agent", "local_agent_broker", "desktop_workspace"),
    "apply_local_agent_result": ("tutor_agent", "local_agent_broker", "desktop_workspace"),
}


def _event(event_id: str, capability: str, targets: tuple[str, ...], role: str,
           *, tool: str | None = None, workbench: str | None = None,
           origin: str = "learnflow") -> EventContract:
    owner, default_tool, default_workbench = CAPABILITY_OWNERS[capability]
    return EventContract(event_id, owner, capability, tool or default_tool,
                         workbench or default_workbench, targets, role, origin)


EVENTS = {
    item.id: item for item in (
        _event("registration_profile_completed", "draft_learning_project", ("human", "value"), "self_report"),
        _event("profile_updated", "draft_learning_project", ("human", "value"), "self_report", workbench="profile"),
        _event("career_goal_confirmed", "draft_learning_project", ("value",), "confirmed_goal", workbench="profile"),
        _event("user_message", "draft_learning_project", KERNEL_NAMES, "interaction"),
        _event("project_proposal_created", "draft_learning_project", ("structure", "value", "practice"), "proposal"),
        _event("project_proposal_revised", "revise_learning_project_proposal", KERNEL_NAMES, "proposal"),
        _event("project_proposal_user_edited", "revise_learning_project_proposal", KERNEL_NAMES, "explicit_edit"),
        _event("project_proposal_accepted", "create_project", ("structure", "value"), "confirmed_action"),
        _event("project_created", "create_project", ("structure", "value"), "action_result"),
        _event("project_selected", "enter_project", ("structure",), "navigation"),
        _event("source_added", "add_source", ("structure", "practice"), "artifact"),
        _event("source_processed", "add_source", ("structure", "practice"), "artifact"),
        _event("roadmap_discussed", "plan_learning_path", ("structure",), "proposal"),
        _event("roadmap_applied", "apply_learning_path", ("structure",), "confirmed_action"),
        _event("checkpoint_entered", "navigate_checkpoint", ("structure",), "navigation"),
        _event("lecture_generated", "generate_lecture", ("knowledge",), "exposure"),
        _event("lecture_viewed", "generate_lecture", ("knowledge",), "exposure"),
        _event("assessment_generated", "generate_assessment", (), "artifact"),
        _event("learning_work_task_plan_created", "plan_learning_work_task", (), "artifact", origin="companion"),
        _event("learning_work_task_plan_confirmed", "plan_learning_work_task", (), "confirmed_action", origin="companion"),
        _event("learning_work_task_plan_replanned", "plan_learning_work_task", (), "operational", origin="companion"),
        _event("learning_work_task_generated", "generate_learning_work_task", (), "artifact", origin="companion"),
        _event("learning_work_task_generation_follow_up", "generate_learning_work_task", (), "operational", origin="companion"),
        _event("learning_work_task_review_submitted", "review_learning_work_task", (), "operational", origin="companion"),
        _event("personalized_learning_handoff_opened", "open_personalized_learning", (), "navigation", origin="companion"),
        _event("personalized_learning_result_received", "open_personalized_learning", (), "operational", origin="companion"),
        _event("explanation_requested", "explain_selection", ("knowledge", "human"), "assistance"),
        _event("code_review_requested", "explain_selection", ("practice", "human"), "assistance", workbench="assessment"),
        _event("concept_attempt_evaluated", "evaluate_attempt", ("knowledge", "practice"), "graded_attempt"),
        _event("exercise_attempt_evaluated", "evaluate_attempt", ("knowledge", "practice"), "graded_attempt"),
        _event("remediation_started", "request_remediation_explanation", ("knowledge", "human", "practice"), "diagnosis", origin="fused"),
        _event("remediation_mode_rejected", "request_remediation_explanation", ("human", "knowledge"), "preference_evidence", origin="fused"),
        _event("remediation_explanation_requested", "request_remediation_explanation", ("human", "knowledge"), "assistance", origin="fused"),
        _event("remediation_retry_evaluated", "retry_attempt", ("knowledge", "practice"), "graded_retry", origin="fused"),
        _event("remediation_variant_evaluated", "evaluate_transfer_variant", ("knowledge", "practice"), "transfer_evidence", origin="fused"),
        _event("remediation_completed", "evaluate_transfer_variant", ("knowledge", "human", "practice"), "evidence_writeback", origin="fused"),
        _event("review_attempt_evaluated", "evaluate_review_attempt", ("knowledge", "practice"), "spaced_retrieval"),
        _event("review_item_skipped", "manage_review_item", (), "operational"),
        _event("review_item_deferred", "manage_review_item", (), "operational"),
        _event("review_item_suspended", "manage_review_item", (), "operational"),
        _event("review_item_resumed", "manage_review_item", (), "operational"),
        _event("project_completed", "advance_checkpoint", ("structure", "value", "practice"), "milestone"),
        _event("workspace_linked", "link_project_workspace", (), "operational"),
        _event("workspace_change_applied", "apply_workspace_change", (), "operational"),
        _event("local_agent_started", "delegate_local_agent_task", (), "operational"),
        _event("local_agent_completed", "inspect_local_agent_run", (), "operational"),
        _event("local_agent_canceled", "cancel_local_agent_run", (), "operational"),
        _event("local_agent_result_applied", "apply_local_agent_result", (), "operational"),
        _event("task_completed", "record_task_outcome", (), "operational"),
        _event("task_failed", "record_task_outcome", ("structure",), "operational_failure"),
        _event("tool_failed", "record_task_outcome", ("structure",), "operational_failure"),
    )
}


def capability_manifest() -> list[dict[str, Any]]:
    result = []
    for capability, spec in sorted(ACTION_BOARD.items()):
        owner, tool, workbench = CAPABILITY_OWNERS.get(capability, ("unassigned", "unassigned", "unassigned"))
        row = asdict(spec)
        row.update({"owner_agent": owner, "tool": tool, "workbench": workbench})
        result.append(row)
    return result


def validate_registry() -> list[str]:
    errors: list[str] = []
    if len(AGENTS) != 3:
        errors.append("exactly three primary agent contracts are required")
    if tuple(KERNELS) != KERNEL_NAMES:
        errors.append("kernel registry must preserve the canonical five-kernel order")
    for capability in ACTION_BOARD:
        if capability not in CAPABILITY_OWNERS:
            errors.append(f"capability has no owner binding: {capability}")
    for capability, (agent, tool, workbench) in CAPABILITY_OWNERS.items():
        if capability not in ACTION_BOARD:
            errors.append(f"owner binding references unknown capability: {capability}")
        if agent not in AGENTS or tool not in TOOLS or workbench not in WORKBENCHES:
            errors.append(f"invalid capability binding: {capability}")
    direct_writers = {tool.id for tool in TOOLS.values() if tool.writes_kernels}
    if direct_writers != {"five_kernel_reducer"}:
        errors.append("five_kernel_reducer must be the only direct KernelState writer")
    for event in EVENTS.values():
        if event.owner_agent not in AGENTS or event.capability not in ACTION_BOARD:
            errors.append(f"invalid event owner/capability: {event.id}")
        if event.tool not in TOOLS or event.workbench not in WORKBENCHES:
            errors.append(f"invalid event tool/workbench: {event.id}")
        if set(event.kernel_targets) - set(KERNEL_NAMES):
            errors.append(f"invalid event kernel target: {event.id}")
    for skill in SKILLS.values():
        if skill.owner_agent not in AGENTS or set(skill.tools) - set(TOOLS):
            errors.append(f"invalid skill contract: {skill.id}")
    return errors


def normalize_event_provenance(
    event_type: str,
    source: str,
    provenance: dict[str, Any] | None,
) -> dict[str, Any]:
    result = dict(provenance or {})
    contract = EVENTS.get(event_type)
    result.update({
        "event_schema": EVENT_SCHEMA_VERSION,
        "architecture_registry": REGISTRY_VERSION,
        "contract_id": contract.id if contract else f"unclassified:{event_type}",
        "source_system": source,
    })
    if contract:
        result.update({
            "owner_agent": contract.owner_agent,
            "capability": contract.capability,
            "tool": contract.tool,
            "workbench": contract.workbench,
            "kernel_targets": list(contract.kernel_targets),
            "evidence_role": contract.evidence_role,
        })
    return result


def registry_manifest() -> dict[str, Any]:
    payload = {
        "version": REGISTRY_VERSION,
        "event_schema": EVENT_SCHEMA_VERSION,
        "authority": {
            "kernel_source_of_truth": "EvidenceEvent ledger",
            "kernel_write_path": "EvidenceEvent -> five_kernel_reducer -> KernelMutation",
            "memory_projection": "KernelMutation -> MemoryFact -> MemoryModule -> MemoryClaim",
            "external_workflow_role": "optional content adapter; never strategy or kernel authority",
        },
        "agents": [asdict(item) for item in AGENTS.values()],
        "kernels": [asdict(item) for item in KERNELS.values()],
        "capabilities": capability_manifest(),
        "tools": [asdict(item) for item in TOOLS.values()],
        "skills": [asdict(item) for item in SKILLS.values()],
        "workbenches": [asdict(item) for item in WORKBENCHES.values()],
        "important_events": [asdict(item) for item in EVENTS.values()],
        "validation_errors": validate_registry(),
    }
    digest_input = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    payload["digest"] = hashlib.sha256(digest_input.encode("utf-8")).hexdigest()
    return payload
