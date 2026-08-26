from __future__ import annotations

import asyncio
import uuid

from fastapi.testclient import TestClient

from app.api import learning_task_conversion
from app.main import app
from app.services.learning_task_conversion_xfyun import XfyunWorkflowError
from app.services.personalized_learning_handoff import (
    scoped_personalized_learning_entry_id,
)


class _FakeGateway:
    submitted_feedback = []
    submitted_upstream = []

    async def capabilities(self):
        return {
            "schema_version": "learning-task-conversion-capabilities-v1",
            "service": "learning-task-conversion",
        }

    async def generate_catalog_match(self, _query: str):
        return None

    async def task_bundle(self, task_card_id: str):
        return {
            "schema_version": "learning-task-conversion-integration-bundle-v1",
            "task_card_id": task_card_id,
            "verification_status": "verified",
            "task": {
                "schema_version": "learning-task-to-personalized-learning-v1",
                "work_task": {
                    "work_task_id": "task-unity-camera",
                    "enterprise_task_name": "Unity摄像机跟随模块开发",
                    "enterprise_task_description": "完成跟随、遮挡检测和验收。",
                    "teaching_task_name": "Unity摄像机跟随学习型工作任务",
                    "teaching_task_description": "在实训环境中完成模块并提交验收记录。",
                    "work_situation": "在Unity项目中为第三人称角色开发摄像机模块。",
                    "task_steps": [
                        {
                            "step": 1,
                            "step_id": "step_01",
                            "name": "配置摄像机跟随",
                            "action": "配置Cinemachine跟随对象与阻尼。",
                            "deliverable": "摄像机配置",
                            "check": "摄像机平滑跟随角色",
                            "knowledge_point_ids": ["kp_camera"],
                            "skill_point_ids": ["sp_camera"],
                        }
                    ],
                    "knowledge_points": [
                        {
                            "knowledge_id": "kp_camera",
                            "display_code": "K1",
                            "name": "Cinemachine跟随与阻尼参数",
                            "scope": "理解跟随对象、构图与阻尼的作用。",
                            "learning_resources": [],
                        }
                    ],
                    "skill_points": [
                        {
                            "skill_id": "sp_camera",
                            "display_code": "S1",
                            "name": "配置第三人称摄像机",
                            "observable_action": "能完成跟随参数配置并验证。",
                        }
                    ],
                },
            },
            "strong_relationships": [
                {
                    "relation_id": "REL-CAMERA-01",
                    "knowledge_id": "kp_camera",
                    "skill_id": "sp_camera",
                    "relation_type": "required_for_step",
                    "strength": "high",
                    "applies_to_steps": ["配置摄像机跟随"],
                    "reason": "知识点直接支撑本步骤技能动作。",
                }
            ],
            "artifacts": {
                "interactive_html_url": f"https://example.test/tasks/{task_card_id}/interactive.html",
                "pdf_url": f"https://example.test/tasks/{task_card_id}/document.pdf",
                "personalized_learning_json_url": f"https://example.test/tasks/{task_card_id}/personalized-learning.json",
                "feedback_json_url": f"https://example.test/tasks/{task_card_id}/feedback.json",
            },
        }

    async def submit_upstream_handoff(self, payload):
        self.submitted_upstream.append(payload)
        return {"status": "accepted", "upstream_task_id": payload["upstream_task_id"]}

    async def personalized_learning_handoff(self, task_card_id: str):
        return {
            "schema_version": "learning-task-to-personalized-learning-v1",
            "task_card_id": task_card_id,
            "work_task": {"task_steps": [{"step_id": "step_01"}]},
        }

    async def submit_downstream_feedback(self, payload):
        self.submitted_feedback.append(payload)
        return {"status": "accepted", "task_card_id": payload["task_card_id"]}


class _FakeXfyunClient:
    def __init__(self):
        self.calls = []

    async def run(self, user_input: str, *, uid: str):
        self.calls.append({"user_input": user_input, "uid": uid})
        return {
            "schema_version": "learning-task-conversion-xfyun-run-v1",
            "provider": "xunfei-xingchen",
            "app_id": "app-test",
            "flow_id": "flow-test",
            "run_id": "run-test",
            "content": (
                "[打开任务网页](https://example.test/api/v1/learning-task-conversion/"
                "tasks/ltc_generated_01/interactive.html)"
            ),
            "usage": {},
        }


