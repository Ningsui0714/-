from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models.learning import (
    AgentSession, AgentMessage, AgentAction, LearningProjectProposal,
)
from app.models.project import Project, Roadmap, Checkpoint, Task
from app.schemas.agent import (
    AgentSessionCreate, TutorTurnRequest, LearningEventRequest,
    ProjectProposalUpdateRequest, ProjectProposalAcceptRequest,
)
from app.services.learning_runtime import (
    PUBLIC_EVENT_TYPES, record_event, get_state_summary, evaluate_checkpoint_status,
)
from app.services.tutor_service import (
    get_or_create_session, get_messages, process_turn, execute_action,
    action_card, action_result, finalize_action_for_task,
    proposal_acceptance_action, finalize_proposal_acceptance,
    get_session_state_summary, _is_confirmation,
)
from app.services.project_proposals import (
    list_session_proposals, proposal_view, set_proposal_status,
    start_resource_search, update_project_proposal,
)
from app.services.auth import (
    CurrentLearner, get_current_learner, require_owned_project,
    require_owned_checkpoint, valid_desktop_request,
)


router = APIRouter(prefix="/agent", tags=["Tutor"])
events_router = APIRouter(tags=["Learning Evidence"])


def _message_out(message: AgentMessage) -> dict:
    return {
        "id": message.id,
        "role": message.role,
        "content": message.content,
        "meta_data": message.meta_data or {},
        "created_at": message.created_at.isoformat() if message.created_at else None,
    }


async def _owned_session(
    db: AsyncSession, learner_id: int, session_id: int,
) -> AgentSession:
    session = (await db.execute(select(AgentSession).where(
        AgentSession.id == session_id,
        AgentSession.learner_id == learner_id,
    ))).scalar_one_or_none()
    if not session:
        raise HTTPException(404, "Tutor session not found")
    return session


async def _owned_proposal(
    db: AsyncSession, learner_id: int, proposal_id: int,
) -> LearningProjectProposal:
    proposal = (await db.execute(select(LearningProjectProposal).where(
        LearningProjectProposal.id == proposal_id,
        LearningProjectProposal.learner_id == learner_id,
    ))).scalar_one_or_none()
    if not proposal:
        raise HTTPException(404, "Project proposal not found")
    return proposal


async def _owned_action(
    db: AsyncSession, learner_id: int, action_id: int,
) -> AgentAction:
    action = (await db.execute(select(AgentAction).where(
        AgentAction.id == action_id,
        AgentAction.learner_id == learner_id,
    ))).scalar_one_or_none()
    if not action:
        raise HTTPException(404, "Action not found")
    return action


