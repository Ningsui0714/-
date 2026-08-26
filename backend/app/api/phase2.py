"""
Phase 2 API routes:
- Lecture generation (SSE streaming)
- Lecture retrieval
- Q&A agent for selected text
"""
import hashlib
import json
from fastapi import APIRouter, Depends, HTTPException, Body
from fastapi.responses import StreamingResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.db.database import get_db
from app.models.project import (
    ArtifactAnnotation, Project, Roadmap, Checkpoint, CheckpointChunk, Chunk,
    Lecture, Task, LectureVersion, ProcessAnimation,
)
from app.schemas.project import (
    AgentMessage, LectureAskRequest, AnimationGenerateRequest,
)
from app.services.lecture_agent import LectureAgent, QAAgent
from app.services.auth import (
    CurrentLearner, get_current_learner, require_owned_animation,
    require_owned_annotation, require_owned_checkpoint,
)
from app.services.workspace_files import sync_managed_layout_for_project

router = APIRouter()


@router.post("/checkpoints/{checkpoint_id}/lecture/generate")
async def generate_lecture_task(
    checkpoint_id: int,
    db: AsyncSession = Depends(get_db),
    req: dict = Body(default={}),
    current: CurrentLearner = Depends(get_current_learner),
):
    """Create a background lecture-generation task (T1).

    Returns {task_id, status}. If a task is already running for this
    checkpoint, returns the existing one (frontend subscribes to it).
    mode: "fresh" (default) clears partial content; "resume" reuses saved sections.
    """
    await require_owned_checkpoint(db, current.learner.id, checkpoint_id)
    mode = (req or {}).get("mode", "fresh")
    feedback = (req or {}).get("feedback") or ""
    if not settings.llm_api_key or settings.llm_api_key == "***":
        raise HTTPException(400, "请先配置 API Key: 在设置页填写 LLM_API_KEY")

    result = await db.execute(select(Checkpoint).where(Checkpoint.id == checkpoint_id))
    checkpoint = result.scalar_one_or_none()
    if not checkpoint:
        raise HTTPException(404, "Checkpoint not found")

    from app.models.project import Project, Roadmap
    roadmap = (await db.execute(select(Roadmap).where(Roadmap.id == checkpoint.roadmap_id))).scalar_one_or_none()
    project_id = roadmap.project_id if roadmap else None

    # Deduplicate: reuse an already-running task
    from app.services.task_manager import find_running_task, manager
    running = await find_running_task(checkpoint_id, "lecture_generate")
    if running:
        return {"task_id": running.id, "status": running.status, "already_running": True}

    task = Task(
        learner_id=current.learner.id,
        project_id=project_id,
        checkpoint_id=checkpoint_id,
        type="lecture_generate",
        status="queued",
        payload={"checkpoint_id": checkpoint_id, "resume": mode == "resume", "feedback": feedback},
        progress={"current": 0, "total": 0, "message": "排队中..."},
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    from app.services.task_runners import run_lecture_generation
    manager.submit(task.id, run_lecture_generation(task.id))

    return {"task_id": task.id, "status": task.status, "already_running": False}


@router.get("/checkpoints/{checkpoint_id}/lecture/task")
async def get_lecture_task(
    checkpoint_id: int,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    """Latest generation task for a checkpoint (used on page load / reconnect)."""
    await require_owned_checkpoint(db, current.learner.id, checkpoint_id)
    result = await db.execute(
        select(Task)
        .where(Task.checkpoint_id == checkpoint_id, Task.type == "lecture_generate")
        .order_by(Task.id.desc())
        .limit(1)
    )
    task = result.scalar_one_or_none()
    if not task:
        return {"task_id": None}
    from app.api.tasks import _snapshot
    lecture = (await db.execute(
        select(Lecture).where(Lecture.checkpoint_id == checkpoint_id)
    )).scalar_one_or_none()
    sections = [s for s in (lecture.sections if lecture and lecture.sections else []) if s]
    return _snapshot(task, sections)


@router.get("/checkpoints/{checkpoint_id}/lecture/generate")
async def generate_lecture_stream(
    checkpoint_id: int,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    """Legacy direct-SSE generation endpoint (kept for compatibility; use POST + /tasks/{id}/events)."""
    await require_owned_checkpoint(db, current.learner.id, checkpoint_id)
    from app.api.tasks import _snapshot as _unused  # noqa: F401
    try:
        # Quick API key check
        if not settings.llm_api_key or settings.llm_api_key == "***":
            async def _key_error():
                yield f"data: {json.dumps({'type': 'error', 'message': '请先配置 API Key...'}, ensure_ascii=False)}\n\n"
            return StreamingResponse(_key_error(), media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})

        # Get checkpoint
        result = await db.execute(select(Checkpoint).where(Checkpoint.id == checkpoint_id))
        checkpoint = result.scalar_one_or_none()
        if not checkpoint:
            raise HTTPException(404, "Checkpoint not found")

        # Get project
        r = await db.execute(select(Roadmap).where(Roadmap.id == checkpoint.roadmap_id))
        roadmap = r.scalar_one_or_none()
        project = None
        if roadmap:
            p = await db.execute(select(Project).where(Project.id == roadmap.project_id))
            project = p.scalar_one_or_none()
        user_level = project.user_level if project else "beginner"

        # Get chunks via CP
        cc_result = await db.execute(
            select(Chunk).join(CheckpointChunk)
            .where(CheckpointChunk.checkpoint_id == checkpoint_id)
            .order_by(Chunk.index)
        )
        chunks_raw = cc_result.scalars().all()
        chunks = [{"id": c.id, "content": c.content, "meta": c.meta_data or {}} for c in chunks_raw]

        agent = LectureAgent()

        async def event_stream():
            try:
                async for section_data in agent.generate_full_lecture(
                    checkpoint_title=checkpoint.title,
                    checkpoint_description=checkpoint.description or "",
                    user_level=user_level,
                    chunks=chunks,
                ):
                    yield f"data: {json.dumps(section_data, ensure_ascii=False)}\n\n"
            except Exception as e:
                import traceback; traceback.print_exc()
                yield f"data: {json.dumps({'type': 'error', 'message': f'{type(e).__name__}: {str(e)[:300]}'}, ensure_ascii=False)}\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"})

    except HTTPException:
        raise
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(500, f"{type(e).__name__}: {str(e)[:200]}")


