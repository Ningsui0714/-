"""
Settings API: read/write .env config, test connections.
"""
import os
import json
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from typing import Optional

from app.core.config import settings
from app.services.auth import CurrentLearner, get_current_learner, valid_desktop_request

router = APIRouter()

DEFAULT_ENV_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env"
)
ENV_PATH = os.environ.get("LEARNFLOW_SETTINGS_PATH", DEFAULT_ENV_PATH)

RUNTIME_FIELDS = {
    "LLM_API_KEY": "llm_api_key",
    "LLM_BASE_URL": "llm_base_url",
    "LLM_MODEL": "llm_model",
    "EMBEDDING_BACKEND": "embedding_backend",
    "EMBEDDING_MODEL": "embedding_model",
    "EMBEDDING_API_KEY": "embedding_api_key",
    "EMBEDDING_BASE_URL": "embedding_base_url",
    "VISION_API_KEY": "vision_api_key",
    "VISION_BASE_URL": "vision_base_url",
    "VISION_MODEL": "vision_model",
    "VISION_API_ENHANCE": "vision_api_enhance",
}
SECRET_ENV_KEYS = {"LLM_API_KEY", "EMBEDDING_API_KEY", "VISION_API_KEY"}


def _configured_env_path() -> str:
    """Resolve the desktop path at request time, not only at module import."""
    return os.environ.get("LEARNFLOW_SETTINGS_PATH", ENV_PATH)


def _read_env_file(path: str) -> dict:
    config = {}
    if not os.path.exists(path):
        return config
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, val = line.partition("=")
                config[key.strip()] = val.strip()
    return config


class SettingsUpdate(BaseModel):
    llm_api_key: Optional[str] = None
    llm_base_url: Optional[str] = None
    llm_model: Optional[str] = None
    embedding_backend: Optional[str] = None
    embedding_model: Optional[str] = None
    embedding_api_key: Optional[str] = None
    embedding_base_url: Optional[str] = None
    vision_api_key: Optional[str] = None
    vision_base_url: Optional[str] = None
    vision_model: Optional[str] = None
    vision_api_enhance: Optional[bool] = None


def _read_env() -> dict:
    """Read .env file into dict."""
    path = _configured_env_path()
    config = _read_env_file(path)
    if config or os.path.exists(path):
        return config

    # Older desktop builds wrote settings to backend/.env. Read it once as a
    # migration source, then _write_env() moves the values to the desktop path.
    if path != DEFAULT_ENV_PATH:
        return _read_env_file(DEFAULT_ENV_PATH)
    return config


def _normalize_base_url(value: str) -> str:
    value = (value or "").strip()
    # DeepSeek's current OpenAI-compatible endpoint is the host itself. The
    # old /v1 preset is accepted by some proxies but is not the official V4 URL.
    if value.rstrip("/") in {
        "https://api.deepseek.com",
        "https://api.deepseek.com/v1",
    }:
        return "https://api.deepseek.com"
    return value


def _sync_runtime_from_env(raw: dict) -> None:
    """Keep the live Settings object aligned with the persisted config."""
    for env_key, field in RUNTIME_FIELDS.items():
        if env_key not in raw:
            continue
        value = raw[env_key]
        if env_key in {"LLM_BASE_URL", "EMBEDDING_BASE_URL", "VISION_BASE_URL"}:
            value = _normalize_base_url(value)
        if env_key == "VISION_API_ENHANCE":
            value = value.lower() in ("1", "true", "yes")
        setattr(settings, field, value)


def _is_configured_key(value: str) -> bool:
    return bool(value and value not in ("sk-your-key-here", "***") and "…" not in value)


def _write_env(updates: dict):
    """Write updates to .env, preserving existing keys and order."""
    path = _configured_env_path()
    target_exists = os.path.exists(path)
    source_path = path if target_exists else ""
    if not target_exists and path != DEFAULT_ENV_PATH and os.path.exists(DEFAULT_ENV_PATH):
        # Migrate only settings fields. Never copy the whole development .env
        # (database URLs, tokens, and unrelated secrets) into desktop storage.
        legacy = _read_env_file(DEFAULT_ENV_PATH)
        inherited = {key: legacy[key] for key in RUNTIME_FIELDS if key in legacy}
        inherited.update(updates)
        updates = inherited

    seen_keys = set(updates.keys())
    lines = []

    if source_path:
        with open(source_path, "r") as f:
            for line in f:
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or "=" not in stripped:
                    lines.append(line)
                else:
                    key = stripped.split("=", 1)[0].strip()
                    if key in updates:
                        lines.append(f"{key}={updates[key]}\n")
                        seen_keys.discard(key)
                    else:
                        lines.append(line)

    # Append new keys not already in file
    for key in seen_keys:
        lines.append(f"{key}={updates[key]}\n")

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        f.writelines(lines)

    for env_key, value in updates.items():
        field = RUNTIME_FIELDS.get(env_key)
        if field:
            setattr(settings, field, value.lower() == "true" if env_key == "VISION_API_ENHANCE" else value)


