import asyncio

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.database import async_session
from app.main import app
from app.models.learning import KernelState, LearnerBadge, LearningLifeEvent
from app.models.project import Checkpoint, Project, Roadmap, Task
from app.services.learning_runtime import (
    create_attempt, evaluate_checkpoint_status, get_kernel_projection,
)
from app.services.profile import evaluate_project_badge, process_major_event_candidates


def registration(username: str, display_name: str, background: str, *, career_goal: str = "", confirmed: bool = False):
    return {
        "username": username,
        "password": "learnflow-pass-123",
        "display_name": display_name,
        "education_stage": "undergraduate",
        "background": background,
        "focus_areas": ["人工智能"],
        "weekly_hours": 6,
        "preferred_modes": ["explanation", "practice", "project"],
        "career_goal": career_goal,
        "career_goal_status": "confirmed" if confirmed else "exploring",
    }


def test_two_cookie_clients_are_strictly_isolated():
    with TestClient(app) as alice, TestClient(app) as bob:
        alice_user = alice.post("/api/auth/register", json=registration(
            "alice_isolation", "Alice", "学过 Python",
        ))
        bob_user = bob.post("/api/auth/register", json=registration(
            "bob_isolation", "Bob", "只学过 JavaScript",
        ))
        assert alice_user.status_code == bob_user.status_code == 200
        alice_learner = alice_user.json()["learner_id"]
        bob_learner = bob_user.json()["learner_id"]

        project = alice.post("/api/projects", json={
            "name": "Alice 私有项目", "description": "不能被 Bob 看见", "user_level": "beginner",
        }).json()
        project_id = project["id"]
        assert bob.get(f"/api/projects/{project_id}").status_code == 404
        assert bob.delete(f"/api/projects/{project_id}").status_code == 404
        assert bob.get(f"/api/projects/{project_id}/sources").status_code == 404
        assert bob.get("/api/projects").json() == []

        session_id = alice.post("/api/agent/sessions", json={"session_type": "global"}).json()["id"]
        assert bob.get(f"/api/agent/sessions/{session_id}").status_code == 404
        proposal_response = alice.post(
            f"/api/agent/sessions/{session_id}/turns",
            json={"message": "我想系统学习离散数学并持续完成证明练习"},
        ).json()
        proposal_id = proposal_response["proposal_update"]["id"]
        assert bob.get(f"/api/agent/project-proposals/{proposal_id}").status_code == 404
        assert bob.post(
            f"/api/agent/project-proposals/{proposal_id}/accept",
            json={"client_event_id": "bob-cannot-accept"},
        ).status_code == 404

        async def create_private_task():
            async with async_session() as db:
                task = Task(
                    learner_id=alice_learner,
                    project_id=project_id,
                    type="test_task",
                    status="queued",
                    payload={},
                )
                db.add(task)
                await db.commit()
                return task.id

        task_id = asyncio.run(create_private_task())
        assert alice.get(f"/api/tasks/{task_id}").status_code == 200
        assert bob.get(f"/api/tasks/{task_id}").status_code == 404
        assert bob.post(f"/api/tasks/{task_id}/cancel").status_code == 404
        assert bob.get(f"/api/tasks/{task_id}/events").status_code == 404

        shared_event = {
            "client_event_id": "same-client-event-id",
            "event_type": "learning_feedback",
            "payload": {"value": "ok"},
        }
        alice_event = alice.post("/api/learning-events", json=shared_event)
        bob_event = bob.post("/api/learning-events", json=shared_event)
        assert alice_event.status_code == bob_event.status_code == 200
        assert alice_event.json()["id"] != bob_event.json()["id"]

        alice_memories = alice.get("/api/profile/memories").json()["dimensions"]
        bob_memories = bob.get("/api/profile/memories").json()["dimensions"]
        assert "学过 Python" in str(alice_memories)
        assert "只学过 JavaScript" not in str(alice_memories)
        assert "只学过 JavaScript" in str(bob_memories)

        assert alice.get("/api/settings").status_code == 404
        assert alice.post("/api/auth/logout").status_code == 200
        assert alice.get("/api/projects").status_code == 401

        async def kernel_owners():
            async with async_session() as db:
                return set((await db.execute(select(KernelState.learner_id).where(
                    KernelState.learner_id.in_([alice_learner, bob_learner]),
                ))).scalars().all())

        assert asyncio.run(kernel_owners()) == {alice_learner, bob_learner}


def test_login_password_session_and_dev_switching():
    with TestClient(app) as client:
        created = client.post("/api/auth/register", json=registration(
            "case_sensitive_demo", "Case User", "Python 基础",
        ))
        assert created.status_code == 200
        account_id = created.json()["id"]
        assert client.post("/api/auth/logout").status_code == 200
        assert client.post("/api/auth/login", json={
            "username": "CASE_SENSITIVE_DEMO", "password": "wrong-password",
        }).status_code == 401
        logged_in = client.post("/api/auth/login", json={
            "username": "CASE_SENSITIVE_DEMO", "password": "learnflow-pass-123",
        })
        assert logged_in.status_code == 200
        assert logged_in.json()["is_dev_login"] is False
        assert client.get("/api/settings").status_code == 404

        switched = client.post(f"/api/dev/accounts/{account_id}/login")
        assert switched.status_code == 200
        assert switched.json()["is_dev_login"] is True
        assert client.get("/api/settings").status_code == 200


