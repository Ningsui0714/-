"""Feature-scoped client for the Xunfei Xingchen workflow API.

Credentials deliberately live in ``backend/.private`` and are loaded only by
this module.  They are not part of the process-wide LearnFlow settings object,
so unrelated backend features cannot accidentally depend on this integration.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import httpx
from dotenv import dotenv_values


class XfyunWorkflowConfigError(RuntimeError):
    """Raised when the feature-local credential file is absent or incomplete."""


class XfyunWorkflowError(RuntimeError):
    """Normalized failure raised by the Xingchen workflow API client."""

    def __init__(self, message: str, *, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class XfyunWorkflowCredentials:
    app_id: str
    api_key: str
    api_secret: str
    flow_id: str
    base_url: str = "https://xingchen-api.xf-yun.com"
    timeout_seconds: float = 240.0


def default_credentials_path() -> Path:
    backend_root = Path(__file__).resolve().parents[2]
    return backend_root / ".private" / "learning_task_conversion.xfyun.env"


def load_xfyun_workflow_credentials(
    path: str | Path | None = None,
) -> XfyunWorkflowCredentials:
    """Load only the task-conversion credential file, never the global env."""

    credential_path = Path(path) if path is not None else default_credentials_path()
    if not credential_path.is_file():
        raise XfyunWorkflowConfigError(
            f"岗位典型工作任务转化 API 私密配置不存在: {credential_path}"
        )

    values: Mapping[str, str | None] = dotenv_values(credential_path)
    required = {
        "XFYUN_APP_ID": values.get("XFYUN_APP_ID"),
        "XFYUN_API_KEY": values.get("XFYUN_API_KEY"),
        "XFYUN_API_SECRET": values.get("XFYUN_API_SECRET"),
        "XFYUN_FLOW_ID": values.get("XFYUN_FLOW_ID"),
    }
    missing = [key for key, value in required.items() if not str(value or "").strip()]
    if missing:
        raise XfyunWorkflowConfigError(
            "岗位典型工作任务转化 API 私密配置缺少: " + ", ".join(missing)
        )

    try:
        timeout_seconds = float(
            values.get("XFYUN_WORKFLOW_TIMEOUT_SECONDS") or 240.0
        )
    except (TypeError, ValueError) as exc:
        raise XfyunWorkflowConfigError(
            "XFYUN_WORKFLOW_TIMEOUT_SECONDS 必须为数字"
        ) from exc

    return XfyunWorkflowCredentials(
        app_id=str(required["XFYUN_APP_ID"]).strip(),
        api_key=str(required["XFYUN_API_KEY"]).strip(),
        api_secret=str(required["XFYUN_API_SECRET"]).strip(),
        flow_id=str(required["XFYUN_FLOW_ID"]).strip(),
        base_url=str(
            values.get("XFYUN_WORKFLOW_BASE_URL")
            or "https://xingchen-api.xf-yun.com"
        ).rstrip("/"),
        timeout_seconds=timeout_seconds,
    )


class XfyunLearningTaskWorkflowClient:
    """Invoke only the 岗位典型工作任务转化 Plan workflow."""

    _CONNECT_ATTEMPTS = 3

    def __init__(
        self,
        *,
        credentials: XfyunWorkflowCredentials | None = None,
        credentials_path: str | Path | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.credentials = credentials or load_xfyun_workflow_credentials(
            credentials_path
        )
        self.transport = transport

    async def run(
        self,
        user_input: str,
        *,
        uid: str,
        extra_parameters: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_input = user_input.strip()
        if not normalized_input:
            raise XfyunWorkflowError("岗位典型工作任务不能为空", status_code=422)

        parameters: dict[str, Any] = {"AGENT_USER_INPUT": normalized_input}
        if extra_parameters:
            parameters.update(extra_parameters)

        payload = {
            "flow_id": self.credentials.flow_id,
            # Xingchen currently rejects workflow UIDs longer than 40 chars.
            "uid": str(uid)[:40],
            "parameters": parameters,
            "ext": {
                "bot_id": "workflow",
                "caller": "learnflow-learning-task-conversion",
            },
            "stream": False,
        }
        headers = {
            "Authorization": (
                f"Bearer {self.credentials.api_key}:{self.credentials.api_secret}"
            ),
            "Content-Type": "application/json",
        }

        response: httpx.Response | None = None
        async with httpx.AsyncClient(
            base_url=self.credentials.base_url,
            timeout=self.credentials.timeout_seconds,
            transport=self.transport,
        ) as client:
            for attempt in range(self._CONNECT_ATTEMPTS):
                try:
                    response = await client.post(
                        "/workflow/v1/chat/completions",
                        headers=headers,
                        json=payload,
                    )
                    break
                except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                    # The request did not reach Xingchen, so retrying cannot
                    # duplicate a workflow run. Do not replay read/write or
                    # protocol failures whose delivery state is ambiguous.
                    if attempt == self._CONNECT_ATTEMPTS - 1:
                        raise XfyunWorkflowError(
                            "讯飞星辰工作流连接失败（"
                            f"{_http_error_summary(exc)}）。请检查网络或代理后重试"
                        ) from exc
                    await asyncio.sleep(0.25 * (2 ** attempt))
                except httpx.TimeoutException as exc:
                    raise XfyunWorkflowError(
                        "岗位典型工作任务转化工作流响应超时",
                        status_code=504,
                    ) from exc
                except httpx.HTTPError as exc:
                    raise XfyunWorkflowError(
                        "讯飞星辰工作流请求失败（"
                        f"{_http_error_summary(exc)}）"
                    ) from exc

        if response is None:  # defensive; every loop exit above sets or raises
            raise XfyunWorkflowError("讯飞星辰工作流连接失败（未收到响应）")

        if response.status_code >= 400:
            raise XfyunWorkflowError(
                f"讯飞星辰工作流返回 {response.status_code}: "
                f"{response.text.strip()[:500]}"
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise XfyunWorkflowError("讯飞星辰工作流返回了无效 JSON") from exc
        if not isinstance(data, dict):
            raise XfyunWorkflowError("讯飞星辰工作流返回值必须是 JSON 对象")

        code = data.get("code")
        if code != 0:
            raise XfyunWorkflowError(
                f"讯飞星辰工作流执行失败({code}): {data.get('message') or '未知错误'}"
            )

        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise XfyunWorkflowError("讯飞星辰工作流响应缺少 choices")
        first_choice = choices[0]
        delta = first_choice.get("delta") if isinstance(first_choice, dict) else None
        content = delta.get("content") if isinstance(delta, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise XfyunWorkflowError("讯飞星辰工作流响应缺少最终内容")

        return {
            "schema_version": "learning-task-conversion-xfyun-run-v1",
            "provider": "xunfei-xingchen",
            "app_id": self.credentials.app_id,
            "flow_id": self.credentials.flow_id,
            "run_id": data.get("id"),
            "content": content,
            "usage": data.get("usage") or {},
        }


def _http_error_summary(exc: BaseException) -> str:
    """Preserve useful transport details without leaking request secrets."""

    details: list[str] = []
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen and len(details) < 4:
        seen.add(id(current))
        message = str(current).strip()
        label = type(current).__name__
        details.append(f"{label}: {message}" if message else label)
        current = current.__cause__ or current.__context__
    return " → ".join(details)