class _CatalogGateway(_FakeGateway):
    async def generate_catalog_match(self, query: str):
        assert query == "windows系统的安装"
        return "ltc_catalog_windows_01"


class _FakePersonalizedLearningClient:
    def __init__(self):
        self.imports = []

    async def import_entry(self, *, learner_id: int, handoff: dict):
        self.imports.append({"learner_id": learner_id, "handoff": handoff})
        knowledge_id = handoff["focus"]["knowledge_point"]["knowledge_id"]
        entry_id = scoped_personalized_learning_entry_id(
            handoff["entry_id"], learner_id,
        )
        return {
            "status": "ok",
            "entry_id": entry_id,
            "project_id": "PROJ-DOWNSTREAM-001",
            "knowledge_point_id": knowledge_id,
            "redirect_url": (
                "http://127.0.0.1:4173/?project_id=PROJ-DOWNSTREAM-001"
                f"&knowledge_point_id={knowledge_id}&entry_id={entry_id}"
            ),
            "content_generation": {
                "provider": "deterministic_template",
                "model": "",
                "configured": False,
            },
            "assessment": {
                "type": "provisional_self_check",
                "status": "ready",
                "formal_evidence": False,
            },
            "created": True,
        }


class _StageConflictThenSuccessClient(_FakeXfyunClient):
    async def run(self, user_input: str, *, uid: str):
        if not self.calls:
            self.calls.append({"user_input": user_input, "uid": uid})
            raise XfyunWorkflowError(
                "讯飞星辰工作流执行失败(21812): 当前阶段 INTAKE 不接受计划提交"
            )
        return await super().run(user_input, uid=uid)


class _StageConflictClient(_FakeXfyunClient):
    async def run(self, user_input: str, *, uid: str):
        self.calls.append({"user_input": user_input, "uid": uid})
        raise XfyunWorkflowError(
            "讯飞星辰工作流执行失败(21812): 当前阶段 INTAKE 不接受计划提交"
        )


class _WorkflowSelfLinkClient(_FakeXfyunClient):
    async def run(self, user_input: str, *, uid: str):
        self.calls.append({"user_input": user_input, "uid": uid})
        return {
            "run_id": "run-without-task",
            "content": (
                "岗位典型工作任务转化结果\n"
                "[打开交互式任务页]()\n"
                "[下载 PDF](https://agent.xfyun.cn/agentbuilder/work_flow/demo/arrange)"
            ),
            "usage": {},
        }


class _ClarificationWithInternalLinkClient(_FakeXfyunClient):
    async def run(self, user_input: str, *, uid: str):
        self.calls.append({"user_input": user_input, "uid": uid})
        return {
            "run_id": "run-clarification-with-internal-link",
            "content": (
                "请补充一个具体任务。"
                "[继续编排](https://agent.xfyun.cn/agentbuilder/work_flow/internal)"
                "[空入口]()"
            ),
            "usage": {},
        }


class _NeedsRevisionThenSuccessClient(_FakeXfyunClient):
    async def run(self, user_input: str, *, uid: str):
        if not self.calls:
            self.calls.append({"user_input": user_input, "uid": uid})
            return {
                "run_id": "run-needs-revision",
                "content": (
                    '{"schema_version":"learning-work-task-targeted-patch-v1",'
                    '"targets":[{"step_id":"step_01",'
                    '"reason_codes":["CHECK_NOT_VERIFIABLE"]}]}'
                ),
                "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
            }
        return await super().run(user_input, uid=uid)