def test_badges_are_idempotent_and_memory_correction_keeps_history():
    with TestClient(app) as client:
        registered = client.post("/api/auth/register", json=registration(
            "badge_path_user", "Badge User", "掌握 Python 基础",
            career_goal="成为机器学习工程师", confirmed=True,
        ))
        assert registered.status_code == 200
        learner_id = registered.json()["learner_id"]
        initial_journey = client.get("/api/profile/journey").json()
        career_badges = [item for item in initial_journey["badges"] if item["badge_type"] == "career_goal_confirmed"]
        assert len(career_badges) == 1

        client.patch("/api/profile", json={
            "career_goal": "成为机器学习工程师", "career_goal_status": "confirmed",
        })
        repeated = client.get("/api/profile/journey").json()
        assert len([item for item in repeated["badges"] if item["badge_type"] == "career_goal_confirmed"]) == 1

        memories = client.get("/api/profile/memories").json()["dimensions"]
        value_memories = next(item for item in memories if item["kernel"] == "value")["memories"]
        career_memory = next(item for item in value_memories if item["key"] == "career_goal")
        archived = client.post(
            f"/api/profile/memories/{career_memory['memory_id']}/archive",
            json={"reason": "职业方向正在重新考虑"},
        )
        assert archived.status_code == 200

        async def verify_archived_projection():
            async with async_session() as db:
                projection = await get_kernel_projection(db, learner_id)
                return projection["value"]["long_term"]

        assert "career_goal" not in asyncio.run(verify_archived_projection())
        corrected = client.get("/api/profile/journey").json()
        assert len([item for item in corrected["badges"] if item["badge_type"] == "career_goal_confirmed"]) == 1
        career_event = next(item for item in corrected["events"] if item["event_type"] == "career_goal_confirmed")
        assert career_event["status"] == "corrected"


def test_project_completion_badge_requires_verified_nonempty_roadmap():
    with TestClient(app) as client:
        registered = client.post("/api/auth/register", json=registration(
            "project_badge_user", "Project Badge", "Python 基础",
        )).json()
        learner_id = registered["learner_id"]
        project_id = client.post("/api/projects", json={
            "name": "完整验证项目", "description": "", "user_level": "beginner",
        }).json()["id"]

        async def scenario():
            async with async_session() as db:
                assert await evaluate_project_badge(db, learner_id=learner_id, project_id=project_id) == (None, None)
                roadmap = Roadmap(project_id=project_id, raw_json={})
                db.add(roadmap)
                await db.flush()
                checkpoint = Checkpoint(
                    roadmap_id=roadmap.id, title="最终验证", order=1,
                    learning_status="verification_due", legacy_completed=True,
                )
                db.add(checkpoint)
                await db.flush()
                assert await evaluate_project_badge(db, learner_id=learner_id, project_id=project_id) == (None, None)
                checkpoint.legacy_completed = False
                await create_attempt(
                    db, learner_id=learner_id, checkpoint_id=checkpoint.id,
                    item_type="concept", item_id=1, submission={}, result={"correct": True},
                )
                await create_attempt(
                    db, learner_id=learner_id, checkpoint_id=checkpoint.id,
                    item_type="exercise", item_id=1, submission={}, result={"passed": 1, "total": 1},
                )
                assert await evaluate_checkpoint_status(db, checkpoint.id, learner_id=learner_id) == "completed"
                first_event, first_badge = await evaluate_project_badge(
                    db, learner_id=learner_id, project_id=project_id,
                )
                second_event, second_badge = await evaluate_project_badge(
                    db, learner_id=learner_id, project_id=project_id,
                )
                await db.commit()
                return first_event.id, first_badge.id, second_event.id, second_badge

        first_event, first_badge, second_event, second_badge = asyncio.run(scenario())
        assert first_event == second_event
        assert first_badge
        assert second_badge is None
        journey = client.get("/api/profile/journey").json()
        assert len([item for item in journey["badges"] if item["badge_type"] == "project_completed"]) == 1


def test_semantic_career_event_needs_explicit_first_person_and_high_confidence():
    with TestClient(app) as client:
        registered = client.post("/api/auth/register", json=registration(
            "career_semantic_user", "Career Semantic", "Python 基础",
        )).json()
        learner_id = registered["learner_id"]

        async def scenario():
            async with async_session() as db:
                none_low = await process_major_event_candidates(
                    db, learner_id=learner_id,
                    message="我决定成为数据工程师", message_id=900001,
                    candidates=[{"event_type": "career_goal_confirmed", "career_goal": "数据工程师", "confidence": 0.89, "evidence_text": "我决定成为数据工程师"}],
                )
                none_third_person = await process_major_event_candidates(
                    db, learner_id=learner_id,
                    message="朋友决定成为数据工程师", message_id=900002,
                    candidates=[{"event_type": "career_goal_confirmed", "career_goal": "数据工程师", "confidence": 0.98, "evidence_text": "朋友决定成为数据工程师"}],
                )
                created = await process_major_event_candidates(
                    db, learner_id=learner_id,
                    message="我决定成为数据工程师", message_id=900003,
                    candidates=[{"event_type": "career_goal_confirmed", "career_goal": "数据工程师", "confidence": 0.96, "evidence_text": "我决定成为数据工程师"}],
                )
                await db.commit()
                return none_low, none_third_person, created

        none_low, none_third_person, created = asyncio.run(scenario())
        assert none_low == ([], [])
        assert none_third_person == ([], [])
        assert len(created[0]) == len(created[1]) == 1
