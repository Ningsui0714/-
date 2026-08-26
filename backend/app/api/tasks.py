"""
Task API: status query, SSE event stream, cancel.

SSE protocol: server always sends full snapshots; the first event on connect
is the current state (so reconnecting clients recover instantly). The stream
closes after a terminal snapshot.
"""
import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import async_session, get_db
from app.models.project import Task, Lecture
from app.services.task_manager import manager, TERMINAL_STATUSES
from app.services.auth import CurrentLearner, get_current_learner, require_owned_task

router = APIRouter()


def _snapshot(task: Task, sections=None) -> dict:
    data = {
        "type": "snapshot",
        "task_id": task.id,
        "type_name": task.type,
        "status": task.status,
        "progress": task.progress or {},
        "result": task.result or {},
        "error": task.error or {},
    }
    if sections is not None:
        data["sections"] = sections
    return data


@router.get("/tasks/{task_id}")
async def get_task_status(
    task_id: int,
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    task = await require_owned_task(db, current.learner.id, task_id)
    return _snapshot(task)


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(
    task_id: int,
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    task = await require_owned_task(db, current.learner.id, task_id)
    if not manager.cancel(task_id):
        # Not running locally: maybe already finished — reflect DB state
        from app.services.task_manager import get_task
        if task.status in TERMINAL_STATUSES:
            return {"status": task.status, "already_terminal": True}
        # Running in a different process / stale: mark canceled in DB
        from app.services.task_manager import update_task
        from datetime import datetime
        await update_task(task_id, status="canceled", finished_at=datetime.utcnow())
        return {"status": "canceled", "forced": True}
    return {"status": "canceled"}


@router.get("/tasks/{task_id}/events")
async def task_events(
    task_id: int,
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    """SSE stream of task snapshots (polling DB every 1s, diff-based)."""
    # ``expire_all`` below intentionally refreshes task state on every poll.
    # Keep the ownership scope as a scalar before that happens: accessing an
    # expired async ORM relationship from the stream otherwise raises
    # MissingGreenlet before it can emit the first snapshot.
    learner_id = current.learner.id
    task = await require_owned_task(db, learner_id, task_id)
    # FastAPI keeps dependency-scoped sessions alive until a StreamingResponse
    # finishes.  Releasing the ownership-check transaction here is essential
    # for SQLite: otherwise this long-lived reader can block background task
    # progress writes for the entire lifetime of the SSE connection.
    await db.rollback()

    async def event_stream():
        last_payload = None
        try:
            while True:
                # Use a short session per poll and close it before yielding or
                # sleeping.  A session spanning the whole stream keeps a read
                # transaction open and starves task-runner writes in SQLite.
                async with async_session() as stream_db:
                    t = (await stream_db.execute(select(Task).where(
                        Task.id == task_id, Task.learner_id == learner_id,
                    ))).scalar_one_or_none()
                    if t is None:
                        payload = json.dumps(
                            {"type": "error", "message": "任务不存在"},
                            ensure_ascii=False,
                        )
                        terminal = True
                    else:
                        # For lecture tasks include accumulated sections
                        # (partial content).
                        sections = None
                        if t.type == "lecture_generate" and t.checkpoint_id:
                            lecture = (await stream_db.execute(
                                select(Lecture).where(Lecture.checkpoint_id == t.checkpoint_id)
                            )).scalar_one_or_none()
                            if lecture and lecture.sections:
                                sections = [s for s in lecture.sections if s]

                        payload = json.dumps(
                            _snapshot(t, sections), ensure_ascii=False, sort_keys=True,
                        )
                        terminal = t.status in TERMINAL_STATUSES

                if payload != last_payload:
                    yield f"data: {payload}\n\n"
                    last_payload = payload

                if terminal:
                    break
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            raise

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
