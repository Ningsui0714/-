from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import hmac
import mimetypes
from pathlib import Path
import subprocess
import sys

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.database import get_db
from app.models.learning import AgentSession
from app.models.project import (
    Checkpoint, Exercise, Lecture, ProjectWorkspace, Roadmap, WorkspaceOperation,
)
from app.schemas.workspace import (
    WorkspaceFileResponse, WorkspaceFileWriteRequest, WorkspaceLinkRequest,
    WorkspaceLinkResponse, WorkspaceOperationListResponse, WorkspaceOperationRequest,
    WorkspaceOperationResponse, WorkspaceRevealRequest, WorkspaceTreeResponse,
)
from app.services.auth import (
    CurrentLearner, get_current_learner, require_owned_checkpoint, require_owned_project,
)
from app.services.learning_runtime import record_event
from app.services.checkpoint_context import checkpoint_artifacts
from app.services.workspace_files import (
    DESCRIPTOR_SCHEMA, WorkspaceError, apply_operation, build_write_preview,
    canonical_root, initialize_managed_layout, read_workspace_file,
    resolve_workspace_path, scan_workspace_tree, validate_base_hash,
)


router = APIRouter()


def require_desktop_token(
    desktop_token: str | None = Header(default=None, alias="X-LearnFlow-Desktop-Token"),
) -> None:
    expected = settings.desktop_token
    if (
        not settings.desktop_mode
        or not expected
        or not desktop_token
        or not hmac.compare_digest(desktop_token, expected)
    ):
        # Hide local filesystem routes entirely from the browser deployment.
        raise HTTPException(404, "Desktop workspace is unavailable")


def _raise_workspace_error(exc: WorkspaceError):
    raise HTTPException(exc.status_code, {"code": exc.code, "message": exc.detail}) from exc


async def _owned_workspace(
    db: AsyncSession, learner_id: int, project_id: int,
) -> ProjectWorkspace:
    await require_owned_project(db, learner_id, project_id)
    workspace = (await db.execute(select(ProjectWorkspace).where(
        ProjectWorkspace.project_id == project_id,
        ProjectWorkspace.learner_id == learner_id,
    ))).scalar_one_or_none()
    if not workspace:
        raise HTTPException(404, "Project workspace is not linked")
    return workspace


async def _workspace_content(db: AsyncSession, project_id: int):
    checkpoints = list((await db.execute(
        select(Checkpoint)
        .join(Roadmap, Roadmap.id == Checkpoint.roadmap_id)
        .where(Roadmap.project_id == project_id)
    )).scalars().all())
    checkpoint_ids = [item.id for item in checkpoints]
    if not checkpoint_ids:
        return checkpoints, [], []
    lectures = list((await db.execute(
        select(Lecture).where(Lecture.checkpoint_id.in_(checkpoint_ids))
    )).scalars().all())
    exercises = list((await db.execute(
        select(Exercise).where(Exercise.checkpoint_id.in_(checkpoint_ids))
    )).scalars().all())
    return checkpoints, lectures, exercises


async def _validate_agent_scope(
    db: AsyncSession,
    current: CurrentLearner,
    project_id: int,
    checkpoint_id: int | None,
    session_id: int | None,
) -> None:
    if checkpoint_id is None or session_id is None:
        raise HTTPException(400, "Agent 文件提案必须绑定关卡 Tutor 会话")
    checkpoint = await require_owned_checkpoint(db, current.learner.id, checkpoint_id)
    roadmap = await db.get(Roadmap, checkpoint.roadmap_id)
    if not roadmap or roadmap.project_id != project_id:
        raise HTTPException(404, "Checkpoint not found in project")
    session = (await db.execute(select(AgentSession).where(
        AgentSession.id == session_id,
        AgentSession.learner_id == current.learner.id,
        AgentSession.session_type == "checkpoint",
        AgentSession.project_id == project_id,
        AgentSession.checkpoint_id == checkpoint_id,
    ))).scalar_one_or_none()
    if not session:
        raise HTTPException(404, "Checkpoint Tutor session not found")


