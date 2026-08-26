from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.database import get_db
from app.models.project import LocalAgentProfile, LocalAgentRun, LocalAgentRunEvent
from app.schemas.local_agent import (
    LocalAgentApplyRequest, LocalAgentProfileCreate, LocalAgentProfilePatch,
    LocalAgentProfileResponse, LocalAgentRunEventResponse, LocalAgentRunResponse,
)
from app.services.auth import CurrentLearner, get_current_learner
from app.services.local_agent_broker import (
    LocalAgentError, apply_run_result, cancel_run, ensure_seeded_profile, probe_profile,
)
from app.api.workspace import require_desktop_token


router = APIRouter(tags=["Local Agent Broker"])


def _raise_broker_error(exc: LocalAgentError):
    raise HTTPException(exc.status_code, {"code": exc.code, "message": exc.detail}) from exc


async def _owned_profile(
    db: AsyncSession, learner_id: int, profile_id: int,
) -> LocalAgentProfile:
    profile = (await db.execute(select(LocalAgentProfile).where(
        LocalAgentProfile.id == profile_id,
        LocalAgentProfile.learner_id == learner_id,
    ))).scalar_one_or_none()
    if not profile:
        raise HTTPException(404, "Local Agent profile not found")
    return profile


async def _owned_run(db: AsyncSession, learner_id: int, run_id: int) -> LocalAgentRun:
    run = (await db.execute(select(LocalAgentRun).where(
        LocalAgentRun.id == run_id,
        LocalAgentRun.learner_id == learner_id,
    ))).scalar_one_or_none()
    if not run:
        raise HTTPException(404, "Local Agent run not found")
    return run


@router.get(
    "/desktop/agent-profiles",
    response_model=list[LocalAgentProfileResponse],
    dependencies=[Depends(require_desktop_token)],
)
async def list_agent_profiles(
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    await ensure_seeded_profile(db, current.learner.id)
    profiles = list((await db.execute(select(LocalAgentProfile).where(
        LocalAgentProfile.learner_id == current.learner.id,
    ).order_by(LocalAgentProfile.priority.asc(), LocalAgentProfile.id.asc()))).scalars().all())
    await db.commit()
    return profiles


@router.post(
    "/desktop/agent-profiles",
    response_model=LocalAgentProfileResponse,
    dependencies=[Depends(require_desktop_token)],
)
async def create_agent_profile(
    data: LocalAgentProfileCreate,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    if data.adapter == "deterministic_fake" and not settings.competition_demo_mode:
        raise HTTPException(403, "确定性假 Agent 仅供 seeded demo 使用")
    profile = LocalAgentProfile(
        learner_id=current.learner.id, **data.model_dump(), last_probe={},
    )
    db.add(profile)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(409, "Agent 配置名称已存在") from exc
    profile.last_probe = await probe_profile(profile)
    await db.commit()
    await db.refresh(profile)
    return profile


@router.patch(
    "/desktop/agent-profiles/{profile_id}",
    response_model=LocalAgentProfileResponse,
    dependencies=[Depends(require_desktop_token)],
)
async def patch_agent_profile(
    profile_id: int,
    data: LocalAgentProfilePatch,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    profile = await _owned_profile(db, current.learner.id, profile_id)
    patch = data.model_dump(exclude_unset=True)
    patch = {
        key: value for key, value in patch.items()
        if value is not None or key == "executable_path"
    }
    network_policy = patch.get("network_policy", profile.network_policy)
    if profile.adapter == "codex_cli" and network_policy != "unmanaged":
        raise HTTPException(400, "Codex CLI 首版无法保证联网边界，必须标为 unmanaged")
    if profile.adapter == "deterministic_fake" and network_policy != "managed_off":
        raise HTTPException(400, "演示 Agent 必须保持 managed_off")
    if patch.get("task_types") is not None:
        patch["task_types"] = list(dict.fromkeys(patch["task_types"]))
    if patch.get("capabilities") is not None:
        patch["capabilities"] = list(dict.fromkeys(
            item.strip() for item in patch["capabilities"] if item.strip()
        ))
    for key, value in patch.items():
        setattr(profile, key, value)
    profile.updated_at = datetime.utcnow()
    profile.last_probe = await probe_profile(profile)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(409, "Agent 配置名称已存在") from exc
    await db.refresh(profile)
    return profile


@router.delete(
    "/desktop/agent-profiles/{profile_id}",
    dependencies=[Depends(require_desktop_token)],
)
async def delete_agent_profile(
    profile_id: int,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    profile = await _owned_profile(db, current.learner.id, profile_id)
    has_run = (await db.execute(select(LocalAgentRun.id).where(
        LocalAgentRun.profile_id == profile.id,
    ).limit(1))).scalar_one_or_none()
    if has_run:
        profile.enabled = False
        await db.commit()
        return {"status": "disabled", "id": profile.id}
    await db.delete(profile)
    await db.commit()
    return {"status": "deleted", "id": profile.id}


@router.get(
    "/local-agent/runs/{run_id}",
    response_model=LocalAgentRunResponse,
    dependencies=[Depends(require_desktop_token)],
)
async def get_local_agent_run(
    run_id: int,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    return await _owned_run(db, current.learner.id, run_id)


@router.get(
    "/local-agent/runs/{run_id}/events",
    response_model=list[LocalAgentRunEventResponse],
    dependencies=[Depends(require_desktop_token)],
)
async def get_local_agent_run_events(
    run_id: int,
    after: int = 0,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    run = await _owned_run(db, current.learner.id, run_id)
    return list((await db.execute(select(LocalAgentRunEvent).where(
        LocalAgentRunEvent.run_id == run.id,
        LocalAgentRunEvent.sequence > max(after, 0),
    ).order_by(LocalAgentRunEvent.sequence.asc()).limit(500))).scalars().all())


@router.post(
    "/local-agent/runs/{run_id}/cancel",
    response_model=LocalAgentRunResponse,
    dependencies=[Depends(require_desktop_token)],
)
async def cancel_local_agent_run(
    run_id: int,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    run = await _owned_run(db, current.learner.id, run_id)
    await cancel_run(db, run)
    return run


@router.post(
    "/local-agent/runs/{run_id}/apply",
    response_model=LocalAgentRunResponse,
    dependencies=[Depends(require_desktop_token)],
)
async def apply_local_agent_run(
    run_id: int,
    data: LocalAgentApplyRequest,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    if not data.confirm_apply:
        raise HTTPException(400, "第二次确认是应用修改的必要条件")
    run = await _owned_run(db, current.learner.id, run_id)
    try:
        return await apply_run_result(
            db, run, confirmed_deletions=data.confirmed_deletions,
            confirmed_moves=data.confirmed_moves, idempotency_key=data.idempotency_key,
        )
    except LocalAgentError as exc:
        _raise_broker_error(exc)
