import asyncio
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.db.database import async_session, init_db
from app.models.learning import (
    AgentMessage, AgentSession, EvidenceEvent, KernelState, LearningProjectProposal,
    SchemaMigration,
)
from app.models.project import (
    Project, Source, Chunk, Roadmap, Checkpoint, CheckpointChunk, Lecture, Exercise,
    ProjectWorkspace,
)
from app.services.learning_runtime import (
    apply_semantic_observations, create_attempt, evaluate_checkpoint_status,
    get_kernel_projection, record_event,
)
from app.services.profile import memory_projection
from app.services.task_manager import manager
from app.services.auth import load_current_learner
from app.services.roadmap_agent import RoadmapAgent, SubmittedRoadmap
from app.services.tutor_service import _decode_tutor_content, get_or_create_session
from app.services.checkpoint_context import build_checkpoint_tutor_context
from app.services.task_runners import _repair_markdown_fences
from app.services import project_proposals as proposal_service
from app.api.phase1 import _roadmap_planning_context


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        accounts = test_client.get("/api/dev/accounts")
        assert accounts.status_code == 200
        legacy = next(item for item in accounts.json() if item["username"] == "legacy-demo")
        assert test_client.post(f"/api/dev/accounts/{legacy['id']}/login").status_code == 200
        yield test_client


@pytest.fixture
def no_background_tasks(monkeypatch):
    def submit(_task_id, coroutine):
        coroutine.close()
        return None
    monkeypatch.setattr(manager, "submit", submit)


def new_session(client: TestClient) -> int:
    response = client.post("/api/agent/sessions", json={"session_type": "global"})
    assert response.status_code == 200
    return response.json()["id"]


def test_force_new_global_tutor_session_archives_previous_conversation(client: TestClient):
    previous = client.post("/api/agent/sessions", json={"session_type": "global"})
    assert previous.status_code == 200

    fresh = client.post("/api/agent/sessions", json={
        "session_type": "global",
        "force_new": True,
    })
    assert fresh.status_code == 200
    assert fresh.json()["id"] != previous.json()["id"]
    assert fresh.json()["messages"] == []

    resumed = client.post("/api/agent/sessions", json={"session_type": "global"})
    assert resumed.status_code == 200
    assert resumed.json()["id"] == fresh.json()["id"]

    async def previous_status():
        async with async_session() as db:
            session = await db.get(AgentSession, previous.json()["id"])
            return session.status

    assert asyncio.run(previous_status()) == "archived"


def test_force_new_legacy_global_project_scope_archives_project_session(client: TestClient):
    async def seed_project():
        async with async_session() as db:
            project = Project(
                learner_id=await legacy_learner_id(),
                name=f"旧客户端会话归一化-{uuid.uuid4().hex[:8]}",
            )
            db.add(project)
            await db.commit()
            return project.id

    project_id = asyncio.run(seed_project())
    previous = client.post("/api/agent/sessions", json={
        "session_type": "global",
        "project_id": project_id,
    })
    assert previous.status_code == 200
    assert previous.json()["session_type"] == "project"

    fresh = client.post("/api/agent/sessions", json={
        "session_type": "global",
        "project_id": project_id,
        "force_new": True,
    })
    assert fresh.status_code == 200
    assert fresh.json()["session_type"] == "project"
    assert fresh.json()["id"] != previous.json()["id"]

    resumed = client.post("/api/agent/sessions", json={
        "session_type": "project",
        "project_id": project_id,
    })
    assert resumed.status_code == 200
    assert resumed.json()["id"] == fresh.json()["id"]

    async def previous_status():
        async with async_session() as db:
            session = await db.get(AgentSession, previous.json()["id"])
            return session.status

    assert asyncio.run(previous_status()) == "archived"


def test_checkpoint_tutor_session_and_context_are_isolated(client: TestClient, tmp_path):
    root = tmp_path / "checkpoint-workspace"
    root.mkdir()
    (root / "shared.py").write_text("print('shared project file')\n", encoding="utf-8")

    async def seed():
        async with async_session() as db:
            learner_id = await legacy_learner_id()
            project = Project(learner_id=learner_id, name="关卡会话隔离项目")
            db.add(project)
            await db.flush()
            roadmap = Roadmap(project_id=project.id, raw_json={})
            db.add(roadmap)
            await db.flush()
            first = Checkpoint(
                roadmap_id=roadmap.id, title="第一关", description="只看第一关",
                order=1, brief={"goal": "first-only"},
            )
            second = Checkpoint(
                roadmap_id=roadmap.id, title="第二关", description="other-checkpoint-secret",
                order=2, brief={"goal": "second-secret"},
            )
            db.add_all([first, second])
            await db.flush()
            source = Source(project_id=project.id, type="url", url="https://example.com", status="processed")
            db.add(source)
            await db.flush()
            first_chunk = Chunk(source_id=source.id, index=0, content="first assigned resource", meta_data={"file": "first.md"})
            second_chunk = Chunk(source_id=source.id, index=1, content="second hidden resource", meta_data={"file": "second.md"})
            db.add_all([first_chunk, second_chunk])
            await db.flush()
            db.add_all([
                CheckpointChunk(checkpoint_id=first.id, chunk_id=first_chunk.id),
                CheckpointChunk(checkpoint_id=second.id, chunk_id=second_chunk.id),
                Lecture(checkpoint_id=first.id, status="published", sections=[{"title": "第一讲", "content": "first lecture body"}]),
                Lecture(checkpoint_id=second.id, status="published", sections=[{"title": "第二讲", "content": "other lecture secret"}]),
                Exercise(checkpoint_id=first.id, title="第一题", description="first exercise", order=1),
                Exercise(checkpoint_id=second.id, title="第二题", description="other exercise secret", order=1),
                ProjectWorkspace(project_id=project.id, learner_id=learner_id, root_path=str(root), status="linked", platform="test"),
            ])
            await db.commit()
            return learner_id, project.id, first.id, second.id

    learner_id, project_id, first_id, second_id = asyncio.run(seed())
    first = client.post("/api/agent/sessions", json={
        "session_type": "checkpoint", "project_id": project_id, "checkpoint_id": first_id,
    })
    assert first.status_code == 200, first.text
    resumed = client.post("/api/agent/sessions", json={
        "session_type": "checkpoint", "project_id": project_id, "checkpoint_id": first_id,
    })
    second = client.post("/api/agent/sessions", json={
        "session_type": "checkpoint", "project_id": project_id, "checkpoint_id": second_id,
    })
    assert resumed.json()["id"] == first.json()["id"]
    assert second.json()["id"] != first.json()["id"]
    assert first.json()["session_type"] == "checkpoint"

    crossed = client.post(f"/api/agent/sessions/{first.json()['id']}/turns", json={
        "message": "切换关卡", "project_id": project_id, "checkpoint_id": second_id,
    })
    assert crossed.status_code == 409
    turn = client.post(f"/api/agent/sessions/{first.json()['id']}/turns", json={
        "message": "只属于第一关的消息", "project_id": project_id, "checkpoint_id": first_id,
        "context": {"surface": "lecture", "selected_text": "第一关选中文本"},
    })
    assert turn.status_code == 200, turn.text
    untouched = client.get(f"/api/agent/sessions/{second.json()['id']}").json()
    assert all("只属于第一关" not in item["content"] for item in untouched["messages"])

    artifacts = client.get(f"/api/checkpoints/{first_id}/workspace/artifacts")
    assert artifacts.status_code == 200
    assert artifacts.json()["managed_lecture"]["checkpoint_id"] == first_id
    assert [item["title"] for item in artifacts.json()["managed_exercises"]] == ["第一题"]

    async def load_context():
        async with async_session() as db:
            return await build_checkpoint_tutor_context(
                db, learner_id=learner_id, project_id=project_id,
                checkpoint_id=first_id,
                surface_context={"surface": "lecture", "selected_text": "selected"},
            )

    context = asyncio.run(load_context())
    rendered = str(context)
    assert "first assigned resource" in rendered
    assert "shared.py" in rendered
    assert "first lecture body" in rendered
    assert "second hidden resource" not in rendered
    assert "other lecture secret" not in rendered
    assert "other exercise secret" not in rendered
    assert context["scope"]["checkpoint_id"] == first_id
    assert context["five_kernel_projection"]["structure"]["short_term"]["session_scope"] == {
        "project_id": project_id, "checkpoint_id": first_id,
    }