def _mask_key(key: str) -> str:
    """Mask API key for display — show first 8 + last 4 chars."""
    if not key or len(key) < 12:
        return "***"
    return key[:8] + "…" + key[-4:]


def _require_dev_settings(current: CurrentLearner, request: Request):
    if not ((settings.dev_test_login_enabled and current.is_dev_login) or valid_desktop_request(request)):
        raise HTTPException(404, "Not found")


# ── Routes ──


@router.get("/settings")
async def get_settings(request: Request, current: CurrentLearner = Depends(get_current_learner)):
    """Get current settings with masked API keys."""
    _require_dev_settings(current, request)
    from app.core.config import settings as app_settings

    raw = _read_env()
    _sync_runtime_from_env(raw)

    emb_key = raw.get("EMBEDDING_API_KEY", "") or app_settings.embedding_api_key or ""
    vision_key = raw.get("VISION_API_KEY", "") or app_settings.vision_api_key or ""
    llm_key = raw.get("LLM_API_KEY", "") or app_settings.llm_api_key or ""

    return {
        "llm_api_key": _mask_key(llm_key),
        "llm_base_url": _normalize_base_url(raw.get("LLM_BASE_URL", app_settings.llm_base_url)),
        "llm_model": raw.get("LLM_MODEL", app_settings.llm_model),
        "embedding_backend": raw.get("EMBEDDING_BACKEND", app_settings.embedding_backend),
        "embedding_model": raw.get("EMBEDDING_MODEL", app_settings.embedding_model),
        "embedding_api_key": _mask_key(emb_key) if emb_key else "",
        "embedding_base_url": raw.get("EMBEDDING_BASE_URL", app_settings.embedding_base_url or ""),
        "vision_api_key": _mask_key(vision_key) if vision_key else "",
        "vision_base_url": raw.get("VISION_BASE_URL", app_settings.vision_base_url),
        "vision_model": raw.get("VISION_MODEL", app_settings.vision_model),
        "vision_api_enhance": raw.get("VISION_API_ENHANCE", "true").lower() in ("1", "true", "yes") if raw.get("VISION_API_ENHANCE") else bool(app_settings.vision_api_enhance),
        "has_key": _is_configured_key(llm_key),
    }


class TestConnectionRequest(BaseModel):
    api_key: str
    base_url: str
    model: str


@router.post("/settings/test")
async def test_connection(
    req: TestConnectionRequest,
    request: Request,
    current: CurrentLearner = Depends(get_current_learner),
):
    """Test LLM connection with provided credentials."""
    _require_dev_settings(current, request)
    from openai import AsyncOpenAI
    from app.core.config import settings as app_settings

    _sync_runtime_from_env(_read_env())
    api_key = req.api_key if req.api_key != "use_current" else app_settings.llm_api_key
    base_url = _normalize_base_url(req.base_url or app_settings.llm_base_url)

    try:
        client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        resp = await client.chat.completions.create(
            model=req.model,
            messages=[{"role": "user", "content": "say just: OK"}],
            max_tokens=10,
            timeout=15,
        )
        msg = resp.choices[0].message.content
        return {"status": "ok", "message": msg or "(empty response)", "model": resp.model}
    except Exception as e:
        error_str = str(e)
        if "401" in error_str or "Unauthorized" in error_str or "Authentication" in error_str:
            raise HTTPException(400, "认证失败：API Key 无效")
        elif "404" in error_str:
            raise HTTPException(400, f"模型不存在：{req.model}，请检查模型名称")
        elif "timeout" in error_str.lower() or "timed out" in error_str.lower():
            raise HTTPException(400, "连接超时：请检查 Base URL 是否正确")
        else:
            raise HTTPException(400, f"连接失败：{error_str[:200]}")


