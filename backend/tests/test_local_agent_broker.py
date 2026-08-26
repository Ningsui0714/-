from __future__ import annotations

import asyncio
from pathlib import Path
import time

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.config import settings
from app.db.database import async_session
from app.main import app
from app.models.learning import EvidenceEvent, KernelMutation
from app.models.project import (
    Checkpoint, LocalAgentProfile, LocalAgentRun, Project, Roadmap,
)
from app.services import local_agent_broker as broker
from app.services.local_agent_broker import CodexCliAdapter


DESKTOP_TOKEN = "local-agent-test-token"
HEADERS = {"X-LearnFlow-Desktop-Token": DESKTOP_TOKEN}


def registration(username: str):
    return {
        "username": username,
        "password": "learnflow-pass-123",
        "display_name": username,
        "education_stage": "undergraduate",
        "background": "Python 基础",
        "focus_areas": ["工程实践"],
        "weekly_hours": 5,
        "preferred_modes": ["practice", "project"],
        "career_goal": "",
        "career_goal_status": "exploring",
    }


def enable_desktop_demo(monkeypatch, run_dir: Path):
    monkeypatch.setattr(settings, "desktop_mode", True)
    monkeypatch.setattr(settings, "desktop_token", DESKTOP_TOKEN)
    monkeypatch.setattr(settings, "competition_demo_mode", True)
    monkeypatch.setattr(settings, "local_agent_runs_dir", str(run_dir))


def seed_project(client: TestClient, root: Path) -> tuple[int, int]:
    project_response = client.post("/api/projects", json={
        "name": "Broker Test", "description": "isolated Agent", "user_level": "beginner",
    })
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    async def seed_checkpoint():
        async with async_session() as db:
            project = await db.get(Project, project_id)
            roadmap = Roadmap(project_id=project.id, raw_json={})
            db.add(roadmap)
            await db.flush()
            checkpoint = Checkpoint(
                roadmap_id=roadmap.id, title="本地构建", description="Agent test", order=1,
                learning_status="in_progress",
            )
            db.add(checkpoint)
            await db.commit()
            return checkpoint.id

    checkpoint_id = asyncio.run(seed_checkpoint())
    linked = client.post(
        f"/api/projects/{project_id}/workspace/link", headers=HEADERS,
        json={"root_path": str(root), "platform": "test", "create": False, "client_request_id": f"broker-{project_id}"},
    )
    assert linked.status_code == 200, linked.text
    return project_id, checkpoint_id


def wait_for_run(client: TestClient, run_id: int) -> dict:
    for _ in range(100):
        response = client.get(f"/api/local-agent/runs/{run_id}", headers=HEADERS)
        assert response.status_code == 200, response.text
        data = response.json()
        if data["status"] in {"completed", "failed", "canceled", "stale", "applied"}:
            return data
        time.sleep(0.03)
    raise AssertionError("local Agent run did not finish")