class _SlowRejectedPrimaryFastSuccessfulRepairClient(_FakeXfyunClient):
    async def run(self, user_input: str, *, uid: str):
        call_index = len(self.calls)
        self.calls.append({"user_input": user_input, "uid": uid})
        if call_index == 0:
            await asyncio.sleep(0.08)
            return {
                "run_id": "run-slow-rejected-primary",
                "content": '{"hard_errors":["CHECK_NOT_VERIFIABLE"]}',
                "usage": {"total_tokens": 100},
            }
        await asyncio.sleep(0.01)
        return {
            "run_id": "run-fast-successful-repair",
            "content": (
                "https://example.test/api/v1/learning-task-conversion/"
                "tasks/ltc_speculative_01/interactive.html"
            ),
            "usage": {"total_tokens": 80},
        }


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


def test_learning_task_conversion_proxy_requires_login_and_keeps_task_id(monkeypatch):
    fake_xfyun = _FakeXfyunClient()
    monkeypatch.setattr(learning_task_conversion, "_gateway", lambda: _FakeGateway())
    monkeypatch.setattr(learning_task_conversion, "_xfyun_client", lambda: fake_xfyun)
    with TestClient(app) as client:
        assert client.get("/api/learning-task-conversion/capabilities").status_code == 401
        username = f"conversion_{uuid.uuid4().hex[:10]}"
        assert client.post("/api/auth/register", json=_registration(username)).status_code == 200

        capabilities = client.get("/api/learning-task-conversion/capabilities")
        assert capabilities.status_code == 200
        assert capabilities.json()["service"] == "learning-task-conversion"

        bundle = client.get(
            "/api/learning-task-conversion/tasks/ltc_contract_01/bundle"
        )
        assert bundle.status_code == 200
        assert bundle.json()["task_card_id"] == "ltc_contract_01"

        invalid = client.get(
            "/api/learning-task-conversion/tasks/not%20valid/bundle"
        )
        assert invalid.status_code == 422

        workflow_run = client.post(
            "/api/learning-task-conversion/workflow-runs",
            json={"user_input": "Windows 11系统重装与驱动配置"},
        )
        assert workflow_run.status_code == 200
        assert workflow_run.json()["provider"] == "xunfei-xingchen"
        assert fake_xfyun.calls[0]["user_input"] == "Windows 11系统重装与驱动配置"
        assert fake_xfyun.calls[0]["uid"].startswith("lf-")
        assert len(fake_xfyun.calls[0]["uid"]) <= 40

        generated = client.post(
            "/api/learning-task-conversion/generate",
            json={"query": "Windows 11系统重装与驱动配置"},
        )
        assert generated.status_code == 200
        assert generated.json()["schema_version"] == "learnflow-learning-task-generation-v2"
        assert generated.json()["task_card_id"] == "ltc_generated_01"
        assert generated.json()["bundle"]["task_card_id"] == "ltc_generated_01"
        assert fake_xfyun.calls[0]["uid"] != fake_xfyun.calls[1]["uid"]


def test_learning_task_integration_generates_embeddable_artifact(monkeypatch):
    fake_xfyun = _FakeXfyunClient()
    monkeypatch.setattr(learning_task_conversion, "_gateway", lambda: _FakeGateway())
    monkeypatch.setattr(learning_task_conversion, "_xfyun_client", lambda: fake_xfyun)
    with TestClient(app) as client:
        username = f"conversion_embed_{uuid.uuid4().hex[:10]}"
        assert client.post("/api/auth/register", json=_registration(username)).status_code == 200

        generated = client.post(
            "/api/learning-task-conversion/integration-generate",
            json={"query": "Unity第三人称摄像机跟随模块开发", "student_id": "STU-001"},
        )

        assert generated.status_code == 200
        payload = generated.json()
        assert payload["status"] == "success"
        assert payload["task_card_id"] == "ltc_generated_01"
        assert payload["artifact_url"].endswith("/ltc_generated_01/interactive.html")

        empty_run = client.post(
            "/api/learning-task-conversion/workflow-runs",
            json={"user_input": "  "},
        )
        assert empty_run.status_code == 422


