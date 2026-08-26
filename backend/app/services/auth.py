from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.database import get_db
from app.models.learning import AuthSession, Learner, LearnerProfile, UserAccount
from app.models.project import (
    ArtifactAnnotation, Checkpoint, Exercise, LectureNote, ProcessAnimation, Project, Roadmap,
    Source, Task,
)


@dataclass(frozen=True)
class CurrentLearner:
    account: UserAccount
    learner: Learner
    profile: LearnerProfile
    is_dev_login: bool = False


def normalize_username(username: str) -> str:
    return username.strip().casefold()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return "scrypt$16384$8$1$" + base64.urlsafe_b64encode(salt).decode() + "$" + base64.urlsafe_b64encode(digest).decode()


def verify_password(password: str, encoded: str | None) -> bool:
    if not encoded:
        return False
    try:
        algorithm, n, r, p, salt_text, digest_text = encoded.split("$", 5)
        if algorithm != "scrypt":
            return False
        salt = base64.urlsafe_b64decode(salt_text.encode())
        expected = base64.urlsafe_b64decode(digest_text.encode())
        actual = hashlib.scrypt(
            password.encode("utf-8"), salt=salt, n=int(n), r=int(r), p=int(p), dklen=len(expected),
        )
        return hmac.compare_digest(actual, expected)
    except (TypeError, ValueError):
        return False


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def create_auth_session(
    db: AsyncSession, account: UserAccount, *, is_dev_login: bool = False,
) -> str:
    token = secrets.token_urlsafe(32)
    now = datetime.utcnow()
    db.add(AuthSession(
        user_id=account.id,
        token_hash=_token_hash(token),
        is_dev_login=is_dev_login,
        expires_at=now + timedelta(days=settings.auth_session_days),
        last_seen_at=now,
    ))
    account.last_login_at = now
    await db.flush()
    return token


def set_auth_cookie(response: Response, token: str):
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=token,
        max_age=settings.auth_session_days * 24 * 60 * 60,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="lax",
        path="/",
    )


def clear_auth_cookie(response: Response):
    response.delete_cookie(settings.auth_cookie_name, path="/")


async def current_learner_from_request(
    request: Request,
    db: AsyncSession,
    *,
    required: bool = True,
) -> CurrentLearner | None:
    raw_token = request.cookies.get(settings.auth_cookie_name)
    authorization = request.headers.get("authorization", "")
    if not raw_token and authorization.lower().startswith("bearer ") and valid_desktop_request(request):
        raw_token = authorization[7:].strip()
    if not raw_token:
        if required:
            raise HTTPException(401, "请先登录")
        return None
    now = datetime.utcnow()
    row = (await db.execute(
        select(AuthSession, UserAccount, Learner, LearnerProfile)
        .join(UserAccount, UserAccount.id == AuthSession.user_id)
        .join(Learner, Learner.user_id == UserAccount.id)
        .join(LearnerProfile, LearnerProfile.learner_id == Learner.id)
        .where(
            AuthSession.token_hash == _token_hash(raw_token),
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > now,
            UserAccount.status == "active",
        )
    )).first()
    if not row:
        if required:
            raise HTTPException(401, "登录已失效")
        return None
    session, account, learner, profile = row
    # Authentication is a read dependency. Mutating last_seen_at here causes
    # SQLAlchemy to autoflush before the endpoint's next query and can hold a
    # SQLite write lock during long external workflow calls. Session validity
    # is determined by expires_at/revoked_at, so keep request authentication
    # read-only and leave last_seen_at as the session creation/login timestamp.
    return CurrentLearner(
        account=account, learner=learner, profile=profile,
        is_dev_login=bool(session.is_dev_login),
    )


def valid_desktop_request(request: Request) -> bool:
    supplied = request.headers.get("x-learnflow-desktop-token", "")
    return bool(
        settings.desktop_mode
        and settings.desktop_token
        and supplied
        and hmac.compare_digest(supplied, settings.desktop_token)
    )


def auth_token_from_request(request: Request) -> str | None:
    raw = request.cookies.get(settings.auth_cookie_name)
    if raw:
        return raw
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer ") and valid_desktop_request(request):
        token = authorization[7:].strip()
        return token or None
    return None


