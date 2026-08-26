"""可执行注册表：能力 / 工具 / 产品技能 / 工作台 / 重要事件。

权威说明见 docs/AGENT_ARCHITECTURE_GUIDE.md 第 3 节。
新增事件必须补齐全部元数据，并为事件 -> KernelMutation 提供测试。
"""

from __future__ import annotations

from typing import Any

# 唯一合法 Kernel 集合
KERNELS: tuple[str, ...] = ("structure", "knowledge", "human", "value", "practice")

# 证据角色
EVIDENCE_ROLES: tuple[str, ...] = (
    "graded_attempt",
    "self_reported",
    "skipped",
    "ungraded_hazy",
    "assisted_success",
    "interaction_log",
)

# 项目级目标 -> 诊断取样键（与 backend/data/diagnosis_bank.py 对齐）
GOAL_TO_DIAGNOSIS_KEY: dict[str, str] = {
    "GOAL-JAVA-001": "daily",
    "GOAL-JAVA-COMPETITION": "competition",
    "GOAL-JAVA-CERT": "certification",
    "GOAL-JAVA-DAILY": "daily",
}

# ---------------------------------------------------------------------------
# 能力 / 工具 / 产品技能 / 工作台
# ---------------------------------------------------------------------------

CAPABILITIES: list[dict[str, Any]] = [
    {
        "capability_id": "learner_state_discovery",
        "name": "学习信息快速获取",
        "description": "用尽可能少、尽可能自然的有效交互，降低系统对学习者状态的不确定性，产出可验证、可纠正的学习证据。",
        "owning_agent": "Practice Agent",
        "api_ref": "POST /api/discovery/sessions",
    },
    {
        "capability_id": "kernel_projection_read",
        "name": "五核投影读取",
        "description": "按 learner/project/checkpoint/session scope 读取五核投影与近期证据。",
        "owning_agent": "Tutor Agent",
        "api_ref": "GET /api/discovery/sessions/{id}/projection",
    },
    {
        "capability_id": "evidence_ledger",
        "name": "证据账本",
        "description": "append-only 证据事件流，支持幂等写入、回放与导出。",
        "owning_agent": "Practice Agent",
        "api_ref": "GET /api/learners/{learner_id}/discovery/events",
    },
]

TOOLS: list[dict[str, Any]] = [
    {
        "tool_id": "discovery_session",
        "name": "发现会话",
        "capability_id": "learner_state_discovery",
        "input_schema_ref": "POST /api/discovery/sessions",
        "offline_supported": True,
    },
    {
        "tool_id": "question_bank_validator",
        "name": "题目校验器",
        "capability_id": "learner_state_discovery",
        "input_schema_ref": "backend/learner_discovery/validator.py",
        "offline_supported": True,
    },
    {
        "tool_id": "kernel_projection",
        "name": "五核投影",
        "capability_id": "kernel_projection_read",
        "input_schema_ref": "GET /api/discovery/sessions/{id}/projection",
        "offline_supported": True,
    },
]

PRODUCT_SKILLS: list[dict[str, Any]] = [
    {
        "skill_id": "discovery_workbench",
        "name": "学习状态发现工作台",
        "capability_id": "learner_state_discovery",
        "ui_ref": "frontend/discovery.html",
    },
    {
        "skill_id": "kernel_projection_panel",
        "name": "五核投影面板",
        "capability_id": "kernel_projection_read",
        "ui_ref": "frontend/discovery.html#projection",
    },
]

WORKBENCHES: list[dict[str, Any]] = [
    {
        "workbench_id": "discovery",
        "name": "学习状态发现工作台",
        "capability_ids": ["learner_state_discovery", "kernel_projection_read", "evidence_ledger"],
        "entry_url": "/discovery.html",
        "student_owned": True,
    },
]

# ---------------------------------------------------------------------------
# 重要事件注册表
# 每个事件声明：稳定 ID、能力/工具/Agent/工作台、scope、证据角色与置信度、
# 目标 Kernel、幂等键、provenance、是否可参与长期巩固、Reducer 规则。
# ---------------------------------------------------------------------------