def test_learning_task_integration_auto_repairs_clear_rejected_task(monkeypatch):
    fake_xfyun = _NeedsRevisionThenSuccessClient()
    monkeypatch.setattr(learning_task_conversion, "_gateway", lambda: _FakeGateway())
    monkeypatch.setattr(learning_task_conversion, "_xfyun_client", lambda: fake_xfyun)
    with TestClient(app) as client:
        username = f"auto_repair_{uuid.uuid4().hex[:10]}"
        assert client.post("/api/auth/register", json=_registration(username)).status_code == 200

        generated = client.post(
            "/api/learning-task-conversion/integration-generate",
            json={
                "query": "配置交换机VLAN与Trunk并验收跨VLAN连通性",
                "student_id": "STU-001",
            },
        )

        assert generated.status_code == 200
        payload = generated.json()
        assert payload["status"] == "success"
        assert payload["task_card_id"] == "ltc_generated_01"
        assert len(fake_xfyun.calls) == 2
        repair_input = fake_xfyun.calls[1]["user_input"]
        assert repair_input.startswith("配置交换机VLAN与Trunk并验收跨VLAN连通性\n")
        assert "不反问、不换题" in repair_input
        assert "Plan的repair_budget=1" in repair_input
        assert len(repair_input) <= 500
        assert fake_xfyun.calls[0]["uid"] != fake_xfyun.calls[1]["uid"]


def test_learning_task_generation_reuses_reviewed_catalog_before_xingchen(monkeypatch):
    fake_xfyun = _FakeXfyunClient()
    monkeypatch.setattr(
        learning_task_conversion, "_gateway", lambda: _CatalogGateway()
    )
    monkeypatch.setattr(
        learning_task_conversion, "_xfyun_client", lambda: fake_xfyun
    )
    with TestClient(app) as client:
        username = f"catalog_first_{uuid.uuid4().hex[:10]}"
        assert client.post(
            "/api/auth/register", json=_registration(username)
        ).status_code == 200

        generated = client.post(
            "/api/learning-task-conversion/generate",
            json={"query": "windows系统的安装"},
        )

        assert generated.status_code == 200
        payload = generated.json()
        assert payload["status"] == "success"
        assert payload["task_card_id"] == "ltc_catalog_windows_01"
        assert payload["execute_id"] == "catalog:ltc_catalog_windows_01"
        assert fake_xfyun.calls == []


def test_auto_revision_prompt_distinguishes_role_from_single_work_task():
    task_prompt = learning_task_conversion._auto_revision_prompt(
        "新能源汽车电池包安装与验收", "CHECK_NOT_VERIFIABLE",
    )
    role_prompt = learning_task_conversion._auto_revision_prompt(
        "我想当网络工程师", "",
    )

    assert "明确的单个企业任务" in task_prompt
    assert "不得拆成多个任务" in task_prompt
    assert "检查点改成可观察、可记录或可测量" in task_prompt
    assert "自动选择其中一个可执行的典型企业任务" in role_prompt
    assert len(task_prompt) <= 500
    assert len(role_prompt) <= 500


def test_auto_revision_prompt_normalizes_learning_intent_and_battery_pack_object():
    prompt = learning_task_conversion._auto_revision_prompt(
        "我要学新能源汽车的电池安装",
        "候选内容没有保留任务对象",
    )

    assert "对象锚点为“新能源汽车的电池包”" in prompt
    assert "任务名称、描述和至少一个步骤必须原样写出该对象" in prompt
    assert "其余不足标待复核并继续生成" in prompt
    assert len(prompt) <= 500


def test_generation_uses_speculative_repair_without_adding_two_latencies(monkeypatch):
    fake_xfyun = _SlowRejectedPrimaryFastSuccessfulRepairClient()
    monkeypatch.setattr(learning_task_conversion, "_gateway", lambda: _FakeGateway())
    monkeypatch.setattr(learning_task_conversion, "_xfyun_client", lambda: fake_xfyun)
    monkeypatch.setattr(
        learning_task_conversion,
        "_SPECULATIVE_REPAIR_HEAD_START_SECONDS",
        0.005,
    )
    with TestClient(app) as client:
        username = f"spec_repair_{uuid.uuid4().hex[:10]}"
        assert client.post("/api/auth/register", json=_registration(username)).status_code == 200

        generated = client.post(
            "/api/learning-task-conversion/integration-generate",
            json={"query": "Windows系统安装与驱动配置", "student_id": "STU-001"},
        )

        payload = generated.json()
        assert generated.status_code == 200
        assert payload["status"] == "success"
        assert payload["task_card_id"] == "ltc_speculative_01"
        assert len(fake_xfyun.calls) == 2


