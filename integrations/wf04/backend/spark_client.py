"""标准库 urllib 实现的 OpenAI 兼容聊天客户端（零第三方依赖）。

讲解正文本地化后，后端直接用 ``urllib`` 调用 OpenAI 兼容端点。
当前默认直连 DeepSeek Chat Completions，同时保留星火等 OpenAI 兼容
端点的配置能力，不再依赖星辰画布工作流。
本模块只负责 chat completion 请求/响应；检索侧（本地 FTS5 知识库 + Bing RSS
联网证据）均不需要 embedding，因此不提供 embeddings 调用。

凭据注意：这里的内容模型凭据与星辰工作流网关的
``api_key:api_secret`` 是两套独立凭据，不能混用。
"""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from contextlib import closing
from dataclasses import dataclass
from typing import Any

SPARK_DEFAULT_API_BASE = "https://api.deepseek.com/chat/completions"
SPARK_DEFAULT_MODEL = "deepseek-v4-flash"


class SparkError(Exception):
    """OpenAI 兼容内容模型调用失败。

    ``kind`` 用于让上层决定降级策略：
    - ``timeout`` / ``network``：可重试（引擎至多重试 1 次）
    - ``auth`` / ``refused``：不重试（配错或限流，重试无意义）
    - ``parse`` / ``empty``：响应异常，走模板降级
    - ``http``：服务端错误
    """

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message


@dataclass(frozen=True)
class SparkConfig:
    api_base: str = SPARK_DEFAULT_API_BASE
    api_key: str = ""
    model: str = SPARK_DEFAULT_MODEL
    timeout: float = 60.0
    max_tokens: int = 1600
    temperature: float = 0.4

    @property
    def configured(self) -> bool:
        return bool(self.api_key.strip())

    @property
    def provider_label(self) -> str:
        identity = f"{self.api_base} {self.model}".lower()
        return "DeepSeek" if "deepseek" in identity else "OpenAI 兼容模型"


class SparkClient:
    def __init__(self, config: SparkConfig) -> None:
        self.config = config

    @property
    def configured(self) -> bool:
        return self.config.configured

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """POST 到 OpenAI 兼容端点，返回 ``choices[0].message.content``。

        恒为 ``stream:false``；底层不重试，重试/降级由调用方决定。
        """
        if not self.config.configured:
            raise SparkError("auth", f"未配置{self.config.provider_label} API 密钥")
        body: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": (
                self.config.temperature if temperature is None else temperature
            ),
            "max_tokens": (
                self.config.max_tokens if max_tokens is None else max_tokens
            ),
            "stream": False,
        }
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.config.api_base,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.config.api_key.strip()}",
            },
            method="POST",
        )
        try:
            response = urllib.request.urlopen(request, timeout=self.config.timeout)
        except urllib.error.HTTPError as error:
            status = int(getattr(error, "code", 0) or 0)
            reason = str(getattr(error, "reason", "") or "")
            if status in (401, 403):
                raise SparkError("auth", f"{self.config.provider_label}鉴权失败（HTTP {status}）") from error
            if status == 429:
                raise SparkError("refused", f"{self.config.provider_label}请求过于频繁（HTTP 429）") from error
            if status >= 500:
                raise SparkError("http", f"{self.config.provider_label}服务端错误（HTTP {status}）") from error
            raise SparkError("http", f"{self.config.provider_label}请求失败（HTTP {status}）：{reason}") from error
        except (socket.timeout, TimeoutError) as error:
            raise SparkError("timeout", f"{self.config.provider_label}请求超时") from error
        except urllib.error.URLError as error:
            raise SparkError(
                "network", f"{self.config.provider_label}网络错误：{getattr(error, 'reason', error)}"
            ) from error
        try:
            with closing(response):
                raw = response.read().decode("utf-8", errors="replace")
        except Exception as error:
            raise SparkError("network", f"读取{self.config.provider_label}响应失败：{error}") from error
        try:
            data = json.loads(raw)
        except (ValueError, TypeError) as error:
            raise SparkError(
                "parse", f"{self.config.provider_label}响应不是合法 JSON：{str(error)[:160]}"
            ) from error
        choices = data.get("choices") if isinstance(data, dict) else None
        if not isinstance(choices, list) or not choices:
            raise SparkError("empty", f"{self.config.provider_label}响应没有 choices")
        content = ""
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            message = choice.get("message")
            if isinstance(message, dict) and isinstance(message.get("content"), str):
                content = message["content"]
                break
        if not content.strip():
            raise SparkError("empty", f"{self.config.provider_label}响应正文为空")
        return content.strip()
