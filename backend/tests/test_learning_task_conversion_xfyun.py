from __future__ import annotations

import httpx
import pytest

from app.services.learning_task_conversion_xfyun import (
    XfyunLearningTaskWorkflowClient,
    XfyunWorkflowCredentials,
    XfyunWorkflowError,
)


def _credentials() -> XfyunWorkflowCredentials:
    return XfyunWorkflowCredentials(
        app_id="app-test",
        api_key="key-test",
        api_secret="secret-test",
        flow_id="flow-test",
        base_url="https://xingchen.example",
        timeout_seconds=3.0,
    )


@pytest.mark.asyncio
async def test_xfyun_client_uses_feature_credentials_and_returns_content():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/workflow/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer key-test:secret-test"
        body = __import__("json").loads(request.content)
        assert body["flow_id"] == "flow-test"
        assert body["parameters"]["AGENT_USER_INPUT"] == "Windows 系统重装"
        assert len(body["uid"]) <= 40
        assert body["stream"] is False
        return httpx.Response(
            200,
            json={
                "code": 0,
                "message": "Success",
                "id": "run-test",
                "choices": [
                    {
                        "delta": {"role": "assistant", "content": "https://example/task"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"total_tokens": 20},
            },
        )

    client = XfyunLearningTaskWorkflowClient(
        credentials=_credentials(),
        transport=httpx.MockTransport(handler),
    )
    result = await client.run("Windows 系统重装", uid="learner-1")
    assert result["schema_version"] == "learning-task-conversion-xfyun-run-v1"
    assert result["content"] == "https://example/task"
    assert result["flow_id"] == "flow-test"


@pytest.mark.asyncio
async def test_xfyun_client_normalizes_workflow_error():
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "code": 20805,
                "message": "flow is draft",
                "choices": [{"delta": {"content": ""}}],
            },
        )

    client = XfyunLearningTaskWorkflowClient(
        credentials=_credentials(),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(XfyunWorkflowError, match="20805"):
        await client.run("任务", uid="learner-1")


@pytest.mark.asyncio
async def test_xfyun_client_rejects_empty_task_before_network_call():
    client = XfyunLearningTaskWorkflowClient(credentials=_credentials())
    with pytest.raises(XfyunWorkflowError, match="不能为空") as failure:
        await client.run("   ", uid="learner-1")
    assert failure.value.status_code == 422


@pytest.mark.asyncio
async def test_xfyun_client_retries_connect_failure_and_keeps_error_detail():
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ConnectError("TLS handshake failed", request=request)

    client = XfyunLearningTaskWorkflowClient(
        credentials=_credentials(),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(XfyunWorkflowError, match="ConnectError.*TLS handshake failed"):
        await client.run("任务", uid="learner-1")
    assert attempts == 3