def _normalized_sections(raw_sections: list) -> list[dict]:
    return [{
        "title": str(item.get("title", ""))[:500],
        "content": str(item.get("content", ""))[:2_000_000],
        "keywords": list(item.get("keywords") or [])[:100],
        "questions": list(item.get("questions") or [])[:100],
    } for item in raw_sections if isinstance(item, dict)]


def _serialize_annotation(item: ArtifactAnnotation) -> dict:
    anchor = dict(item.anchor or {})
    return {
        "id": item.id,
        "checkpoint_id": item.checkpoint_id,
        "artifact_type": item.artifact_type,
        "artifact_id": item.artifact_id,
        "artifact_version": item.artifact_version,
        "section_index": int(anchor.get("section_index") or 0),
        "surface": anchor.get("surface") or "content",
        "selection": anchor.get("selection") or "",
        "anchor": anchor,
        "note": item.body or "",
        "status": item.status or "anchored",
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


async def _reanchor_lecture_annotations(
    db: AsyncSession, lecture: Lecture, sections: list[dict], next_version: int,
) -> None:
    annotations = list((await db.execute(select(ArtifactAnnotation).where(
        ArtifactAnnotation.artifact_type == "lecture",
        ArtifactAnnotation.artifact_id == lecture.id,
    ))).scalars().all())
    for item in annotations:
        anchor = dict(item.anchor or {})
        selection = str(anchor.get("selection") or "")
        old_index = int(anchor.get("section_index") or 0)
        new_index = None
        if selection and 0 <= old_index < len(sections) and selection in sections[old_index].get("content", ""):
            new_index = old_index
        elif selection:
            matches = [
                index for index, section in enumerate(sections)
                if selection in section.get("content", "")
            ]
            if len(matches) == 1:
                new_index = matches[0]
        if new_index is None:
            item.status = "orphaned"
        else:
            anchor["section_index"] = new_index
            item.anchor = anchor
            item.status = "anchored"
        item.artifact_version = next_version


async def _save_lecture_versioned(
    checkpoint_id: int,
    sections_data: dict,
    db: AsyncSession,
    current: CurrentLearner,
) -> dict:
    await require_owned_checkpoint(db, current.learner.id, checkpoint_id)
    lecture = (await db.execute(select(Lecture).where(
        Lecture.checkpoint_id == checkpoint_id,
    ))).scalar_one_or_none()
    sections = _normalized_sections(sections_data.get("sections") or [])
    base_version = int(sections_data.get("base_version", lecture.version if lecture else 0) or 0)
    request_key = str(sections_data.get("idempotency_key") or "").strip()
    if not request_key:
        digest = hashlib.sha256(json.dumps(sections, sort_keys=True).encode()).hexdigest()
        request_key = f"compat:{checkpoint_id}:{base_version}:{digest}"
    scoped_key = f"lecture:{current.learner.id}:{request_key}"[:160]
    replay = (await db.execute(select(LectureVersion).where(
        LectureVersion.idempotency_key == scoped_key,
    ))).scalar_one_or_none()
    if replay:
        current_version = lecture.version if lecture else 0
        if current_version != replay.source_version + 1:
            raise HTTPException(409, {"code": "idempotency_stale", "message": "该保存请求已执行，但讲义已有更新"})
        return {"status": "ok", "sections": len(lecture.sections or []), "version": current_version, "idempotent_replay": True}

    if not lecture:
        if base_version != 0:
            raise HTTPException(409, {"code": "version_conflict", "message": "讲义尚未创建，请重新载入"})
        lecture = Lecture(
            checkpoint_id=checkpoint_id,
            sections=[], status="draft", version=0,
        )
        db.add(lecture)
        await db.flush()
    if int(lecture.version or 0) != base_version:
        raise HTTPException(409, {
            "code": "version_conflict", "message": "讲义已被其他编辑更新，请重新载入",
            "current_version": int(lecture.version or 0),
        })
    db.add(LectureVersion(
        checkpoint_id=checkpoint_id, sections=list(lecture.sections or []),
        source_version=base_version, reason="before_edit", idempotency_key=scoped_key,
    ))
    next_version = base_version + 1
    lecture.sections = sections
    lecture.status = "published"
    lecture.version = next_version
    await _reanchor_lecture_annotations(db, lecture, sections, next_version)

    # A generated lecture is exposure material, not proof of mastery.
    cp_result = await db.execute(
        select(Checkpoint).where(Checkpoint.id == checkpoint_id)
    )
    cp = cp_result.scalar_one_or_none()
    if cp and cp.learning_status not in {"completed", "verification_due"}:
        cp.learning_status = "in_progress"
    roadmap = await db.get(Roadmap, cp.roadmap_id) if cp else None

    from app.services.learning_runtime import record_event
    await record_event(
        db, event_type="lecture_generated", source="legacy_api",
        learner_id=current.learner.id,
        checkpoint_id=checkpoint_id,
        payload={"sections_count": len(sections)},
        provenance={"endpoint": "lecture/save"},
        client_event_id=f"lecture:{checkpoint_id}:save:v{next_version}",
    )

    await db.commit()
    if roadmap:
        await sync_managed_layout_for_project(db, roadmap.project_id)
    return {"status": "ok", "sections": len(sections), "version": next_version}


@router.put("/checkpoints/{checkpoint_id}/lecture")
async def put_lecture(
    checkpoint_id: int,
    sections_data: dict,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    """Versioned managed-lecture save with optimistic concurrency."""
    return await _save_lecture_versioned(checkpoint_id, sections_data, db, current)


@router.post("/checkpoints/{checkpoint_id}/lecture/save")
async def save_lecture_compat(
    checkpoint_id: int,
    sections_data: dict,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    """One-release compatibility adapter for legacy generated-lecture clients."""
    return await _save_lecture_versioned(checkpoint_id, sections_data, db, current)


@router.get("/checkpoints/{checkpoint_id}/lecture")
async def get_lecture(
    checkpoint_id: int,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    """Get stored lecture for a checkpoint."""
    await require_owned_checkpoint(db, current.learner.id, checkpoint_id)
    result = await db.execute(
        select(Lecture).where(Lecture.checkpoint_id == checkpoint_id)
    )
    lecture = result.scalar_one_or_none()
    if not lecture:
        # Return checkpoint info even without lecture
        cp_result = await db.execute(
            select(Checkpoint).where(Checkpoint.id == checkpoint_id)
        )
        cp = cp_result.scalar_one_or_none()
        if not cp:
            raise HTTPException(404, "Checkpoint not found")
        return {
            "id": None,
            "checkpoint_id": checkpoint_id,
            "checkpoint_title": cp.title,
            "sections": [],
            "status": "none",
            "version": 0,
        }

    return {
        "id": lecture.id,
        "checkpoint_id": lecture.checkpoint_id,
        "sections": lecture.sections or [],
        "status": lecture.status,
        "version": int(lecture.version or 1),
        "concept_graph": lecture.concept_graph or {},
        "animations": [
            {
                "id": a.id,
                "section_index": a.section_index,
                "source": a.source,
                "kind": a.kind or "animation",
                "title": a.title,
                "subtitle": a.subtitle,
                "legend": a.legend or [],
                "steps": a.steps or [],
            }
            for a in (
                await db.execute(
                    select(ProcessAnimation)
                    .where(ProcessAnimation.checkpoint_id == checkpoint_id)
                    .order_by(ProcessAnimation.id)
                )
            ).scalars().all()
        ],
    }


# ── Process animations (process-animator) ──

@router.post("/animations/generate")
async def generate_animation(
    req: AnimationGenerateRequest,
    current: CurrentLearner = Depends(get_current_learner),
):
    """手动/工作台：过程文本 → 动画 JSON（不落库，前端预览用）。"""
    if not req.text or not req.text.strip():
        raise HTTPException(400, "text 不能为空")
    if len(req.text) > 8000:
        raise HTTPException(400, "text 过长（≤8000 字符）")
    from app.services.animation_agent import AnimationAgent
    try:
        data = await AnimationAgent().extract_steps(req.text)
    except Exception as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})
    return {"ok": True, "animation": data}


@router.get("/animations/{animation_id}")
async def get_animation(
    animation_id: int,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    """按 id 取动画（LectureRenderer 懒加载用）。"""
    anim = await require_owned_animation(db, current.learner.id, animation_id)
    return {
        "id": anim.id,
        "checkpoint_id": anim.checkpoint_id,
        "section_index": anim.section_index,
        "source": anim.source,
        "kind": anim.kind or "animation",
        "title": anim.title,
        "subtitle": anim.subtitle,
        "legend": anim.legend or [],
        "steps": anim.steps or [],
    }


# ── Concept graph (concept map) ──

@router.post("/checkpoints/{checkpoint_id}/concept-graph/generate")
async def generate_concept_graph(
    checkpoint_id: int,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    """Create a background concept-graph generation task."""
    await require_owned_checkpoint(db, current.learner.id, checkpoint_id)
    if not settings.llm_api_key or settings.llm_api_key == "***":
        raise HTTPException(400, "请先配置 API Key: 在设置页填写 LLM_API_KEY")
    cp = (await db.execute(select(Checkpoint).where(Checkpoint.id == checkpoint_id))).scalar_one_or_none()
    if not cp:
        raise HTTPException(404, "Checkpoint not found")
    roadmap = (await db.execute(
        select(Roadmap).where(Roadmap.id == cp.roadmap_id)
    )).scalar_one_or_none()

    from app.services.task_manager import find_running_task, manager
    running = await find_running_task(checkpoint_id, "concept_graph")
    if running:
        return {"task_id": running.id, "status": running.status, "already_running": True}

    task = Task(
        learner_id=current.learner.id,
        project_id=roadmap.project_id if roadmap else None,
        checkpoint_id=checkpoint_id,
        type="concept_graph",
        status="queued",
        payload={"checkpoint_id": checkpoint_id},
        progress={"current": 0, "total": 0, "message": "排队中..."},
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    from app.services.task_runners import run_concept_graph_generation
    manager.submit(task.id, run_concept_graph_generation(task.id))
    return {"task_id": task.id, "status": task.status, "already_running": False}


@router.get("/checkpoints/{checkpoint_id}/concept-graph/task")
async def get_concept_graph_task(
    checkpoint_id: int,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    await require_owned_checkpoint(db, current.learner.id, checkpoint_id)
    result = await db.execute(
        select(Task)
        .where(Task.checkpoint_id == checkpoint_id, Task.type == "concept_graph")
        .order_by(Task.id.desc())
        .limit(1)
    )
    task = result.scalar_one_or_none()
    if not task:
        return {"task_id": None}
    from app.api.tasks import _snapshot
    return _snapshot(task)


# ── T5: Lecture versioning + rollback ──

@router.get("/checkpoints/{checkpoint_id}/lecture/versions")
async def list_lecture_versions(
    checkpoint_id: int,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    """List snapshotted versions (newest first)."""
    await require_owned_checkpoint(db, current.learner.id, checkpoint_id)
    rows = (await db.execute(
        select(LectureVersion)
        .where(LectureVersion.checkpoint_id == checkpoint_id)
        .order_by(LectureVersion.id.desc())
    )).scalars().all()
    return [{
        "id": v.id,
        "created_at": v.created_at.isoformat() if v.created_at else None,
        "reason": v.reason or "",
        "sections_count": len(v.sections or []),
        "source_version": int(v.source_version or 1),
        "preview": ((v.sections or [{}])[0].get("title", "") if v.sections else ""),
    } for v in rows]


@router.post("/checkpoints/{checkpoint_id}/lecture/rollback")
async def rollback_lecture(
    checkpoint_id: int,
    data: dict,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    """Restore a previous version. Current content is snapshotted first."""
    await require_owned_checkpoint(db, current.learner.id, checkpoint_id)
    version_id = (data or {}).get("version_id")
    if not version_id:
        raise HTTPException(400, "缺少 version_id")
    version = (await db.execute(
        select(LectureVersion).where(
            LectureVersion.id == version_id,
            LectureVersion.checkpoint_id == checkpoint_id,
        )
    )).scalar_one_or_none()
    if not version:
        raise HTTPException(404, "Version not found")

    lecture = (await db.execute(
        select(Lecture).where(Lecture.checkpoint_id == checkpoint_id)
    )).scalar_one_or_none()
    if not lecture:
        lecture = Lecture(checkpoint_id=checkpoint_id, sections=[], status="draft")
        db.add(lecture)
        await db.flush()

    # Snapshot current state before replacing (safety)
    if lecture.sections:
        db.add(LectureVersion(
            checkpoint_id=checkpoint_id,
            sections=list(lecture.sections),
            source_version=int(lecture.version or 1),
            reason="before_rollback",
        ))

    lecture.sections = list(version.sections or [])
    lecture.status = "published"
    lecture.version = int(lecture.version or 1) + 1
    await _reanchor_lecture_annotations(db, lecture, lecture.sections, lecture.version)
    await db.commit()
    roadmap = await db.get(Roadmap, checkpoint.roadmap_id)
    if roadmap:
        await sync_managed_layout_for_project(db, roadmap.project_id)
    return {"status": "ok", "sections": len(lecture.sections or []), "version": lecture.version}


@router.post("/checkpoints/{checkpoint_id}/ask")
async def ask_question(
    checkpoint_id: int,
    req: LectureAskRequest,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    """Answer a question / run a quick action about selected lecture text (T9)."""
    await require_owned_checkpoint(db, current.learner.id, checkpoint_id)
    result = await db.execute(
        select(Lecture).where(Lecture.checkpoint_id == checkpoint_id)
    )
    lecture = result.scalar_one_or_none()

    cp = (await db.execute(
        select(Checkpoint).where(Checkpoint.id == checkpoint_id)
    )).scalar_one_or_none()
    checkpoint_title = cp.title if cp else ""

    # Find the section that contains the selected text
    section_content = ""
    section_index = -1
    if lecture and lecture.sections:
        for i, s in enumerate(lecture.sections):
            if req.selection in s.get("content", ""):
                section_content = s.get("content", "")
                section_index = i
                break
        if not section_content and lecture.sections:
            section_content = lecture.sections[0].get("content", "")
            section_index = 0

    # Trace: deterministic source lookup (no LLM)
    if req.action == "trace":
        trace = await _trace_selection(db, checkpoint_id, req.selection)
        return {"answer": "", "kind": "trace", "trace": trace}

    agent = QAAgent()
    if req.action:
        answer = await agent.quick_action(
            action=req.action,
            selected_text=req.selection,
            section_content=section_content,
            checkpoint_title=checkpoint_title,
        )
    else:
        answer = await agent.answer(
            question=req.question,
            selected_text=req.selection,
            section_content=section_content,
            checkpoint_title=checkpoint_title,
            history=[m.model_dump() for m in req.history],
        )

    return {"answer": answer, "kind": "chat", "section_index": section_index}


async def _trace_selection(db: AsyncSession, checkpoint_id: int, selection: str) -> dict:
    """Find which source chunk contains the selected text (T9 trace)."""
    selection = (selection or "").strip()
    if len(selection) < 4:
        return {"found": False, "reason": "选中内容太短，无法定位"}
    chunks = (await db.execute(
        select(Chunk).join(CheckpointChunk)
        .where(CheckpointChunk.checkpoint_id == checkpoint_id)
        .order_by(Chunk.index)
    )).scalars().all()
    needle = selection[:60]
    best = None
    for c in chunks:
        if needle in c.content:
            best = c
            break
    if not best:
        # Fallback: prefix match on any chunk of the same source
        return {"found": False, "reason": "在关联切片中未找到该段文字（可能来自生成内容而非资料原文）"}
    meta = best.meta_data or {}
    idx = best.content.find(needle)
    return {
        "found": True,
        "chunk_id": best.id,
        "file": meta.get("file", ""),
        "headings": meta.get("headings", []),
        "heading_chain": meta.get("heading_chain", []),
        "preview": best.content[max(0, idx - 80):idx + 160],
    }


# ── Managed-artifact annotations ──

async def _owned_artifact(
    db: AsyncSession, learner_id: int, artifact_type: str, artifact_id: int,
) -> tuple[int, int]:
    if artifact_type == "lecture":
        artifact = (await db.execute(
            select(Lecture).join(Checkpoint).join(Roadmap).join(Project).where(
                Lecture.id == artifact_id, Project.learner_id == learner_id,
            )
        )).scalar_one_or_none()
        if not artifact:
            raise HTTPException(404, "Lecture not found")
        return artifact.checkpoint_id, int(artifact.version or 1)
    if artifact_type == "exercise":
        from app.services.auth import require_owned_exercise
        artifact = await require_owned_exercise(db, learner_id, artifact_id)
        return artifact.checkpoint_id, 1
    raise HTTPException(400, "artifact_type must be lecture or exercise")


@router.get("/artifacts/{artifact_type}/{artifact_id}/annotations")
async def list_artifact_annotations(
    artifact_type: str, artifact_id: int,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    await _owned_artifact(db, current.learner.id, artifact_type, artifact_id)
    rows = list((await db.execute(select(ArtifactAnnotation).where(
        ArtifactAnnotation.learner_id == current.learner.id,
        ArtifactAnnotation.artifact_type == artifact_type,
        ArtifactAnnotation.artifact_id == artifact_id,
    ).order_by(ArtifactAnnotation.id.desc()))).scalars().all())
    return [_serialize_annotation(item) for item in rows]


@router.post("/artifacts/{artifact_type}/{artifact_id}/annotations")
async def create_artifact_annotation(
    artifact_type: str, artifact_id: int, data: dict,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    checkpoint_id, artifact_version = await _owned_artifact(
        db, current.learner.id, artifact_type, artifact_id,
    )
    request_key = str(data.get("idempotency_key") or "").strip() or None
    if request_key:
        request_key = request_key[:160]
        existing = (await db.execute(select(ArtifactAnnotation).where(
            ArtifactAnnotation.learner_id == current.learner.id,
            ArtifactAnnotation.idempotency_key == request_key,
        ))).scalar_one_or_none()
        if existing:
            return _serialize_annotation(existing)
    anchor = dict(data.get("anchor") or {})
    anchor["selection"] = str(anchor.get("selection") or data.get("selection") or "")[:2000]
    if "section_index" not in anchor:
        anchor["section_index"] = int(data.get("section_index") or 0)
    item = ArtifactAnnotation(
        learner_id=current.learner.id, checkpoint_id=checkpoint_id,
        artifact_type=artifact_type, artifact_id=artifact_id,
        artifact_version=artifact_version, anchor=anchor,
        body=str(data.get("body") or data.get("note") or "")[:100_000],
        status="anchored", idempotency_key=request_key,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    if artifact_type == "lecture":
        from app.services.progress import update_notes_count
        count = len(list((await db.execute(select(ArtifactAnnotation).where(
            ArtifactAnnotation.checkpoint_id == checkpoint_id,
            ArtifactAnnotation.artifact_type == "lecture",
        ))).scalars().all()))
        await update_notes_count(checkpoint_id, count)
    return _serialize_annotation(item)


@router.put("/artifact-annotations/{annotation_id}")
async def update_artifact_annotation(
    annotation_id: int, data: dict,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    item = await require_owned_annotation(db, current.learner.id, annotation_id)
    if "body" in data or "note" in data:
        item.body = str(data.get("body", data.get("note", "")))[:100_000]
    await db.commit()
    return _serialize_annotation(item)


@router.delete("/artifact-annotations/{annotation_id}")
async def delete_artifact_annotation(
    annotation_id: int,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    item = await require_owned_annotation(db, current.learner.id, annotation_id)
    checkpoint_id, artifact_type = item.checkpoint_id, item.artifact_type
    await db.delete(item)
    await db.commit()
    if artifact_type == "lecture":
        from app.services.progress import update_notes_count
        count = len(list((await db.execute(select(ArtifactAnnotation).where(
            ArtifactAnnotation.checkpoint_id == checkpoint_id,
            ArtifactAnnotation.artifact_type == "lecture",
        ))).scalars().all()))
        await update_notes_count(checkpoint_id, count)
    return {"status": "ok"}


# Legacy lecture-note routes remain as thin compatibility adapters for one release.

@router.get("/checkpoints/{checkpoint_id}/notes")
async def list_notes(
    checkpoint_id: int,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    await require_owned_checkpoint(db, current.learner.id, checkpoint_id)
    lecture = (await db.execute(select(Lecture).where(
        Lecture.checkpoint_id == checkpoint_id,
    ))).scalar_one_or_none()
    if not lecture:
        return []
    return await list_artifact_annotations("lecture", lecture.id, db, current)


@router.post("/checkpoints/{checkpoint_id}/notes")
async def create_note(
    checkpoint_id: int,
    data: dict,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    await require_owned_checkpoint(db, current.learner.id, checkpoint_id)
    lecture = (await db.execute(select(Lecture).where(
        Lecture.checkpoint_id == checkpoint_id,
    ))).scalar_one_or_none()
    if not lecture:
        raise HTTPException(409, "讲义尚未创建")
    return await create_artifact_annotation("lecture", lecture.id, {
        "anchor": {
            "section_index": int(data.get("section_index", 0) or 0),
            "selection": str(data.get("selection") or "")[:2000],
        },
        "body": data.get("note", ""),
        "idempotency_key": data.get("idempotency_key"),
    }, db, current)


@router.put("/notes/{note_id}")
async def update_note(
    note_id: int,
    data: dict,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    return await update_artifact_annotation(note_id, data, db, current)


@router.delete("/notes/{note_id}")
async def delete_note(
    note_id: int,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    return await delete_artifact_annotation(note_id, db, current)