def test_learning_task_generation_retries_one_stale_xingchen_stage(monkeypatch):
    fake_xfyun = _StageConflictThenSuccessClient()
    monkeypatch.setattr(learning_task_conversion, "_gateway", lambda: _FakeGateway())
    monkeypatch.setattr(learning_task_conversion, "_xfyun_client", lambda: fake_xfyun)
    with TestClient(app) as client:
        username = f"conversion_retry_{uuid.uuid4().hex[:10]}"
        assert client.post("/api/auth/register", json=_registration(username)).status_code == 200

        generated = client.post(
            "/api/learning-task-conversion/generate",
            json={"query": "Linux系统安装与基础配置"},
        )
        assert generated.status_code == 200
        assert generated.json()["task_card_id"] == "ltc_generated_01"
        assert len(fake_xfyun.calls) == 2


def test_learning_task_generation_persists_and_replays_session_turn(monkeypatch):
    fake_xfyun = _FakeXfyunClient()
    monkeypatch.setattr(learning_task_conversion, "_gateway", lambda: _FakeGateway())
    monkeypatch.setattr(learning_task_conversion, "_xfyun_client", lambda: fake_xfyun)
    with TestClient(app) as client:
        username = f"conversion_session_{uuid.uuid4().hex[:10]}"
        assert client.post("/api/auth/register", json=_registration(username)).status_code == 200
        session = client.post("/api/agent/sessions", json={"session_type": "global"}).json()
        payload = {
            "query": "Unity游戏客户端登录与场景加载模块开发",
            "session_id": session["id"],
            "client_turn_id": "conversion-turn-001",
        }

        first = client.post("/api/learning-task-conversion/generate", json=payload)
        second = client.post("/api/learning-task-conversion/generate", json=payload)

        assert first.status_code == 200
        assert second.status_code == 200
        assert second.json()["replayed"] is True
        assert len(fake_xfyun.calls) == 1
        assert "查看学习型任务" in first.json()["message"]
        assert "PDF" not in first.json()["message"]
        assert "JSON" not in first.json()["message"]
        loaded = client.get(f"/api/agent/sessions/{session['id']}").json()
        generated = [
            item for item in loaded["messages"]
            if item.get("meta_data", {}).get("message_kind") == "learning_task_generated"
        ]
        assert len(generated) == 1
        assert "/wf03/tasks/ltc_generated_01" in generated[0]["content"]


def test_learning_task_generation_persistence_tolerates_stale_replay_check(monkeypatch):
    fake_xfyun = _FakeXfyunClient()

    async def always_miss_replay(*_args, **_kwargs):
        return None

    monkeypatch.setattr(learning_task_conversion, "_gateway", lambda: _FakeGateway())
    monkeypatch.setattr(learning_task_conversion, "_xfyun_client", lambda: fake_xfyun)
    monkeypatch.setattr(
        learning_task_conversion,
        "_replay_generation_result",
        always_miss_replay,
    )
    with TestClient(app) as client:
        username = f"conversion_race_{uuid.uuid4().hex[:10]}"
        assert client.post("/api/auth/register", json=_registration(username)).status_code == 200
        session = client.post("/api/agent/sessions", json={"session_type": "global"}).json()
        payload = {
            "query": "Unity游戏客户端登录与场景加载模块开发",
            "session_id": session["id"],
            "client_turn_id": "conversion-race-001",
        }

        first = client.post("/api/learning-task-conversion/generate", json=payload)
        second = client.post("/api/learning-task-conversion/generate", json=payload)

        assert first.status_code == 200
        assert second.status_code == 200
        assert len(fake_xfyun.calls) == 2
        loaded = client.get(f"/api/agent/sessions/{session['id']}").json()
        matching_messages = [
            item for item in loaded["messages"]
            if item.get("meta_data", {}).get("client_turn_id") == "conversion-race-001"
        ]
        assert len(matching_messages) == 2


