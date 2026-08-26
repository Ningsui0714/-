from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
import uuid

from fastapi.testclient import TestClient

from app.api import learning_task_plan
from app.main import app


def _registration(username: str) -> dict:
    return {
        "username": username,
        "password": "learnflow-pass-123",
        "display_name": username,
        "education_stage": "undergraduate",
        "background": "计算机基础",
        "focus_areas": ["工程实践"],
        "weekly_hours": 5,
        "preferred_modes": ["practice"],
        "career_goal": "",
        "career_goal_status": "exploring",
    }


def _run() -> dict:
    run_id = "run_abcdef0123456789abcdef0123456789"
    fingerprint = "b" * 64
    return {
        "schema_version": "learning-work-task-agent-state-v1",
        "run_id": run_id,
        "phase": "CONTRACT_READY",
        "status": "active",
        "checkpoint_version": 1,
        "task_contract": {
            "raw_input": "Linux系统安装与基础配置",
            "input_level": "single_work_task",
            "semantic_fingerprint": fingerprint,
        },
        "plan": {
            "schema_version": "learning-work-task-plan-v1",
            "run_id": run_id,
            "plan_version": 1,
            "goal": "形成Linux系统安装与基础配置的可执行任务计划。",
            "task_contract_fingerprint": fingerprint,
            "success_criteria": ["保持任务语义", "步骤可以执行", "产物可以验收"],
            "unknowns": [],
            "work_packages": [{
                "package_id": "wp_evidence",
                "agent_role": "evidence_explorer",
                "objective": "检索并验证任务所需的真实作业证据。",
                "depends_on": [],
                "allowed_tools": ["task_database", "evidence_verifier"],
                "expected_artifact": "evidence_ledger",
                "completion_condition": "所有关键事实均具有可追溯来源。",
            }],
            "repair_budget": 2,
            "stop_conditions": ["任务语义发生变化时终止。"],
        },
        "state": {"phase": "CONTRACT_READY"},
        "next_actions": ["审核并提交 TaskPlan"],
    }


class _FakePlanGateway:
    def __init__(self):
        self.run = _run()
        self.create_calls = 0

    async def create(self, query: str):
        assert query == "Linux系统安装与基础配置"
        self.create_calls += 1
        return deepcopy(self.run)

    async def get(self, run_id: str):
        assert run_id == self.run["run_id"]
        return deepcopy(self.run)

    async def confirm(self, run_id: str, *, expected_plan_version: int):
        assert run_id == self.run["run_id"]
        if self.run["phase"] == "CONTRACT_READY":
            assert expected_plan_version == 1
            self.run["phase"] = "PLAN_READY"
            self.run["checkpoint_version"] = 2
            self.run["plan"]["plan_version"] = 2
        return deepcopy(self.run)


def test_analysis_for_rebuilds_shallow_v3_cache():
    run = _run()
    shallow = {
        "schema_version": "learning-work-task-planning-analysis-v3",
        "run_id": run["run_id"],
        "plan_version": run["plan"]["plan_version"],
        "metrics": {"stage_substep_count": 24},
        "stages": [],
    }

    analysis = learning_task_plan._analysis_for(
        run,
        SimpleNamespace(meta_data={"planning_analysis": shallow}),
    )

    assert analysis is not shallow
    assert analysis["metrics"]["stage_substep_count"] >= 140


