"""Validated adapter for the岗位典型工作任务转化 service.

The remote Xingchen-backed service is an artifact producer, not a LearnFlow
state authority.  This gateway only calls fixed, server-configured paths and
checks the versioned handoff contracts before returning them to the API layer.
"""
from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.core.config import settings


class LearningTaskConversionError(RuntimeError):
    """Normalized failure raised by the external workflow adapter."""

    def __init__(self, message: str, *, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


class LearningTaskConversionGateway:
    _READ_ATTEMPTS = 6
    _TRANSIENT_STATUS_CODES = {429, 502, 503, 504}

    def __init__(
        self,
        *,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        configured_base = base_url or settings.learning_task_conversion_base_url
        self.base_url = configured_base.rstrip("/")
        self.timeout_seconds = (
            timeout_seconds
            if timeout_seconds is not None
            else settings.learning_task_conversion_timeout_seconds
        )
        self.transport = transport

    async def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_method = method.upper()
        attempts = self._READ_ATTEMPTS if normalized_method == "GET" else 1
        response: httpx.Response | None = None
        last_error: httpx.HTTPError | None = None

        async with httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout_seconds,
            follow_redirects=False,
            transport=self.transport,
        ) as client:
            for attempt in range(attempts):
                try:
                    response = await client.request(
                        normalized_method, path, json=payload,
                    )
                    if (
                        response.status_code not in self._TRANSIENT_STATUS_CODES
                        or attempt == attempts - 1
                    ):
                        break
                except httpx.HTTPError as exc:
                    last_error = exc
                    if attempt == attempts - 1:
                        break
                await asyncio.sleep(min(0.15 * (2 ** attempt), 1.2))

        if response is None:
            if isinstance(last_error, httpx.TimeoutException):
                raise LearningTaskConversionError(
                    "岗位典型工作任务转化服务响应超时",
                    status_code=504,
                ) from last_error
            raise LearningTaskConversionError(
                f"岗位典型工作任务转化服务不可用: {last_error or '连接失败'}"
            ) from last_error

        if response.status_code >= 400:
            detail = response.text.strip()[:500]
            raise LearningTaskConversionError(
                f"岗位典型工作任务转化服务返回 {response.status_code}: {detail}",
                status_code=502,
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise LearningTaskConversionError(
                "岗位典型工作任务转化服务返回了无效 JSON"
            ) from exc
        if not isinstance(data, dict):
            raise LearningTaskConversionError(
                "岗位典型工作任务转化服务返回值必须是 JSON 对象"
            )
        return data

    async def capabilities(self) -> dict[str, Any]:
        payload = await self._request(
            "GET", "/api/v1/learning-task-conversion/capabilities"
        )
        if payload.get("schema_version") != "learning-task-conversion-capabilities-v1":
            raise LearningTaskConversionError("不支持的岗位任务转化能力契约版本")
        return payload

    async def generate_catalog_match(self, query: str) -> str | None:
        """Reuse one reviewed enterprise task before invoking the model.

        The task catalogue is the authoritative WF03 cache.  A successful
        match already contains the reviewed workflow steps and knowledge-skill
        mappings, so sending the same task through a fresh model repair run can
        only lose information.  Returning ``None`` keeps unseen tasks on the
        Xingchen Plan path.
        """

        normalized_query = query.strip()
        if not normalized_query:
            return None
        search = await self._request(
            "POST",
            "/api/v1/wf03/typical-tasks/search",
            payload={"query": normalized_query, "limit": 5},
        )
        if search.get("status") != "ready":
            return None
        task_id = str(
            search.get("primary_task_id") or search.get("best_task_id") or ""
        ).strip()
        candidates = search.get("candidates")
        if not task_id or not isinstance(candidates, list):
            return None
        matched = next(
            (
                item for item in candidates
                if isinstance(item, dict)
                and str(item.get("task_id") or "").strip() == task_id
            ),
            None,
        )
        if matched is None:
            return None

        generated = await self._request(
            "POST",
            "/api/v1/wf03/learning-tasks/generate",
            payload={"typical_task_id": task_id},
        )
        task_card_id = str(generated.get("task_card_id") or "").strip()
        if generated.get("status") != "ready" or not task_card_id:
            return None
        # Validate the persisted delivery now.  This prevents a stale catalogue
        # row from bypassing the same integration gate used by model output.
        await self.task_bundle(task_card_id)
        return task_card_id

    async def submit_upstream_handoff(
        self,
        handoff: dict[str, Any],
    ) -> dict[str, Any]:
        if handoff.get("schema_version") != "competency-graph-learning-task-handoff-v1":
            raise LearningTaskConversionError(
                "上游岗位能力图谱交接契约版本不正确",
                status_code=422,
            )
        return await self._request(
            "POST",
            "/api/v1/learning-task-conversion/upstream-handoffs",
            payload=handoff,
        )

    async def task_bundle(self, task_card_id: str) -> dict[str, Any]:
        payload = await self._request(
            "GET",
            f"/api/v1/learning-task-conversion/tasks/{task_card_id}/bundle",
        )
        return self._validate_bundle(payload, task_card_id)

    async def personalized_learning_handoff(
        self,
        task_card_id: str,
    ) -> dict[str, Any]:
        payload = await self._request(
            "GET",
            (
                "/api/v1/learning-task-conversion/tasks/"
                f"{task_card_id}/personalized-learning.json"
            ),
        )
        if payload.get("schema_version") != "learning-task-to-personalized-learning-v1":
            raise LearningTaskConversionError("不支持的个性化学习交付契约版本")
        work_task = payload.get("work_task")
        if not isinstance(work_task, dict) or not work_task.get("task_steps"):
            raise LearningTaskConversionError("个性化学习交付缺少工作任务步骤")
        return payload

    async def submit_downstream_feedback(
        self,
        feedback: dict[str, Any],
    ) -> dict[str, Any]:
        if (
            feedback.get("schema_version")
            != "personalized-learning-to-task-conversion-feedback-v1"
        ):
            raise LearningTaskConversionError(
                "下游反馈契约版本不正确",
                status_code=422,
            )
        return await self._request(
            "POST",
            "/api/v1/learning-task-conversion/downstream-feedback",
            payload=feedback,
        )

    @staticmethod
    def _validate_bundle(
        payload: dict[str, Any],
        task_card_id: str,
    ) -> dict[str, Any]:
        if (
            payload.get("schema_version")
            != "learning-task-conversion-integration-bundle-v1"
        ):
            raise LearningTaskConversionError("不支持的岗位任务转化集成包版本")
        if payload.get("task_card_id") != task_card_id:
            raise LearningTaskConversionError("岗位任务转化集成包的任务 ID 不一致")

        task = payload.get("task")
        if not isinstance(task, dict):
            raise LearningTaskConversionError("岗位任务转化集成包缺少个性化学习交付")
        if task.get("schema_version") != "learning-task-to-personalized-learning-v1":
            raise LearningTaskConversionError("个性化学习交付契约版本不正确")
        work_task = task.get("work_task")
        if not isinstance(work_task, dict):
            raise LearningTaskConversionError("个性化学习交付缺少 work_task")
        steps = work_task.get("task_steps")
        if not isinstance(steps, list) or not steps:
            raise LearningTaskConversionError("个性化学习交付缺少任务步骤")

        knowledge_ids = {
            str(item.get("knowledge_id"))
            for item in work_task.get("knowledge_points", [])
            if isinstance(item, dict) and item.get("knowledge_id")
        }
        skill_ids = {
            str(item.get("skill_id"))
            for item in work_task.get("skill_points", [])
            if isinstance(item, dict) and item.get("skill_id")
        }
        for index, step in enumerate(steps, start=1):
            if not isinstance(step, dict):
                raise LearningTaskConversionError(f"第 {index} 个任务步骤格式错误")
            required = ("step_id", "action", "deliverable", "check")
            if any(not str(step.get(key) or "").strip() for key in required):
                raise LearningTaskConversionError(f"第 {index} 个任务步骤字段不完整")
            step_knowledge = {str(value) for value in step.get("knowledge_point_ids", [])}
            step_skills = {str(value) for value in step.get("skill_point_ids", [])}
            if not step_knowledge or not step_skills:
                raise LearningTaskConversionError(
                    f"第 {index} 个任务步骤缺少知识点或技能点映射"
                )
            if step_knowledge - knowledge_ids or step_skills - skill_ids:
                raise LearningTaskConversionError(
                    f"第 {index} 个任务步骤引用了未定义的知识点或技能点"
                )
        return payload