def test_learning_task_generation_turns_intake_conflict_into_clarification(monkeypatch):
    fake_xfyun = _StageConflictClient()
    monkeypatch.setattr(learning_task_conversion, "_xfyun_client", lambda: fake_xfyun)
    with TestClient(app) as client:
        username = f"conversion_clarify_{uuid.uuid4().hex[:10]}"
        assert client.post("/api/auth/register", json=_registration(username)).status_code == 200

        response = client.post(
            "/api/learning-task-conversion/generate",
            json={"query": "我还不知道"},
        )

        assert response.status_code == 200
        assert response.json()["status"] == "needs_clarification"
        assert response.json()["task_card_id"] == ""
        assert response.json()["bundle"] is None
        assert "请再补充一个可执行对象或结果" in response.json()["message"]
        assert len(fake_xfyun.calls) == 2


def test_learning_task_generation_never_exposes_empty_or_workflow_self_links(monkeypatch):
    fake_xfyun = _WorkflowSelfLinkClient()
    monkeypatch.setattr(learning_task_conversion, "_xfyun_client", lambda: fake_xfyun)
    with TestClient(app) as client:
        username = f"conversion_self_link_{uuid.uuid4().hex[:10]}"
        assert client.post("/api/auth/register", json=_registration(username)).status_code == 200

        response = client.post(
            "/api/learning-task-conversion/generate",
            json={"query": "Unity游戏客户端开发"},
        )

        payload = response.json()
        assert response.status_code == 200
        assert payload["status"] == "needs_revision"
        assert payload["task_card_id"] == ""
        assert payload["bundle"] is None
        assert "agent.xfyun.cn" not in payload["message"]
        assert "[]()" not in payload["message"]


def test_learning_task_clarification_never_exposes_workflow_content(monkeypatch):
    fake_xfyun = _ClarificationWithInternalLinkClient()
    monkeypatch.setattr(learning_task_conversion, "_xfyun_client", lambda: fake_xfyun)
    with TestClient(app) as client:
        username = f"safe_clarify_{uuid.uuid4().hex[:10]}"
        assert client.post("/api/auth/register", json=_registration(username)).status_code == 200

        response = client.post(
            "/api/learning-task-conversion/generate",
            json={"query": "我还不知道"},
        )

        payload = response.json()
        assert response.status_code == 200
        assert payload["status"] == "needs_clarification"
        assert "请再补充一个可执行对象或结果" in payload["message"]
        assert "agent.xfyun.cn" not in payload["message"]
        assert "[]()" not in payload["message"]