def test_seeded_agent_requires_two_confirmations_and_writes_zero_kernel_events(tmp_path, monkeypatch):
    enable_desktop_demo(monkeypatch, tmp_path / "runs")
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "main.txt").write_text("original\n", encoding="utf-8")
    (root / ".env").write_text("SECRET=not-copied\n", encoding="utf-8")
    symlink_supported = True
    try:
        (root / "linked-secret").symlink_to(root / ".env")
    except OSError:
        symlink_supported = False

    with TestClient(app) as client:
        registered = client.post("/api/auth/register", json=registration("broker_two_confirmations"))
        assert registered.status_code == 200
        learner_id = registered.json()["learner_id"]
        project_id, checkpoint_id = seed_project(client, root)
        profiles = client.get("/api/desktop/agent-profiles", headers=HEADERS)
        assert profiles.status_code == 200
        fake = next(item for item in profiles.json() if item["adapter"] == "deterministic_fake")
        assert fake["network_policy"] == "managed_off"
        assert fake["last_probe"]["network_boundary_enforced"] is True

        session = client.post("/api/agent/sessions", json={
            "session_type": "checkpoint", "project_id": project_id, "checkpoint_id": checkpoint_id,
        }).json()
        proposal = client.post(f"/api/agent/sessions/{session['id']}/turns", json={
            "message": "请让本地 Agent 修改项目文件并补一个演示结果",
            "project_id": project_id, "checkpoint_id": checkpoint_id,
        })
        assert proposal.status_code == 200, proposal.text
        card = proposal.json()["action_card"]
        assert card["status"] == "pending_confirmation"
        assert card["target_summary"]["profile_name"] == "Seeded Demo Agent"
        assert card["target_summary"]["network_policy"] == "managed_off"
        assert not (root / "learnflow-seeded-agent.md").exists()

        without_token = client.post(f"/api/agent/actions/{card['id']}/confirm")
        assert without_token.status_code == 404
        confirmed = client.post(f"/api/agent/actions/{card['id']}/confirm", headers=HEADERS)
        assert confirmed.status_code == 200, confirmed.text
        run_id = confirmed.json()["executed_action"]["result"]["local_agent_run"]["id"]
        finished = wait_for_run(client, run_id)
        assert finished["status"] == "completed", finished
        assert finished["result"]["requires_second_confirmation"] is True
        assert finished["changed_files"][0]["path"] == "learnflow-seeded-agent.md"
        assert not (root / "learnflow-seeded-agent.md").exists()

        async def inspect_isolation_and_events():
            async with async_session() as db:
                run = await db.get(LocalAgentRun, run_id)
                isolation = Path(run.isolation_root)
                event_count = (await db.execute(select(func.count(EvidenceEvent.id)).where(
                    EvidenceEvent.learner_id == learner_id,
                    EvidenceEvent.event_type.in_(["local_agent_started", "local_agent_completed"]),
                ))).scalar_one()
                kernel_count = (await db.execute(select(func.count(KernelMutation.id)).where(
                    KernelMutation.learner_id == learner_id,
                ))).scalar_one()
                return isolation, event_count, kernel_count

        isolation, event_count, kernel_count_before_apply = asyncio.run(inspect_isolation_and_events())
        assert not (isolation / "base" / ".env").exists()
        assert not (isolation / "worktree" / ".env").exists()
        if symlink_supported:
            assert not (isolation / "base" / "linked-secret").exists()
        assert event_count == 2

        refused = client.post(f"/api/local-agent/runs/{run_id}/apply", headers=HEADERS, json={
            "confirm_apply": False, "confirmed_deletions": [], "confirmed_moves": [],
            "idempotency_key": "refused-apply",
        })
        assert refused.status_code == 400
        assert not (root / "learnflow-seeded-agent.md").exists()

        applied = client.post(f"/api/local-agent/runs/{run_id}/apply", headers=HEADERS, json={
            "confirm_apply": True, "confirmed_deletions": [], "confirmed_moves": [],
            "idempotency_key": "accepted-apply",
        })
        assert applied.status_code == 200, applied.text
        assert applied.json()["status"] == "applied"
        assert (root / "learnflow-seeded-agent.md").exists()

        async def kernel_count():
            async with async_session() as db:
                return (await db.execute(select(func.count(KernelMutation.id)).where(
                    KernelMutation.learner_id == learner_id,
                ))).scalar_one()

        assert asyncio.run(kernel_count()) == kernel_count_before_apply


def test_apply_rejects_stale_workspace_and_preserves_user_content(tmp_path, monkeypatch):
    enable_desktop_demo(monkeypatch, tmp_path / "runs")
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "learnflow-seeded-agent.md"
    target.write_text("baseline\n", encoding="utf-8")

    with TestClient(app) as client:
        assert client.post("/api/auth/register", json=registration("broker_stale_guard")).status_code == 200
        project_id, checkpoint_id = seed_project(client, root)
        client.get("/api/desktop/agent-profiles", headers=HEADERS)
        session = client.post("/api/agent/sessions", json={
            "session_type": "checkpoint", "project_id": project_id, "checkpoint_id": checkpoint_id,
        }).json()
        proposed = client.post(f"/api/agent/sessions/{session['id']}/turns", json={
            "message": "请让本地 Agent 修改项目文件",
            "project_id": project_id, "checkpoint_id": checkpoint_id,
        }).json()["action_card"]
        confirmed = client.post(f"/api/agent/actions/{proposed['id']}/confirm", headers=HEADERS).json()
        run_id = confirmed["executed_action"]["result"]["local_agent_run"]["id"]
        assert wait_for_run(client, run_id)["status"] == "completed"
        target.write_text("user changed after run\n", encoding="utf-8")
        stale = client.post(f"/api/local-agent/runs/{run_id}/apply", headers=HEADERS, json={
            "confirm_apply": True, "confirmed_deletions": [], "confirmed_moves": [],
            "idempotency_key": "stale-apply",
        })
        assert stale.status_code == 409
        assert target.read_text(encoding="utf-8") == "user changed after run\n"
        assert client.get(f"/api/local-agent/runs/{run_id}", headers=HEADERS).json()["status"] == "stale"


