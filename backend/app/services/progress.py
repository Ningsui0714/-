"""
Learning progress tracking (T10).

Checkpoint.progress JSON:
{
  "lecture_generated": bool,
  "exercises_done": int,          # distinct exercises passed all test cases
  "concept_total": int,           # distinct concept questions submitted
  "concept_correct": int,         # distinct concept questions answered right
  "notes_count": int,
  "solved_exercise_ids": [...],
  "submitted_question_ids": [...],
  "correct_question_ids": [...],
}
All updates are copy-on-read (SQLAlchemy JSON columns compare by == at flush).
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import async_session
from app.models.project import Checkpoint


async def get_progress(checkpoint_id: int) -> dict:
    async with async_session() as db:
        cp = (await db.execute(
            select(Checkpoint).where(Checkpoint.id == checkpoint_id)
        )).scalar_one_or_none()
        return dict(cp.progress or {}) if cp else {}


async def _apply_update(db: AsyncSession, checkpoint_id: int, mutate) -> None:
    cp = (await db.execute(
        select(Checkpoint).where(Checkpoint.id == checkpoint_id)
    )).scalar_one_or_none()
    if not cp:
        return
    p = dict(cp.progress or {})
    mutate(p)
    cp.progress = p


async def _update(checkpoint_id: int, mutate, db: AsyncSession | None = None):
    """Update progress in the caller transaction when one is available.

    API handlers already own a transaction. Reusing it keeps the progress write
    atomic with its learning attempt and avoids a second SQLite writer lock.
    Background callers may omit ``db`` and retain the original self-committing
    behavior.
    """
    if db is not None:
        await _apply_update(db, checkpoint_id, mutate)
        return

    async with async_session() as owned_db:
        await _apply_update(owned_db, checkpoint_id, mutate)
        await owned_db.commit()


async def mark_lecture_generated(checkpoint_id: int):
    await _update(checkpoint_id, lambda p: p.update({"lecture_generated": True}))


async def record_exercise_solved(
    checkpoint_id: int,
    exercise_id: int,
    db: AsyncSession | None = None,
):
    def m(p):
        ids = set(p.get("solved_exercise_ids") or [])
        ids.add(exercise_id)
        p["solved_exercise_ids"] = sorted(ids)
        p["exercises_done"] = len(ids)
    await _update(checkpoint_id, m, db=db)


async def record_concept_answer(
    checkpoint_id: int,
    question_id: int,
    correct: bool,
    db: AsyncSession | None = None,
):
    def m(p):
        submitted = set(p.get("submitted_question_ids") or [])
        correct_ids = set(p.get("correct_question_ids") or [])
        submitted.add(question_id)
        if correct:
            correct_ids.add(question_id)
        else:
            correct_ids.discard(question_id)
        p["submitted_question_ids"] = sorted(submitted)
        p["correct_question_ids"] = sorted(correct_ids)
        p["concept_total"] = len(submitted)
        p["concept_correct"] = len(correct_ids)
    await _update(checkpoint_id, m, db=db)


async def update_notes_count(checkpoint_id: int, count: int):
    await _update(checkpoint_id, lambda p: p.update({"notes_count": count}))