def test_learning_task_conversion_proxies_both_handoff_directions(monkeypatch):
    gateway = _FakeGateway()
    personalized = _FakePersonalizedLearningClient()
    monkeypatch.setattr(learning_task_conversion, "_gateway", lambda: gateway)
    monkeypatch.setattr(
        learning_task_conversion,
        "_personalized_learning_client",
        lambda: personalized,
    )
    with TestClient(app) as client:
        username = f"conversion_handoff_{uuid.uuid4().hex[:10]}"
        assert client.post("/api/auth/register", json=_registration(username)).status_code == 200

        upstream = {
            "schema_version": "competency-graph-learning-task-handoff-v1",
            "upstream_task_id": "unity-role-01",
            "correlation_id": "handoff-test-01",
            "task_name": "Unity 游戏客户端角色移动模块开发与验收",
        }
        upstream_response = client.post(
            "/api/learning-task-conversion/upstream-handoffs",
            json=upstream,
        )
        assert upstream_response.status_code == 200
        assert gateway.submitted_upstream[-1]["task_name"] == upstream["task_name"]

        handoff = client.get(
            "/api/learning-task-conversion/tasks/ltc_generated_01/personalized-learning"
        )
        assert handoff.status_code == 200
        assert handoff.json()["task_card_id"] == "ltc_generated_01"

        knowledge_entry = client.get(
            "/api/learning-task-conversion/tasks/ltc_generated_01/knowledge/"
            "kp_camera/personalized-learning-entry"
        )
        assert knowledge_entry.status_code == 200
        entry = knowledge_entry.json()
        assert entry["schema_version"] == (
            "learning-task-knowledge-to-personalized-learning-v1"
        )
        assert entry["focus"]["knowledge_point"]["knowledge_id"] == "kp_camera"
        assert entry["focus"]["source_steps"][0]["step_id"] == "step_01"
        assert entry["focus"]["strongly_related_skills"][0]["skill_id"] == "sp_camera"
        assert entry["focus"]["relationships"][0]["strength"] == "strong"
        assert entry["focus"]["relationships"][0]["step_id"] == "step_01"
        assert entry["focus"]["relationships"][0]["skill_ids"] == ["sp_camera"]
        assert "focus.relationships" in entry["generation_contract"]["immutable_fields"]

        opened = client.post(
            "/api/learning-task-conversion/tasks/ltc_generated_01/knowledge/"
            "kp_camera/personalized-learning-entry"
        )
        assert opened.status_code == 200
        assert opened.json()["navigation"]["entry_path"].endswith(
            "/ltc_generated_01/knowledge/kp_camera"
        )

        launched = client.post(
            "/api/learning-task-conversion/tasks/ltc_generated_01/knowledge/"
            "kp_camera/personalized-learning-launch"
        )
        assert launched.status_code == 200
        assert launched.json()["project_id"] == "PROJ-DOWNSTREAM-001"
        assert launched.json()["knowledge_point_id"] == "kp_camera"
        assert launched.json()["redirect_url"].startswith("http://127.0.0.1:4173/")
        assert len(personalized.imports) == 1
        assert personalized.imports[0]["learner_id"] > 0
        assert personalized.imports[0]["handoff"]["entry_id"] == entry["entry_id"]

        result_payload = {
            "schema_version": "personalized-learning-result-v1",
            "entry_id": launched.json()["entry_id"],
            "project_id": launched.json()["project_id"],
            "knowledge_point_id": "kp_camera",
            "result_type": "assessment_completed",
            "result_id": "assessment-provisional-001",
            "formal_evidence": False,
            "summary": {
                "assessment_type": "provisional_self_check",
                "score": 3,
                "total": 5,
                "weak_point_count": 1,
                "feedback": "本次为练习型初测。",
            },
        }
        result_url = (
            "/api/learning-task-conversion/tasks/ltc_generated_01/knowledge/"
            "kp_camera/personalized-learning-results"
        )
        received = client.post(result_url, json=result_payload)
        replayed = client.post(result_url, json=result_payload)
        assert received.status_code == 200
        assert replayed.status_code == 200
        assert received.json()["event_id"] == replayed.json()["event_id"]
        assert received.json()["formal_evidence"] is False

        rejected_formal = client.post(
            result_url,
            json={
                **result_payload,
                "result_id": "assessment-formal-001",
                "formal_evidence": True,
            },
        )
        assert rejected_formal.status_code == 422

        missing_knowledge = client.get(
            "/api/learning-task-conversion/tasks/ltc_generated_01/knowledge/"
            "kp_missing/personalized-learning-entry"
        )
        assert missing_knowledge.status_code == 404

        feedback = {
            "schema_version": "personalized-learning-to-task-conversion-feedback-v1",
            "task_card_id": "ltc_generated_01",
            "correlation_id": f"feedback-{uuid.uuid4().hex}",
            "source_system": "learnflow-task-review",
            "status": "accepted_with_feedback",
            "issues": [{"issue_id": "issue-01"}],
            "summary": "步骤映射需要复核",
        }
        feedback_response = client.post(
            "/api/learning-task-conversion/downstream-feedback",
            json=feedback,
        )
        assert feedback_response.status_code == 200
        assert gateway.submitted_feedback[-1]["task_card_id"] == "ltc_generated_01"

        submitted_count = len(gateway.submitted_feedback)
        invalid_feedback = {**feedback, "issues": {"issue_id": "not-an-array"}}
        invalid_feedback["correlation_id"] = f"invalid-{uuid.uuid4().hex}"
        invalid_response = client.post(
            "/api/learning-task-conversion/downstream-feedback",
            json=invalid_feedback,
        )
        assert invalid_response.status_code == 422
        assert len(gateway.submitted_feedback) == submitted_count
