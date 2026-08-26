import asyncio
from types import SimpleNamespace
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import settings
from app.api.tasks import task_events
from app.db.database import async_session
from app.main import app
from app.models.learning import Learner
from app.models.project import Checkpoint, Project, Roadmap, Task
from app.services.task_manager import manager, update_task


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        accounts = test_client.get("/api/dev/accounts")
        assert accounts.status_code == 200
        legacy = next(item for item in accounts.json() if item["username"] == "legacy-demo")
        assert test_client.post(f"/api/dev/accounts/{legacy['id']}/login").status_code == 200
        yield test_client


async def _seed_checkpoint() -> tuple[int, int]:
    async with async_session() as db:
        learner_id = (await db.execute(select(Learner.id).where(
            Learner.key == "local-default",
        ))).scalar_one()
        suffix = uuid.uuid4().hex[:8]
        project = Project(
            learner_id=learner_id,
            name=f"phase3-generation-{suffix}",
            description="generation route regression test",
        )
        db.add(project)
        await db.flush()
        roadmap = Roadmap(project_id=project.id, raw_json={})
        db.add(roadmap)
        await db.flush()
        checkpoint = Checkpoint(
            roadmap_id=roadmap.id,
            title="Generation checkpoint",
            order=1,
            prerequisites=[],
            learning_status="in_progress",
        )
        db.add(checkpoint)
        await db.commit()
        return checkpoint.id, learner_id


def test_concept_and_exercise_generation_routes_create_owned_tasks(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    checkpoint_id, learner_id = asyncio.run(_seed_checkpoint())
    monkeypatch.setattr(settings, "llm_api_key", "test-api-key")

    def submit(_task_id, coroutine):
        coroutine.close()
        return None

    monkeypatch.setattr(manager, "submit", submit)

    concept = client.post(f"/api/checkpoints/{checkpoint_id}/concepts/generate")
    exercise = client.post(f"/api/checkpoints/{checkpoint_id}/exercises/generate")

    assert concept.status_code == 200, concept.text
    assert exercise.status_code == 200, exercise.text
    assert concept.json()["status"] == "queued"
    assert exercise.json()["status"] == "queued"

    async def load_tasks():
        async with async_session() as db:
            return list((await db.execute(
                select(Task).where(Task.checkpoint_id == checkpoint_id).order_by(Task.id)
            )).scalars().all())

    tasks = asyncio.run(load_tasks())
    assert [task.type for task in tasks] == ["concept_generate", "exercise_generate"]
    assert all(task.learner_id == learner_id for task in tasks)


def test_task_event_stream_releases_sqlite_reads_before_background_writes():
    """An active SSE subscription must not lock task-runner progress updates."""

    async def exercise_stream():
        checkpoint_id, learner_id = await _seed_checkpoint()
        async with async_session() as db:
            task = Task(
                learner_id=learner_id,
                checkpoint_id=checkpoint_id,
                type="concept_generate",
                status="running",
                payload={"checkpoint_id": checkpoint_id},
                progress={"message": "排队中..."},
            )
            db.add(task)
            await db.commit()
            await db.refresh(task)
            task_id = task.id

            current = SimpleNamespace(learner=SimpleNamespace(id=learner_id))
            response = await task_events(task_id, current, db)

            # The dependency-scoped ownership-check session outlives the SSE
            # response, so the endpoint must explicitly release its read txn.
            assert not db.in_transaction()

            stream = response.body_iterator
            first_event = await anext(stream)
            assert f'"task_id": {task_id}' in first_event

            updated = await asyncio.wait_for(
                update_task(
                    task_id,
                    progress={"current": 1, "total": 1, "message": "完成"},
                ),
                timeout=5,
            )
            await stream.aclose()
            return updated

    updated = asyncio.run(exercise_stream())
    assert updated is not None
    assert updated.progress["message"] == "完成"
