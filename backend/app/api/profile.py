from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models.learning import LearnerBadge, LearnerProfile, LearningLifeEvent
from app.models.project import Project
from app.schemas.auth import MemoryArchiveRequest, ProfileUpdateRequest
from app.services.auth import CurrentLearner, get_current_learner
from app.services.learning_runtime import record_event
from app.services.profile import (
    award_career_goal, badge_view, life_event_view, memory_projection, set_memory_archive,
)


router = APIRouter(prefix="/profile", tags=["Learner Profile"])


def _profile_fields(current: CurrentLearner) -> dict:
    profile = current.profile
    return {
        "username": current.account.username,
        "display_name": current.learner.display_name,
        "education_stage": profile.education_stage,
        "background": profile.background,
        "focus_areas": profile.focus_areas or [],
        "weekly_hours": profile.weekly_hours,
        "preferred_modes": profile.preferred_modes or [],
        "career_goal": profile.career_goal or "",
        "career_goal_status": profile.career_goal_status,
    }


@router.get("")
async def get_profile(
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    project_count = await db.scalar(select(func.count(Project.id)).where(
        Project.learner_id == current.learner.id,
    ))
    badge_count = await db.scalar(select(func.count(LearnerBadge.id)).where(
        LearnerBadge.learner_id == current.learner.id,
    ))
    return {
        "profile": _profile_fields(current),
        "stats": {"projects": project_count or 0, "badges": badge_count or 0},
    }


@router.patch("")
async def update_profile(
    data: ProfileUpdateRequest,
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    patch = data.model_dump(exclude_unset=True)
    if "display_name" in patch:
        current.learner.display_name = patch.pop("display_name").strip()
    for field, value in patch.items():
        setattr(current.profile, field, value.strip() if isinstance(value, str) else value)
    if current.profile.career_goal_status == "confirmed" and not current.profile.career_goal.strip():
        raise HTTPException(400, "确认职业理想前需要填写目标")
    evidence = await record_event(
        db,
        learner_id=current.learner.id,
        event_type="profile_updated",
        source="profile",
        payload=patch,
        confidence=1.0,
        provenance={"self_report": True},
        client_event_id=f"profile-update:{int(datetime.utcnow().timestamp() * 1000)}",
    )
    if "career_goal" in patch or "career_goal_status" in patch:
        if current.profile.career_goal_status == "confirmed":
            career_event = await record_event(
                db,
                learner_id=current.learner.id,
                event_type="career_goal_confirmed",
                source="profile",
                payload={"career_goal": current.profile.career_goal.strip()},
                confidence=1.0,
                provenance={"explicit_profile_confirmation": True},
                client_event_id=f"career-goal:{current.profile.career_goal.strip().casefold()}",
            )
            await award_career_goal(
                db,
                learner_id=current.learner.id,
                career_goal=current.profile.career_goal,
                confidence=1.0,
                source_event_id=career_event.id,
            )
    await db.commit()
    return {"profile": _profile_fields(current), "evidence_id": evidence.id}


@router.get("/memories")
async def get_memories(
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    return {"dimensions": await memory_projection(db, current.learner.id)}


@router.post("/memories/{memory_id}/archive")
async def archive_memory(
    memory_id: str,
    data: MemoryArchiveRequest,
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    try:
        archive = await set_memory_archive(
            db, learner_id=current.learner.id, memory_id=memory_id,
            archived=True, reason=data.reason,
        )
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    await db.commit()
    return {"memory_id": memory_id, "status": archive.status}


@router.post("/memories/{memory_id}/restore")
async def restore_memory(
    memory_id: str,
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    try:
        archive = await set_memory_archive(
            db, learner_id=current.learner.id, memory_id=memory_id, archived=False,
        )
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    await db.commit()
    return {"memory_id": memory_id, "status": archive.status}


@router.get("/journey")
async def get_journey(
    limit: int = 50,
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    events = (await db.execute(select(LearningLifeEvent).where(
        LearningLifeEvent.learner_id == current.learner.id,
    ).order_by(LearningLifeEvent.occurred_at.desc()).limit(min(max(limit, 1), 100)))).scalars().all()
    badges = (await db.execute(select(LearnerBadge).where(
        LearnerBadge.learner_id == current.learner.id,
    ))).scalars().all()
    badge_by_event = {badge.life_event_id: badge for badge in badges}
    return {
        "events": [life_event_view(event, badge_by_event.get(event.id)) for event in events],
        "badges": [badge_view(badge) for badge in sorted(badges, key=lambda item: item.awarded_at, reverse=True)],
    }
