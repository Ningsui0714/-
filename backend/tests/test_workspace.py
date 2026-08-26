from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.config import settings
from app.db.database import async_session
from app.main import app
from app.models.learning import AgentSession, EvidenceEvent, KernelMutation, LearningAttempt
from app.models.project import (
    ArtifactAnnotation, Checkpoint, Exercise, Lecture, LectureVersion,
    Project, Roadmap, Task, WorkspaceOperation,
)


DESKTOP_TOKEN = "workspace-test-token"
DESKTOP_HEADERS = {"X-LearnFlow-Desktop-Token": DESKTOP_TOKEN}


def registration(username: str):
    return {
        "username": username,
        "password": "learnflow-pass-123",
        "display_name": username,
        "education_stage": "undergraduate",
        "background": "Python 基础",
        "focus_areas": ["工程实践"],
        "weekly_hours": 5,
        "preferred_modes": ["explanation", "practice", "project"],
        "career_goal": "",
        "career_goal_status": "exploring",
    }


def enable_desktop(monkeypatch):
    monkeypatch.setattr(settings, "desktop_mode", True)
    monkeypatch.setattr(settings, "desktop_token", DESKTOP_TOKEN)


def create_project(client: TestClient, name: str = "Local Workspace") -> dict:
    response = client.post("/api/projects", json={
        "name": name,
        "description": "desktop test",
        "user_level": "beginner",
    })
    assert response.status_code == 200
    return response.json()


def link_workspace(client: TestClient, project_id: int, root: Path, request_id: str = "link-1"):
    return client.post(
        f"/api/projects/{project_id}/workspace/link",
        headers=DESKTOP_HEADERS,
        json={
            "root_path": str(root),
            "platform": "test",
            "create": False,
            "client_request_id": request_id,
        },
    )


def test_browser_mode_hides_local_filesystem_routes(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "desktop_mode", False)
    monkeypatch.setattr(settings, "desktop_token", "")
    with TestClient(app) as client:
        registered = client.post("/api/auth/register", json=registration("workspace_browser_hidden"))
        assert registered.status_code == 200
        assert "desktop_auth_token" not in registered.json()
        project = create_project(client)
        response = link_workspace(client, project["id"], tmp_path)
        assert response.status_code == 404
        assert not (tmp_path / ".learnflow").exists()


def test_desktop_user_can_open_model_settings_without_dev_switch(monkeypatch, tmp_path):
    enable_desktop(monkeypatch)
    monkeypatch.setattr(
        "app.api.settings.ENV_PATH",
        str(tmp_path / "settings.env"),
    )
    with TestClient(app) as client:
        registered = client.post(
            "/api/auth/register",
            headers=DESKTOP_HEADERS,
            json=registration("workspace_desktop_settings"),
        )
        assert registered.status_code == 200
        assert registered.json()["is_dev_login"] is False
        settings_response = client.get("/api/settings", headers=DESKTOP_HEADERS)
        assert settings_response.status_code == 200
        saved = client.put(
            "/api/settings",
            headers=DESKTOP_HEADERS,
            json={"llm_model": "desktop-test-model"},
        )
        assert saved.status_code == 200
        assert "LLM_MODEL" in saved.json()["updated"]