async def legacy_learner_id() -> int:
    async with async_session() as db:
        return (await db.execute(select(KernelState.learner_id).limit(1))).scalar_one()


def test_model_json_fallback_is_unwrapped_for_tutor_display():
    reply, observations, opportunity, learning_intent, major_events, local_agent_task = _decode_tutor_content(
        """```json
{"reply":"第一段\\n\\n第二段","observations":[{"kernel":"knowledge","key":"understanding"}],"project_opportunity":null}
```"""
    )
    assert reply == "第一段\n\n第二段"
    assert observations == [{"kernel": "knowledge", "key": "understanding"}]
    assert opportunity is None
    assert learning_intent is None
    assert major_events == []
    assert local_agent_task is None


def test_malformed_math_fence_cannot_swallow_following_markdown():
    malformed = """手动验证：

$$
L = z^2
```

后续解释不应进入公式。

```python
print('still code')
```
"""
    repaired = _repair_markdown_fences(malformed)
    assert "$$\nL = z^2\n$$" in repaired
    assert "```python\nprint('still code')\n```" in repaired
    assert repaired.count("$$") == 2


def test_unclosed_math_is_closed_without_touching_code_dollars():
    malformed = """```python
price = '$5'
```

$$
x^2 + y^2
"""
    repaired = _repair_markdown_fences(malformed)
    assert "price = '$5'" in repaired
    assert repaired.rstrip().endswith("$$")


def test_formal_roadmap_uses_profile_and_treats_stage_preview_as_soft_reference(client: TestClient):
    session_id = new_session(client)
    created = client.post(
        f"/api/agent/sessions/{session_id}/turns",
        json={"message": "创建一个路线规划上下文测试项目"},
    ).json()
    project_id = created["executed_action"]["result"]["project"]["id"]

    async def seed_and_load_context():
        async with async_session() as db:
            learner_id = await legacy_learner_id()
            proposal = LearningProjectProposal(
                learner_id=learner_id,
                session_id=session_id,
                proposal_key=f"roadmap-context-{project_id}",
                proposal_type="build",
                status="accepted",
                action_type="create",
                accepted_project_id=project_id,
                artifact={
                    "learning_goal": "理解规划上下文",
                    "practice_goal": "完成可验证产物",
                    "estimated_effort": "每周 5 小时",
                    "acceptance_criteria": ["能够独立完成"],
                    "risks": ["前置基础不足"],
                    "milestones": [
                        {"id": "preview-only", "title": "仅供预览的阶段", "purpose": "提供方向"},
                    ],
                },
            )
            db.add(proposal)
            db.add(Source(
                project_id=project_id,
                type="github",
                url="https://github.com/example/structured-course",
                role="main",
                status="processed",
                meta_data={
                    "repo_analysis": {
                        "structure_logic": "tutorial-progression",
                        "readme_toc": [{"title": "张量与自动求导"}],
                        "dir_groups": [{"name": "Chapter 03 Attention", "is_chapter": True}],
                    },
                },
            ))
            await db.commit()
            current = await load_current_learner(db, learner_id)
            return await _roadmap_planning_context(db, current, project_id)

    context = asyncio.run(seed_and_load_context())
    assert context["input_policy"]["stage_preview_weight"] == "low"
    assert context["learner_profile"]["weekly_hours"] >= 0
    assert context["five_kernel_memory"]
    domains = context["repository_knowledge_domains"]
    assert len(domains) == 1
    assert domains[0]["role"] == "main"
    assert domains[0]["type"] == "github"
    assert domains[0]["structure_logic"] == "tutorial-progression"
    assert domains[0]["domains"] == [
        {"label": "张量与自动求导", "evidence": "README 目录"},
        {"label": "Chapter 03 Attention", "evidence": "章节目录"},
    ]
    assert context["proposal_reference"]["usage"] == "soft_reference_only"
    assert context["proposal_reference"]["stage_preview"][0]["title"] == "仅供预览的阶段"

    agent = object.__new__(RoadmapAgent)
    agent._planning_context = context
    rendered = agent._build_planning_context()
    assert "用户画像与五核记忆" in rendered
    assert "项目来源知识领域" in rendered
    assert "不是学习者状态或掌握证据" in rendered
    assert "低权重参考，不是正式路线骨架" in rendered
    assert "可以合并、重排或舍弃" in rendered


def test_confirmed_route_has_a_structured_submission_fallback():
    class StructuredModel:
        async def ainvoke(self, _messages):
            return SubmittedRoadmap.model_validate({
                "checkpoints": [
                    {
                        "title": "PyTorch 热身",
                        "description": "跑通最小训练循环",
                        "order": 9,
                        "prerequisites": [99],
                        "files": ["chapter01.py", "invented.py"],
                        "key_concepts": ["张量", "自动求导"],
                    },
                    {
                        "title": "因果自注意力",
                        "description": "实现注意力并验证形状",
                        "order": 12,
                        "prerequisites": [1],
                        "files": ["chapter02.py"],
                        "key_concepts": ["因果掩码"],
                    },
                ],
            })

    class FakeLlm:
        def with_structured_output(self, _schema):
            return StructuredModel()

    agent = object.__new__(RoadmapAgent)
    agent.llm = FakeLlm()
    agent._existing_roadmap = None
    agent._last_submitted_roadmap = None
    agent._planning_context = {}
    result = asyncio.run(agent._force_structured_submission(
        message="用户确认路线",
        history=[],
        topic="MiniGPT",
        sources_info=[{
            "source_id": 1,
            "role": "main",
            "repo_analysis": {
                "file_summaries": {
                    "chapter01.py": "训练循环",
                    "chapter02.py": "注意力",
                },
            },
        }],
    ))
    checkpoints = result["updated_roadmap"]["checkpoints"]
    assert [item["order"] for item in checkpoints] == [1, 2]
    assert checkpoints[0]["prerequisites"] == []
    assert checkpoints[0]["files"] == ["chapter01.py"]
    assert checkpoints[1]["prerequisites"] == [1]


def test_roadmap_submission_requires_a_confirmed_tutor_action(client: TestClient):
    session_id = new_session(client)
    created = client.post(
        f"/api/agent/sessions/{session_id}/turns",
        json={"message": f"创建一个路线写入保护测试 {uuid.uuid4().hex[:8]} 项目"},
    ).json()
    project_id = created["executed_action"]["result"]["project"]["id"]

    response = client.post(
        f"/api/projects/{project_id}/roadmap/chat",
        json={"message": "直接写入路线", "history": [], "require_submission": True},
    )
    assert response.status_code == 409
    assert "确认" in response.json()["detail"]


def test_roadmap_chunk_tools_are_scoped_to_current_project_sources():
    async def seed_chunks():
        async with async_session() as db:
            learner_id = await legacy_learner_id()
            first = Project(learner_id=learner_id, name="路线来源隔离 A")
            second = Project(learner_id=learner_id, name="路线来源隔离 B")
            db.add_all([first, second])
            await db.flush()
            allowed = Source(project_id=first.id, type="url", url="https://example.com/a", status="processed")
            blocked = Source(project_id=second.id, type="url", url="https://example.com/b", status="processed")
            db.add_all([allowed, blocked])
            await db.flush()
            allowed_chunk = Chunk(source_id=allowed.id, index=0, content="allowed-roadmap-content", meta_data={"file": "a.md"})
            blocked_chunk = Chunk(source_id=blocked.id, index=0, content="blocked-roadmap-content", meta_data={"file": "b.md"})
            db.add_all([allowed_chunk, blocked_chunk])
            await db.commit()
            return allowed.id, allowed_chunk.id, blocked_chunk.id

    source_id, allowed_chunk_id, blocked_chunk_id = asyncio.run(seed_chunks())
    agent = object.__new__(RoadmapAgent)
    agent._existing_roadmap = None
    agent._last_submitted_roadmap = None
    tools = agent._build_tools([], [{"source_id": source_id, "role": "main"}])
    read_chunk = next(item for item in tools if item.name == "read_chunk")
    result = read_chunk.invoke({"chunk_ids": [allowed_chunk_id, blocked_chunk_id]})
    assert "allowed-roadmap-content" in result
    assert "blocked-roadmap-content" not in result
    assert f"[chunk-{blocked_chunk_id}] （不存在）" in result


