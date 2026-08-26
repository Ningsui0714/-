import asyncio
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.database import async_session
from app.main import app
from app.models.learning import EvidenceEvent, KernelState, Learner
from app.models.project import Checkpoint, ConceptQuestion, Exercise, Project, Roadmap
from app.services.remediation import RemediationStrategy


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        accounts = test_client.get("/api/dev/accounts")
        assert accounts.status_code == 200
        legacy = next(item for item in accounts.json() if item["username"] == "legacy-demo")
        assert test_client.post(f"/api/dev/accounts/{legacy['id']}/login").status_code == 200
        yield test_client


async def _seed_items():
    async with async_session() as db:
        learner_id = (await db.execute(select(Learner.id).where(
            Learner.key == "local-default",
        ))).scalar_one()
        suffix = uuid.uuid4().hex[:8]
        project = Project(
            learner_id=learner_id,
            name=f"remediation-test-{suffix}",
            description="deterministic remediation integration test",
        )
        db.add(project)
        await db.flush()
        roadmap = Roadmap(project_id=project.id, raw_json={})
        db.add(roadmap)
        await db.flush()
        checkpoint = Checkpoint(
            roadmap_id=roadmap.id,
            title="Remediation checkpoint",
            order=1,
            prerequisites=[],
            learning_status="in_progress",
        )
        db.add(checkpoint)
        await db.flush()
        question = ConceptQuestion(
            checkpoint_id=checkpoint.id,
            question="Which condition covers an empty list?",
            options=["values is None", "not values"],
            answer_indexes=[1],
            q_type="single",
            difficulty="easy",
            explanation="An empty list is falsy, so not values covers it.",
            order=1,
        )
        exercise = Exercise(
            checkpoint_id=checkpoint.id,
            title="Print two",
            description="Read no input and print 2.",
            starter_code="print(1)",
            solution="print(2)",
            test_cases=[{"input": "", "expected": "2"}],
            hints=["Compare actual output with expected output."],
            order=1,
            judge_mode="test_cases",
        )
        db.add_all([question, exercise])
        await db.commit()
        return checkpoint.id, question.id, exercise.id, learner_id


def test_remediation_strategy_is_deterministic_and_avoids_rejected_modes():
    first = RemediationStrategy.decide(
        item_type="concept", error_class="concept_misconception",
    )
    again = RemediationStrategy.decide(
        item_type="concept", error_class="concept_misconception",
    )
    switched = RemediationStrategy.decide(
        item_type="concept", error_class="concept_misconception",
        ineffective_modes=[first["delivery_mode"]],
    )
    assert first == again
    assert first["decision_owner"] == "deterministic_policy"
    assert switched["delivery_mode"] != first["delivery_mode"]


def test_concept_wrong_retry_variant_and_evidence_writeback(client: TestClient):
    checkpoint_id, question_id, _, learner_id = asyncio.run(_seed_items())
    wrong = client.post(
        f"/api/checkpoints/{checkpoint_id}/concepts/{question_id}/submit",
        json={"answer_indexes": [0], "assistance_level": "none"},
    )
    assert wrong.status_code == 200
    remediation = wrong.json()["remediation"]
    assert remediation["status"] == "explaining"
    assert remediation["strategy"]["decision_owner"] == "deterministic_policy"
    assert len(remediation["evidence_event_ids"]) >= 2

    premature_variant = client.post(
        f"/api/remediation/{remediation['id']}/variant/submit",
        json={"answer_indexes": [1]},
    )
    assert premature_variant.status_code == 409

    original_mode = remediation["current_delivery_mode"]
    switched = client.post(
        f"/api/remediation/{remediation['id']}/explanations",
        json={"action": "switch"},
    )
    assert switched.status_code == 200
    assert original_mode in switched.json()["ineffective_modes"]
    assert switched.json()["current_delivery_mode"] != original_mode
    assert len(switched.json()["evidence_event_ids"]) >= 4

    retry = client.post(
        f"/api/checkpoints/{checkpoint_id}/concepts/{question_id}/submit",
        json={
            "answer_indexes": [1],
            "assistance_level": "guided",
            "remediation_case_id": remediation["id"],
            "attempt_role": "retry",
        },
    )
    assert retry.status_code == 200
    retried = retry.json()["remediation"]
    assert retried["status"] == "variant_ready"
    assert retried["variant"]["type"] == "concept_choice"
    assert "answer_indexes" not in retried["variant"]

    variant = client.post(
        f"/api/remediation/{remediation['id']}/variant/submit",
        json={"answer_indexes": [1]},
    )
    assert variant.status_code == 200
    assert variant.json()["result"]["correct"] is True
    assert "answer_indexes" not in variant.json()["result"]
    assert variant.json()["remediation"]["status"] == "completed"

    async def event_types_and_human_state():
        async with async_session() as db:
            event_types = list((await db.execute(select(EvidenceEvent.event_type).where(
                EvidenceEvent.learner_id == learner_id,
                EvidenceEvent.checkpoint_id == checkpoint_id,
            ))).scalars().all())
            human = (await db.execute(select(KernelState).where(
                KernelState.learner_id == learner_id,
                KernelState.kernel_name == "human",
            ))).scalar_one()
            return event_types, dict(human.short_term or {})

    types, human_state = asyncio.run(event_types_and_human_state())
    assert "remediation_started" in types
    assert "remediation_mode_rejected" in types
    assert "remediation_retry_evaluated" in types
    assert "remediation_variant_evaluated" in types
    assert "remediation_completed" in types
    assert original_mode in human_state["ineffective_explanation_modes"]
    assert human_state["last_effective_explanation_mode"] == switched.json()["current_delivery_mode"]


def test_exercise_wrong_then_retry_uses_same_case(client: TestClient):
    _, _, exercise_id, _ = asyncio.run(_seed_items())
    wrong = client.post(
        f"/api/exercises/{exercise_id}/submit",
        json={"code": "print(1)", "assistance_level": "none"},
    )
    assert wrong.status_code == 200
    body = wrong.json()
    assert body["passed"] == 0
    remediation = body["remediation"]
    assert remediation["item_type"] == "exercise"

    retry = client.post(
        f"/api/exercises/{exercise_id}/submit",
        json={
            "code": "print(2)",
            "assistance_level": "guided",
            "remediation_case_id": remediation["id"],
            "attempt_role": "retry",
        },
    )
    assert retry.status_code == 200
    retried = retry.json()["remediation"]
    assert retried["id"] == remediation["id"]
    assert retried["status"] == "variant_ready"

    variant = client.post(
        f"/api/remediation/{remediation['id']}/variant/submit",
        json={"answer_text": "2"},
    )
    assert variant.status_code == 200
    assert variant.json()["remediation"]["status"] == "completed"