@router.post("/sessions")
async def create_or_resume_session(
    data: AgentSessionCreate,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    project_id = data.project_id
    session_type = data.session_type
    if project_id is not None:
        await require_owned_project(db, current.learner.id, project_id)
    if data.checkpoint_id is not None:
        checkpoint = await require_owned_checkpoint(db, current.learner.id, data.checkpoint_id)
        roadmap = await db.get(Roadmap, checkpoint.roadmap_id)
        if not roadmap:
            raise HTTPException(404, "Checkpoint roadmap not found")
        if project_id is not None and project_id != roadmap.project_id:
            raise HTTPException(400, "Checkpoint does not belong to project")
        project_id = roadmap.project_id
        session_type = "checkpoint"
    elif session_type == "checkpoint":
        raise HTTPException(400, "checkpoint session requires checkpoint_id")
    elif project_id is not None and session_type == "global":
        # Keep legacy global+project_id clients on exactly the same normalized
        # scope used by get_or_create_session, including force_new archival.
        session_type = "project"
    if data.force_new:
        scope_query = select(AgentSession).where(
            AgentSession.learner_id == current.learner.id,
            AgentSession.session_type == session_type,
            AgentSession.status == "active",
        )
        if session_type == "checkpoint":
            scope_query = scope_query.where(
                AgentSession.project_id == project_id,
                AgentSession.checkpoint_id == data.checkpoint_id,
            )
        elif session_type == "project":
            scope_query = scope_query.where(AgentSession.project_id == project_id)
        else:
            scope_query = scope_query.where(AgentSession.project_id.is_(None))
        active_sessions = (await db.execute(scope_query)).scalars().all()
        for active_session in active_sessions:
            active_session.status = "archived"
            active_session.pending_action_id = None
            active_session.updated_at = datetime.utcnow()
        await db.flush()
    session = await get_or_create_session(
        db,
        learner_id=current.learner.id,
        session_type=session_type,
        project_id=project_id,
        checkpoint_id=data.checkpoint_id,
    )
    await db.commit()
    messages = await get_messages(db, session.id)
    pending = await db.get(AgentAction, session.pending_action_id) if session.pending_action_id else None
    proposals = await list_session_proposals(db, session.id)
    return {
        "id": session.id,
        "session_type": session.session_type,
        "project_id": session.project_id,
        "checkpoint_id": session.checkpoint_id,
        "messages": [_message_out(m) for m in messages],
        "state_summary": await get_session_state_summary(db, session),
        "action_card": action_card(pending),
        "project_proposals": [proposal_view(item) for item in proposals],
    }


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    session = await _owned_session(db, current.learner.id, session_id)
    messages = await get_messages(db, session.id)
    pending = await db.get(AgentAction, session.pending_action_id) if session.pending_action_id else None
    proposals = await list_session_proposals(db, session.id)
    return {
        "id": session.id,
        "session_type": session.session_type,
        "project_id": session.project_id,
        "checkpoint_id": session.checkpoint_id,
        "messages": [_message_out(m) for m in messages],
        "state_summary": await get_session_state_summary(db, session),
        "action_card": action_card(pending),
        "project_proposals": [proposal_view(item) for item in proposals],
    }


@router.post("/sessions/{session_id}/turns")
async def tutor_turn(
    session_id: int,
    data: TutorTurnRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    session = await _owned_session(db, current.learner.id, session_id)
    pending = await db.get(AgentAction, session.pending_action_id) if session.pending_action_id else None
    if (
        pending and pending.capability == "delegate_local_agent_task"
        and (data.selected_action_id == pending.id or _is_confirmation(data.message))
        and not valid_desktop_request(request)
    ):
        raise HTTPException(404, "Local Agent Broker is unavailable")
    if session.session_type == "checkpoint":
        if data.project_id is not None and data.project_id != session.project_id:
            raise HTTPException(409, "Checkpoint Tutor project scope is immutable")
        if data.checkpoint_id is not None and data.checkpoint_id != session.checkpoint_id:
            raise HTTPException(409, "Checkpoint Tutor scope is immutable")
    if data.project_id is not None:
        await require_owned_project(db, current.learner.id, data.project_id)
    if data.checkpoint_id is not None:
        await require_owned_checkpoint(db, current.learner.id, data.checkpoint_id)
    return await process_turn(
        db, session,
        message=data.message,
        project_id=data.project_id,
        checkpoint_id=data.checkpoint_id,
        selected_action_id=data.selected_action_id,
        client_turn_id=data.client_turn_id,
        context=data.context,
    )


@router.get("/project-proposals/{proposal_id}")
async def get_project_proposal(
    proposal_id: int,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    proposal = await _owned_proposal(db, current.learner.id, proposal_id)
    return proposal_view(proposal)


@router.get("/projects/{project_id}/accepted-proposal")
async def get_accepted_project_proposal(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    await require_owned_project(db, current.learner.id, project_id)
    proposal = (await db.execute(
        select(LearningProjectProposal)
        .where(
            LearningProjectProposal.accepted_project_id == project_id,
            LearningProjectProposal.learner_id == current.learner.id,
            LearningProjectProposal.status == "accepted",
        )
        .order_by(LearningProjectProposal.updated_at.desc())
        .limit(1)
    )).scalar_one_or_none()
    return proposal_view(proposal) if proposal else None


@router.patch("/project-proposals/{proposal_id}")
async def patch_project_proposal(
    proposal_id: int,
    data: ProjectProposalUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    proposal = await _owned_proposal(db, current.learner.id, proposal_id)
    try:
        await update_project_proposal(
            db, proposal,
            patch=data.patch,
            lock_fields=data.lock_fields,
            unlock_fields=data.unlock_fields,
            client_event_id=data.client_event_id,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    await db.commit()
    return proposal_view(proposal)


@router.post("/project-proposals/{proposal_id}/accept")
async def accept_project_proposal(
    proposal_id: int,
    data: ProjectProposalAcceptRequest,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    proposal = await _owned_proposal(db, current.learner.id, proposal_id)
    if proposal.status not in {"draft", "ready", "accepted"}:
        raise HTTPException(400, "这个项目提案当前不能创建")
    was_accepted = proposal.status == "accepted"
    try:
        action = await proposal_acceptance_action(db, proposal)
        action.target = {**dict(action.target or {}), "accept_client_event_id": data.client_event_id}
        message = await execute_action(db, action)
        await finalize_proposal_acceptance(db, proposal, action)
    except Exception as exc:
        action = await db.get(AgentAction, proposal.accepted_action_id) if proposal.accepted_action_id else None
        if action:
            action.status = "failed"
            action.error = {"message": str(exc)[:500]}
            action.finished_at = datetime.utcnow()
        await db.commit()
        raise HTTPException(400, str(exc)) from exc
    if not was_accepted:
        db.add(AgentMessage(
            session_id=proposal.session_id,
            role="assistant",
            content=message,
            meta_data={"action_id": action.id, "proposal_id": proposal.id},
        ))
    await db.commit()
    session = await _owned_session(db, current.learner.id, proposal.session_id)
    proposals = await list_session_proposals(db, proposal.session_id)
    return {
        "session_id": proposal.session_id,
        "message": message,
        "executed_action": action_result(action),
        "action_card": None,
        "project_proposals": [proposal_view(item) for item in proposals],
        "proposal_update": proposal_view(proposal),
        "state_summary": await get_session_state_summary(db, session),
    }


@router.post("/project-proposals/{proposal_id}/dismiss")
async def dismiss_project_proposal(
    proposal_id: int,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    proposal = await _owned_proposal(db, current.learner.id, proposal_id)
    try:
        await set_proposal_status(db, proposal, "dismissed")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    await db.commit()
    return proposal_view(proposal)


@router.post("/project-proposals/{proposal_id}/reopen")
async def reopen_project_proposal(
    proposal_id: int,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    proposal = await _owned_proposal(db, current.learner.id, proposal_id)
    try:
        await set_proposal_status(db, proposal, "ready")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    await db.commit()
    return proposal_view(proposal)


@router.post("/project-proposals/{proposal_id}/refresh-sources")
async def refresh_project_proposal_sources(
    proposal_id: int,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    proposal = await _owned_proposal(db, current.learner.id, proposal_id)
    await start_resource_search(db, proposal, force=True)
    return proposal_view(proposal)


@router.get("/actions/{action_id}")
async def get_action(
    action_id: int,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    action = await _owned_action(db, current.learner.id, action_id)
    task = None
    if action.task_id:
        task = (await db.execute(select(Task).where(
            Task.id == action.task_id,
            Task.learner_id == current.learner.id,
        ))).scalar_one_or_none()
        if task and task.status in {"completed", "failed", "canceled"} and action.status == "running":
            await finalize_action_for_task(task)
            await db.refresh(action)
    result = action_result(action)
    if task:
        result["task"] = {
            "id": task.id,
            "status": task.status,
            "progress": task.progress or {},
            "error": task.error or {},
        }
    return result


@router.post("/actions/{action_id}/confirm")
async def confirm_action(
    action_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    action = await _owned_action(db, current.learner.id, action_id)
    if action.capability == "delegate_local_agent_task" and not valid_desktop_request(request):
        raise HTTPException(404, "Local Agent Broker is unavailable")
    if action.status not in {"pending_confirmation", "needs_input"}:
        return action_result(action)
    if action.status == "needs_input":
        raise HTTPException(400, "这个行动还缺少必要信息")
    action.status = "ready"
    try:
        message = await execute_action(db, action)
    except Exception as exc:
        action.status = "failed"
        action.error = {"message": str(exc)[:500]}
        action.finished_at = datetime.utcnow()
        await db.commit()
        raise HTTPException(400, str(exc))
    db.add(AgentMessage(
        session_id=action.session_id,
        role="assistant",
        content=message,
        meta_data={
            "action_id": action.id,
            "local_agent_run_id": (
                ((action.result or {}).get("local_agent_run") or {}).get("id")
            ),
        },
    ))
    await db.commit()
    session = await _owned_session(db, current.learner.id, action.session_id)
    return {
        "message": message,
        "executed_action": action_result(action),
        "state_summary": await get_session_state_summary(db, session),
    }


@router.post("/actions/{action_id}/cancel")
async def cancel_action(
    action_id: int,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    action = await _owned_action(db, current.learner.id, action_id)
    if action.status in {"completed", "failed", "canceled"}:
        return action_result(action)
    action.status = "canceled"
    action.finished_at = datetime.utcnow()
    session = await _owned_session(db, current.learner.id, action.session_id)
    if session and session.pending_action_id == action.id:
        session.pending_action_id = None
    if action.task_id:
        from app.services.task_manager import manager
        manager.cancel(action.task_id)
    await db.commit()
    return action_result(action)


@events_router.post("/learning-events")
async def create_learning_event(
    data: LearningEventRequest,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    if data.event_type not in PUBLIC_EVENT_TYPES:
        raise HTTPException(400, "Unsupported learning event type")
    if data.project_id is not None:
        await require_owned_project(db, current.learner.id, data.project_id)
    if data.checkpoint_id is not None:
        await require_owned_checkpoint(db, current.learner.id, data.checkpoint_id)
    if data.session_id is not None:
        await _owned_session(db, current.learner.id, data.session_id)
    event = await record_event(
        db,
        event_type=data.event_type,
        source="ui",
        learner_id=current.learner.id,
        project_id=data.project_id,
        checkpoint_id=data.checkpoint_id,
        session_id=data.session_id,
        payload=data.payload,
        confidence=0.8 if data.event_type in {"lecture_viewed", "learning_feedback"} else 1.0,
        provenance={"client": "frontend"},
        client_event_id=data.client_event_id,
    )
    if data.checkpoint_id:
        await evaluate_checkpoint_status(
            db, data.checkpoint_id, learner_id=current.learner.id,
        )
    await db.commit()
    return {"id": event.id, "state_summary": await get_state_summary(
        db, data.project_id, data.checkpoint_id,
        learner_id=current.learner.id,
    )}