def test_explicit_project_command_executes_in_same_turn(client: TestClient):
    session_id = new_session(client)
    response = client.post(
        f"/api/agent/sessions/{session_id}/turns",
        json={"message": "帮我建一个强化学习项目"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["executed_action"]["status"] == "completed"
    assert body["executed_action"]["result"]["project"]["name"] == "强化学习"
    assert "已建立并进入" in body["message"]


def test_add_source_is_direct_and_idempotent(client: TestClient, no_background_tasks):
    session_id = new_session(client)
    created = client.post(
        f"/api/agent/sessions/{session_id}/turns",
        json={"message": "创建一个线性代数项目"},
    ).json()
    project_id = created["executed_action"]["result"]["project"]["id"]

    first = client.post(
        f"/api/agent/sessions/{session_id}/turns",
        json={"message": "把 https://example.com/linear-algebra 加到当前项目"},
    )
    assert first.status_code == 200
    assert first.json()["executed_action"]["status"] == "running"

    second = client.post(
        f"/api/agent/sessions/{session_id}/turns",
        json={"message": "把 https://example.com/linear-algebra/ 加到当前项目"},
    )
    assert second.status_code == 200
    assert second.json()["executed_action"]["result"]["source"]["id"] == first.json()["executed_action"]["result"]["source"]["id"]

    async def count_sources():
        async with async_session() as db:
            rows = (await db.execute(
                select(Source).where(Source.project_id == project_id)
            )).scalars().all()
            return len(rows)

    assert asyncio.run(count_sources()) == 1


def test_global_main_agent_references_active_project_without_becoming_project_tutor(
    client: TestClient,
    no_background_tasks,
):
    project_session_id = new_session(client)
    created = client.post(
        f"/api/agent/sessions/{project_session_id}/turns",
        json={"message": "创建一个跨会话上下文项目"},
    ).json()
    project_id = created["executed_action"]["result"]["project"]["id"]
    assert created["executed_action"]["result"]["navigate_to_project"] is True
    assert created["state_summary"]["session_scope"] == "global"
    assert created["state_summary"]["active_project"] is None
    assert created["state_summary"]["referenced_project"]["id"] == project_id

    global_session_id = new_session(client)
    assert global_session_id == project_session_id
    resumed = client.get(f"/api/agent/sessions/{global_session_id}").json()
    assert resumed["session_type"] == "global"
    assert resumed["project_id"] is None
    assert resumed["state_summary"]["tutor_role"] == "main_agent"
    response = client.post(
        f"/api/agent/sessions/{global_session_id}/turns",
        json={"message": "把 https://example.com/context-source 加到当前项目"},
    )
    assert response.status_code == 200
    assert response.json()["executed_action"]["status"] == "running"
    assert response.json()["executed_action"]["result"]["project"]["id"] == project_id


def test_project_session_handoff_uses_message_and_evidence_refs(client: TestClient):
    global_session_id = new_session(client)
    created = client.post(
        f"/api/agent/sessions/{global_session_id}/turns",
        json={"message": "创建一个会话交接项目"},
    ).json()
    project_id = created["executed_action"]["result"]["project"]["id"]
    project_session = client.post(
        "/api/agent/sessions",
        json={"session_type": "project", "project_id": project_id},
    ).json()
    assert project_session["id"] != global_session_id
    assert project_session["state_summary"]["session_scope"] == "project"
    assert project_session["state_summary"]["tutor_role"] == "project_tutor"
    assert project_session["state_summary"]["active_project"]["id"] == project_id

    async def handoff():
        async with async_session() as db:
            session = await db.get(AgentSession, project_session["id"])
            return (session.context_summary or {}).get("handoff") or {}

    context = asyncio.run(handoff())
    assert context["from_session_id"] == global_session_id
    assert context["message_refs"]
    assert context["evidence_refs"]
    welcome = [
        message for message in project_session["messages"]
        if message["meta_data"].get("message_kind") == "project_welcome"
    ]
    assert len(welcome) == 1
    assert welcome[0]["meta_data"]["project_owner"] is True
    assert "资料选择、正式路线规划" in welcome[0]["content"]

    resumed = client.post(
        "/api/agent/sessions",
        json={"session_type": "project", "project_id": project_id},
    ).json()
    assert len([
        message for message in resumed["messages"]
        if message["meta_data"].get("message_kind") == "project_welcome"
    ]) == 1


def test_accepted_project_welcome_carries_candidate_source_attachment(
    client: TestClient,
    no_background_tasks,
):
    session_id = new_session(client)

    async def create_unique_proposal():
        async with async_session() as db:
            learner_id = await legacy_learner_id()
            proposal = LearningProjectProposal(
                learner_id=learner_id,
                session_id=session_id,
                proposal_key=f"welcome-attachment-{uuid.uuid4().hex[:12]}",
                proposal_type="build",
                status="ready",
                artifact={
                    "title": "项目 Tutor 欢迎语测试",
                    "learning_goal": "验证项目 Tutor 能持续承接项目上下文",
                    "practice_goal": "完成一个可验证产物",
                    "candidate_sources": [{
                        "title": "example/learning-source",
                        "url": "https://github.com/example/learning-source",
                        "type": "github",
                    }],
                },
                source_status="completed",
            )
            db.add(proposal)
            await db.commit()
            await db.refresh(proposal)
            return proposal.id

    proposal_id = asyncio.run(create_unique_proposal())
    accepted = client.post(
        f"/api/agent/project-proposals/{proposal_id}/accept",
        json={"client_event_id": f"welcome-attachment-{proposal_id}"},
    ).json()
    project_id = accepted["executed_action"]["result"]["project"]["id"]
    project_session = client.post(
        "/api/agent/sessions",
        json={"session_type": "project", "project_id": project_id},
    ).json()
    welcome = next(
        message for message in project_session["messages"]
        if message["meta_data"].get("message_kind") == "project_welcome"
    )
    assert welcome["meta_data"]["attachment"] == {
        "type": "candidate_sources",
        "proposal_id": proposal_id,
    }
    assert "候选来源" in welcome["content"]


def test_candidate_source_completion_continues_project_tutor_session(
    client: TestClient,
    monkeypatch,
):
    monkeypatch.setattr("app.services.tutor_service.settings.llm_api_key", "")
    session_id = new_session(client)
    created = client.post(
        f"/api/agent/sessions/{session_id}/turns",
        json={"message": f"创建一个来源收尾测试 {uuid.uuid4().hex[:8]} 项目"},
    ).json()
    project_id = created["executed_action"]["result"]["project"]["id"]
    proposal_id = 900_000 + project_id

    response = client.post(
        f"/api/agent/sessions/{session_id}/turns",
        json={
            "message": "候选来源选择完毕，请继续安排下一步。",
            "project_id": project_id,
            "client_turn_id": f"candidate-sources-completed-{project_id}",
            "context": {
                "interaction": "candidate_sources_completed",
                "proposal_id": proposal_id,
            },
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["executed_action"] is None
    assert body["message"] == "未接入模型。"

    restored = client.get(f"/api/agent/sessions/{session_id}").json()
    completed_turn = next(
        message for message in reversed(restored["messages"])
        if message["role"] == "user"
        and message["meta_data"].get("interaction") == "candidate_sources_completed"
    )
    assert completed_turn["meta_data"]["proposal_id"] == proposal_id


def test_tutor_reports_missing_model_without_fallback_copy(client: TestClient, monkeypatch):
    monkeypatch.setattr("app.services.tutor_service.settings.llm_api_key", "")
    session_id = new_session(client)
    response = client.post(
        f"/api/agent/sessions/{session_id}/turns",
        json={"message": "请解释一下这个概念", "client_turn_id": f"missing-model-{uuid.uuid4().hex}"},
    )
    assert response.status_code == 200
    assert response.json()["message"] == "未接入模型。"


def test_project_tutor_routes_formal_learning_into_checkpoints(
    client: TestClient,
    monkeypatch,
):
    monkeypatch.setattr("app.services.tutor_service.settings.llm_api_key", "")
    session_id = new_session(client)
    created = client.post(
        f"/api/agent/sessions/{session_id}/turns",
        json={"message": f"创建一个 Tutor 关卡边界测试 {uuid.uuid4().hex[:8]} 项目"},
    ).json()
    project_id = created["executed_action"]["result"]["project"]["id"]

    completed = client.post(
        f"/api/agent/sessions/{session_id}/turns",
        json={
            "message": "候选来源选择完毕，请继续安排下一步。",
            "project_id": project_id,
            "context": {
                "interaction": "candidate_sources_completed",
                "proposal_id": 910_000 + project_id,
            },
        },
    )
    assert completed.status_code == 200

    async def fake_roadmap_chat(self, message, **_kwargs):
        if "已经明确确认" in message or "以“开始”明确确认" in message:
            return {
                "message": "路线已经按确认结果保存。",
                "updated_roadmap": {
                    "checkpoints": [
                        {
                            "title": "PyTorch 热身",
                            "description": "在关卡内完成张量、自动求导与最小训练循环。",
                            "order": 1,
                            "prerequisites": [],
                            "chunk_ids": [],
                            "files": [],
                            "key_concepts": ["张量", "自动求导", "训练循环"],
                        },
                        {
                            "title": "因果自注意力",
                            "description": "实现并验证注意力中的张量形状流动。",
                            "order": 2,
                            "prerequisites": [1],
                            "chunk_ids": [],
                            "files": [],
                            "key_concepts": ["因果掩码", "多头注意力"],
                        },
                    ],
                    "archives": [],
                },
            }
        return {
            "message": "正式路线提案：先做 PyTorch 热身，再进入因果自注意力。确认后写入项目关卡。",
            "updated_roadmap": None,
        }

    monkeypatch.setattr("app.services.tutor_service.settings.llm_api_key", "test-key")
    monkeypatch.setattr(RoadmapAgent, "chat", fake_roadmap_chat)

    planned = client.post(
        f"/api/agent/sessions/{session_id}/turns",
        json={
            "message": (
                "A 几乎没用过 PyTorch；B 能说出自注意力的大意，但不清楚张量形状；"
                "C 可以租 GPU，但需要环境指导。每周投入 7 小时。"
            ),
            "project_id": project_id,
        },
    )
    assert planned.status_code == 200
    planned_body = planned.json()
    assert planned_body["executed_action"]["title"] == "规划学习路线"
    assert planned_body["executed_action"]["result"]["updated_roadmap"] is None
    assert "正式路线提案" in planned_body["message"]
    assert "import torch" not in planned_body["message"]
    confirmation_card = planned_body["action_card"]
    assert confirmation_card["title"] == "应用学习路线"
    assert confirmation_card["status"] == "pending_confirmation"
    assert confirmation_card["primary_label"] == "确认并生成关卡图"

    applied = client.post(
        f"/api/agent/actions/{confirmation_card['id']}/confirm",
    )
    assert applied.status_code == 200
    applied_body = applied.json()
    assert applied_body["executed_action"]["title"] == "应用学习路线"
    assert applied_body["executed_action"]["result"]["updated_roadmap"] is not None
    assert "讲义、练习、代码任务和验证会放在各自关卡中" in applied_body["message"]

    async def route_state():
        async with async_session() as db:
            session = await db.get(AgentSession, session_id)
            checkpoints = list((await db.execute(
                select(Checkpoint)
                .join(Roadmap, Roadmap.id == Checkpoint.roadmap_id)
                .where(Roadmap.project_id == project_id)
                .order_by(Checkpoint.order)
            )).scalars().all())
            lectures = list((await db.execute(
                select(Lecture).where(Lecture.checkpoint_id.in_([item.id for item in checkpoints]))
            )).scalars().all()) if checkpoints else []
            return session.context_summary, checkpoints, lectures

    context_summary, checkpoints, lectures = asyncio.run(route_state())
    assert (context_summary.get("learning_flow") or {}).get("phase") == "roadmap_ready"
    assert [item.title for item in checkpoints] == ["PyTorch 热身", "因果自注意力"]
    assert lectures == []

    entered = client.post(
        f"/api/agent/sessions/{session_id}/turns",
        json={"message": "开始", "project_id": project_id},
    )
    assert entered.status_code == 200
    assert entered.json()["executed_action"]["title"] == "进入检查点"
    assert entered.json()["executed_action"]["result"]["checkpoint"]["title"] == "PyTorch 热身"


def test_direct_checkpoint_learning_request_and_confirmation_use_roadmap_tool(
    client: TestClient,
    monkeypatch,
):
    session_id = new_session(client)
    created = client.post(
        f"/api/agent/sessions/{session_id}/turns",
        json={"message": f"创建一个 直接关卡测试 {uuid.uuid4().hex[:8]} 项目"},
    ).json()
    project_id = created["executed_action"]["result"]["project"]["id"]

    async def fake_roadmap_chat(self, message, **_kwargs):
        confirmed = "已经明确确认" in message
        return {
            "message": "路线已保存。" if confirmed else "正式路线提案，共两关，请确认。",
            "updated_roadmap": ({
                "checkpoints": [
                    {
                        "title": "基础关",
                        "description": "完成基础训练闭环",
                        "order": 1,
                        "prerequisites": [],
                        "chunk_ids": [],
                        "files": [],
                        "key_concepts": ["训练循环"],
                    },
                    {
                        "title": "实践关",
                        "description": "完成可验证实践产物",
                        "order": 2,
                        "prerequisites": [1],
                        "chunk_ids": [],
                        "files": [],
                        "key_concepts": ["实践验证"],
                    },
                ],
                "archives": [],
            } if confirmed else None),
        }

    monkeypatch.setattr("app.services.tutor_service.settings.llm_api_key", "test-key")
    monkeypatch.setattr(RoadmapAgent, "chat", fake_roadmap_chat)

    proposed = client.post(
        f"/api/agent/sessions/{session_id}/turns",
        json={"message": "我想直接进入关卡学习", "project_id": project_id},
    )
    assert proposed.status_code == 200
    assert proposed.json()["executed_action"]["title"] == "规划学习路线"
    assert proposed.json()["executed_action"]["result"]["updated_roadmap"] is None

    confirmed = client.post(
        f"/api/agent/sessions/{session_id}/turns",
        json={"message": "确认", "project_id": project_id},
    )
    assert confirmed.status_code == 200
    body = confirmed.json()
    assert body["executed_action"]["title"] == "应用学习路线"
    assert len(body["executed_action"]["result"]["updated_roadmap"]["checkpoints"]) == 2


def test_confirmation_recovers_a_recent_text_only_route_proposal(
    client: TestClient,
    monkeypatch,
):
    session_id = new_session(client)
    created = client.post(
        f"/api/agent/sessions/{session_id}/turns",
        json={"message": f"创建一个 文本路线恢复测试 {uuid.uuid4().hex[:8]} 项目"},
    ).json()
    project_id = created["executed_action"]["result"]["project"]["id"]

    async def seed_text_proposal():
        async with async_session() as db:
            session = await db.get(AgentSession, session_id)
            session.session_type = "project"
            session.project_id = project_id
            session.context_summary = {}
            db.add(AgentMessage(
                session_id=session_id,
                role="assistant",
                content="## 正式学习路线（确认后生效）\n阶段 0 基础关；阶段 1 实践关。",
            ))
            await db.commit()

    asyncio.run(seed_text_proposal())

    async def fake_roadmap_chat(self, message, **_kwargs):
        del message
        return {
            "message": "路线已真实写入。",
            "updated_roadmap": {
                "checkpoints": [
                    {
                        "title": "基础关", "description": "基础", "order": 1,
                        "prerequisites": [], "chunk_ids": [], "files": [], "key_concepts": [],
                    },
                    {
                        "title": "实践关", "description": "实践", "order": 2,
                        "prerequisites": [1], "chunk_ids": [], "files": [], "key_concepts": [],
                    },
                ],
                "archives": [],
            },
        }

    monkeypatch.setattr("app.services.tutor_service.settings.llm_api_key", "test-key")
    monkeypatch.setattr(RoadmapAgent, "chat", fake_roadmap_chat)
    response = client.post(
        f"/api/agent/sessions/{session_id}/turns",
        json={"message": "确认", "project_id": project_id},
    )
    assert response.status_code == 200
    assert response.json()["executed_action"]["title"] == "应用学习路线"
    assert response.json()["executed_action"]["result"]["updated_roadmap"] is not None


def test_natural_route_confirmation_after_tutor_prompt_applies_roadmap(
    client: TestClient,
    monkeypatch,
):
    session_id = new_session(client)
    created = client.post(
        f"/api/agent/sessions/{session_id}/turns",
        json={"message": f"创建一个 自然确认路线测试 {uuid.uuid4().hex[:8]} 项目"},
    ).json()
    project_id = created["executed_action"]["result"]["project"]["id"]

    async def seed_route_prompt():
        async with async_session() as db:
            session = await db.get(AgentSession, session_id)
            session.session_type = "project"
            session.project_id = project_id
            session.context_summary = {"learning_flow": {"phase": "roadmap_intake"}}
            db.add(AgentMessage(
                session_id=session_id,
                role="assistant",
                content=(
                    "我已经根据你的目标整理好路线：先完成基础关，再进入实践关。"
                    "确认这条路线后，我就正式建立路线。"
                ),
            ))
            await db.commit()

    asyncio.run(seed_route_prompt())

    async def fake_roadmap_chat(self, message, **_kwargs):
        assert "已经明确确认" in message
        return {
            "message": "路线已真实写入。",
            "updated_roadmap": {
                "checkpoints": [
                    {
                        "title": "基础关", "description": "基础", "order": 1,
                        "prerequisites": [], "chunk_ids": [], "files": [], "key_concepts": [],
                    },
                    {
                        "title": "实践关", "description": "实践", "order": 2,
                        "prerequisites": [1], "chunk_ids": [], "files": [], "key_concepts": [],
                    },
                ],
                "archives": [],
            },
        }

    monkeypatch.setattr("app.services.tutor_service.settings.llm_api_key", "test-key")
    monkeypatch.setattr(RoadmapAgent, "chat", fake_roadmap_chat)
    response = client.post(
        f"/api/agent/sessions/{session_id}/turns",
        json={"message": "我确认这条路线", "project_id": project_id},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["executed_action"]["title"] == "应用学习路线"
    assert body["executed_action"]["result"]["updated_roadmap"] is not None
    assert body["executed_action"]["result"]["checkpoint"]["title"] == "基础关"
    assert body["executed_action"]["result"]["entry_mode"] == "automatic_after_roadmap"
    assert "已直接进入第一关「基础关」" in body["message"]

    async def route_state():
        async with async_session() as db:
            checkpoints = list((await db.execute(
                select(Checkpoint)
                .join(Roadmap, Roadmap.id == Checkpoint.roadmap_id)
                .where(Roadmap.project_id == project_id)
                .order_by(Checkpoint.order)
            )).scalars().all())
            session = await db.get(AgentSession, session_id)
            events = list((await db.execute(
                select(EvidenceEvent.event_type, EvidenceEvent.payload)
                .where(EvidenceEvent.session_id == session_id)
                .order_by(EvidenceEvent.id)
            )).all())
            return [item.title for item in checkpoints], session.checkpoint_id, events

    titles, active_checkpoint_id, events = asyncio.run(route_state())
    assert titles == ["基础关", "实践关"]
    assert active_checkpoint_id == body["executed_action"]["result"]["checkpoint"]["id"]
    entered = [payload for event_type, payload in events if event_type == "checkpoint_entered"]
    assert entered == [{"title": "基础关", "entry_mode": "automatic_after_roadmap"}]


def test_add_source_uses_recent_url(client: TestClient, no_background_tasks):
    session_id = new_session(client)
    client.post(
        f"/api/agent/sessions/{session_id}/turns",
        json={"message": "创建一个分步来源项目"},
    )
    client.post(
        f"/api/agent/sessions/{session_id}/turns",
        json={"message": "https://example.com/recent-source"},
    )
    response = client.post(
        f"/api/agent/sessions/{session_id}/turns",
        json={"message": "添加这个来源"},
    )
    assert response.status_code == 200
    assert response.json()["executed_action"]["status"] == "running"
    assert response.json()["executed_action"]["result"]["source"]["url"] == "https://example.com/recent-source"


def test_project_opportunity_requires_confirmation(client: TestClient):
    session_id = new_session(client)
    response = client.post(
        f"/api/agent/sessions/{session_id}/turns",
        json={"message": "我想系统学习概率论并做一套配套练习"},
    )
    assert response.status_code == 200
    proposal = response.json()["proposal_update"]
    assert proposal["status"] == "ready"
    assert response.json()["executed_action"] is None

    confirmed = client.post(
        f"/api/agent/project-proposals/{proposal['id']}/accept",
        json={"client_event_id": f"accept-probability-{proposal['id']}"},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["executed_action"]["status"] == "completed"


def test_plain_question_does_not_create_project_card(client: TestClient):
    session_id = new_session(client)
    response = client.post(
        f"/api/agent/sessions/{session_id}/turns",
        json={"message": "什么是矩阵的特征值？"},
    )
    assert response.status_code == 200
    assert response.json()["action_card"] is None


def test_acknowledgement_is_low_confidence_only(client: TestClient):
    session_id = new_session(client)
    response = client.post(
        f"/api/agent/sessions/{session_id}/turns",
        json={"message": "懂了"},
    )
    assert response.status_code == 200

    async def event_for_message():
        async with async_session() as db:
            return (await db.execute(
                select(EvidenceEvent)
                .where(
                    EvidenceEvent.session_id == session_id,
                    EvidenceEvent.event_type == "user_message",
                )
                .order_by(EvidenceEvent.id.desc())
                .limit(1)
            )).scalar_one()

    event = asyncio.run(event_for_message())
    assert event.confidence == pytest.approx(0.25)


def test_evidence_is_written_for_explicit_action(client: TestClient):
    async def latest():
        async with async_session() as db:
            return (await db.execute(
                select(EvidenceEvent)
                .where(EvidenceEvent.event_type == "project_created")
                .order_by(EvidenceEvent.id.desc())
                .limit(1)
            )).scalar_one_or_none()

    event = asyncio.run(latest())
    assert event is not None
    assert event.source == "tutor_tool"
    assert event.provenance.get("action_id")


def test_action_confirmation_is_not_repeated(client: TestClient):
    session_id = new_session(client)
    proposal = client.post(
        f"/api/agent/sessions/{session_id}/turns",
        json={"message": "我想制定一个系统学习统计学的计划并持续练习"},
    ).json()
    proposal_id = proposal["proposal_update"]["id"]
    turn = client.post(
        f"/api/agent/sessions/{session_id}/turns",
        json={"message": "就这个"},
    )
    assert turn.status_code == 200
    assert turn.json()["executed_action"]["status"] == "completed"
    assert turn.json()["proposal_update"]["id"] == proposal_id
    assert turn.json()["proposal_update"]["status"] == "accepted"


def test_continue_accepts_project_proposal_without_main_agent_teaching(
    client: TestClient,
    monkeypatch,
):
    session_id = new_session(client)
    proposal_key = f"continue-handoff-{uuid.uuid4().hex[:12]}"

    async def seed_proposal():
        async with async_session() as db:
            learner_id = await legacy_learner_id()
            proposal = LearningProjectProposal(
                learner_id=learner_id,
                session_id=session_id,
                proposal_key=proposal_key,
                proposal_type="build",
                status="ready",
                action_type="create",
                artifact={
                    "title": "RL Gymnasium 热身",
                    "learning_goal": "理解 Gymnasium 中环境与智能体的交互循环",
                    "practice_goal": "完成可运行的 CartPole 随机策略",
                    "learner_start": ["会 Python，尚未使用 Gymnasium"],
                    "estimated_effort": "每周 2–3 小时",
                    "milestones": [{"id": "warmup", "title": "Gymnasium 热身"}],
                    "acceptance_criteria": ["能独立运行 CartPole 循环"],
                    "risks": ["环境安装问题"],
                },
            )
            db.add(proposal)
            await db.commit()
            await db.refresh(proposal)
            return proposal.id

    proposal_id = asyncio.run(seed_proposal())

    async def fail_if_llm_is_called(*_args, **_kwargs):
        raise AssertionError("项目确认回合不应调用主 Agent LLM")

    monkeypatch.setattr(
        "app.services.tutor_service._generate_tutor_reply",
        fail_if_llm_is_called,
    )
    response = client.post(
        f"/api/agent/sessions/{session_id}/turns",
        json={
            "message": "继续",
            "client_turn_id": f"accept-{proposal_key}",
        },
    )
    assert response.status_code == 200
    body = response.json()
    project = body["executed_action"]["result"]["project"]
    assert body["executed_action"]["status"] == "completed"
    assert body["executed_action"]["result"]["navigate_to_project"] is True
    assert body["proposal_update"]["id"] == proposal_id
    assert body["proposal_update"]["status"] == "accepted"
    assert body["message"] == (
        "已建立并进入「RL Gymnasium 热身」，"
        "项目 Tutor 与路径规划 Agent 已接手。"
    )

    async def load_handoff_and_planning_context():
        async with async_session() as db:
            project_session = await get_or_create_session(
                db,
                learner_id=await legacy_learner_id(),
                session_type="project",
                project_id=project["id"],
            )
            await db.commit()
            current = await load_current_learner(db, await legacy_learner_id())
            planning_context = await _roadmap_planning_context(
                db, current, project["id"],
            )
            return project_session.context_summary, planning_context

    handoff, planning_context = asyncio.run(load_handoff_and_planning_context())
    assert handoff["handoff"]["from_session_id"] == session_id
    assert handoff["handoff"]["message_refs"]
    assert handoff["handoff"]["evidence_refs"]
    assert planning_context["proposal_reference"]["proposal_id"] == proposal_id
    assert planning_context["proposal_reference"]["learning_goal"].startswith("理解 Gymnasium")
    assert planning_context["proposal_reference"]["practice_goal"].startswith("完成可运行")
    assert planning_context["proposal_reference"]["estimated_effort"] == "每周 2–3 小时"


def test_gpt_goal_creates_and_evolves_one_build_proposal(client: TestClient, no_background_tasks):
    session_id = new_session(client)
    first = client.post(
        f"/api/agent/sessions/{session_id}/turns",
        json={"message": "我想自己动手实现一个g p t"},
    ).json()
    proposal = first["proposal_update"]
    assert proposal["proposal_type"] == "build"
    assert "GPT" in proposal["artifact"]["title"]
    proposal_id = proposal["id"]

    second = client.post(
        f"/api/agent/sessions/{session_id}/turns",
        json={"message": "用p y to r ch"},
    ).json()
    assert second["proposal_update"]["id"] == proposal_id
    assert second["project_proposals"][0]["artifact"]["details"]["stack"] == ["Python", "PyTorch"]

    third = client.post(
        f"/api/agent/sessions/{session_id}/turns",
        json={"message": "没用过Pytorch，只学过python的CS61A"},
    ).json()
    assert third["proposal_update"]["id"] == proposal_id
    titles = [item["title"] for item in third["proposal_update"]["artifact"]["milestones"]]
    assert titles[:2] == ["PyTorch 张量与自动求导", "手写最小 PyTorch 训练循环"]
    assert "CS61A" in " ".join(third["proposal_update"]["artifact"]["learner_start"])
    assert "当前基础" in third["proposal_update"]["last_change_summary"]

    short_turn = client.post(
        f"/api/agent/sessions/{session_id}/turns",
        json={"message": "张量和列表有什么区别？"},
    ).json()
    assert short_turn["proposal_update"] is None
    assert any(item["id"] == proposal_id for item in short_turn["project_proposals"])

    edited = client.patch(
        f"/api/agent/project-proposals/{proposal_id}",
        json={
            "patch": {"title": "我的 PyTorch MiniGPT"},
            "lock_fields": ["title"],
            "client_event_id": f"edit-gpt-title-{proposal_id}",
        },
    ).json()
    assert edited["artifact"]["title"] == "我的 PyTorch MiniGPT"
    assert "title" in edited["locked_fields"]

    accepted = client.post(
        f"/api/agent/project-proposals/{proposal_id}/accept",
        json={"client_event_id": f"accept-gpt-{proposal_id}"},
    ).json()
    repeated = client.post(
        f"/api/agent/project-proposals/{proposal_id}/accept",
        json={"client_event_id": f"accept-gpt-{proposal_id}-retry"},
    ).json()
    assert accepted["executed_action"]["result"]["project"]["id"] == repeated["executed_action"]["result"]["project"]["id"]

    async def count_created():
        async with async_session() as db:
            proposals = (await db.execute(
                select(LearningProjectProposal).where(LearningProjectProposal.id == proposal_id)
            )).scalars().all()
            projects = (await db.execute(
                select(Project).where(Project.name == "我的 PyTorch MiniGPT")
            )).scalars().all()
            return len(proposals), len(projects)

    assert asyncio.run(count_created()) == (1, 1)


def test_resource_search_failure_does_not_remove_proposal(
    client: TestClient,
    no_background_tasks,
    monkeypatch,
):
    session_id = new_session(client)
    response = client.post(
        f"/api/agent/sessions/{session_id}/turns",
        json={"message": "我想自己动手实现一个 Transformer"},
    ).json()
    proposal = response["proposal_update"]
    assert proposal["source_task_id"]

    class FailingClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def get(self, *_args, **_kwargs):
            raise RuntimeError("offline")

    monkeypatch.setattr(proposal_service.httpx, "AsyncClient", lambda **_kwargs: FailingClient())
    asyncio.run(proposal_service.run_resource_search(proposal["source_task_id"]))
    latest = client.get(f"/api/agent/project-proposals/{proposal['id']}").json()
    assert latest["source_status"] == "failed"
    assert latest["artifact"]["title"]


def test_resource_search_ranking_prefers_relevant_popular_learning_repositories():
    artifact = {
        "title": "从 Python 到手写 MiniGPT",
        "learning_goal": "理解并亲手实现 GPT",
        "practice_goal": "用 PyTorch 完成一个可训练的 decoder-only Transformer",
        "learner_start": ["没用过 PyTorch，只学过 Python"],
        "source_search_query": "gpt pytorch language:Python",
        "details": {"stack": ["Python", "PyTorch"]},
        "milestones": [],
    }
    items = [
        {
            "full_name": "rasbt/LLMs-from-scratch",
            "html_url": "https://github.com/rasbt/LLMs-from-scratch",
            "description": "Implement a ChatGPT-like LLM in PyTorch from scratch, step by step",
            "stargazers_count": 102176,
            "forks_count": 15654,
            "pushed_at": "2026-08-10T01:11:40Z",
            "language": "Jupyter Notebook",
            "topics": ["llm", "pytorch", "transformer"],
            "license": {"spdx_id": "MIT"},
            "fork": False,
            "archived": False,
        },
        {
            "full_name": "karpathy/minGPT",
            "html_url": "https://github.com/karpathy/minGPT",
            "description": "A minimal PyTorch re-implementation of the OpenAI GPT training",
            "stargazers_count": 24785,
            "forks_count": 3312,
            "pushed_at": "2024-08-15T04:09:40Z",
            "language": "Python",
            "topics": ["gpt", "pytorch"],
            "license": {"spdx_id": "MIT"},
            "fork": False,
            "archived": False,
        },
        {
            "full_name": "otahina/PowerPoint-Generator-Python-Project",
            "html_url": "https://github.com/otahina/PowerPoint-Generator-Python-Project",
            "description": "Generate PowerPoint slides using ChatGPT",
            "stargazers_count": 405,
            "forks_count": 20,
            "pushed_at": "2026-01-01T00:00:00Z",
            "language": "Python",
            "topics": [],
            "license": None,
            "fork": False,
            "archived": False,
        },
    ]
    candidates = proposal_service._rank_repository_candidates(
        items, artifact, None, generation=1, previous_urls=[],
    )
    assert [item["title"] for item in candidates] == [
        "rasbt/LLMs-from-scratch", "karpathy/minGPT",
    ]
    assert candidates[0]["quality"] == "excellent"
    assert candidates[0]["rank_score"] > candidates[1]["rank_score"]
    assert all("PowerPoint" not in item["title"] for item in candidates)

    first_plans = proposal_service._github_search_plans(artifact, 1)
    refresh_plans = proposal_service._github_search_plans(artifact, 2)
    assert len(first_plans) == len(refresh_plans) == 3
    assert first_plans == refresh_plans
    assert "nanoGPT OR minGPT" in first_plans[-1]["q"]


def test_force_refresh_creates_a_new_search_generation(client: TestClient, no_background_tasks):
    session_id = new_session(client)
    async def create_searching_proposal():
        async with async_session() as db:
            learner_id = await legacy_learner_id()
            stored = LearningProjectProposal(
                learner_id=learner_id,
                session_id=session_id,
                proposal_key=f"refresh-candidates-{uuid.uuid4().hex[:12]}",
                proposal_type="build",
                status="ready",
                artifact={
                    "title": "刷新候选测试 GPT",
                    "learning_goal": "从零实现 GPT",
                    "practice_goal": "用 PyTorch 完成可训练模型",
                    "learner_start": ["尚未使用过 PyTorch"],
                    "milestones": [],
                    "details": {"stack": ["Python", "PyTorch"]},
                    "source_search_query": "gpt pytorch language:Python",
                },
            )
            db.add(stored)
            await db.flush()
            await proposal_service.start_resource_search(db, stored)
            return proposal_service.proposal_view(stored)

    proposal = asyncio.run(create_searching_proposal())
    first_task_id = proposal["source_task_id"]
    assert proposal["artifact"]["source_search_generation"] == 1

    async def finish_first_search():
        async with async_session() as db:
            stored = await db.get(LearningProjectProposal, proposal["id"])
            task = await db.get(proposal_service.Task, first_task_id)
            artifact = dict(stored.artifact or {})
            artifact["candidate_sources"] = [{
                "title": "example/old", "url": "https://github.com/example/old", "type": "github",
            }]
            artifact["source_search_completed_query"] = artifact["source_search_query"]
            stored.artifact = artifact
            stored.source_status = "completed"
            task.status = "completed"
            await db.commit()

    asyncio.run(finish_first_search())
    refreshed = client.post(
        f"/api/agent/project-proposals/{proposal['id']}/refresh-sources",
    ).json()
    assert refreshed["source_status"] == "queued"
    assert refreshed["source_task_id"] != first_task_id
    assert refreshed["artifact"]["source_search_generation"] == 2
    assert refreshed["artifact"]["candidate_sources"][0]["title"] == "example/old"


def test_distinct_long_term_goals_keep_at_most_three_active_proposals(client: TestClient):
    session_id = new_session(client)
    for message in (
        "我想自己动手实现一个编译器",
        "我想系统学习微积分",
        "我想构建一个数据库",
        "我想研究操作系统",
    ):
        client.post(f"/api/agent/sessions/{session_id}/turns", json={"message": message})
    session = client.get(f"/api/agent/sessions/{session_id}").json()
    keys = [item["proposal_key"] for item in session["project_proposals"]]
    assert len(keys) == 3
    assert len(set(keys)) == 3


def test_missing_parameter_is_asked_once_then_reused(client: TestClient):
    session_id = new_session(client)
    first = client.post(
        f"/api/agent/sessions/{session_id}/turns",
        json={"message": "创建一个学习项目"},
    ).json()
    action_id = first["executed_action"]["id"]
    assert first["executed_action"]["status"] == "needs_input"

    second = client.post(
        f"/api/agent/sessions/{session_id}/turns",
        json={"message": "图论"},
    ).json()
    assert second["executed_action"]["id"] == action_id
    assert second["executed_action"]["status"] == "completed"
    assert second["executed_action"]["result"]["project"]["name"] == "图论"


def test_duplicate_project_name_is_disambiguated_once(client: TestClient):
    async def create_duplicates():
        async with async_session() as db:
            learner_id = await legacy_learner_id()
            first = Project(learner_id=learner_id, name="同名课程", description="第一版", user_level="beginner")
            second = Project(learner_id=learner_id, name="同名课程", description="第二版", user_level="beginner")
            db.add_all([first, second])
            await db.commit()
            return first.id, second.id

    _, second_id = asyncio.run(create_duplicates())
    session_id = new_session(client)
    first_turn = client.post(
        f"/api/agent/sessions/{session_id}/turns",
        json={"message": "进入同名课程项目"},
    ).json()
    action_id = first_turn["executed_action"]["id"]
    assert first_turn["executed_action"]["status"] == "needs_input"

    selected = client.post(
        f"/api/agent/sessions/{session_id}/turns",
        json={"message": "选项 2"},
    ).json()
    assert selected["executed_action"]["id"] == action_id
    assert selected["executed_action"]["status"] == "completed"
    assert selected["executed_action"]["result"]["project"]["id"] == second_id


def test_duplicate_turn_request_replays_without_side_effect(client: TestClient):
    session_id = new_session(client)
    payload = {
        "message": "创建一个幂等回合项目",
        "client_turn_id": "turn-idempotency-project-create",
    }
    first = client.post(f"/api/agent/sessions/{session_id}/turns", json=payload).json()
    second = client.post(f"/api/agent/sessions/{session_id}/turns", json=payload).json()
    assert second["executed_action"]["id"] == first["executed_action"]["id"]

    async def count_projects():
        async with async_session() as db:
            return len((await db.execute(
                select(Project).where(Project.name == "幂等回合")
            )).scalars().all())

    assert asyncio.run(count_projects()) == 1


def test_lecture_is_exposure_not_completion(client: TestClient):
    async def scenario():
        async with async_session() as db:
            learner_id = await legacy_learner_id()
            project = Project(learner_id=learner_id, name="完成语义测试", description="", user_level="beginner")
            db.add(project)
            await db.flush()
            roadmap = Roadmap(project_id=project.id, raw_json={"checkpoints": []})
            db.add(roadmap)
            await db.flush()
            checkpoint = Checkpoint(
                roadmap_id=roadmap.id,
                title="只生成讲义",
                order=1,
                completed=False,
                learning_status="not_started",
                legacy_completed=False,
            )
            db.add(checkpoint)
            await db.flush()
            db.add(Lecture(checkpoint_id=checkpoint.id, sections=[{"title": "一", "content": "内容"}], status="published"))
            await db.flush()

            status = await evaluate_checkpoint_status(db, checkpoint.id)
            assert status == "in_progress"
            assert checkpoint.completed is False

            await create_attempt(
                db, learner_id=learner_id, checkpoint_id=checkpoint.id, item_type="concept", item_id=1,
                submission={"answer_indexes": [0]}, result={"correct": True},
            )
            await create_attempt(
                db, learner_id=learner_id, checkpoint_id=checkpoint.id, item_type="exercise", item_id=1,
                submission={"code": "pass"}, result={"passed": 1, "total": 1},
            )
            status = await evaluate_checkpoint_status(db, checkpoint.id)
            assert status == "completed"
            assert checkpoint.completed is True
            await db.rollback()

    asyncio.run(scenario())


def test_assisted_attempts_do_not_complete_checkpoint(client: TestClient):
    async def scenario():
        async with async_session() as db:
            learner_id = await legacy_learner_id()
            project = Project(learner_id=learner_id, name="辅助作答测试", description="", user_level="beginner")
            db.add(project)
            await db.flush()
            roadmap = Roadmap(project_id=project.id, raw_json={"checkpoints": []})
            db.add(roadmap)
            await db.flush()
            checkpoint = Checkpoint(
                roadmap_id=roadmap.id,
                title="独立性验证",
                order=1,
                completed=False,
                learning_status="not_started",
                legacy_completed=False,
            )
            db.add(checkpoint)
            await db.flush()
            await create_attempt(
                db, learner_id=learner_id, checkpoint_id=checkpoint.id, item_type="concept", item_id=1,
                submission={}, result={"correct": True}, assistance_level="guided",
            )
            await create_attempt(
                db, learner_id=learner_id, checkpoint_id=checkpoint.id, item_type="exercise", item_id=1,
                submission={}, result={"passed": 1, "total": 1}, assistance_level="hint",
            )
            assert await evaluate_checkpoint_status(db, checkpoint.id) == "in_progress"
            assert checkpoint.completed is False
            await db.rollback()

    asyncio.run(scenario())


def test_legacy_completion_requires_verification(client: TestClient):
    async def scenario():
        async with async_session() as db:
            learner_id = await legacy_learner_id()
            project = Project(learner_id=learner_id, name="旧进度测试", description="", user_level="beginner")
            db.add(project)
            await db.flush()
            roadmap = Roadmap(project_id=project.id, raw_json={"checkpoints": []})
            db.add(roadmap)
            await db.flush()
            checkpoint = Checkpoint(
                roadmap_id=roadmap.id,
                title="旧完成关卡",
                order=1,
                completed=True,
                learning_status="verification_due",
                legacy_completed=True,
                progress={"lecture_generated": True},
            )
            db.add(checkpoint)
            await db.flush()
            assert await evaluate_checkpoint_status(db, checkpoint.id, learner_id=learner_id) == "verification_due"
            await db.rollback()

    asyncio.run(scenario())


def test_structure_and_knowledge_memories_have_distinct_boundaries(client: TestClient):
    async def scenario():
        async with async_session() as db:
            learner_id = await legacy_learner_id()
            project = Project(
                learner_id=learner_id,
                name="五核边界测试",
                description="验证结构位置与知识理解不会混写",
                user_level="beginner",
            )
            db.add(project)
            await db.flush()
            roadmap = Roadmap(project_id=project.id, raw_json={})
            db.add(roadmap)
            await db.flush()
            foundation = Checkpoint(
                roadmap_id=roadmap.id, title="张量形状", order=1,
                prerequisites=[], learning_status="in_progress",
            )
            db.add(foundation)
            await db.flush()
            attention = Checkpoint(
                roadmap_id=roadmap.id, title="因果自注意力", order=2,
                prerequisites=[foundation.id], learning_status="in_progress",
            )
            db.add(attention)
            await db.flush()

            await record_event(
                db, learner_id=learner_id, event_type="checkpoint_entered",
                source="test", project_id=project.id, checkpoint_id=foundation.id,
                payload={"title": foundation.title},
            )
            await record_event(
                db, learner_id=learner_id, event_type="checkpoint_entered",
                source="test", project_id=project.id, checkpoint_id=attention.id,
                payload={"title": attention.title},
            )
            await record_event(
                db, learner_id=learner_id, event_type="user_message",
                source="test", project_id=project.id, checkpoint_id=attention.id,
                payload={"text": "我为什么看不懂 Q、K、V 的张量形状？"},
            )
            await record_event(
                db, learner_id=learner_id, event_type="user_message",
                source="test", project_id=project.id,
                payload={"text": "我的目标是亲手实现一个 MiniGPT"},
            )
            semantic_event = await record_event(
                db, learner_id=learner_id, event_type="learning_feedback",
                source="test", project_id=project.id,
                payload={"value": "semantic-boundary"},
            )
            await apply_semantic_observations(db, semantic_event, [
                {
                    "kernel": "structure",
                    "short_term": {
                        "deferred_threads": ["完成张量热身后回到注意力"],
                        "concept_understanding": {"qkv": "错误维度"},
                    },
                    "reason": "结构只保留返回线索",
                },
                {
                    "kernel": "knowledge",
                    "short_term": {
                        "misconceptions": {"qkv": "把 Q、K、V 当成三个独立输入"},
                        "path_position": {"checkpoint_id": attention.id},
                    },
                    "reason": "知识只保留具体误解",
                },
            ])

            projection = await get_kernel_projection(db, learner_id)
            structure = projection["structure"]["short_term"]
            knowledge = projection["knowledge"]["short_term"]
            value = projection["value"]["short_term"]

            assert structure["path_position"]["checkpoint_title"] == "因果自注意力"
            assert structure["path_dependencies"][0]["title"] == "张量形状"
            assert structure["resume_anchor"]["checkpoint_id"] == attention.id
            assert structure["focus_transition"]["from_checkpoint_id"] == foundation.id
            assert structure["deferred_threads"] == ["完成张量热身后回到注意力"]
            assert "concept_understanding" not in structure

            assert knowledge["knowledge_gap"].startswith("我为什么看不懂")
            assert "current_misconception" not in knowledge
            assert knowledge["misconceptions"]["qkv"] == "把 Q、K、V 当成三个独立输入"
            assert "path_position" not in knowledge
            assert value["current_priority"] == "我的目标是亲手实现一个 MiniGPT"
            assert "current_goal" not in structure
            await db.rollback()

    asyncio.run(scenario())


def test_profile_projects_legacy_goal_to_value_and_marks_self_report(client: TestClient):
    async def scenario():
        async with async_session() as db:
            learner_id = await legacy_learner_id()
            structure = (await db.execute(select(KernelState).where(
                KernelState.learner_id == learner_id,
                KernelState.kernel_name == "structure",
            ))).scalar_one()
            short = dict(structure.short_term or {})
            short["current_goal"] = "历史版本误写的目标"
            structure.short_term = short
            await record_event(
                db, learner_id=learner_id,
                event_type="registration_profile_completed", source="test",
                payload={
                    "background": "只学过 Python",
                    "weekly_hours": 5,
                    "preferred_modes": ["practice"],
                    "focus_areas": ["AI"],
                },
            )

            dimensions = await memory_projection(db, learner_id)
            structure_memories = next(
                item["memories"] for item in dimensions if item["kernel"] == "structure"
            )
            value_memories = next(
                item["memories"] for item in dimensions if item["kernel"] == "value"
            )
            knowledge_memories = next(
                item["memories"] for item in dimensions if item["kernel"] == "knowledge"
            )

            assert not any(item["key"] == "current_goal" for item in structure_memories)
            assert next(item for item in value_memories if item["key"] == "current_goal")["summary"] == "历史版本误写的目标"
            background = next(item for item in knowledge_memories if item["key"] == "declared_background")
            assert background["verification_status"] == "self_reported"
            assert "尚未通过答题或实践验证" in background["summary"]
            await db.rollback()

    asyncio.run(scenario())


def test_five_kernel_migration_is_idempotent(client: TestClient):
    async def scenario():
        await init_db()
        await init_db()
        async with async_session() as db:
            learner_id = await legacy_learner_id()
            kernel_count = len((await db.execute(select(KernelState).where(
                KernelState.learner_id == learner_id,
            ))).scalars().all())
            migration_count = len((await db.execute(
                select(SchemaMigration).where(
                    SchemaMigration.version.in_([
                        "v2-five-kernel-tutor", "v3-evolving-project-proposals",
                        "v4-user-isolation-profile-badges",
                    ])
                )
            )).scalars().all())
            return kernel_count, migration_count

    assert asyncio.run(scenario()) == (5, 3)