EVENT_REGISTRY: dict[str, dict[str, Any]] = {
    "goal_candidate_stated": {
        "event_id": "goal_candidate_stated",
        "description": "学习者自述想学什么、期望什么结果（自述，不证明能力）。",
        "capability": "learner_state_discovery",
        "tool": "discovery_session",
        "agent": "Tutor Agent",
        "workbench": "discovery",
        "scope": {"learner_id": True, "project_id": True, "session_id": True},
        "evidence_role": "self_reported",
        "confidence": 0.5,
        "kernel_targets": ["value"],
        "idempotency_key": "client_event_id",
        "provenance": {"policy_version": "v1"},
        "long_term_eligible": False,
        "reducer_rule": "value.goal_candidates 追加/更新候选（confirmed=false，记录事件引用）",
    },
    "goal_clarified": {
        "event_id": "goal_clarified",
        "description": "学习者澄清目标或期望产物，细化候选目标。",
        "capability": "learner_state_discovery",
        "tool": "discovery_session",
        "agent": "Tutor Agent",
        "workbench": "discovery",
        "scope": {"learner_id": True, "project_id": True, "session_id": True},
        "evidence_role": "self_reported",
        "confidence": 0.6,
        "kernel_targets": ["value"],
        "idempotency_key": "client_event_id",
        "provenance": {"policy_version": "v1"},
        "long_term_eligible": False,
        "reducer_rule": "更新 value 候选目标的 desired_outcome / 文本",
    },
    "goal_confirmed": {
        "event_id": "goal_confirmed",
        "description": "学习者确认目标与期望产物，进入可执行 scope。",
        "capability": "learner_state_discovery",
        "tool": "discovery_session",
        "agent": "Tutor Agent",
        "workbench": "discovery",
        "scope": {"learner_id": True, "project_id": True, "session_id": True},
        "evidence_role": "self_reported",
        "confidence": 0.8,
        "kernel_targets": ["value", "structure"],
        "idempotency_key": "client_event_id",
        "provenance": {"policy_version": "v1"},
        "long_term_eligible": True,
        "reducer_rule": "value.confirmed_goal 置为确认目标；structure 锚定 project/checkpoint",
    },
    "discovery_session_started": {
        "event_id": "discovery_session_started",
        "description": "发现会话开始（structure 位置锚点）。",
        "capability": "learner_state_discovery",
        "tool": "discovery_session",
        "agent": "Practice Agent",
        "workbench": "discovery",
        "scope": {"learner_id": True, "project_id": True, "session_id": True},
        "evidence_role": "interaction_log",
        "confidence": 1.0,
        "kernel_targets": ["structure"],
        "idempotency_key": "client_event_id",
        "provenance": {"policy_version": "v1"},
        "long_term_eligible": False,
        "reducer_rule": "structure.position 置 started，记录恢复锚点",
    },
    "question_presented": {
        "event_id": "question_presented",
        "description": "向学习者展示了一道冻结题目（不产生能力证据）。",
        "capability": "learner_state_discovery",
        "tool": "discovery_session",
        "agent": "Practice Agent",
        "workbench": "discovery",
        "scope": {"learner_id": True, "project_id": True, "session_id": True},
        "evidence_role": "interaction_log",
        "confidence": 1.0,
        "kernel_targets": ["structure"],
        "idempotency_key": "client_event_id",
        "provenance": {"policy_version": "v1"},
        "long_term_eligible": False,
        "reducer_rule": "structure.seen_question_ids 追加去重，position.question_index 更新",
    },
    "answer_submitted": {
        "event_id": "answer_submitted",
        "description": "客观题确定性判题结果（独立/辅助）。",
        "capability": "learner_state_discovery",
        "tool": "discovery_session",
        "agent": "Practice Agent",
        "workbench": "discovery",
        "scope": {"learner_id": True, "project_id": True, "session_id": True},
        "evidence_role": "graded_attempt",
        "confidence": 1.0,
        "kernel_targets": ["knowledge", "practice"],
        "idempotency_key": "client_event_id",
        "provenance": {"grading_version": "v1", "policy_version": "v1"},
        "long_term_eligible": True,
        "reducer_rule": (
            "knowledge：独立正确 -> verified_once（≥1 道不同题）/ stable（≥2 道）；"
            "答错 -> 状态降级为 candidate，记录误解候选；"
            "practice：独立正确 -> applied，辅助正确 -> assisted，迁移题 -> transferred"
        ),
    },
    "answer_skipped": {
        "event_id": "answer_skipped",
        "description": "学习者跳过本题（本轮未作答，不等于知识错误）。",
        "capability": "learner_state_discovery",
        "tool": "discovery_session",
        "agent": "Practice Agent",
        "workbench": "discovery",
        "scope": {"learner_id": True, "project_id": True, "session_id": True},
        "evidence_role": "skipped",
        "confidence": 1.0,
        "kernel_targets": ["knowledge", "structure"],
        "idempotency_key": "client_event_id",
        "provenance": {"policy_version": "v1"},
        "long_term_eligible": False,
        "reducer_rule": "knowledge 记录 skipped 计数（不改掌握状态）；structure 位置推进",
    },
    "answer_hazy": {
        "event_id": "answer_hazy",
        "description": "学习者给出含糊/无法判定的回答，标记不确定性。",
        "capability": "learner_state_discovery",
        "tool": "discovery_session",
        "agent": "Practice Agent",
        "workbench": "discovery",
        "scope": {"learner_id": True, "project_id": True, "session_id": True},
        "evidence_role": "ungraded_hazy",
        "confidence": 0.3,
        "kernel_targets": ["knowledge"],
        "idempotency_key": "client_event_id",
        "provenance": {"grading_version": "v1", "policy_version": "v1"},
        "long_term_eligible": False,
        "reducer_rule": "knowledge 记录 hazy 计数并标记需澄清，不改掌握状态",
    },
    "reasoning_explained": {
        "event_id": "reasoning_explained",
        "description": "学习者解释答题理由/思路（开放题证据，可能无法可靠评分）。",
        "capability": "learner_state_discovery",
        "tool": "discovery_session",
        "agent": "Practice Agent",
        "workbench": "discovery",
        "scope": {"learner_id": True, "project_id": True, "session_id": True},
        "evidence_role": "self_reported",
        "confidence": 0.6,
        "kernel_targets": ["knowledge"],
        "idempotency_key": "client_event_id",
        "provenance": {"rubric_version": "v1", "policy_version": "v1"},
        "long_term_eligible": False,
        "reducer_rule": "knowledge 记录解释证据（explained_ok 或 need_review），支持误解候选判定，不独立升级掌握",
    },
    "assisted_success": {
        "event_id": "assisted_success",
        "description": "辅助/提示后答对（支持'在帮助下可以完成'，不等于独立掌握）。",
        "capability": "learner_state_discovery",
        "tool": "discovery_session",
        "agent": "Practice Agent",
        "workbench": "discovery",
        "scope": {"learner_id": True, "project_id": True, "session_id": True},
        "evidence_role": "assisted_success",
        "confidence": 0.5,
        "kernel_targets": ["practice", "knowledge"],
        "idempotency_key": "client_event_id",
        "provenance": {"grading_version": "v1", "policy_version": "v1"},
        "long_term_eligible": False,
        "reducer_rule": "practice.independence=assisted；knowledge 记录 assisted 计数，不升级 verified/stable",
    },
    "preference_stated": {
        "event_id": "preference_stated",
        "description": "学习者明确表达难度/节奏/形式/支持偏好。",
        "capability": "learner_state_discovery",
        "tool": "discovery_session",
        "agent": "Tutor Agent",
        "workbench": "discovery",
        "scope": {"learner_id": True, "project_id": True, "session_id": True},
        "evidence_role": "self_reported",
        "confidence": 0.6,
        "kernel_targets": ["human"],
        "idempotency_key": "client_event_id",
        "provenance": {"policy_version": "v1"},
        "long_term_eligible": True,
        "reducer_rule": "human.preferences 追加/更新候选偏好（status=candidate，记录事件引用）",
    },
    "discovery_session_completed": {
        "event_id": "discovery_session_completed",
        "description": "发现会话结束（completed / insufficient_evidence / stopped）。",
        "capability": "learner_state_discovery",
        "tool": "discovery_session",
        "agent": "Practice Agent",
        "workbench": "discovery",
        "scope": {"learner_id": True, "project_id": True, "session_id": True},
        "evidence_role": "interaction_log",
        "confidence": 1.0,
        "kernel_targets": ["structure"],
        "idempotency_key": "client_event_id",
        "provenance": {"policy_version": "v1"},
        "long_term_eligible": False,
        "reducer_rule": "structure.position.session_status 置结束态",
    },
    "evidence_correction": {
        "event_id": "evidence_correction",
        "description": "用户纠正/归档一条既有证据（状态可被纠正）。",
        "capability": "learner_state_discovery",
        "tool": "discovery_session",
        "agent": "Tutor Agent",
        "workbench": "discovery",
        "scope": {"learner_id": True, "project_id": True, "session_id": True},
        "evidence_role": "self_reported",
        "confidence": 0.9,
        "kernel_targets": ["knowledge", "practice"],
        "idempotency_key": "client_event_id",
        "provenance": {"policy_version": "v1"},
        "long_term_eligible": True,
        "reducer_rule": (
            "knowledge：按 payload.recomputed 快照重算 KC 状态（剔除被纠正事件贡献），"
            "记录 corrected_event_ids；practice：同步降级独立性"
        ),
    },
}


def get_event_meta(event_type: str) -> dict[str, Any]:
    meta = EVENT_REGISTRY.get(event_type)
    if meta is None:
        raise KeyError(f"未登记的事件类型：{event_type}")
    return meta


def require_registered(event_type: str) -> None:
    get_event_meta(event_type)


def registry_summary() -> dict[str, Any]:
    return {
        "kernels": list(KERNELS),
        "evidence_roles": list(EVIDENCE_ROLES),
        "capabilities": CAPABILITIES,
        "tools": TOOLS,
        "product_skills": PRODUCT_SKILLS,
        "workbenches": WORKBENCHES,
        "events": list(EVENT_REGISTRY.keys()),
    }
