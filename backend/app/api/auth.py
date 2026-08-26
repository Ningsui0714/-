from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.database import get_db
from app.models.learning import AuthSession, Learner, LearnerProfile, UserAccount
from app.models.project import Project
from app.schemas.auth import LoginRequest, RegisterRequest
from app.services.auth import (
    CurrentLearner, auth_token_from_request, clear_auth_cookie, create_auth_session,
    get_current_learner, hash_password, normalize_username, set_auth_cookie,
    valid_desktop_request, verify_password,
)
from app.services.learning_runtime import ensure_kernel_states, record_event
from app.services.profile import award_career_goal
from app.services.demo_seed import DEMO_USERNAME, demo_manifest


router = APIRouter(tags=["Authentication"])
dev_router = APIRouter(prefix="/dev", tags=["Development"])


def _account_view(current: CurrentLearner, desktop_auth_token: str | None = None) -> dict:
    result = {
        "id": current.account.id,
        "username": current.account.username,
        "display_name": current.learner.display_name,
        "learner_id": current.learner.id,
        "is_legacy_demo": bool(current.account.is_legacy_demo),
        "profile": {
            "education_stage": current.profile.education_stage,
            "background": current.profile.background,
            "focus_areas": current.profile.focus_areas or [],
            "weekly_hours": current.profile.weekly_hours,
            "preferred_modes": current.profile.preferred_modes or [],
            "career_goal": current.profile.career_goal or "",
            "career_goal_status": current.profile.career_goal_status,
        },
        "dev_test_login_enabled": settings.dev_test_login_enabled,
        "is_dev_login": current.is_dev_login,
    }
    if desktop_auth_token:
        result["desktop_auth_token"] = desktop_auth_token
    return result


