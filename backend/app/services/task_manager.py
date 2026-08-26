"""
In-process async task manager + error taxonomy.

Design (T1):
- Tasks are persisted in DB (status/progress/result/error); execution runs in
  an in-process asyncio task registered here.
- SSE subscribers poll DB state (snapshot on connect + 1s diff polling), so
  reconnection is trivially safe and no in-memory pub/sub is required.
- Browser closing the page does NOT cancel the task; only an explicit
  cancel request does. Server restart marks stale tasks as failed.
"""
import asyncio
from datetime import datetime
from typing import Awaitable, Dict, Optional

from sqlalchemy import select

from app.db.database import async_session
from app.models.project import Task

TERMINAL_STATUSES = {"completed", "failed", "canceled"}

# ── Error taxonomy ──

ERROR_GUIDANCE = {
    "llm_not_configured": "请先在设置页配置 LLM API Key，然后重新生成。",
    "llm_auth": "API Key 无效或已过期，请检查设置页的配置。",
    "llm_network": "网络连接失败或模型服务不可用，请检查网络后重试。",
    "llm_rate_limit": "请求过于频繁被限流，请稍等片刻后重试。",
    "llm_timeout": "模型响应超时。可稍后重试，或减少内容规模。",
    "llm_format": "模型输出格式不符合要求（已自动重试仍失败）。请重新生成，若持续出现请反馈。",
    "context_too_long": "内容超出模型上下文限制。可减少参考资料规模后重试。",
    "retrieval_empty": "未找到与主题相关的参考资料切片，请确认来源已处理完成。",
    "server_restart": "任务因服务重启而中断，请重新发起。",
    "internal": "内部错误，请查看服务端日志。",
}


def classify_error(e: Exception) -> dict:
    """Map an exception to a structured error {code, message, guidance, retryable}."""
    name = type(e).__name__
    msg = str(e)[:300]
    msg_lower = msg.lower()

    if name == "AuthenticationError":
        code = "llm_auth"
    elif name == "RateLimitError":
        code = "llm_rate_limit"
    elif name in ("APIConnectionError", "APITimeoutError", "ConnectionError",
                  "TimeoutError", "ReadTimeout", "ConnectError"):
        code = "llm_network"
    elif name == "BadRequestError" and ("context" in msg_lower or "token" in msg_lower
                                        or "maximum" in msg_lower):
        code = "context_too_long"
    elif name == "JSONDecodeError" or "json" in name.lower():
        code = "llm_format"
    elif name == "ValueError" and ("json" in msg_lower or "no json" in msg_lower):
        code = "llm_format"
    elif name in ("ValueError",) and ("api key" in msg_lower or "未配置" in msg_lower):
        code = "llm_not_configured"
    else:
        code = "internal"

    return {
        "code": code,
        "message": msg,
        "guidance": ERROR_GUIDANCE.get(code, ERROR_GUIDANCE["internal"]),
        "retryable": code in ("llm_network", "llm_rate_limit", "llm_timeout", "llm_format"),
    }


async def update_task(task_id: int, **fields) -> Optional[Task]:
    """Open a fresh session, apply fields, commit, return refreshed task (or None)."""
    async with async_session() as db:
        task = (await db.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
        if not task:
            return None
        for k, v in fields.items():
            setattr(task, k, v)
        await db.commit()
        await db.refresh(task)
        result = task
    if result.status in TERMINAL_STATUSES and result.agent_action_id:
        from app.services.tutor_service import finalize_action_for_task
        await finalize_action_for_task(result)
    return result


async def get_task(task_id: int) -> Optional[Task]:
    async with async_session() as db:
        task = (await db.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
        return task


async def find_running_task(checkpoint_id: int, task_type: str) -> Optional[Task]:
    """Find a non-terminal task for a checkpoint (used to reject duplicates)."""
    async with async_session() as db:
        task = (await db.execute(
            select(Task)
            .where(Task.checkpoint_id == checkpoint_id,
                   Task.type == task_type,
                   Task.status.in_(["queued", "running"]))
            .order_by(Task.id.desc())
        )).scalar_one_or_none()
        return task


async def mark_stale_tasks_failed():
    """On startup: any queued/running task died with the old process."""
    async with async_session() as db:
        tasks = (await db.execute(
            select(Task).where(Task.status.in_(["queued", "running"]))
        )).scalars().all()
        for t in tasks:
            t.status = "failed"
            t.error = {
                "code": "server_restart",
                "message": "服务重启导致任务中断",
                "guidance": ERROR_GUIDANCE["server_restart"],
                "retryable": True,
            }
            t.finished_at = datetime.utcnow()
        if tasks:
            await db.commit()
    for task in tasks:
        if task.agent_action_id:
            from app.services.tutor_service import finalize_action_for_task
            await finalize_action_for_task(task)


class TaskManager:
    """Registry of running asyncio tasks, backed by DB state."""

    def __init__(self):
        self._running: Dict[int, asyncio.Task] = {}

    def submit(self, task_id: int, coro: Awaitable) -> asyncio.Task:
        """Register and run a coroutine as a background task."""
        t = asyncio.create_task(self._wrap(task_id, coro))
        self._running[task_id] = t
        return t

    async def _wrap(self, task_id: int, coro: Awaitable):
        try:
            await coro
        except asyncio.CancelledError:
            await update_task(task_id, status="canceled", finished_at=datetime.utcnow())
            raise
        except Exception as e:
            err = classify_error(e)
            await update_task(task_id, status="failed", error=err, finished_at=datetime.utcnow())
        finally:
            self._running.pop(task_id, None)

    def cancel(self, task_id: int) -> bool:
        t = self._running.get(task_id)
        if not t or t.done():
            return False
        t.cancel()
        return True

    def is_running(self, task_id: int) -> bool:
        t = self._running.get(task_id)
        return t is not None and not t.done()


manager = TaskManager()