async def get_current_learner(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> CurrentLearner:
    return await current_learner_from_request(request, db, required=True)


async def load_current_learner(db: AsyncSession, learner_id: int) -> CurrentLearner:
    row = (await db.execute(
        select(UserAccount, Learner, LearnerProfile)
        .join(Learner, Learner.user_id == UserAccount.id)
        .join(LearnerProfile, LearnerProfile.learner_id == Learner.id)
        .where(Learner.id == learner_id, UserAccount.status == "active")
    )).first()
    if not row:
        raise HTTPException(404, "Learner not found")
    return CurrentLearner(account=row[0], learner=row[1], profile=row[2])


async def require_owned_project(db: AsyncSession, learner_id: int, project_id: int) -> Project:
    project = (await db.execute(select(Project).where(
        Project.id == project_id, Project.learner_id == learner_id,
    ))).scalar_one_or_none()
    if not project:
        raise HTTPException(404, "Project not found")
    return project


async def require_owned_checkpoint(db: AsyncSession, learner_id: int, checkpoint_id: int) -> Checkpoint:
    checkpoint = (await db.execute(
        select(Checkpoint)
        .join(Roadmap, Roadmap.id == Checkpoint.roadmap_id)
        .join(Project, Project.id == Roadmap.project_id)
        .where(Checkpoint.id == checkpoint_id, Project.learner_id == learner_id)
    )).scalar_one_or_none()
    if not checkpoint:
        raise HTTPException(404, "Checkpoint not found")
    return checkpoint


async def require_owned_task(db: AsyncSession, learner_id: int, task_id: int) -> Task:
    task = (await db.execute(select(Task).where(
        Task.id == task_id, Task.learner_id == learner_id,
    ))).scalar_one_or_none()
    if not task:
        raise HTTPException(404, "Task not found")
    return task


async def require_owned_source(
    db: AsyncSession, learner_id: int, source_id: int,
    project_id: int | None = None,
) -> Source:
    query = select(Source).join(Project, Project.id == Source.project_id).where(
        Source.id == source_id,
        Project.learner_id == learner_id,
    )
    if project_id is not None:
        query = query.where(Source.project_id == project_id)
    source = (await db.execute(query)).scalar_one_or_none()
    if not source:
        raise HTTPException(404, "Source not found")
    return source


async def require_owned_exercise(db: AsyncSession, learner_id: int, exercise_id: int) -> Exercise:
    exercise = (await db.execute(
        select(Exercise)
        .join(Checkpoint, Checkpoint.id == Exercise.checkpoint_id)
        .join(Roadmap, Roadmap.id == Checkpoint.roadmap_id)
        .join(Project, Project.id == Roadmap.project_id)
        .where(Exercise.id == exercise_id, Project.learner_id == learner_id)
    )).scalar_one_or_none()
    if not exercise:
        raise HTTPException(404, "Exercise not found")
    return exercise


async def require_owned_note(db: AsyncSession, learner_id: int, note_id: int) -> LectureNote:
    note = (await db.execute(
        select(LectureNote)
        .join(Checkpoint, Checkpoint.id == LectureNote.checkpoint_id)
        .join(Roadmap, Roadmap.id == Checkpoint.roadmap_id)
        .join(Project, Project.id == Roadmap.project_id)
        .where(LectureNote.id == note_id, Project.learner_id == learner_id)
    )).scalar_one_or_none()
    if not note:
        raise HTTPException(404, "Note not found")
    return note


async def require_owned_annotation(
    db: AsyncSession, learner_id: int, annotation_id: int,
) -> ArtifactAnnotation:
    annotation = (await db.execute(select(ArtifactAnnotation).where(
        ArtifactAnnotation.id == annotation_id,
        ArtifactAnnotation.learner_id == learner_id,
    ))).scalar_one_or_none()
    if not annotation:
        raise HTTPException(404, "Annotation not found")
    return annotation


async def require_owned_animation(
    db: AsyncSession, learner_id: int, animation_id: int,
) -> ProcessAnimation:
    animation = await db.get(ProcessAnimation, animation_id)
    try:
        if animation and animation.project_id:
            await require_owned_project(db, learner_id, animation.project_id)
            return animation
        if animation and animation.checkpoint_id:
            await require_owned_checkpoint(db, learner_id, animation.checkpoint_id)
            return animation
    except HTTPException:
        pass
    raise HTTPException(404, "Animation not found")
