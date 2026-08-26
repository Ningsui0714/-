"""LearnFlow-facing API for the岗位典型工作任务转化 adapter."""
from __future__ import annotations

import asyncio
import re
import hmac
from hashlib import sha256
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.core.config import settings
from app.models.learning import (
    AgentMessage, AgentSession, EvidenceEvent, Learner, UserAccount,
)
from app.services.auth import CurrentLearner, get_current_learner
from app.services.learning_task_conversion_gateway import (
    LearningTaskConversionError,
    LearningTaskConversionGateway,
)
from app.services.learning_task_conversion_xfyun import (
    XfyunLearningTaskWorkflowClient,
    XfyunWorkflowConfigError,
    XfyunWorkflowError,
)
from app.services.personalized_learning_handoff import (
    PersonalizedLearningHandoffClient,
    PersonalizedLearningHandoffConfigError,
    PersonalizedLearningHandoffError,
    scoped_personalized_learning_entry_id,
)
from app.services.learning_runtime import record_event


router = APIRouter(
    prefix="/learning-task-conversion",
    tags=["岗位典型工作任务转化集成"],
)

_SPECULATIVE_REPAIR_HEAD_START_SECONDS = 5.0


class LearningTaskGenerationRequest(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    session_id: int | None = Field(default=None, ge=1)
    client_turn_id: str | None = Field(default=None, min_length=3, max_length=120)


class LearningTaskIntegrationRequest(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    student_id: str = Field(default="", max_length=120)


class PersonalizedLearningResultRequest(BaseModel):
    schema_version: str = Field(
        pattern=r"^personalized-learning-result-v1$",
    )
    entry_id: str = Field(min_length=8, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    project_id: str = Field(min_length=3, max_length=120, pattern=r"^[A-Za-z0-9_-]+$")
    knowledge_point_id: str = Field(
        min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$",
    )
    result_type: str = Field(pattern=r"^assessment_completed$")
    result_id: str = Field(min_length=3, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    formal_evidence: bool = False
    summary: dict[str, Any] = Field(default_factory=dict)


def _require_learning_task_integration(request: Request) -> None:
    configured = settings.learning_task_conversion_integration_token.strip()
    supplied = request.headers.get("x-learning-task-conversion-token", "").strip()
    if configured:
        if supplied and hmac.compare_digest(supplied, configured):
            return
        raise HTTPException(status_code=401, detail="学习型任务转化服务凭据无效")
    host = request.client.host if request.client else ""
    if settings.dev_test_login_enabled and host in {"127.0.0.1", "::1", "localhost", "testclient"}:
        return
    raise HTTPException(status_code=503, detail="学习型任务转化服务接口尚未配置")


def _knowledge_handoff_entry(
    bundle: dict[str, Any],
    task_card_id: str,
    knowledge_id: str,
) -> dict[str, Any]:
    """Build the smallest complete handoff for one personalized-learning focus."""

    task_envelope = bundle.get("task")
    work_task = (
        task_envelope.get("work_task")
        if isinstance(task_envelope, dict)
        else None
    )
    if not isinstance(work_task, dict):
        raise LearningTaskConversionError(
            "个性化学习交接缺少学习型工作任务",
            status_code=422,
        )

    knowledge_points = work_task.get("knowledge_points") or []
    knowledge = next(
        (
            item for item in knowledge_points
            if isinstance(item, dict)
            and str(item.get("knowledge_id") or "") == knowledge_id
        ),
        None,
    )
    if knowledge is None:
        raise LearningTaskConversionError(
            "当前学习型任务中不存在该知识点",
            status_code=404,
        )

    source_steps = [
        step for step in work_task.get("task_steps") or []
        if isinstance(step, dict)
        and knowledge_id in {
            str(value) for value in step.get("knowledge_point_ids") or []
        }
    ]
    if not source_steps:
        raise LearningTaskConversionError(
            "该知识点没有可追溯的任务步骤映射",
            status_code=422,
        )

    skill_ids = {
        str(skill_id)
        for step in source_steps
        for skill_id in step.get("skill_point_ids") or []
        if str(skill_id).strip()
    }
    skill_ids.update(
        str(skill_id)
        for skill_id in knowledge.get("related_skill_ids") or []
        if str(skill_id).strip()
    )
    related_skills = [
        skill for skill in work_task.get("skill_points") or []
        if isinstance(skill, dict)
        and str(skill.get("skill_id") or "") in skill_ids
    ]

    explicit_relations = [
        relation for relation in bundle.get("strong_relationships") or []
        if isinstance(relation, dict)
        and str(relation.get("knowledge_id") or "") == knowledge_id
    ]
    if explicit_relations:
        relationships = []
        for relation in explicit_relations:
            raw_requested_steps = relation.get("applies_to_steps") or []
            if not isinstance(raw_requested_steps, (list, tuple, set)):
                raw_requested_steps = [raw_requested_steps]
            requested_steps = {
                str(value).strip()
                for value in raw_requested_steps
                if str(value).strip()
            }
            explicit_step_id = str(relation.get("step_id") or "").strip()
            matched_steps = [
                step for step in source_steps
                if (
                    (explicit_step_id and str(step.get("step_id") or "") == explicit_step_id)
                    or bool(
                        requested_steps.intersection({
                            str(step.get("step_id") or "").strip(),
                            str(step.get("name") or "").strip(),
                            str(step.get("title") or "").strip(),
                            str(step.get("action") or "").strip(),
                        })
                    )
                )
            ]
            # Some providers emit only a knowledge-level relation.  It can be
            # assigned deterministically when this handoff has one source step.
            if not matched_steps and len(source_steps) == 1:
                matched_steps = source_steps
            raw_skill_ids = relation.get("skill_ids") or []
            if not isinstance(raw_skill_ids, (list, tuple, set)):
                raw_skill_ids = [raw_skill_ids]
            else:
                raw_skill_ids = list(raw_skill_ids)
            if relation.get("skill_id"):
                raw_skill_ids = [*raw_skill_ids, relation["skill_id"]]
            normalized_skill_ids = list(dict.fromkeys(
                str(value).strip() for value in raw_skill_ids if str(value).strip()
            ))
            for match_index, step in enumerate(matched_steps):
                relationship = dict(relation)
                relationship.update({
                    "relation_id": (
                        str(relation.get("relation_id") or "")
                        + (f":{match_index + 1}" if len(matched_steps) > 1 else "")
                    ),
                    "relation_type": str(
                        relation.get("relation_type") or "required_for_step"
                    ),
                    "strength": "strong",
                    "step_id": str(step.get("step_id") or ""),
                    "knowledge_id": knowledge_id,
                    "skill_ids": normalized_skill_ids,
                })
                relationships.append(relationship)
        if not relationships:
            raise LearningTaskConversionError(
                "知识点强关系无法定位到已校验任务步骤",
                status_code=422,
            )
    else:
        relationships = [
            {
                "relation_id": f"{step.get('step_id')}:{knowledge_id}",
                "relation_type": "required_for_step",
                "strength": "strong",
                "step_id": str(step.get("step_id") or ""),
                "knowledge_id": knowledge_id,
                "skill_ids": [
                    str(value) for value in step.get("skill_point_ids") or []
                ],
                "basis": "validated_step_mapping",
                "reason": "该知识点与技能点由已校验任务步骤显式共同引用。",
            }
            for step in source_steps
        ]

    entry_seed = f"{task_card_id}:{knowledge_id}"
    entry_id = f"ple_{sha256(entry_seed.encode('utf-8')).hexdigest()[:24]}"
    artifacts = bundle.get("artifacts") if isinstance(bundle.get("artifacts"), dict) else {}
    entry_path = (
        "/personalized-learning/tasks/"
        f"{task_card_id}/knowledge/{knowledge_id}"
    )
    handoff_path = (
        "/api/learning-task-conversion/tasks/"
        f"{task_card_id}/knowledge/{knowledge_id}/personalized-learning-entry"
    )

    return {
        "schema_version": "learning-task-knowledge-to-personalized-learning-v1",
        "entry_id": entry_id,
        "status": "ready",
        "source": {
            "source_system": "learning-work-task-conversion",
            "task_card_id": task_card_id,
            "verification_status": str(bundle.get("verification_status") or ""),
            "full_handoff_json_url": str(
                artifacts.get("personalized_learning_json_url") or ""
            ),
        },
        "task_context": {
            "work_task_id": str(work_task.get("work_task_id") or ""),
            "enterprise_task_name": str(
                work_task.get("enterprise_task_name") or ""
            ),
            "enterprise_task_description": str(
                work_task.get("enterprise_task_description") or ""
            ),
            "teaching_task_name": str(work_task.get("teaching_task_name") or ""),
            "teaching_task_description": str(
                work_task.get("teaching_task_description") or ""
            ),
            "work_situation": work_task.get("work_situation"),
        },
        "focus": {
            "knowledge_point": knowledge,
            "source_steps": source_steps,
            "strongly_related_skills": related_skills,
            "relationships": relationships,
        },
        "generation_contract": {
            "purpose": "围绕选中知识点生成个性化学习目标、内容、练习与评价。",
            "immutable_fields": [
                "task_context.work_task_id",
                "task_context.enterprise_task_name",
                "focus.source_steps[].step_id",
                "focus.source_steps[].action",
                "focus.source_steps[].deliverable",
                "focus.source_steps[].check",
                "focus.relationships",
            ],
            "downstream_may_generate": [
                "learning_objectives",
                "learning_content",
                "learning_sequence",
                "practice_activities",
                "assessment_plan",
                "learner_adaptations",
            ],
            "must_preserve_relation_traceability": True,
        },
        "feedback_contract": {
            "schema_version": "personalized-learning-to-task-conversion-feedback-v1",
            "method": "POST",
            "url": "/api/learning-task-conversion/downstream-feedback",
            "supported_issue_targets": [
                "step_id", "knowledge_id", "skill_id", "relation_id",
            ],
        },
        "navigation": {
            "route_key": "personalized_learning.generate_from_knowledge",
            "entry_path": entry_path,
            "handoff_json_path": handoff_path,
            "return_path": f"/wf03/tasks/{task_card_id}",
        },
    }


def _gateway() -> LearningTaskConversionGateway:
    return LearningTaskConversionGateway()


def _xfyun_client() -> XfyunLearningTaskWorkflowClient:
    # This client alone reads backend/.private/learning_task_conversion.xfyun.env.
    # Do not move these credentials into app.core.config or the global .env.
    return XfyunLearningTaskWorkflowClient()


def _personalized_learning_client() -> PersonalizedLearningHandoffClient:
    return PersonalizedLearningHandoffClient()


def _raise_gateway_error(exc: LearningTaskConversionError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


def _raise_xfyun_error(
    exc: XfyunWorkflowError | XfyunWorkflowConfigError,
) -> None:
    status_code = getattr(exc, "status_code", 503)
    raise HTTPException(status_code=status_code, detail=str(exc)) from exc


def _task_card_id_from_content(content: str) -> str:
    patterns = (
        r"/learning-task-conversion/tasks/(ltc_[A-Za-z0-9_-]{1,96})/",
        r"/learning-tasks/(ltc_[A-Za-z0-9_-]{1,96})/",
        r'"task_card_id"\s*:\s*"(ltc_[A-Za-z0-9_-]{1,96})"',
    )
    for pattern in patterns:
        match = re.search(pattern, content)
        if match:
            return match.group(1)
    return ""


def _failure_reason_from_content(content: str) -> str:
    """Extract a short public reason without exposing workflow internals."""

    match = re.search(r'"hard_errors"\s*:\s*\[\s*"([^"]+)"', content)
    if match:
        return match.group(1).strip()
    match = re.search(r'"errors"\s*:\s*\[\s*"([^"]+)"', content)
    if match:
        return match.group(1).strip()
    return "当前候选任务尚未通过内容与证据门禁"


def _query_requires_clarification(user_input: str) -> bool:
    """Only ask the learner when the input truly contains no usable direction."""

    normalized = re.sub(r"[\s，。！？、,.!?]", "", user_input).lower()
    if not normalized:
        return True
    uncertainty_patterns = (
        r"^(我)?(还)?不知道$",
        r"^(我)?(还)?没想好$",
        r"^(我)?(还)?没决定$",
        r"^(随便|都可以|无所谓)$",
    )
    if any(re.fullmatch(pattern, normalized) for pattern in uncertainty_patterns):
        return True
    remainder = re.sub(
        r"^(我)?(想|要|希望)?(学习|学|了解|入门|从事|做|成为|当)",
        "",
        normalized,
    )
    return not remainder


def _is_explicit_work_task(user_input: str) -> bool:
    normalized = re.sub(r"\s+", "", user_input)
    role_markers = (
        "工程师", "技术员", "技师", "操作员", "运维员", "岗位", "职业",
    )
    if any(marker in normalized for marker in role_markers):
        return False
    action_markers = (
        "安装", "拆装", "装配", "检修", "维修", "维护", "调试", "检测",
        "校准", "配置", "部署", "开发", "制作", "加工", "焊接", "更换",
        "诊断", "排查", "修复", "验收", "测试", "巡检", "交付",
    )
    return any(marker in normalized for marker in action_markers)


def _task_object_anchor(user_input: str) -> str:
    """Derive a short object phrase that repair candidates can preserve verbatim."""

    normalized = re.sub(r"[\s，。！？、,.!?]", "", user_input).strip()
    normalized = re.sub(
        r"^(我)?(想|要|希望)?(学习|学|了解|入门|掌握|做)",
        "",
        normalized,
    )
    for marker in (
        "安装", "拆装", "装配", "检修", "维修", "维护", "调试", "检测",
        "校准", "配置", "部署", "开发", "制作", "加工", "焊接", "更换",
        "诊断", "排查", "修复", "验收", "测试", "巡检", "交付",
    ):
        marker_index = normalized.find(marker)
        if marker_index > 0:
            normalized = normalized[:marker_index]
            break
    normalized = normalized.strip("的")
    if "新能源" in normalized and "汽车" in normalized and normalized.endswith("电池"):
        normalized += "包"
    elif normalized.endswith("动力电池"):
        normalized += "包"
    return normalized[:48]


def _auto_revision_prompt(user_input: str, content: str) -> str:
    """Compile a bounded, auditable repair request accepted by Xingchen tools."""

    hints: list[str] = []
    if "ACTION_NOT_SPECIFIC" in content:
        hints.append("动作写明操作对象和实际操作")
    if "CHECK_NOT_VERIFIABLE" in content:
        hints.append("检查点改成可观察、可记录或可测量")
    if "workflow_steps" in content:
        hints.append("重建完整实际作业步骤")
    if "OBJECT_NOT_PRESERVED" in content or "没有保留任务对象" in content:
        hints.append("原样写出对象锚点")
    hint_text = "；".join(hints[:3])
    if _is_explicit_work_task(user_input):
        level_instruction = (
            "这是明确的单个企业任务，不反问、不换题，也不得拆成多个任务。"
        )
    else:
        level_instruction = (
            "这是岗位或职业方向，不反问、不换题；自动选择其中一个可执行的典型企业任务。"
        )
    object_anchor = _task_object_anchor(user_input) if _is_explicit_work_task(user_input) else ""
    anchor_instruction = (
        f"对象锚点为“{object_anchor}”，任务名称、描述和至少一个步骤必须原样写出该对象；"
        "近义词可并列，不能替代对象锚点。"
        if object_anchor
        else ""
    )
    prompt = (
        f"{user_input}\n"
        f"自动修订要求：{level_instruction}重新生成完整候选，步骤数按实际流程确定；"
        f"{anchor_instruction}"
        "每步包含具体动作、可留存产物、可核验检查点及知识点和技能点映射。"
        "除明显跑题、缺少步骤或安全风险外，其余不足标待复核并继续生成。"
        "Plan的repair_budget=1（不得超过2）。"
    )
    if hint_text:
        prompt += f"优先修复：{hint_text}。"
    # AgentRunCreateRequest has a hard 500-character user_query limit.  The
    # public request schema uses the same limit, so this only removes optional
    # repair hints and never truncates the immutable original input.
    if len(prompt) > 500 and hint_text:
        prompt = prompt[: prompt.rfind("优先修复：")]
    return prompt


def _non_success_result(
    workflow_run: dict[str, Any],
    user_input: str,
) -> dict[str, Any]:
    content = str(workflow_run.get("content") or "").strip()
    if _query_requires_clarification(user_input):
        # Workflow output may contain provider-only URLs or empty Markdown
        # links. Clarification is a fixed public response, never a pass-through
        # of orchestration content.
        message = _clarification_result(user_input)["message"]
        status = "needs_clarification"
    else:
        reason = _failure_reason_from_content(content)
        message = (
            f"系统已经锁定“{user_input}”并完成自动修订，但候选仍未通过发布门禁：{reason}。"
            "原任务没有被替换；本次结果已保留为待复核草稿，不要求学习者重复补充同一信息。"
        )
        status = "needs_revision"
    return {
        "schema_version": "learnflow-learning-task-generation-v2",
        "execute_id": workflow_run.get("run_id") or "",
        "status": status,
        "task_card_id": "",
        "message": message,
        "usage": workflow_run.get("usage") or {},
        "bundle": None,
    }


def _fresh_workflow_uid(learner_id: int) -> str:
    """Keep every task-conversion run isolated from Xingchen stage state."""

    return f"lf-{learner_id}-{uuid4().hex[:24]}"


def _is_workflow_stage_conflict(exc: XfyunWorkflowError) -> bool:
    message = str(exc)
    return "21812" in message or "当前阶段" in message or "INTAKE" in message


def _clarification_result(user_input: str) -> dict[str, Any]:
    """Translate Xingchen's INTAKE state into a user-facing follow-up turn."""

    return {
        "schema_version": "learnflow-learning-task-generation-v2",
        "execute_id": "",
        "status": "needs_clarification",
        "task_card_id": "",
        "message": (
            f"我已识别到你想围绕“{user_input}”生成学习型工作任务，但目前还不能唯一确定"
            "要转换的企业真实工作任务。请再补充一个可执行对象或结果，例如："
            "“Linux系统安装与基础配置”“风力发电机组日常巡检”或"
            "“新能源汽车电池包安装”。补充后我会沿用本次功能继续生成。"
        ),
        "usage": {},
        "bundle": None,
    }


async def _owned_generation_session(
    db: AsyncSession,
    learner_id: int,
    session_id: int | None,
) -> AgentSession | None:
    if session_id is None:
        return None
    session = (await db.execute(select(AgentSession).where(
        AgentSession.id == session_id,
        AgentSession.learner_id == learner_id,
        AgentSession.status == "active",
    ))).scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail="当前任务生成会话不存在或已结束")
    return session


async def _replay_generation_result(
    db: AsyncSession,
    session: AgentSession | None,
    client_turn_id: str,
) -> dict[str, Any] | None:
    if session is None:
        return None
    idempotency_key = f"learning-task-result:{session.learner_id}:{client_turn_id}"
    message = (await db.execute(select(AgentMessage).where(
        AgentMessage.session_id == session.id,
        AgentMessage.idempotency_key == idempotency_key,
    ))).scalar_one_or_none()
    if message is None:
        return None
    stored = dict((message.meta_data or {}).get("generation_result") or {})
    task_card_id = str(stored.get("task_card_id") or "")
    bundle = await _gateway().task_bundle(task_card_id) if task_card_id else None
    return {
        "schema_version": "learnflow-learning-task-generation-v2",
        "execute_id": str(stored.get("execute_id") or ""),
        "status": str(stored.get("status") or "needs_revision"),
        "task_card_id": task_card_id,
        "message": message.content,
        "usage": {},
        "bundle": bundle,
        "replayed": True,
    }


async def _persist_generation_exchange(
    db: AsyncSession,
    session: AgentSession | None,
    *,
    client_turn_id: str,
    user_input: str,
    result: dict[str, Any],
) -> None:
    if session is None:
        return
    learner_id = session.learner_id
    request_key = f"learning-task-request:{learner_id}:{client_turn_id}"
    result_key = f"learning-task-result:{learner_id}:{client_turn_id}"
    request_statement = sqlite_insert(AgentMessage).values(
        session_id=session.id,
        role="user",
        content=user_input,
        meta_data={
            "message_kind": "learning_task_request",
            "client_turn_id": client_turn_id,
        },
        idempotency_key=request_key,
    ).on_conflict_do_nothing(index_elements=["idempotency_key"])
    await db.execute(request_statement)
    public_result = {
        "status": result["status"],
        "task_card_id": result.get("task_card_id") or "",
        "execute_id": result.get("execute_id") or "",
    }
    result_statement = sqlite_insert(AgentMessage).values(
        session_id=session.id,
        role="assistant",
        content=str(result.get("message") or ""),
        meta_data={
            "message_kind": (
                "learning_task_generated"
                if result["status"] == "success"
                else "learning_task_follow_up"
            ),
            "generation_result": public_result,
            "client_turn_id": client_turn_id,
        },
        idempotency_key=result_key,
    ).on_conflict_do_nothing(index_elements=["idempotency_key"])
    inserted_result = await db.execute(result_statement)
    if inserted_result.rowcount:
        await record_event(
            db,
            learner_id=learner_id,
            event_type=(
                "learning_work_task_generated"
                if result["status"] == "success"
                else "learning_work_task_generation_follow_up"
            ),
            source="learning_task_conversion",
            session_id=session.id,
            payload={
                "query": user_input,
                **public_result,
            },
            artifact_refs=(
                [f"learning-task:{result['task_card_id']}"]
                if result.get("task_card_id") else []
            ),
            client_event_id=f"learning-task:{client_turn_id}",
        )
    await db.commit()


async def _run_isolated_workflow(
    client: XfyunLearningTaskWorkflowClient,
    user_input: str,
    *,
    learner_id: int,
) -> dict[str, Any]:
    """Run in a fresh provider session and self-heal one stale-stage failure."""

    try:
        return await client.run(
            user_input,
            uid=_fresh_workflow_uid(learner_id),
        )
    except XfyunWorkflowError as exc:
        if not _is_workflow_stage_conflict(exc):
            raise
        return await client.run(
            user_input,
            uid=_fresh_workflow_uid(learner_id),
        )


def _merge_workflow_usage(*runs: dict[str, Any]) -> dict[str, int]:
    merged: dict[str, int] = {}
    for run in runs:
        usage = run.get("usage") if isinstance(run, dict) else None
        if not isinstance(usage, dict):
            continue
        for key, value in usage.items():
            if isinstance(value, int) and not isinstance(value, bool):
                merged[key] = merged.get(key, 0) + value
    return merged


async def _run_generation_workflow(
    client: XfyunLearningTaskWorkflowClient,
    user_input: str,
    *,
    learner_id: int,
) -> dict[str, Any]:
    """Run Plan once, then repair one clear-but-rejected task automatically."""

    if _query_requires_clarification(user_input):
        return await _run_isolated_workflow(
            client,
            user_input,
            learner_id=learner_id,
        )

    # WF03 is database-first: reviewed enterprise tasks already have complete
    # workflow_steps and must not be degraded by a fresh model repair turn.
    # Only an unseen task continues to the Xingchen Plan workflow below.
    catalog_task_card_id: str | None = None
    if _is_explicit_work_task(user_input):
        try:
            catalog_task_card_id = await _gateway().generate_catalog_match(
                user_input
            )
        except LearningTaskConversionError:
            # Catalogue lookup is an optimization, not a new single point of
            # failure.  Unavailable or unmatched data continues to the model
            # Plan path, which is the required standalone operating mode.
            catalog_task_card_id = None
    if catalog_task_card_id:
        return {
            "schema_version": "learning-task-conversion-catalog-run-v1",
            "provider": "wf03-reviewed-task-catalog",
            "run_id": f"catalog:{catalog_task_card_id}",
            "content": (
                "/api/v1/learning-task-conversion/tasks/"
                f"{catalog_task_card_id}/interactive.html"
            ),
            "usage": {},
            "catalog_reuse": True,
        }

    # Clear tasks receive the proven Plan constraints on the first run.  A
    # repair branch starts after a short head start, rather than waiting several
    # minutes for a rejected draft and then paying the same latency again.
    primary = asyncio.create_task(_run_isolated_workflow(
        client,
        _auto_revision_prompt(user_input, ""),
        learner_id=learner_id,
    ))
    done, _ = await asyncio.wait(
        {primary},
        timeout=_SPECULATIVE_REPAIR_HEAD_START_SECONDS,
    )
    if done:
        initial = await primary
        if _task_card_id_from_content(str(initial.get("content") or "")):
            return initial
        repaired = await _run_isolated_workflow(
            client,
            _auto_revision_prompt(user_input, str(initial.get("content") or "")),
            learner_id=learner_id,
        )
        result = dict(repaired)
        result["usage"] = _merge_workflow_usage(initial, repaired)
        result["auto_revision"] = {
            "attempted": True,
            "mode": "sequential_fast_failure",
            "attempts": 1,
            "initial_run_id": str(initial.get("run_id") or ""),
            "final_run_id": str(repaired.get("run_id") or ""),
        }
        return result

    repair = asyncio.create_task(_run_isolated_workflow(
        client,
        _auto_revision_prompt(
            user_input,
            "ACTION_NOT_SPECIFIC CHECK_NOT_VERIFIABLE workflow_steps",
        ),
        learner_id=learner_id,
    ))
    tasks = (primary, repair)
    completed_runs: list[dict[str, Any]] = []
    errors: list[Exception] = []
    try:
        for finished in asyncio.as_completed(tasks):
            try:
                run = await finished
            except Exception as exc:
                errors.append(exc)
                continue
            completed_runs.append(run)
            if _task_card_id_from_content(str(run.get("content") or "")):
                result = dict(run)
                result["usage"] = _merge_workflow_usage(*completed_runs)
                result["auto_revision"] = {
                    "attempted": True,
                    "mode": "speculative_parallel",
                    "attempts": 1,
                    "winner_run_id": str(run.get("run_id") or ""),
                }
                return result
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    if completed_runs:
        result = dict(completed_runs[-1])
        result["usage"] = _merge_workflow_usage(*completed_runs)
        result["auto_revision"] = {
            "attempted": True,
            "mode": "speculative_parallel",
            "attempts": 1,
            "winner_run_id": "",
        }
        return result
    if errors:
        raise errors[0]
    raise XfyunWorkflowError("自动修订未返回工作流结果")


@router.post("/workflow-runs")
async def run_learning_task_conversion_workflow(
    payload: dict[str, Any] = Body(...),
    current: CurrentLearner = Depends(get_current_learner),
) -> dict[str, Any]:
    """Run only the bound Plan workflow for this feature.

    Callers cannot provide a host, API key, secret, or flow ID.  Those values
    stay in the ignored feature-private file, preventing this endpoint from
    becoming a generic Xingchen proxy.
    """

    user_input = str(payload.get("user_input") or "").strip()
    if not user_input:
        raise HTTPException(status_code=422, detail="请提供明确的岗位典型工作任务")
    if len(user_input) > 500:
        raise HTTPException(status_code=422, detail="岗位典型工作任务描述不能超过500字")

    try:
        return await _run_isolated_workflow(
            _xfyun_client(),
            user_input,
            learner_id=current.learner.id,
        )
    except (XfyunWorkflowError, XfyunWorkflowConfigError) as exc:
        _raise_xfyun_error(exc)


@router.post("/generate")
async def generate_learning_task_from_conversation(
    request: LearningTaskGenerationRequest,
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Generate and resolve one task into the LearnFlow review workspace.

    The endpoint composes the feature-private Xingchen workflow with the fixed
    artifact gateway.  It never accepts credentials, hosts, or flow IDs from
    the browser.
    """

    user_input = request.query.strip()
    client_turn_id = request.client_turn_id or f"learning-task-{uuid4().hex}"
    session = await _owned_generation_session(
        db, current.learner.id, request.session_id,
    )
    replayed = await _replay_generation_result(db, session, client_turn_id)
    if replayed is not None:
        return replayed

    try:
        workflow_run = await _run_generation_workflow(
            _xfyun_client(),
            user_input,
            learner_id=current.learner.id,
        )
        task_card_id = _task_card_id_from_content(workflow_run["content"])
        if not task_card_id:
            result = _non_success_result(workflow_run, user_input)
            await _persist_generation_exchange(
                db, session, client_turn_id=client_turn_id,
                user_input=user_input, result=result,
            )
            return result
        bundle = await _gateway().task_bundle(task_card_id)
        local_url = f"/wf03/tasks/{task_card_id}"
        result = {
            "schema_version": "learnflow-learning-task-generation-v2",
            "execute_id": workflow_run.get("run_id") or "",
            "status": "success",
            "task_card_id": task_card_id,
            "message": (
                "学习型任务已经生成并在中间工作区打开。"
                "你可以按步骤查看产物与验收点，点击知识点直接进入个性化学习。\n\n"
                f"[查看学习型任务]({local_url})"
            ),
            "usage": workflow_run.get("usage") or {},
            "bundle": bundle,
        }
        await _persist_generation_exchange(
            db, session, client_turn_id=client_turn_id,
            user_input=user_input, result=result,
        )
        return result
    except (XfyunWorkflowError, XfyunWorkflowConfigError) as exc:
        if isinstance(exc, XfyunWorkflowError) and _is_workflow_stage_conflict(exc):
            result = _clarification_result(user_input)
            await _persist_generation_exchange(
                db, session, client_turn_id=client_turn_id,
                user_input=user_input, result=result,
            )
            return result
        _raise_xfyun_error(exc)
    except LearningTaskConversionError as exc:
        _raise_gateway_error(exc)


@router.post("/integration-generate")
async def generate_learning_task_for_integration(
    payload: LearningTaskIntegrationRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Generate a WF03 task for an approved external learning shell.

    The caller never supplies provider credentials or a workflow id.  In
    development this endpoint is loopback-only; deployments must configure a
    shared integration token.  The response contains the validated bundle and
    the task artifact URL so the caller can render it in its own workbench.
    """

    _require_learning_task_integration(request)
    learner_id = (await db.execute(
        select(Learner.id)
        .join(UserAccount, UserAccount.id == Learner.user_id)
        .where(UserAccount.status == "active")
        .order_by(Learner.id.asc())
        .limit(1)
    )).scalar_one_or_none()
    if learner_id is None:
        raise HTTPException(status_code=503, detail="学习型任务转化服务尚无可用运行身份")

    user_input = payload.query.strip()
    try:
        workflow_run = await _run_generation_workflow(
            _xfyun_client(), user_input, learner_id=learner_id,
        )
        task_card_id = _task_card_id_from_content(workflow_run["content"])
        if not task_card_id:
            return _non_success_result(workflow_run, user_input)
        bundle = await _gateway().task_bundle(task_card_id)
        artifacts = bundle.get("artifacts") if isinstance(bundle, dict) else None
        artifact_url = (
            str(artifacts.get("interactive_html_url") or "").strip()
            if isinstance(artifacts, dict)
            else ""
        )
        return {
            "schema_version": "learnflow-learning-task-generation-v2",
            "execute_id": workflow_run.get("run_id") or "",
            "status": "success",
            "task_card_id": task_card_id,
            "message": "学习型任务已经生成，可在当前工作台查看并选择知识点进入个性化学习。",
            "usage": workflow_run.get("usage") or {},
            "artifact_url": artifact_url,
            "bundle": bundle,
        }
    except (XfyunWorkflowError, XfyunWorkflowConfigError) as exc:
        if isinstance(exc, XfyunWorkflowError) and _is_workflow_stage_conflict(exc):
            return _clarification_result(user_input)
        _raise_xfyun_error(exc)
    except LearningTaskConversionError as exc:
        _raise_gateway_error(exc)


@router.get("/capabilities")
async def get_learning_task_conversion_capabilities(
    _current: CurrentLearner = Depends(get_current_learner),
) -> dict[str, Any]:
    try:
        return await _gateway().capabilities()
    except LearningTaskConversionError as exc:
        _raise_gateway_error(exc)


@router.post("/upstream-handoffs")
async def submit_competency_graph_handoff(
    payload: dict[str, Any] = Body(...),
    _current: CurrentLearner = Depends(get_current_learner),
) -> dict[str, Any]:
    try:
        return await _gateway().submit_upstream_handoff(payload)
    except LearningTaskConversionError as exc:
        _raise_gateway_error(exc)


@router.get("/tasks/{task_card_id}/bundle")
async def get_learning_task_conversion_bundle(
    task_card_id: str = Path(pattern=r"^[A-Za-z0-9_-]{1,100}$"),
    _current: CurrentLearner = Depends(get_current_learner),
) -> dict[str, Any]:
    try:
        return await _gateway().task_bundle(task_card_id)
    except LearningTaskConversionError as exc:
        _raise_gateway_error(exc)


@router.get("/tasks/{task_card_id}/personalized-learning")
async def get_personalized_learning_handoff(
    task_card_id: str = Path(pattern=r"^[A-Za-z0-9_-]{1,100}$"),
    _current: CurrentLearner = Depends(get_current_learner),
) -> dict[str, Any]:
    try:
        return await _gateway().personalized_learning_handoff(task_card_id)
    except LearningTaskConversionError as exc:
        _raise_gateway_error(exc)


@router.get(
    "/tasks/{task_card_id}/knowledge/{knowledge_id}/personalized-learning-entry"
)
async def get_knowledge_personalized_learning_entry(
    task_card_id: str = Path(pattern=r"^[A-Za-z0-9_-]{1,100}$"),
    knowledge_id: str = Path(pattern=r"^[A-Za-z0-9_-]{1,100}$"),
    _current: CurrentLearner = Depends(get_current_learner),
) -> dict[str, Any]:
    """Return a knowledge-scoped, versioned JSON handoff for downstream use."""

    try:
        bundle = await _gateway().task_bundle(task_card_id)
        return _knowledge_handoff_entry(bundle, task_card_id, knowledge_id)
    except LearningTaskConversionError as exc:
        _raise_gateway_error(exc)


@router.post(
    "/tasks/{task_card_id}/knowledge/{knowledge_id}/personalized-learning-entry"
)
async def open_knowledge_personalized_learning_entry(
    task_card_id: str = Path(pattern=r"^[A-Za-z0-9_-]{1,100}$"),
    knowledge_id: str = Path(pattern=r"^[A-Za-z0-9_-]{1,100}$"),
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Prepare the handoff and record the explicit cross-function navigation."""

    try:
        bundle = await _gateway().task_bundle(task_card_id)
        entry = _knowledge_handoff_entry(bundle, task_card_id, knowledge_id)
        await record_event(
            db,
            learner_id=current.learner.id,
            event_type="personalized_learning_handoff_opened",
            source="learning_task_conversion",
            payload={
                "entry_id": entry["entry_id"],
                "task_card_id": task_card_id,
                "knowledge_id": knowledge_id,
                "schema_version": entry["schema_version"],
            },
            artifact_refs=[
                f"learning-task:{task_card_id}",
                f"knowledge:{knowledge_id}",
            ],
            client_event_id=f"personalized-entry:{current.learner.id}:{entry['entry_id']}",
        )
        await db.commit()
        return entry
    except LearningTaskConversionError as exc:
        _raise_gateway_error(exc)


@router.post(
    "/tasks/{task_card_id}/knowledge/{knowledge_id}/personalized-learning-launch"
)
async def launch_knowledge_personalized_learning(
    task_card_id: str = Path(pattern=r"^[A-Za-z0-9_-]{1,100}$"),
    knowledge_id: str = Path(pattern=r"^[A-Za-z0-9_-]{1,100}$"),
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Import the verified handoff with server-owned identity and return a URL."""

    try:
        bundle = await _gateway().task_bundle(task_card_id)
        entry = _knowledge_handoff_entry(bundle, task_card_id, knowledge_id)
        result = await _personalized_learning_client().import_entry(
            learner_id=current.learner.id,
            handoff=entry,
        )
        await record_event(
            db,
            learner_id=current.learner.id,
            event_type="personalized_learning_handoff_opened",
            source="learning_task_conversion",
            payload={
                "entry_id": entry["entry_id"],
                "task_card_id": task_card_id,
                "knowledge_id": knowledge_id,
                "schema_version": entry["schema_version"],
                "downstream_project_id": result["project_id"],
                "downstream_created": result["created"],
            },
            artifact_refs=[
                f"learning-task:{task_card_id}",
                f"knowledge:{knowledge_id}",
            ],
            client_event_id=(
                f"personalized-launch:{current.learner.id}:{entry['entry_id']}"
            ),
        )
        await db.commit()
        return result
    except LearningTaskConversionError as exc:
        _raise_gateway_error(exc)
    except PersonalizedLearningHandoffConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except PersonalizedLearningHandoffError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.post(
    "/tasks/{task_card_id}/knowledge/{knowledge_id}/personalized-learning-results"
)
async def receive_personalized_learning_result(
    payload: PersonalizedLearningResultRequest,
    task_card_id: str = Path(pattern=r"^[A-Za-z0-9_-]{1,100}$"),
    knowledge_id: str = Path(pattern=r"^[A-Za-z0-9_-]{1,100}$"),
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Persist a verified downstream result as a zero-kernel audit artifact.

    The imported direction only supports provisional self-checks.  The result
    is useful for continuity and review, but cannot become mastery evidence
    until LearnFlow owns a formal assessment specification and attempt.
    """

    try:
        bundle = await _gateway().task_bundle(task_card_id)
        entry = _knowledge_handoff_entry(bundle, task_card_id, knowledge_id)
    except LearningTaskConversionError as exc:
        _raise_gateway_error(exc)

    expected_entry_id = scoped_personalized_learning_entry_id(
        str(entry["entry_id"]),
        current.learner.id,
    )
    if payload.entry_id != expected_entry_id or payload.knowledge_point_id != knowledge_id:
        raise HTTPException(status_code=409, detail="个性化学习结果身份与当前交接不一致")
    if payload.formal_evidence:
        raise HTTPException(
            status_code=422,
            detail="当前交接仅允许回传临时自测结果，不能声明正式掌握证据",
        )

    summary = payload.summary
    assessment_type = str(summary.get("assessment_type") or "").strip()
    if assessment_type != "provisional_self_check":
        raise HTTPException(status_code=422, detail="当前仅接受练习型初测结果")

    def bounded_count(name: str, *, minimum: int, maximum: int) -> int:
        value = summary.get(name)
        if isinstance(value, bool) or not isinstance(value, int):
            raise HTTPException(status_code=422, detail=f"{name} 必须是整数")
        if value < minimum or value > maximum:
            raise HTTPException(status_code=422, detail=f"{name} 超出允许范围")
        return value

    total = bounded_count("total", minimum=1, maximum=100)
    score = bounded_count("score", minimum=0, maximum=total)
    weak_point_count = bounded_count(
        "weak_point_count", minimum=0, maximum=total,
    )

    launch_events = (await db.execute(
        select(EvidenceEvent)
        .where(
            EvidenceEvent.learner_id == current.learner.id,
            EvidenceEvent.event_type == "personalized_learning_handoff_opened",
        )
        .order_by(EvidenceEvent.id.desc())
        .limit(100)
    )).scalars().all()
    launch_found = any(
        str((event.payload or {}).get("task_card_id") or "") == task_card_id
        and str((event.payload or {}).get("knowledge_id") or "") == knowledge_id
        and str((event.payload or {}).get("downstream_project_id") or "")
        == payload.project_id
        for event in launch_events
    )
    if not launch_found:
        raise HTTPException(status_code=409, detail="没有找到与该结果匹配的个性化学习启动记录")

    event = await record_event(
        db,
        learner_id=current.learner.id,
        event_type="personalized_learning_result_received",
        source="personalized_learning",
        payload={
            "task_card_id": task_card_id,
            "knowledge_id": knowledge_id,
            "entry_id": expected_entry_id,
            "downstream_project_id": payload.project_id,
            "result_type": payload.result_type,
            "result_id": payload.result_id,
            "assessment_type": assessment_type,
            "score": score,
            "total": total,
            "weak_point_count": weak_point_count,
            "formal_evidence": False,
            "feedback": str(summary.get("feedback") or "").strip()[:500],
        },
        artifact_refs=[
            f"learning-task:{task_card_id}",
            f"knowledge:{knowledge_id}",
            f"personalized-project:{payload.project_id}",
            f"assessment:{payload.result_id}",
        ],
        client_event_id=(
            f"personalized-result:{expected_entry_id}:{payload.result_id}"
        ),
    )
    await db.commit()
    return {
        "status": "accepted",
        "event_id": event.id,
        "result_id": payload.result_id,
        "formal_evidence": False,
    }


@router.post("/downstream-feedback")
async def submit_personalized_learning_feedback(
    payload: dict[str, Any] = Body(...),
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    issues = payload.get("issues")
    if issues is None:
        issues = []
    elif not isinstance(issues, list):
        raise HTTPException(status_code=422, detail="issues 必须是数组")
    try:
        result = await _gateway().submit_downstream_feedback(payload)
        task_card_id = str(payload.get("task_card_id") or "")
        await record_event(
            db,
            learner_id=current.learner.id,
            event_type="learning_work_task_review_submitted",
            source="learning_task_conversion",
            payload={
                "task_card_id": task_card_id,
                "issue_count": len(issues),
                "status": str(payload.get("status") or ""),
            },
            artifact_refs=([f"learning-task:{task_card_id}"] if task_card_id else []),
            client_event_id=str(payload.get("correlation_id") or uuid4()),
        )
        await db.commit()
        return result
    except LearningTaskConversionError as exc:
        _raise_gateway_error(exc)
