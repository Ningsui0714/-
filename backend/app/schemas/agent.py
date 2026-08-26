from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class AgentSessionCreate(BaseModel):
    session_type: Literal["global", "project", "checkpoint"] = "global"
    project_id: Optional[int] = None
    checkpoint_id: Optional[int] = None
    force_new: bool = False


class TutorTurnRequest(BaseModel):
    message: str = Field(min_length=1, max_length=12000)
    project_id: Optional[int] = None
    checkpoint_id: Optional[int] = None
    selected_action_id: Optional[int] = None
    client_turn_id: Optional[str] = Field(default=None, min_length=3, max_length=160)
    context: dict[str, Any] = Field(default_factory=dict)


class LearningEventRequest(BaseModel):
    client_event_id: str = Field(min_length=3, max_length=160)
    event_type: str = Field(min_length=2, max_length=80)
    project_id: Optional[int] = None
    checkpoint_id: Optional[int] = None
    session_id: Optional[int] = None
    payload: dict[str, Any] = Field(default_factory=dict)


class TutorObservation(BaseModel):
    kernel: Literal["structure", "knowledge", "human", "value", "practice"] = Field(
        description=(
            "structure 只表示路径位置、依赖、转向与返回线索；knowledge 只表示具体概念的"
            "理解、知识缺口、已诊断误解与验证状态；目标归 value，能力产物归 practice。"
        )
    )
    short_term: dict[str, Any] = Field(
        default_factory=dict,
        description="只写本轮证据直接支持的短期字段，不复制其他维度内容。",
    )
    reason: str = ""


class ProjectOpportunity(BaseModel):
    should_propose: bool = False
    title: str = ""
    description: str = ""
    reason: str = ""
    initial_concepts: list[str] = Field(default_factory=list)
    practice_artifact: str = ""
    proposal_type: Literal["build", "mastery", "exam", "research"] = "build"
    learning_goal: str = ""
    practice_goal: str = ""
    learner_start: list[str] = Field(default_factory=list)
    estimated_effort: str = ""
    milestones: list[dict[str, Any]] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    source_search_query: str = ""


class LearningIntent(BaseModel):
    immediate_need: str = ""
    long_term_goal: str = ""
    artifact_intent: str = ""
    relevant_proposal_key: str = ""
    horizon: Literal["short", "long", "unclear"] = "unclear"


class MajorEventCandidate(BaseModel):
    event_type: Literal["career_goal_confirmed"]
    career_goal: str = Field(min_length=2, max_length=200)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_text: str = Field(default="", max_length=500)


class LocalAgentTaskProposal(BaseModel):
    should_delegate: bool = False
    task_type: Literal["code_change", "bug_fix", "refactor", "test", "documentation"] = "code_change"
    goal: str = Field(default="", max_length=2000)
    constraints: list[str] = Field(default_factory=list)
    required_capabilities: list[str] = Field(default_factory=lambda: ["code_edit"])
    reason: str = Field(default="", max_length=500)


class TutorModelOutput(BaseModel):
    reply: str
    observations: list[TutorObservation] = Field(default_factory=list)
    project_opportunity: Optional[ProjectOpportunity] = None
    learning_intent: Optional[LearningIntent] = None
    major_event_candidates: list[MajorEventCandidate] = Field(default_factory=list)
    local_agent_task: Optional[LocalAgentTaskProposal] = None


class ProjectProposalUpdateRequest(BaseModel):
    patch: dict[str, Any] = Field(default_factory=dict)
    lock_fields: list[str] = Field(default_factory=list)
    unlock_fields: list[str] = Field(default_factory=list)
    client_event_id: Optional[str] = Field(default=None, min_length=3, max_length=160)


class ProjectProposalAcceptRequest(BaseModel):
    client_event_id: str = Field(min_length=3, max_length=160)