def test_settings_preserve_api_key_and_normalize_deepseek(monkeypatch, tmp_path):
    enable_desktop(monkeypatch)
    settings_path = tmp_path / "settings.env"
    monkeypatch.delenv("LEARNFLOW_SETTINGS_PATH", raising=False)
    monkeypatch.setattr("app.api.settings.ENV_PATH", str(settings_path))
    # Keep the process-global settings isolated from the other TestClient cases.
    monkeypatch.setattr(settings, "llm_api_key", settings.llm_api_key)
    monkeypatch.setattr(settings, "llm_base_url", settings.llm_base_url)
    monkeypatch.setattr(settings, "llm_model", settings.llm_model)

    with TestClient(app) as client:
        registered = client.post(
            "/api/auth/register",
            headers=DESKTOP_HEADERS,
            json=registration("workspace_settings_key_roundtrip"),
        )
        assert registered.status_code == 200

        secret = "sk-test-settings-roundtrip-1234"
        saved = client.put(
            "/api/settings",
            headers=DESKTOP_HEADERS,
            json={
                "llm_api_key": secret,
                "llm_base_url": "https://api.deepseek.com/v1/",
                "llm_model": "deepseek-v4-flash",
            },
        )
        assert saved.status_code == 200, saved.text
        assert "LLM_API_KEY" in saved.json()["updated"]

        current = client.get("/api/settings", headers=DESKTOP_HEADERS)
        assert current.status_code == 200
        assert current.json()["has_key"] is True
        assert current.json()["llm_api_key"] == "sk-test-…1234"
        assert current.json()["llm_base_url"] == "https://api.deepseek.com"

        # The settings form intentionally sends no key when the input is blank.
        # Even an explicit blank must not destroy the persisted credential.
        preserved = client.put(
            "/api/settings",
            headers=DESKTOP_HEADERS,
            json={
                "llm_api_key": "",
                "llm_base_url": "https://api.deepseek.com/v1",
                "llm_model": "deepseek-v4-flash",
            },
        )
        assert preserved.status_code == 200, preserved.text
        assert "LLM_API_KEY" not in preserved.json()["updated"]

        after_blank_save = client.get("/api/settings", headers=DESKTOP_HEADERS)
        assert after_blank_save.json()["has_key"] is True
        assert after_blank_save.json()["llm_api_key"] == "sk-test-…1234"
        assert after_blank_save.json()["llm_base_url"] == "https://api.deepseek.com"
        assert f"LLM_API_KEY={secret}" in settings_path.read_text(encoding="utf-8")


