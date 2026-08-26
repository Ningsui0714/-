from __future__ import annotations

import httpx
import pytest

from app.services.learning_task_conversion_gateway import (
    LearningTaskConversionError,
    LearningTaskConversionGateway,
)


def _bundle(task_card_id: str = "ltc_demo") -> dict:
    return {
        "schema_version": "learning-task-conversion-integration-bundle-v1",
        "task_card_id": task_card_id,
        "status": "ready",
        "verification_status": "verified",
        "task": {
            "schema_version": "learning-task-to-personalized-learning-v1",
            "work_task": {
                "work_task_id": "task_docker_01",
                "enterprise_task_name": "Docker 容器镜像构建、运行与验收",
                "task_steps": [
                    {
                        "step_id": "step_01",
                        "action": "编写 Dockerfile 并构建镜像",
                        "deliverable": "可复现的镜像构建记录",
                        "check": "镜像标签存在且构建命令退出码为 0",
                        "knowledge_point_ids": ["knowledge_01"],
                        "skill_point_ids": ["skill_01"],
                    }
                ],
                "knowledge_points": [
                    {"knowledge_id": "knowledge_01", "name": "镜像分层"}
                ],
                "skill_points": [
                    {"skill_id": "skill_01", "name": "构建容器镜像"}
                ],
            },
        },
        "strong_relationships": [],
        "artifacts": {},
    }


@pytest.mark.asyncio
async def test_gateway_accepts_valid_learning_task_bundle():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/tasks/ltc_demo/bundle")
        return httpx.Response(200, json=_bundle())

    gateway = LearningTaskConversionGateway(
        base_url="https://conversion.example",
        transport=httpx.MockTransport(handler),
    )
    result = await gateway.task_bundle("ltc_demo")
    assert result["task"]["work_task"]["task_steps"][0]["step_id"] == "step_01"


@pytest.mark.asyncio
async def test_gateway_rejects_dangling_step_relationships():
    invalid = _bundle()
    invalid["task"]["work_task"]["task_steps"][0]["knowledge_point_ids"] = [
        "missing_knowledge"
    ]

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=invalid)

    gateway = LearningTaskConversionGateway(
        base_url="https://conversion.example",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(LearningTaskConversionError, match="未定义"):
        await gateway.task_bundle("ltc_demo")


@pytest.mark.asyncio
async def test_gateway_normalizes_remote_failures():
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"detail": "temporarily unavailable"})

    gateway = LearningTaskConversionGateway(
        base_url="https://conversion.example",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(LearningTaskConversionError, match="503") as failure:
        await gateway.capabilities()
    assert failure.value.status_code == 502


@pytest.mark.asyncio
async def test_gateway_retries_transient_get_without_replaying_post():
    attempts = {"get": 0, "post": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            attempts["get"] += 1
            if attempts["get"] < 3:
                return httpx.Response(502, request=request)
            return httpx.Response(
                200,
                request=request,
                json={
                    "schema_version": "learning-task-conversion-capabilities-v1",
                    "service": "learning-task-conversion",
                },
            )
        attempts["post"] += 1
        return httpx.Response(502, request=request)

    gateway = LearningTaskConversionGateway(
        base_url="https://task.example",
        transport=httpx.MockTransport(handler),
    )
    assert (await gateway.capabilities())["service"] == "learning-task-conversion"
    assert attempts["get"] == 3

    with pytest.raises(LearningTaskConversionError):
        await gateway.submit_downstream_feedback({
            "schema_version": "personalized-learning-to-task-conversion-feedback-v1",
        })
    assert attempts["post"] == 1


@pytest.mark.asyncio
async def test_gateway_generates_reviewed_catalog_match_with_complete_bundle():
    calls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path.endswith("/typical-tasks/search"):
            return httpx.Response(200, json={
                "status": "ready",
                "primary_task_id": "tt_windows_01",
                "candidates": [{
                    "task_id": "tt_windows_01",
                    "task_name": "Windows 11系统重装与驱动配置",
                }],
            })
        if request.url.path.endswith("/learning-tasks/generate"):
            return httpx.Response(200, json={
                "status": "ready",
                "task_card_id": "ltc_catalog_windows_01",
            })
        if request.url.path.endswith("/tasks/ltc_catalog_windows_01/bundle"):
            return httpx.Response(200, json=_bundle("ltc_catalog_windows_01"))
        raise AssertionError(request.url.path)

    gateway = LearningTaskConversionGateway(
        base_url="https://conversion.example",
        transport=httpx.MockTransport(handler),
    )
    task_card_id = await gateway.generate_catalog_match("windows系统的安装")

    assert task_card_id == "ltc_catalog_windows_01"
    assert calls == [
        "/api/v1/wf03/typical-tasks/search",
        "/api/v1/wf03/learning-tasks/generate",
        "/api/v1/learning-task-conversion/tasks/ltc_catalog_windows_01/bundle",
    ]
