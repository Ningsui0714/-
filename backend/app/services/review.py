"""Deterministic, rebuildable spaced-review scheduling.

ReviewSchedule is an operational projection.  It never writes KernelState and
never upgrades mastery by itself; graded review attempts still travel through
EvidenceEvent and the five-kernel reducer.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.learning import EvidenceEvent, LearningAttempt, RemediationCase, ReviewSchedule
from app.models.project import ConceptQuestion, Exercise


POLICY_VERSION = "review-policy-v1"
INTERVAL_DAYS = (1, 3, 7, 14, 30, 60)
ACTIVE_PHASE = "active"
REMEDIATION_PHASE = "remediation"
SUSPENDED_PHASE = "suspended"


def review_submission_key(
    learner_id: int, schedule_id: int, client_submission_id: str,
) -> str:
    raw = f"review:{learner_id}:{schedule_id}:{client_submission_id.strip()}"
    if len(raw) <= 160:
        return raw
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"review:{learner_id}:sha256:{digest}"


def interval_days(level: int) -> int:
    return INTERVAL_DAYS[max(0, min(int(level), len(INTERVAL_DAYS) - 1))]


def _passed(attempt: LearningAttempt) -> bool:
    result = dict(attempt.result or {})
    if "passed" in result and isinstance(result.get("passed"), bool):
        return bool(result.get("passed"))
    if attempt.item_type == "concept":
        return bool(result.get("correct"))
    if attempt.item_type == "exercise":
        total = int(result.get("total") or 0)
        return total > 0 and int(result.get("passed") or 0) == total
    return bool(result.get("correct") or result.get("passed"))


def _subject_key(meta: dict[str, Any], item_type: str, item_id: int) -> str:
    targets = meta.get("targets") or meta.get("concepts") or []
    if isinstance(targets, dict):
        targets = list(targets)
    if isinstance(targets, list) and targets:
        first = targets[0]
        if isinstance(first, dict):
            first = first.get("id") or first.get("key") or first.get("name")
        if str(first or "").strip():
            return f"concept:{str(first).strip()[:220]}"
    learning_target = str(meta.get("learning_target") or "").strip()
    if learning_target:
        return f"target:{learning_target[:220]}"
    return f"{item_type}:{item_id}"


async def _item_meta(
    db: AsyncSession, item_type: str, item_id: int,
) -> dict[str, Any]:
    if item_type == "concept":
        item = await db.get(ConceptQuestion, item_id)
    elif item_type == "exercise":
        item = await db.get(Exercise, item_id)
    else:
        item = None
    return dict(getattr(item, "assessment_meta", None) or {})


async def load_owned_schedule(
    db: AsyncSession, learner_id: int, schedule_id: int,
) -> ReviewSchedule | None:
    return (await db.execute(select(ReviewSchedule).where(
        ReviewSchedule.id == schedule_id,
        ReviewSchedule.learner_id == learner_id,
    ))).scalar_one_or_none()


async def get_or_create_schedule(
    db: AsyncSession,
    *,
    learner_id: int,
    project_id: int | None,
    checkpoint_id: int,
    item_type: str,
    item_id: int,
    now: datetime | None = None,
) -> ReviewSchedule:
    schedule = (await db.execute(select(ReviewSchedule).where(
        ReviewSchedule.learner_id == learner_id,
        ReviewSchedule.item_type == item_type,
        ReviewSchedule.item_id == item_id,
    ))).scalar_one_or_none()
    if schedule:
        return schedule
    meta = await _item_meta(db, item_type, item_id)
    schedule = ReviewSchedule(
        learner_id=learner_id,
        project_id=project_id,
        checkpoint_id=checkpoint_id,
        item_type=item_type,
        item_id=item_id,
        subject_key=_subject_key(meta, item_type, item_id),
        phase=ACTIVE_PHASE,
        due_at=now or datetime.utcnow(),
        interval_level=0,
        policy_version=POLICY_VERSION,
        version=1,
    )
    db.add(schedule)
    await db.flush()
    return schedule


async def apply_assessment_result(
    db: AsyncSession,
    *,
    attempt: LearningAttempt,
    passed: bool,
    event_id: int | None,
    question_form: str = "original",
    remediation_status: str | None = None,
    is_review: bool = False,
    now: datetime | None = None,
) -> ReviewSchedule:
    """Project one evaluated attempt into deterministic scheduling state."""
    current_time = now or attempt.evaluated_at or datetime.utcnow()
    schedule = await get_or_create_schedule(
        db,
        learner_id=attempt.learner_id,
        project_id=attempt.project_id,
        checkpoint_id=attempt.checkpoint_id,
        item_type=attempt.item_type,
        item_id=int(attempt.item_id),
        now=current_time,
    )
    if schedule.last_attempt_id == attempt.id:
        return schedule

    schedule.last_attempt_id = attempt.id
    schedule.last_event_id = event_id
    schedule.last_question_form = question_form
    schedule.updated_at = current_time
    schedule.policy_version = POLICY_VERSION
    schedule.suspended_at = None
    schedule.defer_count = 0

    if not passed:
        schedule.phase = REMEDIATION_PHASE
        schedule.interval_level = 0
        schedule.lapse_count = int(schedule.lapse_count or 0) + 1
        schedule.last_grade = "again"
        schedule.due_at = current_time
    elif remediation_status in {"explaining", "variant_ready"}:
        schedule.phase = REMEDIATION_PHASE
        schedule.last_grade = "retry"
        schedule.due_at = current_time
    else:
        assisted = (attempt.assistance_level or "none") != "none"
        if assisted:
            grade = "hard"
            next_level = max(0, int(schedule.interval_level or 0) - 1)
        elif question_form == "validated_variant":
            grade = "easy"
            next_level = min(len(INTERVAL_DAYS) - 1, int(schedule.interval_level or 0) + 2)
        else:
            grade = "good"
            next_level = min(len(INTERVAL_DAYS) - 1, int(schedule.interval_level or 0) + 1)
        if is_review and await has_spaced_stable_evidence(
            db, attempt.learner_id, attempt.item_type, int(attempt.item_id),
        ):
            next_level = len(INTERVAL_DAYS) - 1
        schedule.phase = ACTIVE_PHASE
        schedule.interval_level = next_level
        schedule.last_grade = grade
        schedule.due_at = current_time + timedelta(days=interval_days(next_level))
        if is_review:
            schedule.successful_reviews = int(schedule.successful_reviews or 0) + 1
            schedule.last_reviewed_at = current_time
    schedule.version = int(schedule.version or 0) + 1
    await db.flush()
    return schedule


async def stable_review_events(
    db: AsyncSession, learner_id: int, item_type: str, item_id: int,
) -> list[EvidenceEvent]:
    rows = list((await db.execute(select(EvidenceEvent).where(
        EvidenceEvent.learner_id == learner_id,
        EvidenceEvent.event_type == "review_attempt_evaluated",
    ))).scalars().all())
    relevant = [row for row in rows if (
        (row.payload or {}).get("source_item_type") == item_type
        and (row.payload or {}).get("item_id") == item_id
    )]
    relevant.sort(key=lambda row: row.occurred_at or row.created_at or datetime.min)
    last_failure = max(
        (index for index, row in enumerate(relevant) if not bool((row.payload or {}).get("passed"))),
        default=-1,
    )
    matching = [row for row in relevant[last_failure + 1:] if (
        bool((row.payload or {}).get("passed"))
        and bool((row.payload or {}).get("independent", True))
        and bool((row.payload or {}).get("stability_eligible", True))
    )]
    matching.sort(key=lambda row: row.occurred_at or row.created_at or datetime.min)
    if len(matching) < 2:
        return []
    start = matching[0].occurred_at or matching[0].created_at
    end = matching[-1].occurred_at or matching[-1].created_at
    if not (
        end - start >= timedelta(hours=72)
        and any(
            (row.payload or {}).get("question_form") == "validated_variant"
            for row in matching
        )
    ):
        return []
    return matching


async def has_spaced_stable_evidence(
    db: AsyncSession, learner_id: int, item_type: str, item_id: int,
) -> bool:
    return bool(await stable_review_events(db, learner_id, item_type, item_id))


async def mark_remediation_pending(
    db: AsyncSession, remediation: RemediationCase,
) -> ReviewSchedule:
    source = await db.get(LearningAttempt, remediation.source_attempt_id)
    if not source:
        raise ValueError("纠错案例缺少来源 Attempt")
    schedule = await get_or_create_schedule(
        db,
        learner_id=remediation.learner_id,
        project_id=remediation.project_id,
        checkpoint_id=remediation.checkpoint_id,
        item_type=remediation.item_type,
        item_id=int(remediation.item_id),
    )
    schedule.phase = REMEDIATION_PHASE
    schedule.due_at = datetime.utcnow()
    schedule.updated_at = datetime.utcnow()
    schedule.version = int(schedule.version or 0) + 1
    await db.flush()
    return schedule


async def schedule_after_remediation(
    db: AsyncSession,
    remediation: RemediationCase,
    *,
    now: datetime | None = None,
) -> ReviewSchedule:
    current_time = now or remediation.completed_at or datetime.utcnow()
    schedule = await get_or_create_schedule(
        db,
        learner_id=remediation.learner_id,
        project_id=remediation.project_id,
        checkpoint_id=remediation.checkpoint_id,
        item_type=remediation.item_type,
        item_id=int(remediation.item_id),
        now=current_time,
    )
    schedule.phase = ACTIVE_PHASE
    schedule.interval_level = 0
    schedule.last_grade = "remediated"
    schedule.last_attempt_id = remediation.variant_attempt_id or remediation.retry_attempt_id
    schedule.last_question_form = "validated_variant"
    schedule.last_reviewed_at = current_time
    schedule.due_at = current_time + timedelta(days=INTERVAL_DAYS[0])
    schedule.defer_count = 0
    schedule.suspended_at = None
    schedule.updated_at = current_time
    schedule.version = int(schedule.version or 0) + 1
    await db.flush()
    return schedule


def schedule_bucket(schedule: ReviewSchedule, *, now: datetime | None = None) -> str:
    current_time = now or datetime.utcnow()
    if schedule.phase == SUSPENDED_PHASE:
        return "suspended"
    if schedule.phase == REMEDIATION_PHASE:
        return "wrong"
    if schedule.due_at <= current_time - timedelta(days=1):
        return "overdue"
    if schedule.due_at <= current_time:
        return "due"
    if int(schedule.interval_level or 0) >= len(INTERVAL_DAYS) - 1:
        return "stable"
    return "upcoming"


def serialize_schedule(
    schedule: ReviewSchedule, *, now: datetime | None = None,
) -> dict[str, Any]:
    return {
        "id": schedule.id,
        "learner_id": schedule.learner_id,
        "project_id": schedule.project_id,
        "checkpoint_id": schedule.checkpoint_id,
        "item_type": schedule.item_type,
        "item_id": schedule.item_id,
        "subject_key": schedule.subject_key,
        "phase": schedule.phase,
        "bucket": schedule_bucket(schedule, now=now),
        "due_at": schedule.due_at.isoformat() if schedule.due_at else None,
        "interval_level": int(schedule.interval_level or 0),
        "interval_days": interval_days(int(schedule.interval_level or 0)),
        "successful_reviews": int(schedule.successful_reviews or 0),
        "lapse_count": int(schedule.lapse_count or 0),
        "defer_count": int(schedule.defer_count or 0),
        "last_grade": schedule.last_grade or "",
        "last_attempt_id": schedule.last_attempt_id,
        "last_event_id": schedule.last_event_id,
        "last_question_form": schedule.last_question_form or "original",
        "last_reviewed_at": (
            schedule.last_reviewed_at.isoformat() if schedule.last_reviewed_at else None
        ),
        "suspended_at": schedule.suspended_at.isoformat() if schedule.suspended_at else None,
        "policy_version": schedule.policy_version,
        "version": int(schedule.version or 1),
    }


def _valid_choice_variant(meta: dict[str, Any]) -> dict[str, Any] | None:
    variant = dict(meta.get("variant") or {})
    options = list(variant.get("options") or [])
    answers = [
        int(value) for value in list(variant.get("answer_indexes") or [])
        if str(value).lstrip("-").isdigit()
    ]
    if (
        variant.get("type") != "concept_choice"
        or not (
            variant.get("validated") is True
            or variant.get("validator_status") == "passed"
        )
        or len(options) < 2
        or not answers
        or not all(0 <= value < len(options) for value in answers)
    ):
        return None
    return {
        "type": "concept_choice",
        "prompt": str(variant.get("prompt") or "")[:1500],
        "options": [str(value)[:500] for value in options],
        "answer_indexes": sorted(set(answers)),
        "multiple": len(set(answers)) > 1,
    }


def _valid_output_variant(meta: dict[str, Any]) -> dict[str, Any] | None:
    variant = dict(meta.get("variant") or {})
    expected = str(variant.get("expected") or "").strip()
    if (
        variant.get("type") != "predict_output"
        or not (
            variant.get("validated") is True
            or variant.get("validator_status") == "passed"
        )
        or not expected
    ):
        return None
    return {
        "type": "predict_output",
        "prompt": str(variant.get("prompt") or "")[:1500],
        "input": str(variant.get("input") or "")[:300],
        "expected": expected[:300],
    }


async def review_presentation(
    db: AsyncSession, schedule: ReviewSchedule,
) -> dict[str, Any]:
    """Return one answer-redacted presentation plus a private grading contract."""
    open_case = None
    if schedule.phase == REMEDIATION_PHASE:
        open_case = (await db.execute(
            select(RemediationCase)
            .where(
                RemediationCase.learner_id == schedule.learner_id,
                RemediationCase.item_type == schedule.item_type,
                RemediationCase.item_id == schedule.item_id,
                RemediationCase.status != "completed",
            )
            .order_by(RemediationCase.updated_at.desc(), RemediationCase.id.desc())
            .limit(1)
        )).scalar_one_or_none()
    force_original = bool(
        schedule.phase == REMEDIATION_PHASE
        and (not open_case or open_case.status == "explaining")
    )
    if schedule.item_type == "concept":
        question = await db.get(ConceptQuestion, schedule.item_id)
        if not question:
            raise ValueError("概念题已不存在")
        variant = _valid_choice_variant(dict(question.assessment_meta or {}))
        if variant and not force_original and schedule.last_question_form != "validated_variant":
            private = variant
            public = {key: value for key, value in variant.items() if key != "answer_indexes"}
            return {
                "question_form": "validated_variant",
                "version": f"concept:{question.id}:variant:v1",
                "public": public,
                "private": private,
            }
        private = {
            "type": "concept_choice",
            "prompt": question.question,
            "options": list(question.options or []),
            "answer_indexes": list(question.answer_indexes or []),
            "multiple": question.q_type == "multiple",
        }
        public = {key: value for key, value in private.items() if key != "answer_indexes"}
        return {
            "question_form": "original",
            "version": f"concept:{question.id}:original:v1",
            "public": public,
            "private": private,
        }

    exercise = await db.get(Exercise, schedule.item_id)
    if not exercise:
        raise ValueError("代码题已不存在")
    variant = _valid_output_variant(dict(exercise.assessment_meta or {}))
    if variant and not force_original and schedule.last_question_form != "validated_variant":
        public = {key: value for key, value in variant.items() if key != "expected"}
        return {
            "question_form": "validated_variant",
            "version": f"exercise:{exercise.id}:variant:v1",
            "public": public,
            "private": variant,
        }
    files = [
        {key: value for key, value in dict(item).items() if key != "solution"}
        for item in list(exercise.files or [])
    ]
    return {
        "question_form": "original",
        "version": f"exercise:{exercise.id}:original:v1",
        "public": {
            "type": "code",
            "title": exercise.title,
            "prompt": exercise.description,
            "starter_code": exercise.starter_code or "",
            "files": files,
            "entrypoint": exercise.entrypoint or "",
            "requirements": list(exercise.requirements or []),
        },
        "private": {"type": "code"},
    }


async def rebuild_review_schedules(db: AsyncSession) -> int:
    """Backfill schedules from existing evidence without creating new events."""
    attempts = (await db.execute(
        select(LearningAttempt)
        .where(
            LearningAttempt.item_type.in_(("concept", "exercise")),
            LearningAttempt.item_id.is_not(None),
            LearningAttempt.status.in_(("evaluated", "abstained")),
        )
        .order_by(LearningAttempt.evaluated_at, LearningAttempt.id)
    )).scalars().all()
    for attempt in attempts:
        remediation = None
        if attempt.remediation_case_id:
            remediation = await db.get(RemediationCase, attempt.remediation_case_id)
        await apply_assessment_result(
            db,
            attempt=attempt,
            passed=_passed(attempt),
            event_id=None,
            remediation_status=remediation.status if remediation else None,
            is_review=attempt.attempt_role == "review",
            now=attempt.evaluated_at or attempt.submitted_at or datetime.utcnow(),
        )
    cases = (await db.execute(
        select(RemediationCase).order_by(RemediationCase.id)
    )).scalars().all()
    latest_cases: dict[tuple[int, str, int], RemediationCase] = {}
    for remediation in cases:
        latest_cases[
            (remediation.learner_id, remediation.item_type, int(remediation.item_id))
        ] = remediation
    for remediation in latest_cases.values():
        if remediation.status == "completed":
            await schedule_after_remediation(
                db, remediation, now=remediation.completed_at or remediation.updated_at,
            )
        else:
            await mark_remediation_pending(db, remediation)
    await db.flush()
    return len(attempts)