def test_repo_files_dir_can_be_overridden_for_desktop_storage(tmp_path):
    repo_files_dir = tmp_path / "repo-files"
    env = os.environ.copy()
    env["REPO_FILES_DIR"] = str(repo_files_dir)
    result = subprocess.run(
        [sys.executable, "-c", "from app.core.config import settings; print(settings.repo_files_dir)"],
        cwd=Path(__file__).parents[1],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == str(repo_files_dir)


def test_source_cache_and_upload_dirs_are_not_workspace_paths(tmp_path):
    source_cache = tmp_path / "source-cache"
    source_uploads = tmp_path / "source-uploads"
    env = os.environ.copy()
    env["SOURCE_CACHE_DIR"] = str(source_cache)
    env["SOURCE_UPLOADS_DIR"] = str(source_uploads)
    result = subprocess.run(
        [sys.executable, "-c", "from app.core.config import settings; print(settings.source_cache_dir); print(settings.source_uploads_dir)"],
        cwd=Path(__file__).parents[1],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.splitlines() == [str(source_cache), str(source_uploads)]


def test_desktop_bearer_requires_the_per_launch_token(monkeypatch):
    enable_desktop(monkeypatch)
    with TestClient(app) as login_client, TestClient(app) as bearer_client:
        registered = login_client.post(
            "/api/auth/register",
            headers=DESKTOP_HEADERS,
            json=registration("workspace_desktop_bearer"),
        )
        assert registered.status_code == 200
        auth_token = registered.json()["desktop_auth_token"]
        bearer_headers = {
            **DESKTOP_HEADERS,
            "Authorization": f"Bearer {auth_token}",
        }
        assert bearer_client.get("/api/projects", headers=bearer_headers).status_code == 200
        assert bearer_client.get(
            "/api/projects", headers={"Authorization": f"Bearer {auth_token}"},
        ).status_code == 401


def test_desktop_bearer_can_subscribe_to_owned_task_events(monkeypatch):
    """Task streams must accept the same headers the desktop fetch client sends."""
    enable_desktop(monkeypatch)
    with TestClient(app) as login_client, TestClient(app) as stream_client:
        registered = login_client.post(
            "/api/auth/register",
            headers=DESKTOP_HEADERS,
            json=registration("workspace_desktop_task_stream"),
        )
        assert registered.status_code == 200
        learner_id = registered.json()["learner_id"]
        auth_token = registered.json()["desktop_auth_token"]

        async def create_completed_task():
            async with async_session() as db:
                task = Task(
                    learner_id=learner_id,
                    type="test_task",
                    status="completed",
                    progress={"message": "完成"},
                    payload={},
                )
                db.add(task)
                await db.commit()
                return task.id

        task_id = asyncio.run(create_completed_task())
        bearer_headers = {
            **DESKTOP_HEADERS,
            "Authorization": f"Bearer {auth_token}",
        }
        response = stream_client.get(f"/api/tasks/{task_id}/events", headers=bearer_headers)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert f'"task_id": {task_id}' in response.text
        assert '"status": "completed"' in response.text


def test_link_tree_text_write_hash_and_zero_kernel_mutations(tmp_path, monkeypatch):
    enable_desktop(monkeypatch)
    root = tmp_path / "project"
    root.mkdir()
    (root / "main.py").write_text("print('old')\n", encoding="utf-8")
    (root / "asset.bin").write_bytes(b"\x00\x01")
    (root / "pixel.png").write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
    )
    (root / "unsafe.svg").write_text("<svg><script>alert(1)</script></svg>", encoding="utf-8")

    with TestClient(app) as client:
        registered = client.post("/api/auth/register", json=registration("workspace_writer"))
        assert registered.status_code == 200
        learner_id = registered.json()["learner_id"]
        project = create_project(client)
        project_id = project["id"]
        linked = link_workspace(client, project_id, root)
        assert linked.status_code == 200, linked.text
        assert (root / ".learnflow" / "project.lfproject").exists()

        tree = client.get(
            f"/api/projects/{project_id}/workspace/tree", headers=DESKTOP_HEADERS,
        )
        assert tree.status_code == 200
        by_name = {item["name"]: item for item in tree.json()["nodes"]}
        assert by_name["main.py"]["kind"] == "workspace_text"
        assert by_name["asset.bin"]["kind"] == "workspace_binary"
        assert ".learnflow" not in by_name

        image_preview = client.get(
            f"/api/projects/{project_id}/workspace/previews/pixel.png",
            headers=DESKTOP_HEADERS,
        )
        assert image_preview.status_code == 200
        assert image_preview.headers["content-type"].startswith("image/png")
        assert image_preview.headers["x-content-type-options"] == "nosniff"
        unsafe_preview = client.get(
            f"/api/projects/{project_id}/workspace/previews/unsafe.svg",
            headers=DESKTOP_HEADERS,
        )
        assert unsafe_preview.status_code == 415

        current = client.get(
            f"/api/projects/{project_id}/workspace/files/main.py", headers=DESKTOP_HEADERS,
        )
        assert current.status_code == 200
        base_hash = current.json()["sha256"]
        saved = client.put(
            f"/api/projects/{project_id}/workspace/files/main.py",
            headers=DESKTOP_HEADERS,
            json={
                "content": "print('new')\n",
                "base_hash": base_hash,
                "idempotency_key": "save-main-1",
            },
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["status"] == "applied"
        assert (root / "main.py").read_text(encoding="utf-8") == "print('new')\n"
        repeated = client.put(
            f"/api/projects/{project_id}/workspace/files/main.py",
            headers=DESKTOP_HEADERS,
            json={
                "content": "should not replace\n",
                "base_hash": base_hash,
                "idempotency_key": "save-main-1",
            },
        )
        assert repeated.status_code == 200
        assert repeated.json()["id"] == saved.json()["id"]

        (root / "main.py").write_text("external edit\n", encoding="utf-8")
        stale = client.put(
            f"/api/projects/{project_id}/workspace/files/main.py",
            headers=DESKTOP_HEADERS,
            json={
                "content": "stale proposal\n",
                "base_hash": saved.json()["result"]["sha256"],
                "idempotency_key": "save-main-stale",
            },
        )
        assert stale.status_code == 409

        async def operational_evidence():
            async with async_session() as db:
                event_ids = list((await db.execute(select(EvidenceEvent.id).where(
                    EvidenceEvent.learner_id == learner_id,
                    EvidenceEvent.event_type.in_(["workspace_linked", "workspace_change_applied"]),
                ))).scalars().all())
                mutation_count = await db.scalar(select(func.count(KernelMutation.id)).where(
                    KernelMutation.event_id.in_(event_ids),
                )) if event_ids else 0
                return len(event_ids), mutation_count or 0

        event_count, mutation_count = asyncio.run(operational_evidence())
        assert event_count == 2
        assert mutation_count == 0


def test_agent_diff_requires_checkpoint_scope_and_explicit_confirmation(tmp_path, monkeypatch):
    enable_desktop(monkeypatch)
    root = tmp_path / "project"
    root.mkdir()
    target = root / "lesson.py"
    target.write_text("value = 1\n", encoding="utf-8")
    (root / ".env.development").write_text("TOKEN=secret\n", encoding="utf-8")

    with TestClient(app) as client:
        registered = client.post("/api/auth/register", json=registration("workspace_agent_scope"))
        learner_id = registered.json()["learner_id"]
        project = create_project(client)
        project_id = project["id"]
        assert link_workspace(client, project_id, root).status_code == 200

        current = client.get(
            f"/api/projects/{project_id}/workspace/files/lesson.py", headers=DESKTOP_HEADERS,
        ).json()
        missing_scope = client.post(
            f"/api/projects/{project_id}/workspace/operations/propose",
            headers=DESKTOP_HEADERS,
            json={
                "actor": "agent",
                "operation": "write",
                "target_path": "lesson.py",
                "content": "value = 2\n",
                "base_hash": current["sha256"],
                "idempotency_key": "agent-missing-scope",
            },
        )
        assert missing_scope.status_code == 400

        async def create_scope():
            async with async_session() as db:
                roadmap = Roadmap(project_id=project_id, raw_json={})
                db.add(roadmap)
                await db.flush()
                checkpoint = Checkpoint(
                    roadmap_id=roadmap.id,
                    title="Checkpoint",
                    order=1,
                    brief={},
                )
                db.add(checkpoint)
                await db.flush()
                session = AgentSession(
                    learner_id=learner_id,
                    session_type="checkpoint",
                    project_id=project_id,
                    checkpoint_id=checkpoint.id,
                    title="Checkpoint Tutor",
                )
                db.add(session)
                await db.commit()
                return checkpoint.id, session.id

        checkpoint_id, session_id = asyncio.run(create_scope())
        agent_read = client.get(
            f"/api/projects/{project_id}/workspace/agent-files/lesson.py",
            headers=DESKTOP_HEADERS,
            params={"checkpoint_id": checkpoint_id, "session_id": session_id},
        )
        assert agent_read.status_code == 200
        assert agent_read.json()["content"] == "value = 1\n"
        secret_read = client.get(
            f"/api/projects/{project_id}/workspace/agent-files/.env.development",
            headers=DESKTOP_HEADERS,
            params={"checkpoint_id": checkpoint_id, "session_id": session_id},
        )
        assert secret_read.status_code == 403
        secret_denied = client.post(
            f"/api/projects/{project_id}/workspace/operations/propose",
            headers=DESKTOP_HEADERS,
            json={
                "actor": "agent",
                "operation": "create",
                "target_path": ".env.development",
                "content": "TOKEN=secret\n",
                "checkpoint_id": checkpoint_id,
                "session_id": session_id,
                "idempotency_key": "agent-secret-denied",
            },
        )
        assert secret_denied.status_code == 403
        proposed = client.post(
            f"/api/projects/{project_id}/workspace/operations/propose",
            headers=DESKTOP_HEADERS,
            json={
                "actor": "agent",
                "operation": "write",
                "target_path": "lesson.py",
                "content": "value = 2\n",
                "base_hash": current["sha256"],
                "checkpoint_id": checkpoint_id,
                "session_id": session_id,
                "idempotency_key": "agent-write-1",
            },
        )
        assert proposed.status_code == 200, proposed.text
        proposal = proposed.json()
        assert proposal["status"] == "proposed"
        assert "-value = 1" in proposal["result"]["diff"]
        assert target.read_text(encoding="utf-8") == "value = 1\n"

        confirmed = client.post(
            f"/api/projects/{project_id}/workspace/operations/{proposal['id']}/confirm",
            headers=DESKTOP_HEADERS,
        )
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["status"] == "applied"
        assert target.read_text(encoding="utf-8") == "value = 2\n"
        repeated = client.post(
            f"/api/projects/{project_id}/workspace/operations/{proposal['id']}/confirm",
            headers=DESKTOP_HEADERS,
        )
        assert repeated.status_code == 200
        assert repeated.json()["id"] == proposal["id"]


def test_traversal_links_protected_paths_delete_restore_and_user_isolation(tmp_path, monkeypatch):
    enable_desktop(monkeypatch)
    root = tmp_path / "project"
    root.mkdir()
    (root / "delete-me.txt").write_text("recover me", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    (root / "outside-link.txt").symlink_to(outside)

    with TestClient(app) as alice, TestClient(app) as bob:
        alice.post("/api/auth/register", json=registration("workspace_owner_alice"))
        bob.post("/api/auth/register", json=registration("workspace_owner_bob"))
        project = create_project(alice, "Alice Workspace")
        project_id = project["id"]
        assert link_workspace(alice, project_id, root).status_code == 200

        assert bob.get(
            f"/api/projects/{project_id}/workspace/tree", headers=DESKTOP_HEADERS,
        ).status_code == 404
        assert alice.get(
            f"/api/projects/{project_id}/workspace/files/%2E%2E%2Foutside.txt",
            headers=DESKTOP_HEADERS,
        ).status_code in {400, 404}
        assert alice.get(
            f"/api/projects/{project_id}/workspace/files/.learnflow/project.lfproject",
            headers=DESKTOP_HEADERS,
        ).status_code == 403
        assert alice.get(
            f"/api/projects/{project_id}/workspace/files/outside-link.txt",
            headers=DESKTOP_HEADERS,
        ).status_code == 403

        current = alice.get(
            f"/api/projects/{project_id}/workspace/files/delete-me.txt", headers=DESKTOP_HEADERS,
        ).json()
        proposed = alice.post(
            f"/api/projects/{project_id}/workspace/operations/propose",
            headers=DESKTOP_HEADERS,
            json={
                "actor": "user",
                "operation": "delete",
                "target_path": "delete-me.txt",
                "base_hash": current["sha256"],
                "idempotency_key": "delete-1",
            },
        )
        assert proposed.status_code == 200
        assert (root / "delete-me.txt").exists()
        deleted = alice.post(
            f"/api/projects/{project_id}/workspace/operations/{proposed.json()['id']}/confirm",
            headers=DESKTOP_HEADERS,
        )
        assert deleted.status_code == 200
        assert not (root / "delete-me.txt").exists()
        trash_path = root / deleted.json()["result"]["trash_path"]
        assert trash_path.exists()

        restore = alice.post(
            f"/api/projects/{project_id}/workspace/operations/propose",
            headers=DESKTOP_HEADERS,
            json={
                "actor": "user",
                "operation": "restore",
                "target_path": "delete-me.txt",
                "source_operation_id": deleted.json()["id"],
                "idempotency_key": "restore-1",
            },
        )
        assert restore.status_code == 200, restore.text
        restored = alice.post(
            f"/api/projects/{project_id}/workspace/operations/{restore.json()['id']}/confirm",
            headers=DESKTOP_HEADERS,
        )
        assert restored.status_code == 200, restored.text
        assert (root / "delete-me.txt").read_text(encoding="utf-8") == "recover me"
        delete_history = alice.get(
            f"/api/projects/{project_id}/workspace/operations",
            params={"operation": "delete", "status": "applied"},
            headers=DESKTOP_HEADERS,
        )
        assert delete_history.status_code == 200
        assert delete_history.json()["operations"][0]["result"]["restorable"] is False

        async def operation_count():
            async with async_session() as db:
                return await db.scalar(select(func.count(WorkspaceOperation.id)).where(
                    WorkspaceOperation.project_id == project_id,
                ))

        assert asyncio.run(operation_count()) == 2


def test_managed_learning_files_drafts_annotations_and_formal_evidence_are_separate(
    tmp_path, monkeypatch,
):
    enable_desktop(monkeypatch)
    root = tmp_path / "runtime-project"
    root.mkdir()
    script = root / "answer.py"
    script.write_text("import sys\nprint(sys.argv[1] if len(sys.argv) > 1 else 2)\n", encoding="utf-8")

    with TestClient(app) as client:
        registered = client.post("/api/auth/register", json=registration("workspace_runtime_user"))
        learner_id = registered.json()["learner_id"]
        project = create_project(client, "Runtime Project")
        project_id = project["id"]
        assert link_workspace(client, project_id, root).status_code == 200

        assert client.put(
            f"/api/projects/{project_id}/workspace/runtime/config",
            headers=DESKTOP_HEADERS,
            json={"interpreter_path": "/usr/bin/python3"},
        ).status_code == 404
        assert client.post(
            f"/api/projects/{project_id}/workspace/runs",
            headers=DESKTOP_HEADERS,
            json={
                "actor": "user", "mode": "syntax", "path": "answer.py", "args": [],
                "confirmed": True, "idempotency_key": "syntax-answer-1",
            },
        ).status_code == 404

        async def seed_exercise_scope():
            async with async_session() as db:
                roadmap = Roadmap(project_id=project_id, raw_json={})
                db.add(roadmap)
                await db.flush()
                checkpoint = Checkpoint(roadmap_id=roadmap.id, title="Runtime", order=1, brief={})
                db.add(checkpoint)
                await db.flush()
                exercise = Exercise(
                    checkpoint_id=checkpoint.id,
                    title="Bound answer",
                    starter_code="print(0)",
                    test_cases=[{"input": "", "expected": "2"}],
                    order=1,
                )
                lecture = Lecture(
                    checkpoint_id=checkpoint.id, version=1, status="published",
                    sections=[{"title": "Intro", "content": "alpha beta", "keywords": [], "questions": []}],
                )
                session = AgentSession(
                    learner_id=learner_id, session_type="checkpoint",
                    project_id=project_id, checkpoint_id=checkpoint.id,
                    title="Checkpoint Tutor",
                )
                db.add_all([exercise, lecture, session])
                await db.commit()
                return checkpoint.id, exercise.id, lecture.id, session.id

        checkpoint_id, exercise_id, lecture_id, _ = asyncio.run(seed_exercise_scope())
        artifacts = client.get(f"/api/checkpoints/{checkpoint_id}/workspace/artifacts")
        assert artifacts.status_code == 200
        assert artifacts.json()["managed_lecture"]["logical_filename"].endswith(".lflecture")
        assert artifacts.json()["managed_exercises"][0]["logical_filename"].endswith(".lfexercise")

        saved = client.put(f"/api/checkpoints/{checkpoint_id}/lecture", json={
            "sections": [{"title": "Intro", "content": "alpha changed", "keywords": [], "questions": []}],
            "base_version": 1, "idempotency_key": "lecture-edit-1",
        })
        assert saved.status_code == 200, saved.text
        assert saved.json()["version"] == 2
        lecture_descriptor = (
            root / ".learnflow" / "checkpoints" / f"cp-{checkpoint_id}"
            / "lectures" / f"lecture-{lecture_id}.lflecture"
        )
        assert lecture_descriptor.is_file()
        assert json.loads(lecture_descriptor.read_text(encoding="utf-8"))["version"] == 2
        stale = client.put(f"/api/checkpoints/{checkpoint_id}/lecture", json={
            "sections": [{"title": "Bad", "content": "overwrite"}],
            "base_version": 1, "idempotency_key": "lecture-edit-stale",
        })
        assert stale.status_code == 409

        annotation = client.post(
            f"/api/artifacts/lecture/{lecture_id}/annotations",
            json={
                "anchor": {"section_index": 0, "selection": "alpha changed"},
                "body": "remember", "idempotency_key": "lecture-note-1",
            },
        )
        assert annotation.status_code == 200, annotation.text
        orphaning = client.put(f"/api/checkpoints/{checkpoint_id}/lecture", json={
            "sections": [{"title": "Intro", "content": "completely different"}],
            "base_version": 2, "idempotency_key": "lecture-edit-2",
        })
        assert orphaning.status_code == 200
        notes = client.get(f"/api/artifacts/lecture/{lecture_id}/annotations")
        assert notes.json()[0]["status"] == "orphaned"

        draft = client.put(f"/api/exercises/{exercise_id}/draft", json={
            "code": "print(2)", "files": [],
        })
        assert draft.status_code == 200
        loaded_draft = client.get(f"/api/exercises/{exercise_id}/draft")
        assert loaded_draft.json()["code"] == "print(2)"
        run = client.post(f"/api/exercises/{exercise_id}/run", json={"code": "print(2)", "files": []})
        assert run.status_code == 200

        submission_id = "formal-bound-submit-1"
        submitted = client.post(
            f"/api/exercises/{exercise_id}/submit",
            json={
                "code": "print(2)", "files": [], "client_submission_id": submission_id,
            },
        )
        assert submitted.status_code == 200, submitted.text
        assert submitted.json()["passed"] == 1
        replay = client.post(
            f"/api/exercises/{exercise_id}/submit",
            json={
                "code": "print(999)", "files": [], "client_submission_id": submission_id,
            },
        )
        assert replay.status_code == 200
        assert replay.json()["idempotent_replay"] is True
        assert replay.json()["attempt_id"] == submitted.json()["attempt_id"]
        async def verify_ledgers():
            async with async_session() as db:
                attempt = await db.get(LearningAttempt, submitted.json()["attempt_id"])
                run_events = list((await db.execute(select(EvidenceEvent).where(
                    EvidenceEvent.learner_id == learner_id,
                    EvidenceEvent.event_type == "exercise_attempt_evaluated",
                ))).scalars().all())
                attempts = await db.scalar(select(func.count(LearningAttempt.id)).where(
                    LearningAttempt.learner_id == learner_id,
                    LearningAttempt.item_id == exercise_id,
                ))
                versions = await db.scalar(select(func.count(LectureVersion.id)).where(
                    LectureVersion.checkpoint_id == checkpoint_id,
                ))
                note = await db.get(ArtifactAnnotation, annotation.json()["id"])
                return dict(attempt.submission or {}), len(run_events), attempts, versions, note.status

        submission, assessment_count, attempt_count, version_count, note_status = asyncio.run(verify_ledgers())
        assert "workspace_bindings" not in submission
        assert assessment_count == 1
        assert attempt_count == 1
        assert version_count == 2
        assert note_status == "orphaned"