@router.get("/checkpoints/{checkpoint_id}/workspace/artifacts")
async def get_checkpoint_workspace_artifacts(
    checkpoint_id: int,
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    await require_owned_checkpoint(db, current.learner.id, checkpoint_id)
    result = await checkpoint_artifacts(
        db, learner_id=current.learner.id, checkpoint_id=checkpoint_id,
    )
    if not result:
        raise HTTPException(404, "Checkpoint not found")
    return result


def _operation_key(learner_id: int, request_key: str) -> str:
    scoped = f"workspace:{learner_id}:{request_key}"
    if len(scoped) <= 160:
        return scoped
    return f"workspace:{learner_id}:sha256:{hashlib.sha256(request_key.encode('utf-8')).hexdigest()}"


@router.post(
    "/projects/{project_id}/workspace/link",
    response_model=WorkspaceLinkResponse,
    dependencies=[Depends(require_desktop_token)],
)
async def link_workspace(
    project_id: int,
    data: WorkspaceLinkRequest,
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    project = await require_owned_project(db, current.learner.id, project_id)
    try:
        root = canonical_root(data.root_path, create=data.create)
        collision = (await db.execute(select(ProjectWorkspace).where(
            ProjectWorkspace.root_path == str(root),
            ProjectWorkspace.project_id != project_id,
        ))).scalar_one_or_none()
        if collision:
            raise WorkspaceError(409, "该目录已经关联另一个 LearnFlow 项目", "workspace_collision")
        checkpoints, lectures, exercises = await _workspace_content(db, project_id)
        initialize_managed_layout(root, project, checkpoints, lectures, exercises)
    except WorkspaceError as exc:
        _raise_workspace_error(exc)

    workspace = (await db.execute(select(ProjectWorkspace).where(
        ProjectWorkspace.project_id == project_id,
    ))).scalar_one_or_none()
    if workspace:
        if workspace.learner_id != current.learner.id:
            raise HTTPException(404, "Project not found")
        workspace.root_path = str(root)
        workspace.platform = data.platform
        workspace.status = "linked"
        workspace.updated_at = datetime.utcnow()
    else:
        workspace = ProjectWorkspace(
            project_id=project_id,
            learner_id=current.learner.id,
            root_path=str(root),
            status="linked",
            platform=data.platform,
        )
        db.add(workspace)
        await db.flush()
    await record_event(
        db,
        learner_id=current.learner.id,
        event_type="workspace_linked",
        source="desktop_workspace",
        project_id=project_id,
        payload={"workspace_id": workspace.id, "platform": data.platform},
        provenance={"endpoint": "POST /api/projects/{id}/workspace/link"},
        client_event_id=f"workspace-link:{project_id}:{data.client_request_id}",
    )
    await db.commit()
    return WorkspaceLinkResponse(
        id=workspace.id,
        project_id=project_id,
        status=workspace.status,
        platform=workspace.platform,
        root_path=workspace.root_path,
        descriptor_version=DESCRIPTOR_SCHEMA,
    )


@router.get(
    "/projects/{project_id}/workspace/tree",
    response_model=WorkspaceTreeResponse,
    dependencies=[Depends(require_desktop_token)],
)
async def workspace_tree(
    project_id: int,
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    workspace = await _owned_workspace(db, current.learner.id, project_id)
    try:
        root = canonical_root(workspace.root_path)
        nodes = scan_workspace_tree(root)
    except WorkspaceError as exc:
        _raise_workspace_error(exc)
    return WorkspaceTreeResponse(
        workspace_id=workspace.id,
        project_id=project_id,
        root_name=root.name,
        nodes=nodes,
    )


@router.get(
    "/projects/{project_id}/workspace/files/{file_path:path}",
    response_model=WorkspaceFileResponse,
    dependencies=[Depends(require_desktop_token)],
)
async def get_workspace_file(
    project_id: int,
    file_path: str,
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    workspace = await _owned_workspace(db, current.learner.id, project_id)
    try:
        result = read_workspace_file(Path(workspace.root_path), file_path)
    except WorkspaceError as exc:
        _raise_workspace_error(exc)
    mime_type = mimetypes.guess_type(result["path"])[0] or "application/octet-stream"
    previewable = mime_type == "application/pdf" or mime_type in {
        "image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp",
    }
    return WorkspaceFileResponse(**result, mime_type=mime_type, previewable=previewable)


@router.get(
    "/projects/{project_id}/workspace/previews/{file_path:path}",
    dependencies=[Depends(require_desktop_token)],
)
async def preview_workspace_file(
    project_id: int,
    file_path: str,
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    workspace = await _owned_workspace(db, current.learner.id, project_id)
    try:
        relative, target = resolve_workspace_path(Path(workspace.root_path), file_path)
    except WorkspaceError as exc:
        _raise_workspace_error(exc)
    if not target.is_file():
        raise HTTPException(400, "目标不是普通文件")
    mime_type = mimetypes.guess_type(relative)[0] or "application/octet-stream"
    allowed = {
        "application/pdf", "image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp",
    }
    if mime_type not in allowed:
        raise HTTPException(415, "该文件类型不支持内置预览")
    return FileResponse(
        target, media_type=mime_type, filename=Path(relative).name,
        content_disposition_type="inline",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.get(
    "/projects/{project_id}/workspace/agent-files/{file_path:path}",
    response_model=WorkspaceFileResponse,
    dependencies=[Depends(require_desktop_token)],
)
async def get_workspace_file_for_checkpoint_tutor(
    project_id: int,
    file_path: str,
    checkpoint_id: int,
    session_id: int,
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    await _validate_agent_scope(
        db, current, project_id, checkpoint_id, session_id,
    )
    workspace = await _owned_workspace(db, current.learner.id, project_id)
    try:
        result = read_workspace_file(Path(workspace.root_path), file_path, actor="agent")
    except WorkspaceError as exc:
        _raise_workspace_error(exc)
    mime_type = mimetypes.guess_type(result["path"])[0] or "application/octet-stream"
    return WorkspaceFileResponse(**result, mime_type=mime_type, previewable=False)


@router.post(
    "/projects/{project_id}/workspace/reveal",
    dependencies=[Depends(require_desktop_token)],
)
async def reveal_workspace_item(
    project_id: int,
    data: WorkspaceRevealRequest,
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    workspace = await _owned_workspace(db, current.learner.id, project_id)
    try:
        relative, target = resolve_workspace_path(Path(workspace.root_path), data.path)
    except WorkspaceError as exc:
        _raise_workspace_error(exc)
    if sys.platform == "darwin":
        command = ["open", "-R", str(target)]
    elif sys.platform == "win32":
        command = ["explorer.exe", str(target) if target.is_dir() else f"/select,{target}"]
    else:
        command = ["xdg-open", str(target if target.is_dir() else target.parent)]
    try:
        subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
    except OSError as exc:
        raise HTTPException(500, "Unable to open the system file manager") from exc
    return {"status": "opened", "path": relative}


@router.post(
    "/projects/{project_id}/workspace/open",
    dependencies=[Depends(require_desktop_token)],
)
async def open_workspace_item(
    project_id: int,
    data: WorkspaceRevealRequest,
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    workspace = await _owned_workspace(db, current.learner.id, project_id)
    try:
        relative, target = resolve_workspace_path(Path(workspace.root_path), data.path)
    except WorkspaceError as exc:
        _raise_workspace_error(exc)
    if sys.platform == "darwin":
        command = ["open", str(target)]
    elif sys.platform == "win32":
        command = ["explorer.exe", str(target)]
    else:
        command = ["xdg-open", str(target)]
    try:
        subprocess.Popen(
            command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, close_fds=True,
        )
    except OSError as exc:
        raise HTTPException(500, "Unable to open file with the system application") from exc
    return {"status": "opened", "path": relative}


@router.put(
    "/projects/{project_id}/workspace/files/{file_path:path}",
    response_model=WorkspaceOperationResponse,
    dependencies=[Depends(require_desktop_token)],
)
async def put_workspace_file(
    project_id: int,
    file_path: str,
    data: WorkspaceFileWriteRequest,
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    workspace = await _owned_workspace(db, current.learner.id, project_id)
    key = _operation_key(current.learner.id, data.idempotency_key)
    existing = (await db.execute(select(WorkspaceOperation).where(
        WorkspaceOperation.learner_id == current.learner.id,
        WorkspaceOperation.idempotency_key == key,
    ))).scalar_one_or_none()
    if existing:
        return existing
    try:
        preview = build_write_preview(Path(workspace.root_path), file_path, data.content, actor="user")
        validate_base_hash(preview["path"], data.base_hash)
    except WorkspaceError as exc:
        _raise_workspace_error(exc)
    operation = WorkspaceOperation(
        workspace_id=workspace.id,
        learner_id=current.learner.id,
        project_id=project_id,
        actor="user",
        operation="write" if preview["exists"] else "create",
        status="proposed",
        target_path=preview["relative_path"],
        base_hash=data.base_hash,
        payload={
            "actor": "user", "target_path": preview["relative_path"],
            "content": data.content, "base_hash": data.base_hash,
        },
        result={"diff": preview["diff"]},
        idempotency_key=key,
    )
    db.add(operation)
    await db.flush()
    try:
        result = apply_operation(
            Path(workspace.root_path), operation.id, operation.operation, operation.payload,
        )
    except WorkspaceError as exc:
        operation.status = "failed"
        operation.result = {"code": exc.code, "message": exc.detail}
        await db.commit()
        _raise_workspace_error(exc)
    now = datetime.utcnow()
    operation.status = "applied"
    operation.confirmed_at = now
    operation.applied_at = now
    operation.result = result
    await record_event(
        db,
        learner_id=current.learner.id,
        event_type="workspace_change_applied",
        source="workspace_file_service",
        project_id=project_id,
        payload={"operation_id": operation.id, "operation": operation.operation, "path": operation.target_path},
        provenance={"actor": "user", "base_hash": data.base_hash},
        client_event_id=f"workspace-operation:{operation.id}:applied",
    )
    await db.commit()
    return operation


@router.post(
    "/projects/{project_id}/workspace/operations/propose",
    response_model=WorkspaceOperationResponse,
    dependencies=[Depends(require_desktop_token)],
)
async def propose_workspace_operation(
    project_id: int,
    data: WorkspaceOperationRequest,
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    workspace = await _owned_workspace(db, current.learner.id, project_id)
    if data.actor == "agent":
        await _validate_agent_scope(
            db, current, project_id, data.checkpoint_id, data.session_id,
        )
    key = _operation_key(current.learner.id, data.idempotency_key)
    existing = (await db.execute(select(WorkspaceOperation).where(
        WorkspaceOperation.learner_id == current.learner.id,
        WorkspaceOperation.idempotency_key == key,
    ))).scalar_one_or_none()
    if existing:
        return existing

    root = Path(workspace.root_path)
    payload = {
        "actor": data.actor,
        "target_path": data.target_path,
        "destination_path": data.destination_path,
        "content": data.content,
        "base_hash": data.base_hash,
    }
    result = {"requires_confirmation": True}
    try:
        if data.operation in {"create", "write"}:
            if data.content is None:
                raise WorkspaceError(400, "写入提案缺少文本内容", "content_required")
            preview = build_write_preview(root, data.target_path, data.content, actor=data.actor)
            validate_base_hash(preview["path"], data.base_hash)
            payload["target_path"] = preview["relative_path"]
            result.update({"diff": preview["diff"], "new_hash": preview["new_hash"]})
        elif data.operation == "restore":
            if data.source_operation_id is None:
                raise WorkspaceError(400, "恢复操作必须引用一次删除操作", "source_operation_required")
            deleted = (await db.execute(select(WorkspaceOperation).where(
                WorkspaceOperation.id == data.source_operation_id,
                WorkspaceOperation.workspace_id == workspace.id,
                WorkspaceOperation.learner_id == current.learner.id,
                WorkspaceOperation.operation == "delete",
                WorkspaceOperation.status == "applied",
            ))).scalar_one_or_none()
            if not deleted or not (deleted.result or {}).get("trash_path"):
                raise WorkspaceError(404, "找不到可恢复的删除记录", "delete_operation_missing")
            payload["restore_source"] = deleted.result["trash_path"]
            payload["source_operation_id"] = deleted.id
            payload["target_path"] = data.target_path or deleted.target_path
            resolve_workspace_path(root, payload["target_path"], actor=data.actor, allow_missing_leaf=True)
        else:
            _, target = resolve_workspace_path(
                root, data.target_path, actor=data.actor,
                allow_missing_leaf=data.operation == "mkdir",
            )
            if target.is_file():
                validate_base_hash(target, data.base_hash)
            if data.operation in {"rename", "move"}:
                if not data.destination_path:
                    raise WorkspaceError(400, "重命名或移动必须指定目标路径", "destination_required")
                resolve_workspace_path(root, data.destination_path, actor=data.actor, allow_missing_leaf=True)
    except WorkspaceError as exc:
        _raise_workspace_error(exc)

    operation = WorkspaceOperation(
        workspace_id=workspace.id,
        learner_id=current.learner.id,
        project_id=project_id,
        checkpoint_id=data.checkpoint_id,
        session_id=data.session_id,
        actor=data.actor,
        operation=data.operation,
        status="proposed",
        target_path=payload["target_path"],
        destination_path=data.destination_path,
        base_hash=data.base_hash,
        payload=payload,
        result=result,
        idempotency_key=key,
        expires_at=datetime.utcnow() + timedelta(minutes=30),
    )
    db.add(operation)
    await db.commit()
    await db.refresh(operation)
    return operation


@router.get(
    "/projects/{project_id}/workspace/operations",
    response_model=WorkspaceOperationListResponse,
    dependencies=[Depends(require_desktop_token)],
)
async def list_workspace_operations(
    project_id: int,
    operation: str | None = None,
    status: str | None = None,
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    workspace = await _owned_workspace(db, current.learner.id, project_id)
    query = select(WorkspaceOperation).where(
        WorkspaceOperation.workspace_id == workspace.id,
        WorkspaceOperation.learner_id == current.learner.id,
    )
    if operation:
        query = query.where(WorkspaceOperation.operation == operation)
    if status:
        query = query.where(WorkspaceOperation.status == status)
    rows = list((await db.execute(
        query.order_by(WorkspaceOperation.created_at.desc()).limit(100)
    )).scalars().all())
    return WorkspaceOperationListResponse(operations=rows)


@router.post(
    "/projects/{project_id}/workspace/operations/{operation_id}/confirm",
    response_model=WorkspaceOperationResponse,
    dependencies=[Depends(require_desktop_token)],
)
async def confirm_workspace_operation(
    project_id: int,
    operation_id: int,
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    workspace = await _owned_workspace(db, current.learner.id, project_id)
    operation = (await db.execute(select(WorkspaceOperation).where(
        WorkspaceOperation.id == operation_id,
        WorkspaceOperation.workspace_id == workspace.id,
        WorkspaceOperation.project_id == project_id,
        WorkspaceOperation.learner_id == current.learner.id,
    ))).scalar_one_or_none()
    if not operation:
        raise HTTPException(404, "Workspace operation not found")
    if operation.status == "applied":
        return operation
    if operation.status != "proposed":
        raise HTTPException(409, "Workspace operation is no longer confirmable")
    if operation.expires_at and operation.expires_at < datetime.utcnow():
        operation.status = "expired"
        await db.commit()
        raise HTTPException(409, "Workspace operation expired")
    try:
        result = apply_operation(
            Path(workspace.root_path), operation.id, operation.operation, operation.payload or {},
        )
    except WorkspaceError as exc:
        operation.status = "failed" if exc.code != "hash_conflict" else "stale"
        operation.result = {"code": exc.code, "message": exc.detail}
        await db.commit()
        _raise_workspace_error(exc)
    now = datetime.utcnow()
    operation.status = "applied"
    operation.confirmed_at = now
    operation.applied_at = now
    operation.result = result
    if operation.operation == "restore" and (operation.payload or {}).get("source_operation_id"):
        deleted = await db.get(WorkspaceOperation, operation.payload["source_operation_id"])
        if deleted and deleted.workspace_id == workspace.id:
            deleted.result = {
                **(deleted.result or {}),
                "restorable": False,
                "restored_by_operation_id": operation.id,
            }
    await record_event(
        db,
        learner_id=current.learner.id,
        event_type="workspace_change_applied",
        source="workspace_file_service",
        project_id=project_id,
        checkpoint_id=operation.checkpoint_id,
        session_id=operation.session_id,
        payload={
            "operation_id": operation.id, "operation": operation.operation,
            "path": operation.target_path,
        },
        provenance={"actor": operation.actor, "confirmation": "explicit"},
        client_event_id=f"workspace-operation:{operation.id}:applied",
    )
    await db.commit()
    return operation
