from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


AgentAdapter = Literal["codex_cli", "deterministic_fake"]
TaskType = Literal["code_change", "bug_fix", "refactor", "test", "documentation"]
NetworkPolicy = Literal["unmanaged", "managed_off", "managed_on"]


class LocalAgentProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    adapter: AgentAdapter = "codex_cli"
    executable_path: str | None = Field(default=None, max_length=1000)
    enabled: bool = True
    priority: int = Field(default=100, ge=0, le=10000)
    task_types: list[TaskType] = Field(default_factory=lambda: ["code_change", "bug_fix", "refactor", "test", "documentation"])
    capabilities: list[str] = Field(default_factory=lambda: ["code_edit", "test"])
    sandbox_policy: Literal["workspace_write"] = "workspace_write"
    network_policy: NetworkPolicy = "unmanaged"
    timeout_seconds: int = Field(default=900, ge=30, le=3600)

    @model_validator(mode="after")
    def validate_adapter_boundary(self):
        if self.adapter == "codex_cli" and self.network_policy != "unmanaged":
            raise ValueError("Codex CLI 首版无法保证联网边界，network_policy 必须标为 unmanaged")
        if self.adapter == "deterministic_fake" and self.network_policy != "managed_off":
            raise ValueError("确定性演示 Agent 必须使用 managed_off")
        if self.adapter == "deterministic_fake" and self.executable_path:
            raise ValueError("确定性演示 Agent 不接受可执行文件")
        self.task_types = list(dict.fromkeys(self.task_types))
        self.capabilities = list(dict.fromkeys(item.strip() for item in self.capabilities if item.strip()))
        return self


class LocalAgentProfilePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    executable_path: str | None = Field(default=None, max_length=1000)
    enabled: bool | None = None
    priority: int | None = Field(default=None, ge=0, le=10000)
    task_types: list[TaskType] | None = None
    capabilities: list[str] | None = None
    network_policy: NetworkPolicy | None = None
    timeout_seconds: int | None = Field(default=None, ge=30, le=3600)


class LocalAgentProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    adapter: str
    executable_path: str | None
    enabled: bool
    priority: int
    task_types: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    sandbox_policy: str
    network_policy: str
    timeout_seconds: int
    last_probe: dict = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class LocalAgentApplyRequest(BaseModel):
    confirm_apply: bool
    confirmed_deletions: list[str] = Field(default_factory=list)
    confirmed_moves: list[str] = Field(default_factory=list)
    idempotency_key: str = Field(min_length=1, max_length=160)


class LocalAgentRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    checkpoint_id: int
    session_id: int
    action_id: int
    profile_id: int
    task_type: str
    goal: str
    constraints: list[str] = Field(default_factory=list)
    required_capabilities: list[str] = Field(default_factory=list)
    status: str
    changed_files: list[dict] = Field(default_factory=list)
    diff_text: str = ""
    result: dict = Field(default_factory=dict)
    error: dict = Field(default_factory=dict)
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    applied_at: datetime | None


class LocalAgentRunEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sequence: int
    event_type: str
    payload: dict = Field(default_factory=dict)
    created_at: datetime
