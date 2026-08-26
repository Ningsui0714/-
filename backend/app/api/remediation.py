from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models.learning import RemediationCase
from app.services.auth import CurrentLearner, get_current_learner, require_owned_checkpoint
from app.services.remediation import (
    ensure_variant,
    load_owned_case,
    request_explanation_mode,
    serialize_case,
    submit_variant,
)


router = APIRouter(tags=["Remediation"])


async def _require_case(
    db: AsyncSession, learner_id: int, case_id: int,
) -> RemediationCase:
    remediation = await load_owned_case(db, learner_id, case_id)
    if not remediation:
        raise HTTPException(404, "Remediation case not found")
    return remediation


@router.get("/remediation/{case_id}")
async def get_remediation_case(
    case_id: int,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    return serialize_case(await _require_case(db, current.learner.id, case_id))


@router.get("/checkpoints/{checkpoint_id}/remediation-cases")
async def list_remediation_cases(
    checkpoint_id: int,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    await require_owned_checkpoint(db, current.learner.id, checkpoint_id)
    rows = (await db.execute(select(RemediationCase).where(
        RemediationCase.learner_id == current.learner.id,
        RemediationCase.checkpoint_id == checkpoint_id,
    ).order_by(RemediationCase.created_at.desc()))).scalars().all()
    return [serialize_case(item) for item in rows]


@router.post("/remediation/{case_id}/explanations")
async def change_remediation_explanation(
    case_id: int,
    data: dict = Body(default={}),
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    action = str((data or {}).get("action") or "switch")
    if action not in {"switch", "steps", "example"}:
        raise HTTPException(400, "action must be switch, steps, or example")
    remediation = await _require_case(db, current.learner.id, case_id)
    if remediation.status == "completed":
        raise HTTPException(409, "纠错案例已经完成")
    await request_explanation_mode(db, remediation=remediation, action=action)
    await db.commit()
    return serialize_case(remediation)


@router.post("/remediation/{case_id}/variant")
async def create_remediation_variant(
    case_id: int,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    remediation = await _require_case(db, current.learner.id, case_id)
    if remediation.status != "variant_ready":
        raise HTTPException(409, "必须先通过原题重做，才能进入变式验证")
    await ensure_variant(remediation)
    await db.commit()
    return serialize_case(remediation)


@router.post("/remediation/{case_id}/variant/submit")
async def evaluate_remediation_variant(
    case_id: int,
    data: dict = Body(default={}),
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    remediation = await _require_case(db, current.learner.id, case_id)
    if remediation.status != "variant_ready":
        raise HTTPException(409, "必须先通过原题重做，才能提交变式验证")
    remediation, result = await submit_variant(
        db, remediation=remediation, submission=dict(data or {}),
    )
    await db.commit()
    return {"result": result, "remediation": serialize_case(remediation)}