@router.post("/settings/test-embedding")
async def test_embedding(
    req: TestConnectionRequest,
    request: Request,
    current: CurrentLearner = Depends(get_current_learner),
):
    """Test embedding API connection."""
    _require_dev_settings(current, request)
    from openai import AsyncOpenAI
    from app.core.config import settings as app_settings

    # Resolve credentials: use_current → current LLM key; empty → fallback
    api_key = req.api_key
    base_url = req.base_url
    if api_key == "use_current" or not api_key:
        api_key = app_settings.embedding_api_key or app_settings.llm_api_key
    if not base_url:
        base_url = app_settings.embedding_base_url or app_settings.llm_base_url

    try:
        client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        resp = await client.embeddings.create(
            model=req.model or "text-embedding-ada-002",
            input="test",
            timeout=15,
        )
        dims = len(resp.data[0].embedding)
        return {"status": "ok", "dimensions": dims}
    except Exception as e:
        error_str = str(e)
        if "404" in error_str:
            raise HTTPException(400, "Embedding 端点不可用：该 API 可能不支持 embedding，建议使用 local 后端")
        else:
            raise HTTPException(400, f"测试失败：{error_str[:200]}")


@router.put("/settings")
async def save_settings(
    data: SettingsUpdate,
    request: Request,
    current: CurrentLearner = Depends(get_current_learner),
):
    """Save settings to .env file."""
    _require_dev_settings(current, request)
    updates = {}
    # Only include non-None values
    mapping = {
        "llm_api_key": "LLM_API_KEY",
        "llm_base_url": "LLM_BASE_URL",
        "llm_model": "LLM_MODEL",
        "embedding_backend": "EMBEDDING_BACKEND",
        "embedding_model": "EMBEDDING_MODEL",
        "embedding_api_key": "EMBEDDING_API_KEY",
        "embedding_base_url": "EMBEDDING_BASE_URL",
        "vision_api_key": "VISION_API_KEY",
        "vision_base_url": "VISION_BASE_URL",
        "vision_model": "VISION_MODEL",
        "vision_api_enhance": "VISION_API_ENHANCE",
    }
    for field, env_key in mapping.items():
        val = getattr(data, field, None)
        if val is not None:
            if env_key in SECRET_ENV_KEYS:
                val = val.strip()
                # A blank or masked key means “keep the current key”. There is
                # no accidental destructive clear through the settings form.
                if not val or val in {"***"} or "…" in val:
                    continue
            elif isinstance(val, str):
                val = val.strip()
            if env_key in {"LLM_BASE_URL", "EMBEDDING_BASE_URL", "VISION_BASE_URL"}:
                val = _normalize_base_url(val)
            updates[env_key] = "true" if val is True else ("false" if val is False else val)

    if not updates:
        raise HTTPException(400, "No settings to update")

    _write_env(updates)
    return {"status": "ok", "updated": list(updates.keys())}


# 1x1 red PNG (tiny, for vision connectivity test)
_TINY_PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="


@router.post("/settings/test-vision")
async def test_vision(
    req: TestConnectionRequest,
    request: Request,
    current: CurrentLearner = Depends(get_current_learner),
):
    """Test vision connection with a tiny inline image (Moonshot/kimi)."""
    _require_dev_settings(current, request)
    from openai import AsyncOpenAI
    from app.core.config import settings as app_settings

    api_key = req.api_key if req.api_key != "use_current" else (app_settings.vision_api_key or app_settings.llm_api_key)
    base_url = req.base_url or app_settings.vision_base_url

    try:
        client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        resp = await client.chat.completions.create(
            model=req.model,
            messages=[{"role": "user", "content": [
                {"type": "text", "text": "describe this image in one word"},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{_TINY_PNG}"}},
            ]}],
            max_tokens=500,
            temperature=1,
            timeout=30,
        )
        msg = resp.choices[0].message.content
        if not msg:
            raise HTTPException(400, "模型返回空内容：可能是 reasoning 模型且 max_tokens 不足，或该模型不支持图片输入")
        return {"status": "ok", "message": msg.strip()[:100], "model": resp.model}
    except Exception as e:
        error_str = str(e)
        if "401" in error_str or "Authentication" in error_str:
            raise HTTPException(400, "认证失败：VISION_API_KEY 无效")
        elif "404" in error_str:
            raise HTTPException(400, f"模型不存在或不支持图片：{req.model}\n提示：Moonshot 可用 kimi-k2.7-code-highspeed（最快）或 kimi-k2.6/kimi-k3")
        elif "image" in error_str.lower() and "format" in error_str.lower():
            raise HTTPException(400, "该模型不支持图片输入")
        elif "temperature" in error_str.lower():
            raise HTTPException(400, "该模型要求 temperature=1，请使用 kimi 系列模型")
        else:
            raise HTTPException(400, f"连接失败：{error_str[:200]}")
