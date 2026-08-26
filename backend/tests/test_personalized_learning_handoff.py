from __future__ import annotations

from copy import deepcopy

import httpx
import pytest

from app.services.personalized_learning_handoff import (
    PersonalizedLearningHandoffClient,
    PersonalizedLearningHandoffConfig,
    PersonalizedLearningHandoffError,
    load_personalized_learning_handoff_config,
)


def _handoff() -> dict:
    return {
        "schema_version": "learning-task-knowledge-to-personalized-learning-v1",
        "entry_id": "ple_0123456789abcdef01234567",
        "source": {"task_card_id": "ltc_network_001"},
        "focus": {
            "knowledge_point": {
                "knowledge_id": "kp_vlan",
                "name": "VLAN 与 802.1Q",
            },
            "source_steps": [
                {"step_id": "step_config", "name": "配置端口"},
            ],
            "strongly_related_skills": [
                {"skill_id": "skill_vlan", "name": "VLAN 配置"},
            ],
            "relationships": [
                {
                    "relation_id": "rel_vlan_001",
                    "step_id": "step_config",
                    "knowledge_id": "kp_vlan",
                    "skill_ids": ["skill_vlan"],
                },
            ],
        },
    }


def _client(handler) -> PersonalizedLearningHandoffClient:
    return PersonalizedLearningHandoffClient(
        config=PersonalizedLearningHandoffConfig(
            import_url=(
                "http://127.0.0.1:4173/api/integrations/"
                "learning-task-knowledge"
            ),
        ),
        transport=httpx.MockTransport(handler),
    )


def test_handoff_config_accepts_launcher_environment_without_private_file(
    monkeypatch, tmp_path
):
    monkeypatch.setenv(
        "PERSONALIZED_LEARNING_IMPORT_URL",
        "http://127.0.0.1:4174/api/integrations/learning-task-knowledge",
    )
    monkeypatch.setenv("PERSONALIZED_LEARNING_TIMEOUT_SECONDS", "12")
    monkeypatch.setenv(
        "PERSONALIZED_LEARNING_PUBLIC_BASE_URL",
        "https://learning.example/personalized-learning/",
    )

    config = load_personalized_learning_handoff_config(tmp_path / "missing.env")

    assert config.import_url.startswith("http://127.0.0.1:4174/")
    assert config.timeout_seconds == 12
    assert config.public_base_url == (
        "https://learning.example/personalized-learning/"
    )


@pytest.mark.asyncio
async def test_handoff_client_uses_public_reverse_proxy_base_for_redirect():
    async def handler(request: httpx.Request) -> httpx.Response:
        body = __import__("json").loads(request.content)
        return httpx.Response(200, json={
            "status": "ok",
            "entry_id": body["handoff"]["entry_id"],
            "project_id": "project_public_001",
            "knowledge_point_id": "kp_vlan",
            "redirect_url": "/agent.html?project_id=project_public_001",
            "created": True,
        })

    client = PersonalizedLearningHandoffClient(
        config=PersonalizedLearningHandoffConfig(
            import_url=(
                "http://127.0.0.1:4174/api/integrations/"
                "learning-task-knowledge"
            ),
            public_base_url=(
                "https://learning.example/personalized-learning/"
            ),
        ),
        transport=httpx.MockTransport(handler),
    )

    result = await client.import_entry(learner_id=17, handoff=_handoff())

    assert result["redirect_url"] == (
        "https://learning.example/personalized-learning/"
        "agent.html?project_id=project_public_001"
    )


