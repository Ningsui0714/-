from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import (
    Checkpoint, CheckpointChunk, Chunk, Exercise, Lecture, Project,
    ProjectWorkspace, Roadmap,
)
from app.services.learning_runtime import get_kernel_projection
from app.services.workspace_files import WorkspaceError, canonical_root, scan_workspace_tree


def _short(value: object, limit: int = 240) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


def _scoped_five_kernel_projection(
    projection: dict[str, Any], *, project_id: int, checkpoint_id: int,
) -> dict[str, Any]:
    """Return a compact learner projection with an explicit immutable scope.

    The five kernels remain learner-owned. This adapter removes unrelated active
    navigation pointers and marks the scope used for this checkpoint turn; it
    never writes a kernel or treats workspace activity as learning evidence.
    """
    excluded = object()

    def filter_value(value: Any):
        if isinstance(value, dict):
            if value.get("project_id") not in {None, project_id}:
                return excluded
            if value.get("checkpoint_id") not in {None, checkpoint_id}:
                return excluded
            filtered = {}
            for key, item in value.items():
                nested = filter_value(item)
                if nested is not excluded:
                    filtered[key] = nested
            return filtered
        if isinstance(value, list):
            return [item for original in value if (item := filter_value(original)) is not excluded]
        return value

    result: dict[str, Any] = {}
    for kernel_name in ("structure", "knowledge", "human", "value", "practice"):
        source = dict(projection.get(kernel_name) or {})
        short_term = filter_value(dict(source.get("short_term") or {}))
        if kernel_name == "structure":
            short_term.pop("active_project_id", None)
            short_term.pop("active_checkpoint_id", None)
            short_term["session_scope"] = {
                "project_id": project_id,
                "checkpoint_id": checkpoint_id,
            }
        result[kernel_name] = {
            "short_term": short_term,
            "long_term": filter_value(dict(source.get("long_term") or {})),
            "confidence": float(source.get("confidence") or 0.0),
        }
    return result


def _flatten_workspace_nodes(nodes: list[dict], limit: int = 300) -> list[dict]:
    result: list[dict] = []

    def visit(items: list[dict]):
        for item in items:
            if len(result) >= limit:
                return
            result.append({
                "path": item.get("path"),
                "kind": item.get("kind"),
                "size": item.get("size", 0),
                "is_directory": item.get("is_directory", False),
            })
            children = item.get("children")
            if isinstance(children, list):
                visit(children)

    visit(nodes)
    return result


async def checkpoint_artifacts(
    db: AsyncSession, *, learner_id: int, checkpoint_id: int,
) -> dict[str, Any] | None:
    checkpoint = (await db.execute(
        select(Checkpoint, Roadmap, Project)
        .join(Roadmap, Roadmap.id == Checkpoint.roadmap_id)
        .join(Project, Project.id == Roadmap.project_id)
        .where(Checkpoint.id == checkpoint_id, Project.learner_id == learner_id)
    )).one_or_none()
    if not checkpoint:
        return None
    checkpoint_row, roadmap, project = checkpoint
    lecture = (await db.execute(select(Lecture).where(
        Lecture.checkpoint_id == checkpoint_id,
    ))).scalar_one_or_none()
    exercises = list((await db.execute(select(Exercise).where(
        Exercise.checkpoint_id == checkpoint_id,
    ).order_by(Exercise.order, Exercise.id))).scalars().all())
    return {
        "project": {"id": project.id, "name": project.name},
        "checkpoint": {
            "id": checkpoint_row.id,
            "title": checkpoint_row.title,
            "description": checkpoint_row.description or "",
            "status": checkpoint_row.learning_status or "not_started",
        },
        "managed_lecture": ({
            "kind": "managed_lecture",
            "id": lecture.id,
            "checkpoint_id": checkpoint_id,
            "status": lecture.status,
            "version": int(lecture.version or 1),
            "logical_filename": f"{checkpoint_row.order:02d}-{checkpoint_row.title}.lflecture",
            "open_target": f"/projects/{project.id}/checkpoints/{checkpoint_id}",
            "allowed_operations": ["read", "annotate", "edit_versioned", "view_versions"],
            "section_count": len(lecture.sections or []),
        } if lecture else None),
        "managed_exercises": [{
            "kind": "managed_exercise",
            "id": item.id,
            "checkpoint_id": checkpoint_id,
            "title": item.title,
            "order": item.order,
            "version": 1,
            "logical_filename": f"{item.order + 1:02d}-{item.title}.lfexercise",
            "open_target": f"/projects/{project.id}/checkpoints/{checkpoint_id}/exercises?exercise={item.id}",
            "allowed_operations": ["read", "annotate", "edit_draft", "run", "submit"],
            "virtual_files": [
                {"name": value.get("name"), "read_only": bool(value.get("read_only"))}
                for value in (item.files or []) if isinstance(value, dict)
            ],
        } for item in exercises],
        "authority": {
            "lecture_and_exercise": "database",
            "ordinary_project_files": "local_workspace",
        },
    }


