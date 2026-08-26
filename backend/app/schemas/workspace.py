from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


WorkspaceKind = Literal[
    "managed_lecture", "managed_exercise", "workspace_text",
    "workspace_binary", "protected",
]
WorkspaceMutation = Literal[
    "create", "write", "mkdir", "rename", "move", "delete", "restore",
]


class WorkspaceLinkRequest(BaseModel):
    root_path: str = Field(min_length=1)
    platform: str = "unknown"
    create: bool = False
    client_request_id: str = Field(min_length=1, max_length=120)


class WorkspaceLinkResponse(BaseModel):
    id: int
    project_id: int
    status: str
    platform: str
    root_path: str
    descriptor_version: str


class WorkspaceNode(BaseModel):
    name: str
    path: str
    kind: WorkspaceKind
    is_directory: bool = False
    size: int | None = None
    modified_at: datetime | None = None
    protected_reason: str | None = None
    children: list["WorkspaceNode"] = Field(default_factory=list)


class WorkspaceTreeResponse(BaseModel):
    workspace_id: int
    project_id: int
    root_name: str
    nodes: list[WorkspaceNode]


class WorkspaceFileResponse(BaseModel):
    path: str
    kind: WorkspaceKind
    content: str | None = None
    sha256: str | None = None
    size: int
    modified_at: datetime
    read_only: bool = False
    mime_type: str | None = None
    previewable: bool = False


class WorkspaceFileWriteRequest(BaseModel):
    content: str
    base_hash: str | None = None
    idempotency_key: str = Field(min_length=1, max_length=160)


class WorkspaceRevealRequest(BaseModel):
    path: str = Field(min_length=1)


class WorkspaceOperationRequest(BaseModel):
    actor: Literal["user", "agent"] = "agent"
    operation: WorkspaceMutation
    target_path: str = Field(min_length=1)
    destination_path: str | None = None
    content: str | None = None
    base_hash: str | None = None
    checkpoint_id: int | None = None
    session_id: int | None = None
    source_operation_id: int | None = None
    idempotency_key: str = Field(min_length=1, max_length=160)


class WorkspaceOperationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    actor: str
    operation: str
    status: str
    target_path: str
    destination_path: str | None = None
    base_hash: str | None = None
    result: dict = Field(default_factory=dict)
    expires_at: datetime | None = None
    created_at: datetime
    confirmed_at: datetime | None = None
    applied_at: datetime | None = None


class WorkspaceOperationListResponse(BaseModel):
    operations: list[WorkspaceOperationResponse]
