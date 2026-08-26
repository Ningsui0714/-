import asyncio
import uuid
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.database import async_session
from app.main import app
from app.models.learning import (
    EvidenceEvent, KernelState, Learner, LearningAttempt, RemediationCase,
    ReviewSchedule,
)
from app.models.project import Checkpoint, ConceptQuestion, Project, Roadmap
from app.services.demo_seed import seed_competition_demo
from app.services.learning_runtime import create_attempt, record_event
from app.services.review import (
    _valid_choice_variant, _valid_output_variant, apply_assessment_result,
    rebuild_review_schedules,
)


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        accounts = test_client.get("/api/dev/accounts")
        legacy = next(item for item in accounts.json() if item["username"] == "legacy-demo")
        assert test_client.post(f"/api/dev/accounts/{legacy['id']}/login").status_code == 200
        yield test_client


async def _seed_question():
    async with async_session() as db:
        learner_id = (await db.execute(select(Learner.id).where(
            Learner.key == "local-default",
        ))).scalar_one()
        suffix = uuid.uuid4().hex[:8]
        project = Project(
            learner_id=learner_id,
            name=f"review-test-{suffix}",
            description="spaced review integration test",
        )
        db.add(project)
        await db.flush()
        roadmap = Roadmap(project_id=project.id, raw_json={})
        db.add(roadmap)
        await db.flush()
        checkpoint = Checkpoint(
            roadmap_id=roadmap.id,
            title="Review checkpoint",
            order=1,
            learning_status="in_progress",
        )
        db.add(checkpoint)
        await db.flush()
        question = ConceptQuestion(
            checkpoint_id=checkpoint.id,
            question="Which value is falsy?",
            options=["[1]", "[]"],
            answer_indexes=[1],
            q_type="single",
            difficulty="easy",
            explanation="An empty list is falsy.",
            assessment_meta={
                "targets": ["python.truthiness"],
                "variant": {
                    "type": "concept_choice",
                    "validated": True,
                    "prompt": "Which collection is falsy?",
                    "options": ["[0]", "[]"],
                    "answer_indexes": [1],
                },
            },
            order=1,
        )
        db.add(question)
        await db.commit()
        return learner_id, project.id, checkpoint.id, question.id