@pytest.mark.asyncio
async def test_handoff_client_preserves_wf04_identity_and_is_retry_safe():
    requests: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        body = __import__("json").loads(request.content)
        requests.append(body)
        assert body["student_id"] in {"LEARNFLOW-17", "LEARNFLOW-18"}
        return httpx.Response(200, json={
            "status": "ok",
            "entry_id": body["handoff"]["entry_id"],
            "project_id": "project_handoff_001",
            "knowledge_point_id": "kp_vlan",
            "redirect_url": (
                "/?project_id=project_handoff_001&knowledge_point_id=kp_vlan"
            ),
            "created": len(requests) == 1,
            "content_generation": {
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
                "configured": True,
            },
            "assessment": {
                "type": "provisional_self_check",
                "status": "ready",
                "formal_evidence": False,
            },
        })

    client = _client(handler)
    first = await client.import_entry(learner_id=17, handoff=_handoff())
    second = await client.import_entry(learner_id=17, handoff=_handoff())
    other_learner = await client.import_entry(learner_id=18, handoff=_handoff())

    assert first["created"] is True
    assert second["created"] is False
    assert first["entry_id"] == second["entry_id"]
    assert first["project_id"] == second["project_id"]
    assert requests[0]["handoff"]["entry_id"] == requests[1]["handoff"]["entry_id"]
    assert requests[2]["handoff"]["entry_id"] != requests[0]["handoff"]["entry_id"]
    assert other_learner["entry_id"] == requests[2]["handoff"]["entry_id"]
    assert _handoff()["entry_id"] != first["entry_id"]
    assert first["content_generation"] == {
        "provider": "deepseek",
        "model": "deepseek-v4-flash",
        "configured": True,
    }
    assert first["assessment"]["status"] == "ready"
    assert first["assessment"]["formal_evidence"] is False


@pytest.mark.asyncio
async def test_handoff_client_rejects_relationship_identity_drift_before_send():
    handoff = deepcopy(_handoff())
    handoff["focus"]["relationships"][0]["step_id"] = "step_missing"

    async def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("无效交接不应发往 WF04")

    with pytest.raises(PersonalizedLearningHandoffError, match="不存在的步骤"):
        await _client(handler).import_entry(learner_id=17, handoff=handoff)


@pytest.mark.asyncio
async def test_handoff_client_rejects_unknown_relationship_skill_before_send():
    handoff = deepcopy(_handoff())
    handoff["focus"]["relationships"][0]["skill_ids"] = ["skill_missing"]

    async def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("无效技能关系不应发往下游")

    with pytest.raises(PersonalizedLearningHandoffError, match="不存在的技能"):
        await _client(handler).import_entry(learner_id=17, handoff=handoff)


@pytest.mark.asyncio
async def test_handoff_client_rejects_wf04_response_identity_drift():
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "status": "ok",
            "entry_id": "ple_other",
            "project_id": "project_wrong",
            "knowledge_point_id": "kp_other",
            "redirect_url": "/?project_id=project_wrong",
            "created": True,
        })

    with pytest.raises(PersonalizedLearningHandoffError, match="身份不一致"):
        await _client(handler).import_entry(learner_id=17, handoff=_handoff())


@pytest.mark.asyncio
async def test_handoff_client_rejects_cross_origin_redirect():
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "status": "ok",
            "entry_id": _handoff()["entry_id"],
            "project_id": "project_handoff_001",
            "knowledge_point_id": "kp_vlan",
            "redirect_url": "https://malicious.example/project_handoff_001",
            "created": True,
        })

    with pytest.raises(PersonalizedLearningHandoffError, match="不受信任"):
        await _client(handler).import_entry(learner_id=17, handoff=_handoff())


@pytest.mark.asyncio
async def test_handoff_client_rejects_unknown_content_generation_provider():
    async def handler(request: httpx.Request) -> httpx.Response:
        body = __import__("json").loads(request.content)
        return httpx.Response(200, json={
            "status": "ok",
            "entry_id": body["handoff"]["entry_id"],
            "project_id": "project_handoff_001",
            "knowledge_point_id": "kp_vlan",
            "redirect_url": "/agent.html?project_id=project_handoff_001",
            "created": True,
            "content_generation": {"provider": "unknown-provider"},
        })

    with pytest.raises(PersonalizedLearningHandoffError, match="生成来源"):
        await _client(handler).import_entry(learner_id=17, handoff=_handoff())


@pytest.mark.asyncio
async def test_handoff_client_sends_optional_split_deployment_token():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer downstream-secret"
        body = __import__("json").loads(request.content)
        return httpx.Response(200, json={
            "status": "ok",
            "entry_id": body["handoff"]["entry_id"],
            "project_id": "project_token_001",
            "knowledge_point_id": "kp_vlan",
            "redirect_url": "/agent.html?project_id=project_token_001",
            "created": True,
        })

    client = PersonalizedLearningHandoffClient(
        config=PersonalizedLearningHandoffConfig(
            import_url=(
                "https://learning.example/api/integrations/"
                "learning-task-knowledge"
            ),
            api_token="downstream-secret",
        ),
        transport=httpx.MockTransport(handler),
    )

    result = await client.import_entry(learner_id=17, handoff=_handoff())

    assert result["project_id"] == "project_token_001"