async def build_checkpoint_tutor_context(
    db: AsyncSession,
    *,
    learner_id: int,
    project_id: int,
    checkpoint_id: int,
    surface_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    artifacts = await checkpoint_artifacts(
        db, learner_id=learner_id, checkpoint_id=checkpoint_id,
    )
    if not artifacts or int(artifacts["project"]["id"]) != project_id:
        raise ValueError("关卡不属于当前项目")

    checkpoint = await db.get(Checkpoint, checkpoint_id)
    lecture = (await db.execute(select(Lecture).where(
        Lecture.checkpoint_id == checkpoint_id,
    ))).scalar_one_or_none()
    exercises = list((await db.execute(select(Exercise).where(
        Exercise.checkpoint_id == checkpoint_id,
    ).order_by(Exercise.order, Exercise.id))).scalars().all())
    assigned = list((await db.execute(
        select(CheckpointChunk, Chunk)
        .join(Chunk, Chunk.id == CheckpointChunk.chunk_id)
        .where(CheckpointChunk.checkpoint_id == checkpoint_id)
        .order_by(CheckpointChunk.id)
    )).all())
    projection = await get_kernel_projection(db, learner_id)

    workspace_nodes: list[dict] = []
    workspace = (await db.execute(select(ProjectWorkspace).where(
        ProjectWorkspace.project_id == project_id,
        ProjectWorkspace.learner_id == learner_id,
        ProjectWorkspace.status == "linked",
    ))).scalar_one_or_none()
    if workspace:
        try:
            root = canonical_root(workspace.root_path)
            workspace_nodes = _flatten_workspace_nodes(scan_workspace_tree(root))
        except WorkspaceError:
            # A disconnected folder must not make the Tutor session unusable.
            workspace_nodes = []

    incoming = dict(surface_context or {})
    selected_text = incoming.get("selected_text")
    if isinstance(selected_text, str):
        incoming["selected_text"] = selected_text[:12000]
    for content_key in ("code", "content", "file_content"):
        incoming.pop(content_key, None)
    allowed_surface = {
        key: incoming[key]
        for key in (
            "surface", "resource_kind", "resource_id", "title", "section_index",
            "selected_text", "selected_path", "open_file", "language",
        )
        if key in incoming
    }

    return {
        "scope": {
            "learner_id": learner_id,
            "project_id": project_id,
            "checkpoint_id": checkpoint_id,
            "history_policy": "this_checkpoint_session_only",
        },
        "five_kernel_projection": _scoped_five_kernel_projection(
            projection, project_id=project_id, checkpoint_id=checkpoint_id,
        ),
        "checkpoint": {
            **artifacts["checkpoint"],
            "brief": dict(checkpoint.brief or {}) if checkpoint else {},
        },
        "assigned_resources": [{
            "chunk_id": chunk.id,
            "source_id": chunk.source_id,
            "index": chunk.index,
            "summary": _short(chunk.content),
            "metadata": dict(chunk.meta_data or {}),
        } for _, chunk in assigned[:40]],
        "lecture_summary": ({
            "id": lecture.id,
            "status": lecture.status,
            "sections": [{
                "title": _short(section.get("title", ""), 120),
                "summary": _short(section.get("content", ""), 180),
            } for section in (lecture.sections or []) if isinstance(section, dict)],
        } if lecture else None),
        "exercise_summaries": [{
            "id": item.id,
            "title": item.title,
            "summary": _short(item.description, 180),
            "judge_mode": item.judge_mode,
            "virtual_files": [
                {"name": value.get("name"), "read_only": bool(value.get("read_only"))}
                for value in (item.files or []) if isinstance(value, dict)
            ],
        } for item in exercises],
        "project_file_tree": workspace_nodes,
        "current_surface": allowed_surface,
        "content_policy": (
            "Do not infer file contents from the tree. Read ordinary files on demand. "
            "Never use ordinary file writes to modify official lecture or exercise objects."
        ),
    }