def test_plan_api_creates_recovers_and_confirms_owned_run(monkeypatch):
    fake = _FakePlanGateway()
    monkeypatch.setattr(learning_task_plan, "_gateway", lambda: fake)
    with TestClient(app) as client:
        username = f"plan_{uuid.uuid4().hex[:10]}"
        assert client.post("/api/auth/register", json=_registration(username)).status_code == 200
        session = client.post(
            "/api/agent/sessions", json={"session_type": "global"}
        ).json()
        request = {
            "query": "Linux系统安装与基础配置",
            "session_id": session["id"],
            "client_turn_id": "plan-turn-001",
        }

        first = client.post("/api/learning-task-conversion/plans", json=request)
        replay = client.post("/api/learning-task-conversion/plans", json=request)
        run_id = first.json()["run_id"]
        recovered = client.get(f"/api/learning-task-conversion/plans/{run_id}")
        confirmed = client.post(
            f"/api/learning-task-conversion/plans/{run_id}/confirm",
            json={"expected_plan_version": 1, "client_event_id": "confirm-001"},
        )

        assert first.status_code == 200
        assert replay.status_code == 200
        assert fake.create_calls == 1
        assert recovered.status_code == 200
        assert confirmed.status_code == 200
        assert confirmed.json()["phase"] == "PLAN_READY"
        assert confirmed.json()["plan"]["plan_version"] == 2
        assert confirmed.json()["planning_analysis"]["analysis_version"] == 1
        assert confirmed.json()["planning_analysis"]["schema_version"] == (
            "learning-work-task-planning-analysis-v3"
        )
        assert confirmed.json()["planning_analysis"]["hierarchy"] == []
        assert confirmed.json()["planning_analysis"]["candidates"] == []
        assert confirmed.json()["planning_analysis"]["critics"] == []
        assert len(confirmed.json()["planning_analysis"]["stages"]) == 6
        assert confirmed.json()["planning_analysis"]["stages"][2]["status"] == "completed"
        assert confirmed.json()["planning_analysis"]["stages"][3]["status"] == "blocked"
        assert confirmed.json()["planning_analysis"]["stages"][-1]["status"] == "not_started"
        assert confirmed.json()["planning_analysis"]["execution_checklist"] == []

        replanned = client.post(
            f"/api/learning-task-conversion/plans/{run_id}/replan",
            json={
                "target_package_id": "wp_evidence",
                "failure_code": "evidence_gap",
                "observation": "当前来源不足以支持验收标准，需要刷新证据。",
                "expected_analysis_version": 1,
                "client_event_id": "replan-001",
            },
        )
        assert replanned.status_code == 409
        assert "学习型任务 Plan 尚未生成" in replanned.json()["detail"]

        loaded_session = client.get(f"/api/agent/sessions/{session['id']}").json()
        plan_messages = [
            item for item in loaded_session["messages"]
            if item.get("meta_data", {}).get("message_kind") == "learning_task_plan"
        ]
        assert len(plan_messages) == 1
        assert plan_messages[0]["meta_data"]["confirmed_plan_version"] == 2
        assert plan_messages[0]["meta_data"]["planning_analysis"]["analysis_version"] == 1


def test_plan_api_requires_login_and_learner_ownership(monkeypatch):
    fake = _FakePlanGateway()
    monkeypatch.setattr(learning_task_plan, "_gateway", lambda: fake)
    with TestClient(app) as client:
        assert client.post("/api/learning-task-conversion/plans", json={
            "query": "Linux系统安装与基础配置",
            "session_id": 1,
            "client_turn_id": "anonymous-plan",
        }).status_code == 401

        first_user = f"plan_owner_{uuid.uuid4().hex[:10]}"
        assert client.post("/api/auth/register", json=_registration(first_user)).status_code == 200
        session = client.post(
            "/api/agent/sessions", json={"session_type": "global"}
        ).json()
        created = client.post("/api/learning-task-conversion/plans", json={
            "query": "Linux系统安装与基础配置",
            "session_id": session["id"],
            "client_turn_id": "owner-plan",
        }).json()

        assert client.post("/api/auth/logout").status_code == 200
        second_user = f"plan_other_{uuid.uuid4().hex[:10]}"
        assert client.post("/api/auth/register", json=_registration(second_user)).status_code == 200
        assert client.get(
            f"/api/learning-task-conversion/plans/{created['run_id']}"
        ).status_code == 404