def test_delete_requires_separate_confirmation_and_batch_failure_rolls_back(tmp_path, monkeypatch):
    enable_desktop_demo(monkeypatch, tmp_path / "runs")
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "remove-me.txt"
    target.write_text("keep until second confirmation\n", encoding="utf-8")

    with TestClient(app) as client:
        registered = client.post("/api/auth/register", json=registration("broker_delete_confirm"))
        assert registered.status_code == 200
        learner_id = registered.json()["learner_id"]
        project_id, checkpoint_id = seed_project(client, root)
        session_response = client.post("/api/agent/sessions", json={
            "session_type": "checkpoint", "project_id": project_id, "checkpoint_id": checkpoint_id,
        }).json()

        async def seed_completed_run():
            async with async_session() as db:
                profile = LocalAgentProfile(
                    learner_id=learner_id, name="Manual Test Profile", adapter="deterministic_fake",
                    enabled=True, priority=10, task_types=["code_change"], capabilities=["code_edit"],
                    sandbox_policy="workspace_write", network_policy="managed_off", timeout_seconds=60,
                )
                db.add(profile)
                await db.flush()
                from app.models.learning import AgentAction
                action = AgentAction(
                    session_id=session_response["id"], learner_id=learner_id,
                    project_id=project_id, checkpoint_id=checkpoint_id,
                    capability="delegate_local_agent_task", status="completed",
                    side_effect="execution", confirmation_policy="explicit", target={},
                )
                db.add(action)
                await db.flush()
                run = LocalAgentRun(
                    learner_id=learner_id, project_id=project_id, checkpoint_id=checkpoint_id,
                    session_id=session_response["id"], action_id=action.id, profile_id=profile.id,
                    task_type="code_change", goal="delete", status="completed",
                    idempotency_key=f"manual-delete:{project_id}",
                    changed_files=[{
                        "operation": "delete", "path": "remove-me.txt",
                        "base_hash": broker.sha256_file(target), "new_hash": None,
                        "requires_separate_confirmation": True,
                    }],
                )
                db.add(run)
                await db.commit()
                return run.id

        run_id = asyncio.run(seed_completed_run())
        missing_confirmation = client.post(f"/api/local-agent/runs/{run_id}/apply", headers=HEADERS, json={
            "confirm_apply": True, "confirmed_deletions": [], "confirmed_moves": [],
            "idempotency_key": "missing-delete-confirmation",
        })
        assert missing_confirmation.status_code == 400
        assert target.exists()

        original_apply = broker.apply_operation
        def fail_after_delete(*args, **kwargs):
            original_apply(*args, **kwargs)
            raise RuntimeError("simulated batch failure")
        monkeypatch.setattr(broker, "apply_operation", fail_after_delete)
        failed = client.post(f"/api/local-agent/runs/{run_id}/apply", headers=HEADERS, json={
            "confirm_apply": True, "confirmed_deletions": ["remove-me.txt"], "confirmed_moves": [],
            "idempotency_key": "confirmed-delete",
        })
        assert failed.status_code == 500
        assert target.read_text(encoding="utf-8") == "keep until second confirmation\n"


def test_profile_contract_rejects_fake_shell_templates_and_false_network_claims(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "desktop_mode", True)
    monkeypatch.setattr(settings, "desktop_token", DESKTOP_TOKEN)
    monkeypatch.setattr(settings, "competition_demo_mode", False)
    with TestClient(app) as client:
        assert client.post("/api/auth/register", json=registration("broker_profile_contract")).status_code == 200
        fake = client.post("/api/desktop/agent-profiles", headers=HEADERS, json={
            "name": "not allowed", "adapter": "deterministic_fake",
            "network_policy": "managed_off", "executable_path": "/bin/sh -c anything",
        })
        assert fake.status_code in {403, 422}
        false_offline = client.post("/api/desktop/agent-profiles", headers=HEADERS, json={
            "name": "false offline", "adapter": "codex_cli", "network_policy": "managed_off",
        })
        assert false_offline.status_code == 422
        missing = client.post("/api/desktop/agent-profiles", headers=HEADERS, json={
            "name": "missing codex", "adapter": "codex_cli", "network_policy": "unmanaged",
            "executable_path": str(tmp_path / "missing-codex"),
        })
        assert missing.status_code == 200
        assert missing.json()["last_probe"]["available"] is False


def test_codex_adapter_uses_fixed_argument_array_without_shell(monkeypatch, tmp_path):
    captured: dict = {}

    class FakeStdin:
        def write(self, value): captured["prompt"] = value
        async def drain(self): return None
        def close(self): captured["closed"] = True

    class FakeProcess:
        stdin = FakeStdin()

    async def fake_exec(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return FakeProcess()

    executable = tmp_path / "codex"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(0o700)
    profile = LocalAgentProfile(
        learner_id=1, name="Codex", adapter="codex_cli", executable_path=str(executable),
        network_policy="unmanaged", sandbox_policy="workspace_write",
    )
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    asyncio.run(CodexCliAdapter().start(profile, tmp_path, "do the task"))
    assert captured["args"] == (
        str(executable.resolve()), "exec", "--json", "--sandbox", "workspace-write",
        "-C", str(tmp_path), "-",
    )
    assert "shell" not in captured["kwargs"]
    assert captured["kwargs"]["stderr"] == asyncio.subprocess.STDOUT
    assert captured["prompt"] == b"do the task"
