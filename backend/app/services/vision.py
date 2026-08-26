"""
Vision service (T6): image understanding via Moonshot (OpenAI-compatible).

- caption_image(path): one-line Chinese caption describing image type + content
- Used by the manual image-caption task to turn repo images into retrievable
  image chunks (caption-as-text RAG).
"""
import base64
import mimetypes
import os

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

from app.core.config import settings

CAPTION_PROMPT = """请用一句中文描述这张图片（30-60 字）：
1. 先说明图片类型（流程图 / 架构图 / 示意图 / 数据图 / 代码截图 / 表格截图 / 公式 / 界面截图 / 照片等）
2. 再说明核心内容（图中表达的关键信息）
不要评价，不要加前缀。"""


def _get_llm() -> ChatOpenAI:
    api_key = settings.vision_api_key or settings.llm_api_key
    return ChatOpenAI(
        model=settings.vision_model,
        api_key=api_key,
        base_url=settings.vision_base_url,
        temperature=1.0,  # kimi 系列只允许 temperature=1
        timeout=120,
        max_retries=0,
        max_tokens=1500,  # reasoning 模型需要余量，否则 content 为空
    )


def image_to_data_url(path: str) -> str:
    """Read image file → base64 data URL (moonshot vision input format)."""
    mime = mimetypes.guess_type(path)[0] or "image/png"
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def caption_image(path: str) -> str:
    """Generate a one-line Chinese caption for an image file (1 retry on empty)."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"Image not found: {path}")
    data_url = image_to_data_url(path)
    message = HumanMessage(content=[
        {"type": "text", "text": CAPTION_PROMPT},
        {"type": "image_url", "image_url": {"url": data_url}},
    ])
    llm = _get_llm()
    for attempt in range(2):
        resp = llm.invoke([message])
        text = (resp.content or "").strip()
        if text:
            return text[:120]
    raise ValueError("Vision API returned empty caption (twice)")