def _contains_hidden_answers(value):
    if isinstance(value, dict):
        if any(key in value for key in {"answer_indexes", "expected", "solution", "test_cases"}):
            return True
        return any(_contains_hidden_answers(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_hidden_answers(item) for item in value)
    return False


def test_unvalidated_candidate_variants_fall_back_to_original_questions():
    assert _valid_choice_variant({
        "variant": {
            "type": "concept_choice",
            "prompt": "candidate",
            "options": ["a", "b"],
            "answer_indexes": [1],
        },
    }) is None
    assert _valid_output_variant({
        "variant": {
            "type": "predict_output",
            "prompt": "candidate",
            "expected": "42",
        },
    }) is None


def test_all_assessed_items_are_scheduled_and_answers_are_hidden(client: TestClient):
    _, project_id, checkpoint_id, question_id = asyncio.run(_seed_question())
    client_key = f"initial-{uuid.uuid4()}"
    submitted = client.post(
        f"/api/checkpoints/{checkpoint_id}/concepts/{question_id}/submit",
        json={
            "answer_indexes": [1],
            "assistance_level": "none",
            "client_submission_id": client_key,
        },
    )
    assert submitted.status_code == 200
    body = submitted.json()
    schedule_id = body["review_schedule_id"]

    replay = client.post(
        f"/api/checkpoints/{checkpoint_id}/concepts/{question_id}/submit",
        json={
            "answer_indexes": [1],
            "assistance_level": "none",
            "client_submission_id": client_key,
        },
    )
    assert replay.status_code == 200
    assert replay.json()["idempotent_replay"] is True
    assert replay.json()["attempt_id"] == body["attempt_id"]

    item = client.get(f"/api/review/items/{schedule_id}")
    assert item.status_code == 200
    state = item.json()
    assert state["project_id"] == project_id
    assert state["interval_level"] == 1
    assert state["attempt_state"] == "correct_independent"
    assert state["presentation"]["question_form"] == "validated_variant"
    assert not _contains_hidden_answers(state["presentation"])
    history = client.get(f"/api/review/items/{schedule_id}/history")
    assert history.status_code == 200
    assert not _contains_hidden_answers(history.json()["attempts"])

    summary = client.get("/api/review/summary").json()
    assert summary["total"] >= 1
    assert summary["interval_days"] == [1, 3, 7, 14, 30, 60]


def test_review_wrong_reuses_remediation_and_schedules_next_day(client: TestClient):
    _, _, checkpoint_id, question_id = asyncio.run(_seed_question())
    initial = client.post(
        f"/api/checkpoints/{checkpoint_id}/concepts/{question_id}/submit",
        json={
            "answer_indexes": [1],
            "client_submission_id": f"initial-{uuid.uuid4()}",
        },
    ).json()
    schedule_id = initial["review_schedule_id"]
    item = client.get(f"/api/review/items/{schedule_id}").json()
    review_key = f"review-{uuid.uuid4()}"
    wrong_payload = {
        "expected_version": item["version"],
        "client_submission_id": review_key,
        "response_status": "answered",
        "answer_indexes": [0],
        "assistance_level": "none",
        "presentation_version": item["presentation"]["version"],
    }
    wrong = client.post(f"/api/review/items/{schedule_id}/submit", json=wrong_payload)
    assert wrong.status_code == 200
    wrong_body = wrong.json()
    assert wrong_body["outcome"] == "incorrect"
    assert wrong_body["item"]["phase"] == "remediation"
    assert wrong_body["item"]["presentation"]["question_form"] == "original"
    remediation = wrong_body["remediation"]
    assert remediation["status"] == "explaining"

    replay = client.post(f"/api/review/items/{schedule_id}/submit", json=wrong_payload)
    assert replay.status_code == 200
    assert replay.json()["idempotent_replay"] is True
    assert replay.json()["attempt_id"] == wrong_body["attempt_id"]

    retry = client.post(
        f"/api/checkpoints/{checkpoint_id}/concepts/{question_id}/submit",
        json={
            "answer_indexes": [1],
            "assistance_level": "guided",
            "remediation_case_id": remediation["id"],
            "attempt_role": "retry",
            "client_submission_id": f"retry-{uuid.uuid4()}",
        },
    )
    assert retry.status_code == 200
    assert retry.json()["remediation"]["status"] == "variant_ready"

    completed = client.post(
        f"/api/remediation/{remediation['id']}/variant/submit",
        json={"answer_indexes": [1]},
    )
    assert completed.status_code == 200
    assert completed.json()["remediation"]["status"] == "completed"

    refreshed = client.get(f"/api/review/items/{schedule_id}").json()
    assert refreshed["phase"] == "active"
    assert refreshed["interval_level"] == 0
    assert refreshed["last_grade"] == "remediated"
    history = client.get(f"/api/review/items/{schedule_id}/history").json()
    assert {attempt["attempt_role"] for attempt in history["attempts"]} >= {
        "original", "retry", "variant",
    }
    assert not _contains_hidden_answers(history["attempts"])
    due_at = datetime.fromisoformat(refreshed["due_at"])
    assert timedelta(hours=23) <= due_at - datetime.utcnow() <= timedelta(hours=25)

    defer_key = f"defer-{uuid.uuid4()}"
    deferred = client.post(
        f"/api/review/items/{schedule_id}/defer",
        json={"expected_version": refreshed["version"], "client_event_id": defer_key},
    )
    assert deferred.status_code == 200
    deferred_item = deferred.json()["item"]
    assert deferred_item["defer_count"] == 1

    defer_replay = client.post(
        f"/api/review/items/{schedule_id}/defer",
        json={"expected_version": refreshed["version"], "client_event_id": defer_key},
    )
    assert defer_replay.status_code == 200
    assert defer_replay.json()["idempotent_replay"] is True

    second_defer = client.post(
        f"/api/review/items/{schedule_id}/defer",
        json={
            "expected_version": deferred_item["version"],
            "client_event_id": f"defer-{uuid.uuid4()}",
        },
    )
    assert second_defer.status_code == 409


def test_skip_unknown_suspend_resume_and_isolation(client: TestClient):
    _, _, checkpoint_id, question_id = asyncio.run(_seed_question())
    initial = client.post(
        f"/api/checkpoints/{checkpoint_id}/concepts/{question_id}/submit",
        json={"answer_indexes": [1], "client_submission_id": f"initial-{uuid.uuid4()}"},
    ).json()
    schedule_id = initial["review_schedule_id"]
    item = client.get(f"/api/review/items/{schedule_id}").json()

    async def attempt_count():
        async with async_session() as db:
            return int((await db.execute(select(LearningAttempt.id).where(
                LearningAttempt.item_type == "concept",
                LearningAttempt.item_id == question_id,
            ))).scalars().all().__len__())

    before = asyncio.run(attempt_count())
    missing = client.post(f"/api/review/items/{schedule_id}/submit", json={
        "expected_version": item["version"],
        "client_submission_id": f"missing-{uuid.uuid4()}",
        "response_status": "answered",
        "presentation_version": item["presentation"]["version"],
    })
    assert missing.status_code == 422
    assert asyncio.run(attempt_count()) == before

    skipped = client.post(f"/api/review/items/{schedule_id}/submit", json={
        "expected_version": item["version"],
        "client_submission_id": f"skip-{uuid.uuid4()}",
        "response_status": "skipped",
        "presentation_version": item["presentation"]["version"],
    })
    assert skipped.status_code == 200
    assert asyncio.run(attempt_count()) == before

    unknown = client.post(f"/api/review/items/{schedule_id}/submit", json={
        "expected_version": item["version"],
        "client_submission_id": f"unknown-{uuid.uuid4()}",
        "response_status": "unknown",
        "presentation_version": item["presentation"]["version"],
    })
    assert unknown.status_code == 200
    assert unknown.json()["outcome"] == "unknown"
    assert unknown.json()["remediation"]["error_class"] == "concept_gap"

    current = client.get(f"/api/review/items/{schedule_id}").json()
    suspended = client.post(f"/api/review/items/{schedule_id}/suspend", json={
        "expected_version": current["version"],
        "client_event_id": f"suspend-{uuid.uuid4()}",
    })
    assert suspended.status_code == 200
    suspended_item = suspended.json()["item"]
    assert suspended_item["bucket"] == "suspended"
    resumed = client.post(f"/api/review/items/{schedule_id}/resume", json={
        "expected_version": suspended_item["version"],
        "client_event_id": f"resume-{uuid.uuid4()}",
    })
    assert resumed.status_code == 200
    assert resumed.json()["item"]["phase"] == "remediation"

    with TestClient(app) as outsider:
        registered = outsider.post("/api/auth/register", json={
            "username": f"review-outsider-{uuid.uuid4().hex[:10]}",
            "password": "learnflow-pass-123",
            "display_name": "Review Outsider",
            "education_stage": "undergraduate",
            "background": "Python beginner",
            "focus_areas": ["Python"],
            "weekly_hours": 3,
            "preferred_modes": ["practice"],
            "career_goal": "",
            "career_goal_status": "exploring",
        })
        assert registered.status_code == 200
        assert outsider.get(f"/api/review/items/{schedule_id}").status_code == 404


def test_spaced_independent_variant_evidence_reaches_stable_gate():
    learner_id, project_id, checkpoint_id, question_id = asyncio.run(_seed_question())

    async def scenario():
        async with async_session() as db:
            base = datetime.utcnow() - timedelta(days=4)
            second_event = await record_event(
                db,
                learner_id=learner_id,
                project_id=project_id,
                checkpoint_id=checkpoint_id,
                event_type="review_attempt_evaluated",
                source="review",
                payload={
                    "attempt_id": 900001,
                    "source_item_type": "concept",
                    "item_id": question_id,
                    "outcome": "correct",
                    "passed": True,
                    "independent": True,
                    "assistance_level": "none",
                    "question_form": "original",
                },
                occurred_at=base,
                client_event_id=f"stable-a-{uuid.uuid4()}",
            )
            await record_event(
                db,
                learner_id=learner_id,
                project_id=project_id,
                checkpoint_id=checkpoint_id,
                event_type="review_attempt_evaluated",
                source="review",
                payload={
                    "attempt_id": 900002,
                    "source_item_type": "concept",
                    "item_id": question_id,
                    "outcome": "correct",
                    "passed": True,
                    "independent": True,
                    "assistance_level": "none",
                    "question_form": "validated_variant",
                },
                occurred_at=base + timedelta(days=4),
                client_event_id=f"stable-b-{uuid.uuid4()}",
            )
            stable_attempt = await create_attempt(
                db,
                learner_id=learner_id,
                checkpoint_id=checkpoint_id,
                item_type="concept",
                item_id=question_id,
                submission={"answer_indexes": [1]},
                result={"correct": True},
                assistance_level="none",
                attempt_role="review",
                client_submission_id=f"stable-attempt-{uuid.uuid4()}",
            )
            stable_attempt.evaluated_at = base + timedelta(days=4)
            schedule = await apply_assessment_result(
                db,
                attempt=stable_attempt,
                passed=True,
                event_id=second_event.id,
                question_form="validated_variant",
                is_review=True,
                now=base + timedelta(days=4),
            )
            await db.commit()
            knowledge = (await db.execute(select(KernelState).where(
                KernelState.learner_id == learner_id,
                KernelState.kernel_name == "knowledge",
            ))).scalar_one()
            return (
                dict(knowledge.long_term or {}),
                dict(knowledge.short_term or {}),
                schedule.interval_level,
            )

    long_term, short_term, interval_level = asyncio.run(scenario())
    key = f"review:concept:{question_id}"
    assert long_term["mastery"][key]["level"] == "stable"
    assert short_term["retention_status"][f"concept:{question_id}"]["status"] == "spaced_stable"
    assert interval_level == 5


def test_scheduler_grade_transitions_are_explainable():
    learner_id, _, checkpoint_id, question_id = asyncio.run(_seed_question())

    async def scenario():
        async with async_session() as db:
            base = datetime.utcnow()

            async def project(
                *, passed: bool, assistance: str, form: str, role: str, at: datetime,
            ):
                attempt = await create_attempt(
                    db,
                    learner_id=learner_id,
                    checkpoint_id=checkpoint_id,
                    item_type="concept",
                    item_id=question_id,
                    submission={"answer_indexes": [1] if passed else [0]},
                    result={"correct": passed},
                    assistance_level=assistance,
                    attempt_role=role,
                    client_submission_id=f"grade-{uuid.uuid4()}",
                )
                attempt.evaluated_at = at
                schedule = await apply_assessment_result(
                    db,
                    attempt=attempt,
                    passed=passed,
                    event_id=None,
                    question_form=form,
                    is_review=role == "review",
                    now=at,
                )
                return schedule.last_grade, schedule.interval_level, schedule.due_at, schedule.phase

            hard = await project(
                passed=True, assistance="hint", form="original", role="original", at=base,
            )
            good = await project(
                passed=True, assistance="none", form="original", role="review",
                at=base + timedelta(days=1),
            )
            easy = await project(
                passed=True, assistance="none", form="validated_variant", role="review",
                at=base + timedelta(days=4),
            )
            again = await project(
                passed=False, assistance="none", form="original", role="review",
                at=base + timedelta(days=5),
            )
            await db.rollback()
            return hard, good, easy, again

    hard, good, easy, again = asyncio.run(scenario())
    assert hard[:2] == ("hard", 0)
    assert hard[2] - datetime.utcnow() <= timedelta(days=2)
    assert good[:2] == ("good", 1)
    assert easy[:2] == ("easy", 3)
    assert again[:2] == ("again", 0)
    assert again[3] == "remediation"


def test_failure_keeps_historical_mastery_but_resets_current_stability_window():
    learner_id, project_id, checkpoint_id, question_id = asyncio.run(_seed_question())

    async def scenario():
        async with async_session() as db:
            base = datetime.utcnow() - timedelta(days=8)

            async def review_event(
                *, at: datetime, passed: bool, form: str, eligible: bool = True,
            ):
                return await record_event(
                    db,
                    learner_id=learner_id,
                    project_id=project_id,
                    checkpoint_id=checkpoint_id,
                    event_type="review_attempt_evaluated",
                    source="review",
                    payload={
                        "attempt_id": int(at.timestamp()),
                        "source_item_type": "concept",
                        "item_id": question_id,
                        "outcome": "correct" if passed else "incorrect",
                        "passed": passed,
                        "independent": True,
                        "stability_eligible": eligible,
                        "assistance_level": "none",
                        "question_form": form,
                    },
                    occurred_at=at,
                    client_event_id=f"risk-{uuid.uuid4()}",
                )

            await review_event(at=base, passed=True, form="validated_variant")
            await review_event(at=base + timedelta(days=4), passed=True, form="original")
            await review_event(at=base + timedelta(days=5), passed=False, form="original")
            recovery_event = await review_event(
                at=base + timedelta(days=6), passed=True, form="original", eligible=False,
            )
            attempt = await create_attempt(
                db,
                learner_id=learner_id,
                checkpoint_id=checkpoint_id,
                item_type="concept",
                item_id=question_id,
                submission={"answer_indexes": [1]},
                result={"correct": True},
                assistance_level="none",
                attempt_role="retry",
                client_submission_id=f"risk-attempt-{uuid.uuid4()}",
            )
            schedule = await apply_assessment_result(
                db,
                attempt=attempt,
                passed=True,
                event_id=recovery_event.id,
                question_form="original",
                is_review=True,
                now=base + timedelta(days=6),
            )
            await db.commit()
            knowledge = (await db.execute(select(KernelState).where(
                KernelState.learner_id == learner_id,
                KernelState.kernel_name == "knowledge",
            ))).scalar_one()
            return schedule.interval_level, dict(knowledge.short_term or {}), dict(knowledge.long_term or {})

    interval_level, short_term, long_term = asyncio.run(scenario())
    item_key = f"concept:{question_id}"
    assert interval_level == 1
    assert short_term["retention_status"][item_key]["status"] == "retrieved"
    assert long_term["mastery"][f"review:{item_key}"]["level"] == "stable"


def test_seeded_demo_opens_review_with_due_variant_and_remediation():
    async def scenario():
        async with async_session() as db:
            first = await seed_competition_demo(db)
            second = await seed_competition_demo(db)
            learner_id = first["learner_id"]
            schedules = list((await db.execute(select(ReviewSchedule).where(
                ReviewSchedule.learner_id == learner_id,
            ))).scalars().all())
            attempts = list((await db.execute(select(LearningAttempt).where(
                LearningAttempt.learner_id == learner_id,
                LearningAttempt.client_submission_id.in_((
                    "competition-demo-review-concept-baseline",
                    "competition-demo-review-exercise-wrong",
                )),
            ))).scalars().all())
            cases = list((await db.execute(select(RemediationCase).where(
                RemediationCase.learner_id == learner_id,
                RemediationCase.status != "completed",
            ))).scalars().all())
            return first, second, schedules, attempts, cases

    first, second, schedules, attempts, cases = asyncio.run(scenario())
    assert first["entry_path"] == second["entry_path"] == "/review"
    assert len(schedules) == 2
    assert len(attempts) == 2
    assert {item.phase for item in schedules} == {"active", "remediation"}
    concept_schedule = next(item for item in schedules if item.item_type == "concept")
    assert concept_schedule.due_at <= datetime.utcnow()
    assert concept_schedule.last_question_form == "original"
    assert len(cases) == 1


def test_review_backfill_is_repeatable_without_events_or_duplicate_rows():
    learner_id, _, checkpoint_id, question_id = asyncio.run(_seed_question())

    async def scenario():
        async with async_session() as db:
            await create_attempt(
                db,
                learner_id=learner_id,
                checkpoint_id=checkpoint_id,
                item_type="concept",
                item_id=question_id,
                submission={"answer_indexes": [1]},
                result={"correct": True},
                assistance_level="none",
                client_submission_id=f"backfill-{uuid.uuid4()}",
            )
            await db.flush()
            events_before = len(list((await db.execute(select(EvidenceEvent).where(
                EvidenceEvent.learner_id == learner_id,
            ))).scalars().all()))
            await rebuild_review_schedules(db)
            await rebuild_review_schedules(db)
            schedules = list((await db.execute(select(ReviewSchedule).where(
                ReviewSchedule.learner_id == learner_id,
                ReviewSchedule.item_type == "concept",
                ReviewSchedule.item_id == question_id,
            ))).scalars().all())
            events_after = len(list((await db.execute(select(EvidenceEvent).where(
                EvidenceEvent.learner_id == learner_id,
            ))).scalars().all()))
            await db.rollback()
            return events_before, events_after, schedules

    events_before, events_after, schedules = asyncio.run(scenario())
    assert events_after == events_before
    assert len(schedules) == 1