@router.post("/auth/register")
async def register(
    data: RegisterRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    normalized = normalize_username(data.username)
    existing = (await db.execute(
        select(UserAccount.id).where(UserAccount.username_normalized == normalized)
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(409, "用户名已存在")
    account = UserAccount(
        username=data.username.strip(),
        username_normalized=normalized,
        password_hash=hash_password(data.password),
    )
    db.add(account)
    await db.flush()
    learner = Learner(
        user_id=account.id,
        key=f"user-{account.id}",
        display_name=data.display_name.strip(),
    )
    db.add(learner)
    await db.flush()
    profile = LearnerProfile(
        learner_id=learner.id,
        education_stage=data.education_stage,
        background=data.background.strip(),
        focus_areas=data.focus_areas,
        weekly_hours=data.weekly_hours,
        preferred_modes=data.preferred_modes,
        career_goal=data.career_goal.strip(),
        career_goal_status=data.career_goal_status,
    )
    db.add(profile)
    await ensure_kernel_states(db, learner.id)
    registration_event = await record_event(
        db,
        learner_id=learner.id,
        event_type="registration_profile_completed",
        source="registration",
        payload={
            "education_stage": profile.education_stage,
            "background": profile.background,
            "focus_areas": profile.focus_areas,
            "weekly_hours": profile.weekly_hours,
            "preferred_modes": profile.preferred_modes,
            "career_goal": profile.career_goal,
            "career_goal_status": profile.career_goal_status,
        },
        confidence=1.0,
        provenance={"self_report": True},
        client_event_id="registration-profile",
    )
    if profile.career_goal and profile.career_goal_status == "confirmed":
        await award_career_goal(
            db,
            learner_id=learner.id,
            career_goal=profile.career_goal,
            confidence=1.0,
            source_event_id=registration_event.id,
        )
    token = await create_auth_session(db, account)
    await db.commit()
    set_auth_cookie(response, token)
    return _account_view(
        CurrentLearner(account, learner, profile),
        token if valid_desktop_request(request) else None,
    )


@router.post("/auth/login")
async def login(
    data: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    account = (await db.execute(select(UserAccount).where(
        UserAccount.username_normalized == normalize_username(data.username),
        UserAccount.status == "active",
    ))).scalar_one_or_none()
    if not account or not verify_password(data.password, account.password_hash):
        raise HTTPException(401, "用户名或密码错误")
    learner = (await db.execute(select(Learner).where(Learner.user_id == account.id))).scalar_one()
    profile = await db.get(LearnerProfile, learner.id)
    token = await create_auth_session(db, account)
    await db.commit()
    set_auth_cookie(response, token)
    return _account_view(
        CurrentLearner(account, learner, profile),
        token if valid_desktop_request(request) else None,
    )


@router.post("/auth/logout")
async def logout(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    raw = auth_token_from_request(request)
    if raw:
        from app.services.auth import _token_hash
        session = (await db.execute(select(AuthSession).where(
            AuthSession.token_hash == _token_hash(raw), AuthSession.revoked_at.is_(None),
        ))).scalar_one_or_none()
        if session:
            session.revoked_at = datetime.utcnow()
            await db.commit()
    clear_auth_cookie(response)
    return {"status": "ok"}


@router.get("/auth/me")
async def me(current: CurrentLearner = Depends(get_current_learner)):
    return _account_view(current)


@router.get("/demo/status")
async def competition_demo_status():
    return {"enabled": settings.competition_demo_mode, "offline": True}


@router.post("/demo/login")
async def competition_demo_login(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    if not settings.competition_demo_mode:
        raise HTTPException(404, "Not found")
    account = (await db.execute(select(UserAccount).where(
        UserAccount.username_normalized == DEMO_USERNAME,
        UserAccount.status == "active",
    ))).scalar_one_or_none()
    if not account:
        raise HTTPException(503, "演示数据尚未初始化，请重新运行 bash start.sh demo")
    learner = (await db.execute(select(Learner).where(
        Learner.user_id == account.id,
    ))).scalar_one()
    profile = await db.get(LearnerProfile, learner.id)
    token = await create_auth_session(db, account, is_dev_login=True)
    await db.commit()
    set_auth_cookie(response, token)
    return _account_view(
        CurrentLearner(account, learner, profile, is_dev_login=True),
        token if valid_desktop_request(request) else None,
    )


@router.get("/demo/manifest")
async def competition_demo_manifest(
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    if not settings.competition_demo_mode:
        raise HTTPException(404, "Not found")
    manifest = await demo_manifest(db, current.learner.id)
    if not manifest:
        raise HTTPException(503, "演示数据尚未初始化")
    return manifest


def _require_dev():
    if not settings.dev_test_login_enabled:
        raise HTTPException(404, "Not found")


@dev_router.get("/accounts")
async def list_dev_accounts(db: AsyncSession = Depends(get_db)):
    _require_dev()
    rows = (await db.execute(
        select(UserAccount, Learner, func.count(Project.id))
        .join(Learner, Learner.user_id == UserAccount.id)
        .outerjoin(Project, Project.learner_id == Learner.id)
        .group_by(UserAccount.id, Learner.id)
        .order_by(UserAccount.created_at.asc())
    )).all()
    return [{
        "id": account.id,
        "username": account.username,
        "display_name": learner.display_name,
        "created_at": account.created_at.isoformat() if account.created_at else None,
        "last_login_at": account.last_login_at.isoformat() if account.last_login_at else None,
        "project_count": project_count or 0,
        "is_legacy_demo": bool(account.is_legacy_demo),
    } for account, learner, project_count in rows]


@dev_router.post("/accounts/{account_id}/login")
async def dev_login(
    account_id: int,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    _require_dev()
    account = await db.get(UserAccount, account_id)
    if not account or account.status != "active":
        raise HTTPException(404, "Account not found")
    learner = (await db.execute(select(Learner).where(Learner.user_id == account.id))).scalar_one_or_none()
    profile = await db.get(LearnerProfile, learner.id) if learner else None
    if not learner or not profile:
        raise HTTPException(404, "Account not found")
    token = await create_auth_session(db, account, is_dev_login=True)
    await db.commit()
    set_auth_cookie(response, token)
    return _account_view(
        CurrentLearner(account, learner, profile, is_dev_login=True),
        token if valid_desktop_request(request) else None,
    )
