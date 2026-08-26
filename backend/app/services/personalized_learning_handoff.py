"""Feature-scoped adapter for launching personalized learning from WF03.

The downstream endpoint is deliberately loaded from ``backend/.private`` so
the browser never receives service configuration and unrelated LearnFlow
features cannot depend on this integration accidentally.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urljoin, urlsplit

import httpx
from dotenv import dotenv_values


class PersonalizedLearningHandoffConfigError(RuntimeError):
    """Raised when the feature-local downstream configuration is missing."""


class PersonalizedLearningHandoffError(RuntimeError):
    """Normalized downstream import failure."""

    def __init__(self, message: str, *, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def scoped_personalized_learning_entry_id(
    source_entry_id: str,
    learner_id: int,
) -> str:
    """Return the stable downstream handoff identity for one learner."""

    return "ple_" + sha256(
        f"{source_entry_id}:learner:{learner_id}".encode("utf-8")
    ).hexdigest()[:24]


@dataclass(frozen=True)
class PersonalizedLearningHandoffConfig:
    import_url: str
    timeout_seconds: float = 20.0
    api_token: str = ""
    public_base_url: str = ""


def default_config_path() -> Path:
    backend_root = Path(__file__).resolve().parents[2]
    return backend_root / ".private" / "personalized_learning.env"


def load_personalized_learning_handoff_config(
    path: str | Path | None = None,
) -> PersonalizedLearningHandoffConfig:
    config_path = Path(path) if path is not None else default_config_path()
    values: Mapping[str, str | None] = (
        dotenv_values(config_path) if config_path.is_file() else {}
    )
    import_url = str(
        os.getenv("PERSONALIZED_LEARNING_IMPORT_URL")
        or values.get("PERSONALIZED_LEARNING_IMPORT_URL")
        or ""
    ).strip()
    if not import_url and not config_path.is_file():
        raise PersonalizedLearningHandoffConfigError(
            f"个性化学习交接私密配置不存在: {config_path}"
        )
    parsed = urlsplit(import_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise PersonalizedLearningHandoffConfigError(
            "PERSONALIZED_LEARNING_IMPORT_URL 必须是完整的 HTTP(S) 地址"
        )
    public_base_url = str(
        os.getenv("PERSONALIZED_LEARNING_PUBLIC_BASE_URL")
        or values.get("PERSONALIZED_LEARNING_PUBLIC_BASE_URL")
        or ""
    ).strip()
    if public_base_url:
        public_parts = urlsplit(public_base_url)
        if public_parts.scheme not in {"http", "https"} or not public_parts.netloc:
            raise PersonalizedLearningHandoffConfigError(
                "PERSONALIZED_LEARNING_PUBLIC_BASE_URL 必须是完整的 HTTP(S) 地址"
            )
    try:
        timeout_seconds = float(
            os.getenv("PERSONALIZED_LEARNING_TIMEOUT_SECONDS")
            or values.get("PERSONALIZED_LEARNING_TIMEOUT_SECONDS")
            or 20.0
        )
    except (TypeError, ValueError) as exc:
        raise PersonalizedLearningHandoffConfigError(
            "PERSONALIZED_LEARNING_TIMEOUT_SECONDS 必须为数字"
        ) from exc
    return PersonalizedLearningHandoffConfig(
        import_url=import_url,
        timeout_seconds=max(1.0, min(timeout_seconds, 120.0)),
        api_token=str(
            os.getenv("PERSONALIZED_LEARNING_API_TOKEN")
            or values.get("PERSONALIZED_LEARNING_API_TOKEN")
            or ""
        ).strip(),
        public_base_url=public_base_url,
    )


class PersonalizedLearningHandoffClient:
    """Import one verified knowledge-scoped handoff into personalized learning."""

    def __init__(
        self,
        *,
        config: PersonalizedLearningHandoffConfig | None = None,
        config_path: str | Path | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.config = config or load_personalized_learning_handoff_config(config_path)
        self.transport = transport

    @staticmethod
    def _validate_handoff(handoff: dict[str, Any]) -> tuple[str, str]:
        if handoff.get("schema_version") != (
            "learning-task-knowledge-to-personalized-learning-v1"
        ):
            raise PersonalizedLearningHandoffError(
                "个性化学习交接协议版本不受支持",
                status_code=422,
            )
        entry_id = str(handoff.get("entry_id") or "").strip()
        source = handoff.get("source")
        focus = handoff.get("focus")
        knowledge = focus.get("knowledge_point") if isinstance(focus, dict) else None
        task_card_id = str(
            source.get("task_card_id") if isinstance(source, dict) else ""
        ).strip()
        knowledge_id = str(
            knowledge.get("knowledge_id") if isinstance(knowledge, dict) else ""
        ).strip()
        knowledge_name = str(
            knowledge.get("name") if isinstance(knowledge, dict) else ""
        ).strip()
        source_steps = focus.get("source_steps") if isinstance(focus, dict) else None
        related_skills = (
            focus.get("strongly_related_skills") if isinstance(focus, dict) else None
        )
        relationships = focus.get("relationships") if isinstance(focus, dict) else None
        if not entry_id or not task_card_id or not knowledge_id or not knowledge_name:
            raise PersonalizedLearningHandoffError(
                "个性化学习交接缺少稳定任务或知识点身份",
                status_code=422,
            )
        if not isinstance(source_steps, list) or not source_steps:
            raise PersonalizedLearningHandoffError(
                "个性化学习交接缺少来源任务步骤",
                status_code=422,
            )
        step_ids = {
            str(item.get("step_id") or "").strip()
            for item in source_steps
            if isinstance(item, dict) and str(item.get("step_id") or "").strip()
        }
        if len(step_ids) != len(source_steps):
            raise PersonalizedLearningHandoffError(
                "个性化学习交接的步骤 ID 必须唯一且非空",
                status_code=422,
            )
        if not isinstance(related_skills, list):
            raise PersonalizedLearningHandoffError(
                "个性化学习交接的强相关技能必须是数组",
                status_code=422,
            )
        skill_ids = {
            str(item.get("skill_id") or "").strip()
            for item in related_skills
            if isinstance(item, dict) and str(item.get("skill_id") or "").strip()
        }
        if len(skill_ids) != len(related_skills):
            raise PersonalizedLearningHandoffError(
                "个性化学习交接的技能 ID 必须唯一且非空",
                status_code=422,
            )
        if not isinstance(relationships, list) or not relationships:
            raise PersonalizedLearningHandoffError(
                "个性化学习交接缺少步骤—知识点强关系",
                status_code=422,
            )
        for relation in relationships:
            if not isinstance(relation, dict):
                raise PersonalizedLearningHandoffError(
                    "个性化学习交接关系必须是 JSON 对象",
                    status_code=422,
                )
            if str(relation.get("step_id") or "").strip() not in step_ids:
                raise PersonalizedLearningHandoffError(
                    "个性化学习交接关系引用了不存在的步骤",
                    status_code=422,
                )
            relation_knowledge_id = str(
                relation.get("knowledge_id") or knowledge_id
            ).strip()
            if relation_knowledge_id != knowledge_id:
                raise PersonalizedLearningHandoffError(
                    "个性化学习交接关系的知识点与当前入口不一致",
                    status_code=422,
                )
            relation_skill_ids = relation.get("skill_ids")
            if not isinstance(relation_skill_ids, list):
                raise PersonalizedLearningHandoffError(
                    "个性化学习交接关系的技能 ID 必须是数组",
                    status_code=422,
                )
            normalized_relation_skill_ids = {
                str(value).strip()
                for value in relation_skill_ids
                if str(value).strip()
            }
            if (
                len(normalized_relation_skill_ids) != len(relation_skill_ids)
                or normalized_relation_skill_ids - skill_ids
            ):
                raise PersonalizedLearningHandoffError(
                    "个性化学习交接关系引用了不存在的技能",
                    status_code=422,
                )
        return entry_id, knowledge_id

    async def import_entry(
        self,
        *,
        learner_id: int,
        handoff: dict[str, Any],
    ) -> dict[str, Any]:
        source_entry_id, knowledge_id = self._validate_handoff(handoff)
        # WF04 owns a globally unique entry_id. Scope the stable source entry
        # to one learner so retries resume the same project without allowing
        # different learners to share or conflict on that project.
        entry_id = scoped_personalized_learning_entry_id(
            source_entry_id,
            learner_id,
        )
        scoped_handoff = {**handoff, "entry_id": entry_id}
        payload = {
            "student_id": f"LEARNFLOW-{learner_id}",
            "handoff": scoped_handoff,
        }
        try:
            async with httpx.AsyncClient(
                timeout=self.config.timeout_seconds,
                follow_redirects=False,
                transport=self.transport,
                # Local integration endpoints must not be routed through the
                # macOS system HTTP proxy (common in development machines).
                trust_env=False,
            ) as client:
                headers = (
                    {"Authorization": f"Bearer {self.config.api_token}"}
                    if self.config.api_token
                    else None
                )
                response = await client.post(
                    self.config.import_url,
                    json=payload,
                    headers=headers,
                )
        except httpx.TimeoutException as exc:
            raise PersonalizedLearningHandoffError(
                "个性化学习服务响应超时，请稍后重试",
                status_code=504,
            ) from exc
        except httpx.HTTPError as exc:
            raise PersonalizedLearningHandoffError(
                f"个性化学习服务不可用: {exc}",
                status_code=503,
            ) from exc

        if response.status_code >= 400:
            try:
                body = response.json()
            except ValueError:
                body = {}
            detail = str(
                body.get("user_message")
                or body.get("detail")
                or response.text
                or "下游导入失败"
            ).strip()[:500]
            raise PersonalizedLearningHandoffError(
                f"个性化学习服务拒绝了交接（{response.status_code}）：{detail}",
                status_code=502,
            )
        try:
            result = response.json()
        except ValueError as exc:
            raise PersonalizedLearningHandoffError(
                "个性化学习服务返回了无效 JSON"
            ) from exc
        if not isinstance(result, dict):
            raise PersonalizedLearningHandoffError(
                "个性化学习服务返回值必须是 JSON 对象"
            )
        redirect_path = str(result.get("redirect_url") or "").strip()
        if not redirect_path:
            raise PersonalizedLearningHandoffError(
                "个性化学习服务没有返回可打开的项目地址"
            )
        if self.config.public_base_url:
            redirect_url = urljoin(
                self.config.public_base_url.rstrip("/") + "/",
                redirect_path.lstrip("/"),
            )
            trusted_base_url = self.config.public_base_url
        else:
            redirect_url = urljoin(self.config.import_url, redirect_path)
            trusted_base_url = self.config.import_url
        redirect_parts = urlsplit(redirect_url)
        trusted_parts = urlsplit(trusted_base_url)
        if (
            redirect_parts.scheme not in {"http", "https"}
            or redirect_parts.netloc != trusted_parts.netloc
        ):
            raise PersonalizedLearningHandoffError(
                "个性化学习服务返回了不受信任的跳转地址"
            )
        returned_entry_id = str(result.get("entry_id") or "").strip()
        returned_knowledge_id = str(
            result.get("knowledge_point_id") or ""
        ).strip()
        project_id = str(result.get("project_id") or "").strip()
        if returned_entry_id != entry_id or returned_knowledge_id != knowledge_id:
            raise PersonalizedLearningHandoffError(
                "个性化学习服务返回的任务或知识点身份不一致"
            )
        if not project_id:
            raise PersonalizedLearningHandoffError(
                "个性化学习服务未返回可恢复的项目 ID"
            )
        content_generation = result.get("content_generation")
        if not isinstance(content_generation, dict):
            content_generation = {}
        generation_provider = str(
            content_generation.get("provider") or "deterministic_template"
        ).strip()
        if generation_provider not in {
            "deepseek", "spark_openai_compatible", "deterministic_template",
        }:
            raise PersonalizedLearningHandoffError(
                "个性化学习服务返回了未知的内容生成来源"
            )
        assessment = result.get("assessment")
        if not isinstance(assessment, dict):
            assessment = {}
        assessment_status = str(assessment.get("status") or "generating").strip()
        if assessment_status not in {"queued", "generating", "ready", "failed"}:
            raise PersonalizedLearningHandoffError(
                "个性化学习服务返回了未知的测评准备状态"
            )
        return {
            "status": "ok",
            "entry_id": returned_entry_id,
            "project_id": project_id,
            "knowledge_point_id": returned_knowledge_id,
            "redirect_url": redirect_url,
            "content_generation": {
                "provider": generation_provider,
                "model": str(content_generation.get("model") or "").strip()[:80],
                "configured": bool(content_generation.get("configured")),
            },
            "assessment": {
                "type": "provisional_self_check",
                "status": assessment_status,
                "formal_evidence": False,
            },
            "created": bool(result.get("created")),
        }
