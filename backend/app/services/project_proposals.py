"""Persistent, evidence-linked learning project proposals."""
from __future__ import annotations

import asyncio
from datetime import datetime
import hashlib
import json
import math
import re
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.database import async_session
from app.models.learning import (
    AgentSession, EvidenceEvent, LearnerProfile, LearningProjectProposal,
    ProjectProposalRevision,
)
from app.models.project import Project, Task
from app.services.learning_runtime import record_event


ACTIVE_PROPOSAL_STATUSES = ("draft", "ready")
PROPOSAL_TYPES = {"build", "mastery", "exam", "research"}
EDITABLE_FIELDS = {
    "title", "learning_goal", "practice_goal", "learner_start",
    "estimated_effort", "milestones", "acceptance_criteria", "risks",
    "assumptions", "details",
}
PROFILE_HINTS = (
    "学过", "没学过", "没用过", "不会", "熟悉", "基础", "每天", "每周",
    "小时", "分钟", "pytorch", "numpy", "python", "cs61a", "从零",
)
LONG_GOAL_HINTS = (
    "系统学习", "学习计划", "学习路线", "长期", "从零开始", "掌握",
    "做一个", "实现一个", "实现", "构建", "开发", "写一个", "完成一个",
    "备考", "研究", "复现", "项目",
)
SEARCH_STOPWORDS = {
    "a", "an", "and", "build", "complete", "for", "from", "in", "learn",
    "learning", "model", "of", "project", "repository", "the", "to", "using",
    "language", "stars", "fork", "archived", "name", "description", "readme",
    "with", "实现", "一个", "完成", "学习", "项目", "构建", "理解", "掌握",
}
LEARNING_FIT_TERMS = (
    "from scratch", "step by step", "tutorial", "educational", "course", "workshop",
    "minimal", "mini", "tiny", "beginner", "notebook", "hands-on", "hands on",
)
PRACTICE_TERMS = (
    "implementation", "implement", "training", "train", "test", "exercise",
    "pytorch", "python", "code", "decoder", "transformer",
)
OFF_TOPIC_TERMS = (
    "awesome list", "prompt collection", "rag", "serving engine", "api wrapper",
    "powerpoint", "slide generator", "chatbot ui", "inference only",
    "coding agent", "agent framework",
)


def proposal_view(proposal: LearningProjectProposal) -> dict:
    return {
        "id": proposal.id,
        "proposal_key": proposal.proposal_key,
        "proposal_type": proposal.proposal_type,
        "status": proposal.status,
        "action_type": proposal.action_type,
        "target_project_id": proposal.target_project_id,
        "accepted_project_id": proposal.accepted_project_id,
        "artifact": dict(proposal.artifact or {}),
        "revision": proposal.revision or 1,
        "locked_fields": list(proposal.locked_fields or []),
        "last_change_summary": proposal.last_change_summary or "",
        "source_status": proposal.source_status or "idle",
        "source_task_id": proposal.source_task_id,
        "updated_at": proposal.updated_at.isoformat() if proposal.updated_at else None,
    }


async def list_session_proposals(
    db: AsyncSession,
    session_id: int,
    *,
    include_archived: bool = False,
) -> list[LearningProjectProposal]:
    query = select(LearningProjectProposal).where(
        LearningProjectProposal.session_id == session_id,
    )
    if not include_archived:
        query = query.where(LearningProjectProposal.status.in_(ACTIVE_PROPOSAL_STATUSES))
    return list((await db.execute(
        query.order_by(LearningProjectProposal.updated_at.desc(), LearningProjectProposal.id.desc())
    )).scalars().all())


async def get_latest_active_proposal(
    db: AsyncSession,
    session_id: int,
) -> LearningProjectProposal | None:
    return (await db.execute(
        select(LearningProjectProposal)
        .where(
            LearningProjectProposal.session_id == session_id,
            LearningProjectProposal.status.in_(ACTIVE_PROPOSAL_STATUSES),
        )
        .order_by(LearningProjectProposal.updated_at.desc(), LearningProjectProposal.id.desc())
        .limit(1)
    )).scalar_one_or_none()


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", value or "").lower()


def _clean_topic(value: str) -> str:
    text = re.sub(r"\s+", "", value or "")
    text = re.sub(r"^(我想|我要|希望|自己|动手|从零|系统地?)+", "", text)
    text = re.sub(r"^(学习|实现|构建|开发|完成|写|做|掌握|研究|复现)(一个|个)?", "", text)
    text = re.sub(r"(的)?(学习)?(项目|计划|路线)$", "", text)
    return text.strip("，。！？,.!?：:")[:60]


def _topic_from_message(message: str, opportunity: dict | None, intent: dict | None) -> str:
    intent_goal = str((intent or {}).get("long_term_goal") or "").strip()
    opportunity_title = str((opportunity or {}).get("title") or "").strip()
    if intent_goal:
        return _clean_topic(intent_goal)
    if opportunity_title:
        return _clean_topic(opportunity_title)
    compact = _compact(message)
    aliases = (
        ("gpt", "GPT"), ("transformer", "Transformer"), ("pytorch", "PyTorch"),
        ("概率论", "概率论"), ("统计学", "统计学"), ("线性代数", "线性代数"),
        ("强化学习", "强化学习"), ("机器学习", "机器学习"),
    )
    for token, title in aliases:
        if token in compact:
            return title
    match = re.search(
        r"(?:系统学习|学习|实现|构建|开发|完成|写|做|掌握|研究|复现)(?:一个|个)?([^，。！？,.!?]{2,48})",
        re.sub(r"\s+", "", message),
    )
    return _clean_topic(match.group(1)) if match else ""


def _proposal_key(topic: str, proposal_type: str) -> str:
    digest = hashlib.sha1(_compact(topic).encode("utf-8")).hexdigest()[:12]
    return f"{proposal_type}-{digest}"


def _looks_like_long_goal(message: str, opportunity: dict | None, intent: dict | None) -> bool:
    compact = _compact(message)
    if (opportunity or {}).get("should_propose"):
        return True
    if (intent or {}).get("horizon") == "long" and (intent or {}).get("long_term_goal"):
        return True
    has_goal = any(_compact(hint) in compact for hint in LONG_GOAL_HINTS)
    has_first_person = any(word in compact for word in ("我想", "我要", "希望", "打算", "准备"))
    has_artifact = any(word in compact for word in ("实现", "构建", "开发", "完成", "写一个", "做一个", "复现"))
    return has_goal and (has_first_person or has_artifact or "系统学习" in compact)


def _proposal_type(message: str, opportunity: dict | None) -> str:
    candidate = str((opportunity or {}).get("proposal_type") or "")
    if candidate in PROPOSAL_TYPES:
        return candidate
    compact = _compact(message)
    if any(word in compact for word in ("备考", "考试", "考研", "证书")):
        return "exam"
    if any(word in compact for word in ("研究", "论文", "复现")):
        return "research"
    if any(word in compact for word in ("实现", "构建", "开发", "写一个", "做一个")):
        return "build"
    return "mastery"


def _milestone(mid: str, title: str, purpose: str, effort: str = "") -> dict:
    return {
        "id": mid,
        "title": title,
        "purpose": purpose,
        "estimated_effort": effort,
    }


def _base_artifact(
    message: str,
    topic: str,
    proposal_type: str,
    opportunity: dict | None,
) -> dict:
    data = opportunity or {}
    compact_topic = _compact(topic)
    if "gpt" in compact_topic or "transformer" in compact_topic:
        artifact = {
            "title": str(data.get("title") or "从 Python 到手写 MiniGPT"),
            "learning_goal": str(data.get("learning_goal") or "理解并亲手实现 GPT 的完整训练与生成链路"),
            "practice_goal": str(data.get("practice_goal") or data.get("practice_artifact") or "完成一个能在小型文本上训练并生成文本的 MiniGPT 仓库"),
            "learner_start": list(data.get("learner_start") or ["具备 Python 基础，深度学习框架经验待确认"]),
            "estimated_effort": str(data.get("estimated_effort") or "约 6-10 周，可根据每周投入调整"),
            "milestones": list(data.get("milestones") or [
                _milestone("training-loop", "跑通最小训练循环", "建立数据、模型、损失和优化器的共同骨架", "2-3 次练习"),
                _milestone("text-data", "字符级文本数据管线", "完成编码、批次采样与下一词目标", "1-2 次练习"),
                _milestone("attention", "实现因果自注意力", "理解并验证掩码、多头注意力和张量形状", "3-4 次练习"),
                _milestone("mini-gpt", "组装并训练 MiniGPT", "组合 Transformer Block、训练并保存模型", "1-2 周"),
                _milestone("generation", "生成、测试与复盘", "实现 temperature/top-k，并用测试验证关键部件", "2-3 次练习"),
            ]),
            "acceptance_criteria": list(data.get("acceptance_criteria") or [
                "训练损失稳定下降", "能够从提示词继续生成文本", "关键张量形状和因果掩码有自动测试",
            ]),
            "risks": list(data.get("risks") or ["PyTorch 训练循环可能是首要前置缺口", "首次实现需要严格控制模型和数据规模"]),
            "assumptions": ["默认先做字符级小模型，不追求复现商用 GPT 规模"],
            "details": {"stack": ["Python", "技术框架待确认"], "proposal_kind": "runnable_model"},
            "candidate_sources": [],
            "source_search_query": str(data.get("source_search_query") or "gpt from scratch language:Python"),
        }
        return artifact

    title = str(data.get("title") or f"{topic}学习项目")
    practice_goal = str(
        data.get("practice_goal") or data.get("practice_artifact")
        or ("完成一个可运行、可检查的项目产物" if proposal_type == "build" else "完成一项可验证的迁移任务")
    )
    return {
        "title": title,
        "learning_goal": str(data.get("learning_goal") or data.get("description") or message[:500]),
        "practice_goal": practice_goal,
        "learner_start": list(data.get("learner_start") or ["当前基础待在后续对话中确认"]),
        "estimated_effort": str(data.get("estimated_effort") or "根据后续时间约束调整"),
        "milestones": list(data.get("milestones") or [
            _milestone("foundation", "确认基础与前置", "定位现有能力和关键缺口"),
            _milestone("core", f"建立{topic}核心理解", "用小例子和练习形成可检验理解"),
            _milestone("artifact", "完成实践产物", practice_goal),
            _milestone("transfer", "独立验证与迁移", "在新情境中独立完成一次任务"),
        ]),
        "acceptance_criteria": list(data.get("acceptance_criteria") or ["完成约定实践产物", "通过独立验证任务"]),
        "risks": list(data.get("risks") or ["基础和时间投入尚待确认"]),
        "assumptions": [],
        "details": {"proposal_kind": proposal_type},
        "candidate_sources": [],
        "source_search_query": str(data.get("source_search_query") or ""),
    }


def _revision_patch(message: str, proposal: LearningProjectProposal, opportunity: dict | None) -> tuple[dict, str]:
    compact = _compact(message)
    current = dict(proposal.artifact or {})
    patch: dict[str, Any] = {}
    changes: list[str] = []

    data = opportunity or {}
    for field in (
        "learning_goal", "practice_goal", "learner_start", "estimated_effort",
        "milestones", "acceptance_criteria", "risks", "source_search_query",
    ):
        if data.get(field):
            patch[field] = data[field]

    if "pytorch" in compact:
        details = dict(current.get("details") or {})
        details["stack"] = ["Python", "PyTorch"]
        patch["details"] = details
        patch["source_search_query"] = "gpt pytorch language:Python"
        changes.append("将实现路线确定为 PyTorch")

    if ("没用过" in compact or "不会" in compact) and "pytorch" in compact:
        start = ["学过 Python（CS61A）" if "cs61a" in compact else "具备 Python 基础", "尚未使用过 PyTorch"]
        patch["learner_start"] = start
        existing = list(current.get("milestones") or [])
        prep = [
            _milestone("torch-tensors", "PyTorch 张量与自动求导", "掌握 tensor、梯度和参数更新", "1-2 次练习"),
            _milestone("pytorch-loop", "手写最小 PyTorch 训练循环", "跑通 Dataset → Model → Loss → Optimizer", "1-2 次练习"),
        ]
        existing_ids = {str(item.get("id")) for item in existing if isinstance(item, dict)}
        patch["milestones"] = [*prep, *[item for item in existing if str(item.get("id")) not in {"torch-tensors", "pytorch-loop"}]]
        changes.append("根据当前基础补充 PyTorch 张量、自动求导和训练循环前置阶段")
    elif "cs61a" in compact:
        patch["learner_start"] = ["学过 Python（CS61A）", "深度学习框架经验待建立"]
        changes.append("记录 CS61A Python 基础")

    time_match = re.search(r"(?:每天|每周).{0,12}(?:分钟|小时|天)", message)
    if time_match:
        patch["estimated_effort"] = time_match.group(0)
        changes.append("按新的时间投入约束调整节奏")

    return patch, "；".join(dict.fromkeys(changes)) or "根据最新对话细化项目提案"


def _merge_tutor_patch(proposal: LearningProjectProposal, patch: dict) -> dict:
    artifact = dict(proposal.artifact or {})
    locked = set(proposal.locked_fields or [])
    for field, value in patch.items():
        if field not in EDITABLE_FIELDS and field != "source_search_query":
            continue
        if field in locked:
            continue
        if field == "milestones" and "milestone_order" in locked:
            old = [item for item in artifact.get("milestones", []) if isinstance(item, dict)]
            new = [item for item in value if isinstance(item, dict)]
            new_by_id = {str(item.get("id")): item for item in new}
            merged = [{**item, **new_by_id.get(str(item.get("id")), {})} for item in old]
            old_ids = {str(item.get("id")) for item in old}
            merged.extend(item for item in new if str(item.get("id")) not in old_ids)
            artifact[field] = merged
        else:
            artifact[field] = value
    return artifact


async def _append_revision(
    db: AsyncSession,
    proposal: LearningProjectProposal,
    *,
    source: str,
    patch: dict,
    summary: str,
    message_id: int | None = None,
    evidence_id: int | None = None,
):
    db.add(ProjectProposalRevision(
        proposal_id=proposal.id,
        revision=proposal.revision,
        source=source,
        patch=patch,
        snapshot=dict(proposal.artifact or {}),
        change_summary=summary,
        message_id=message_id,
        evidence_id=evidence_id,
    ))


async def _match_existing_project(
    db: AsyncSession, learner_id: int, topic: str,
) -> Project | None:
    normalized = _compact(topic)
    if not normalized:
        return None
    projects = (await db.execute(
        select(Project).where(Project.learner_id == learner_id)
        .order_by(Project.updated_at.desc())
    )).scalars().all()
    for project in projects:
        name = _compact(project.name)
        if name and (name == normalized or name in normalized or normalized in name):
            return project
    return None


def _proposal_relevance(message: str, proposals: list[LearningProjectProposal], intent: dict | None) -> LearningProjectProposal | None:
    requested_key = str((intent or {}).get("relevant_proposal_key") or "").strip()
    if requested_key:
        match = next((item for item in proposals if item.proposal_key == requested_key), None)
        if match:
            return match
    compact = _compact(message)
    scored: list[tuple[int, LearningProjectProposal]] = []
    for proposal in proposals:
        artifact_text = _compact(json.dumps(proposal.artifact or {}, ensure_ascii=False))
        score = 0
        for token in re.findall(r"[a-zA-Z][a-zA-Z0-9+#.-]{1,}|[\u4e00-\u9fff]{2,}", compact):
            if token in artifact_text:
                score += min(len(token), 8)
        if score:
            scored.append((score, proposal))
    if scored:
        return max(scored, key=lambda item: item[0])[1]
    if len(proposals) == 1 and any(_compact(hint) in compact for hint in PROFILE_HINTS):
        return proposals[0]
    return None


async def evolve_project_proposal(
    db: AsyncSession,
    session: AgentSession,
    *,
    message: str,
    user_message_id: int,
    evidence: EvidenceEvent,
    opportunity: dict | None,
    learning_intent: dict | None,
) -> LearningProjectProposal | None:
    proposals = await list_session_proposals(db, session.id)
    relevant = _proposal_relevance(message, proposals, learning_intent)
    explicit_goal = _looks_like_long_goal(message, opportunity, learning_intent)

    if relevant:
        patch, summary = _revision_patch(message, relevant, opportunity)
        if not patch:
            return None
        merged = _merge_tutor_patch(relevant, patch)
        if merged == dict(relevant.artifact or {}):
            return None
        relevant.artifact = merged
        relevant.revision = (relevant.revision or 1) + 1
        relevant.last_change_summary = summary
        relevant.updated_at = datetime.utcnow()
        relevant.message_refs = list(dict.fromkeys([*list(relevant.message_refs or []), user_message_id]))[-50:]
        relevant.evidence_refs = list(dict.fromkeys([*list(relevant.evidence_refs or []), evidence.id]))[-50:]
        await _append_revision(
            db, relevant, source="tutor", patch=patch, summary=summary,
            message_id=user_message_id, evidence_id=evidence.id,
        )
        await record_event(
            db, event_type="project_proposal_revised", source="tutor_tool",
            learner_id=session.learner_id,
            session_id=session.id,
            payload={"proposal_id": relevant.id, "proposal_key": relevant.proposal_key,
                     "revision": relevant.revision, "change_summary": summary,
                     "learning_goal": merged.get("learning_goal", ""),
                     "practice_goal": merged.get("practice_goal", ""),
                     "learner_start": merged.get("learner_start", []),
                     "estimated_effort": merged.get("estimated_effort", "")},
            confidence=0.8, provenance={"message_id": user_message_id},
            client_event_id=f"proposal:{relevant.id}:revision:{relevant.revision}",
        )
        await db.flush()
        return relevant

    if not explicit_goal:
        return None
    topic = _topic_from_message(message, opportunity, learning_intent)
    if not topic:
        return None
    kind = _proposal_type(message, opportunity)
    key = _proposal_key(topic, kind)
    existing = next((item for item in proposals if item.proposal_key == key), None)
    if existing:
        return existing

    if len(proposals) >= 3:
        oldest = min(proposals, key=lambda item: item.updated_at or item.created_at or datetime.min)
        oldest.status = "archived"

    matched_project = await _match_existing_project(db, session.learner_id, topic)
    artifact = _base_artifact(message, topic, kind, opportunity)
    summary = "已根据长期目标生成首版项目提案"
    proposal = LearningProjectProposal(
        learner_id=session.learner_id,
        session_id=session.id,
        proposal_key=key,
        proposal_type=kind,
        status="ready",
        action_type="enter_existing" if matched_project else "create",
        target_project_id=matched_project.id if matched_project else None,
        artifact=artifact,
        revision=1,
        locked_fields=[],
        message_refs=[user_message_id],
        evidence_refs=[evidence.id],
        last_change_summary=(
            f"发现已有相关项目「{matched_project.name}」，建议继续使用"
            if matched_project else summary
        ),
        source_status="idle",
    )
    db.add(proposal)
    await db.flush()
    await _append_revision(
        db, proposal, source="tutor", patch=artifact,
        summary=proposal.last_change_summary,
        message_id=user_message_id, evidence_id=evidence.id,
    )
    await record_event(
        db, event_type="project_proposal_created", source="tutor_tool",
        learner_id=session.learner_id,
        session_id=session.id,
        payload={"proposal_id": proposal.id, "proposal_key": proposal.proposal_key,
                 "proposal_type": proposal.proposal_type, "topic": topic,
                 "action_type": proposal.action_type,
                 "learning_goal": artifact.get("learning_goal", ""),
                 "practice_goal": artifact.get("practice_goal", ""),
                 "learner_start": artifact.get("learner_start", []),
                 "estimated_effort": artifact.get("estimated_effort", "")},
        confidence=0.85, provenance={"message_id": user_message_id},
        client_event_id=f"proposal:{proposal.id}:created",
    )
    await db.flush()
    return proposal


async def update_project_proposal(
    db: AsyncSession,
    proposal: LearningProjectProposal,
    *,
    patch: dict,
    lock_fields: list[str],
    unlock_fields: list[str],
    client_event_id: str | None,
) -> LearningProjectProposal:
    if proposal.status not in ACTIVE_PROPOSAL_STATUSES:
        raise ValueError("这个项目提案当前不可编辑")
    clean_patch = {key: value for key, value in patch.items() if key in EDITABLE_FIELDS}
    artifact = dict(proposal.artifact or {})
    artifact.update(clean_patch)
    locked = set(str(value) for value in proposal.locked_fields or [])
    locked.update(value for value in lock_fields if value in EDITABLE_FIELDS or value == "milestone_order")
    locked.difference_update(unlock_fields)
    proposal.artifact = artifact
    proposal.locked_fields = sorted(locked)
    proposal.revision = (proposal.revision or 1) + 1
    proposal.last_change_summary = "已保存你的项目提案调整"
    proposal.updated_at = datetime.utcnow()
    await _append_revision(
        db, proposal, source="user", patch=clean_patch,
        summary=proposal.last_change_summary,
    )
    await record_event(
        db, event_type="project_proposal_user_edited", source="user",
        learner_id=proposal.learner_id,
        session_id=proposal.session_id,
        payload={"proposal_id": proposal.id, "revision": proposal.revision,
                 "changed_fields": list(clean_patch), "locked_fields": sorted(locked)},
        confidence=1.0, provenance={"proposal_id": proposal.id},
        client_event_id=client_event_id,
    )
    await db.flush()
    return proposal


async def set_proposal_status(
    db: AsyncSession,
    proposal: LearningProjectProposal,
    status: str,
) -> LearningProjectProposal:
    if status not in {"ready", "dismissed"}:
        raise ValueError("不支持的项目提案状态")
    proposal.status = status
    proposal.updated_at = datetime.utcnow()
    await record_event(
        db,
        learner_id=proposal.learner_id,
        event_type="project_proposal_reopened" if status == "ready" else "project_proposal_dismissed",
        source="user", session_id=proposal.session_id,
        payload={"proposal_id": proposal.id, "proposal_key": proposal.proposal_key},
        confidence=1.0, provenance={"proposal_id": proposal.id},
        client_event_id=f"proposal:{proposal.id}:{status}:{proposal.revision}",
    )
    return proposal


def _search_tokens(value: str) -> list[str]:
    tokens = re.findall(r"[a-zA-Z][a-zA-Z0-9+#.-]{1,}|[\u4e00-\u9fff]{2,8}", (value or "").lower())
    return list(dict.fromkeys(
        token.strip(".-") for token in tokens
        if token.strip(".-") and token.strip(".-") not in SEARCH_STOPWORDS
        and not token.startswith(("language:", "stars:", "fork:", "archived:", "in:"))
    ))


def _proposal_search_text(artifact: dict) -> str:
    milestones = " ".join(
        f"{item.get('title', '')} {item.get('purpose', '')}"
        for item in artifact.get("milestones", []) if isinstance(item, dict)
    )
    stack = " ".join(str(item) for item in (artifact.get("details") or {}).get("stack", []))
    return " ".join(str(value or "") for value in (
        artifact.get("title"), artifact.get("learning_goal"), artifact.get("practice_goal"),
        artifact.get("source_search_query"), milestones, stack,
    ))


def _github_search_plans(artifact: dict, generation: int) -> list[dict]:
    """Use complementary GitHub rankings instead of one star-sorted query."""
    raw_query = str(artifact.get("source_search_query") or "").strip()
    language_match = re.search(r"language:([^\s]+)", raw_query, re.IGNORECASE)
    language = language_match.group(1) if language_match else ""
    qualifier = f" language:{language}" if language else ""
    common = f"{qualifier} fork:false archived:false"
    context = _proposal_search_text(artifact).lower()
    exploration_page = 1 + ((max(generation, 1) - 1) % 3)

    if any(term in context for term in ("gpt", "transformer", "language model", "大语言模型")):
        broad_common = " fork:false archived:false"
        return [
            {"q": f'"gpt from scratch" pytorch in:name,description,readme{broad_common}', "sort": "stars", "page": 1},
            {
                "q": f'"build a large language model" pytorch in:name,description,readme{broad_common}',
                "sort": "stars",
                "page": 1,
            },
            {"q": f'nanoGPT OR minGPT in:name,description{common}', "sort": "stars", "page": 1},
        ]

    without_qualifiers = re.sub(
        r"\b(?:language|stars|fork|archived|in):\S+", "", raw_query,
        flags=re.IGNORECASE,
    ).strip()
    tokens = _search_tokens(
        f"{without_qualifiers} {artifact.get('title', '')} {artifact.get('practice_goal', '')}"
    )[:7]
    core = " ".join(tokens) or without_qualifiers or str(artifact.get("title") or "learning project")
    return [
        {"q": f"{core} in:name,description,readme{common}", "sort": "stars", "page": 1},
        {"q": f"{core} tutorial in:name,description,readme{common}", "sort": "stars", "page": 1},
        {"q": f'"{core}" in:name,description,readme{common}', "sort": "updated", "page": exploration_page},
    ]


def _days_since(value: str | None) -> int:
    if not value:
        return 3650
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
        return max(0, (datetime.utcnow() - parsed).days)
    except (TypeError, ValueError):
        return 3650


def _score_repository(item: dict, artifact: dict, profile: LearnerProfile | None) -> dict | None:
    if item.get("archived") or item.get("disabled") or item.get("fork") or item.get("private"):
        return None
    full_name = str(item.get("full_name") or "")
    name = full_name.lower()
    description = str(item.get("description") or "").lower()
    topics = [str(value).lower() for value in item.get("topics") or []]
    language = str(item.get("language") or "")
    haystack = " ".join([name, description, " ".join(topics), language.lower()])
    context = _proposal_search_text(artifact).lower()
    context_tokens = _search_tokens(context)[:24]

    token_hits = [token for token in context_tokens if token in haystack]
    lexical = sum(
        7 if token in name else 4 if token in description else 2
        for token in token_hits
    )
    lexical = min(34, lexical)

    is_gpt_goal = any(term in context for term in ("gpt", "transformer", "language model", "大语言模型"))
    gpt_relevant = any(term in haystack for term in (
        "gpt", "transformer", "language model", "large language model", "llm",
    ))
    build_relevant = any(term in haystack for term in (
        "from scratch", "implementation", "training", "minimal", "mini", "tiny",
        "decoder", "pytorch", "build a large language model",
    ))
    if is_gpt_goal and (not gpt_relevant or not build_relevant):
        return None
    if not is_gpt_goal and not token_hits:
        return None

    start_text = " ".join(str(value) for value in artifact.get("learner_start", [])).lower()
    beginner = any(term in start_text for term in ("尚未", "没用过", "从零", "待建立", "beginner"))
    if profile and profile.education_stage in {"middle_school", "high_school", "undergraduate"}:
        beginner = beginner or not profile.background.strip()

    fit_hits = [term for term in LEARNING_FIT_TERMS if term in haystack]
    practice_hits = [term for term in PRACTICE_TERMS if term in haystack]
    learning_fit = min(18, len(fit_hits) * 3 + len(practice_hits) * 2)
    if beginner and any(term in haystack for term in ("from scratch", "step by step", "minimal", "beginner")):
        learning_fit += 5

    off_topic_hits = [term for term in OFF_TOPIC_TERMS if term in haystack]
    if off_topic_hits and lexical < 16:
        return None
    penalty = min(20, len(off_topic_hits) * 8)

    stars = int(item.get("stargazers_count") or 0)
    forks = int(item.get("forks_count") or 0)
    if stars < 10:
        penalty += 8
    elif stars < 50:
        penalty += 4
    popularity = min(24.0, math.log10(stars + 1) * 4.8) + min(4.0, math.log10(forks + 1))
    age_days = _days_since(item.get("pushed_at"))
    activity = 9 if age_days <= 120 else 7 if age_days <= 365 else 5 if age_days <= 730 else 2 if age_days <= 1460 else 0
    license_info = item.get("license") or {}
    trust = 2 + (3 if license_info.get("spdx_id") or license_info.get("key") else 0)
    trust += 2 if description else 0
    trust += 2 if topics else 0
    total = round(lexical + learning_fit + popularity + activity + trust - penalty, 2)
    if total < 34:
        return None

    reasons = []
    if token_hits:
        reasons.append("覆盖" + "、".join(token_hits[:3]))
    if fit_hits:
        reasons.append("包含循序实践材料")
    if stars >= 10000:
        reasons.append("社区认可度很高")
    elif stars >= 1000:
        reasons.append("社区热度较高")
    if age_days <= 365:
        reasons.append("近期仍在维护")
    quality = "excellent" if total >= 72 else "strong" if total >= 58 else "relevant"
    return {
        "title": item.get("full_name") or item.get("name") or "GitHub repository",
        "url": str(item.get("html_url") or ""),
        "type": "github",
        "description": str(item.get("description") or "")[:240],
        "stars": stars,
        "forks": forks,
        "language": language,
        "license": license_info.get("spdx_id") or license_info.get("key") or "",
        "pushed_at": item.get("pushed_at"),
        "rank_score": total,
        "quality": quality,
        "match_reasons": reasons,
        "reason": "；".join(reasons) or "与当前学习目标相关",
    }


def _rank_repository_candidates(
    items: list[dict],
    artifact: dict,
    profile: LearnerProfile | None,
    *,
    generation: int,
    previous_urls: list[str],
) -> list[dict]:
    scored = [candidate for item in items if (candidate := _score_repository(item, artifact, profile))]
    scored.sort(key=lambda item: (item["rank_score"], item["stars"]), reverse=True)
    if not scored:
        return []
    top_score = scored[0]["rank_score"]
    quality_floor = max(38, top_score - 25)
    eligible = [item for item in scored if item["rank_score"] >= quality_floor]
    cap = 8 if top_score >= 72 and len(eligible) >= 7 else 6 if top_score >= 58 else 4

    previous = set(previous_urls)
    if generation > 1 and len(eligible) > 3:
        head = eligible[:3]
        tail = sorted(eligible[3:], key=lambda item: (item["url"] not in previous, item["rank_score"]), reverse=True)
        eligible = [*head, *tail]

    selected = []
    owner_counts: dict[str, int] = {}
    for item in eligible:
        owner = item["title"].split("/", 1)[0].lower()
        if owner_counts.get(owner, 0) >= 2:
            continue
        selected.append(item)
        owner_counts[owner] = owner_counts.get(owner, 0) + 1
        if len(selected) >= cap:
            break
    return selected


async def start_resource_search(
    db: AsyncSession,
    proposal: LearningProjectProposal,
    *,
    force: bool = False,
) -> LearningProjectProposal:
    artifact = dict(proposal.artifact or {})
    query = str(artifact.get("source_search_query") or "").strip()
    if not settings.github_resource_search_enabled or not query:
        return proposal
    if proposal.source_status in {"queued", "searching"} and proposal.source_task_id:
        return proposal
    if (
        not force
        and proposal.source_status == "completed"
        and artifact.get("source_search_completed_query") == query
    ):
        return proposal
    generation = int(artifact.get("source_search_generation") or 0) + 1
    previous_urls = [
        str(item.get("url")) for item in artifact.get("candidate_sources", [])
        if isinstance(item, dict) and item.get("url")
    ]
    artifact["source_search_generation"] = generation
    artifact["source_search_requested_at"] = datetime.utcnow().isoformat()
    artifact.pop("source_search_last_error", None)
    proposal.artifact = artifact
    task = Task(
        learner_id=proposal.learner_id,
        type="proposal_resource_search",
        status="queued",
        payload={
            "proposal_id": proposal.id,
            "query": query,
            "generation": generation,
            "previous_urls": previous_urls,
        },
        progress={"current": 0, "total": 1, "message": "正在寻找候选仓库..."},
    )
    db.add(task)
    await db.flush()
    proposal.source_task_id = task.id
    proposal.source_status = "queued"
    await db.commit()
    from app.services.task_manager import manager
    manager.submit(task.id, run_resource_search(task.id))
    return proposal


async def run_resource_search(task_id: int):
    async with async_session() as db:
        task = await db.get(Task, task_id)
        if not task:
            return
        proposal = await db.get(LearningProjectProposal, (task.payload or {}).get("proposal_id"))
        if not proposal or proposal.learner_id != task.learner_id:
            task.status = "failed"
            task.error = {"code": "proposal_missing", "message": "项目提案不存在", "retryable": False}
            task.finished_at = datetime.utcnow()
            await db.commit()
            return
        task.status = "running"
        task.started_at = datetime.utcnow()
        task.progress = {"current": 0, "total": 3, "message": "正在从 GitHub 多路检索候选仓库..."}
        proposal.source_status = "searching"
        await db.commit()

        artifact = dict(proposal.artifact or {})
        generation = int((task.payload or {}).get("generation") or 1)
        previous_urls = list((task.payload or {}).get("previous_urls") or [])
        plans = _github_search_plans(artifact, generation)
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "LearnFlow-Tutor",
        }
        if settings.github_token:
            headers["Authorization"] = f"Bearer {settings.github_token}"
        try:
            async def fetch(plan: dict) -> tuple[list[dict], str | None]:
                params = {
                    "q": plan["q"], "order": "desc", "per_page": 30,
                    "page": plan.get("page", 1),
                }
                if plan.get("sort"):
                    params["sort"] = plan["sort"]
                try:
                    async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
                        response = await client.get(
                            "https://api.github.com/search/repositories",
                            params=params, headers=headers,
                        )
                        response.raise_for_status()
                        return list(response.json().get("items", [])), None
                except Exception as exc:
                    return [], str(exc)[:200]

            batches = await asyncio.gather(*(fetch(plan) for plan in plans))
            errors = [error for _, error in batches if error]
            discovered: dict[str, dict] = {}
            for items, _ in batches:
                for item in items:
                    url = str(item.get("html_url") or "")
                    if url.startswith("https://github.com/"):
                        discovered[url] = item
            if not discovered and errors:
                raise RuntimeError(errors[0])

            profile = await db.get(LearnerProfile, proposal.learner_id)
            candidates = _rank_repository_candidates(
                list(discovered.values()), artifact, profile,
                generation=generation, previous_urls=previous_urls,
            )
            artifact["candidate_sources"] = candidates
            artifact["source_search_completed_query"] = str((task.payload or {}).get("query") or "")
            artifact["source_search_refreshed_at"] = datetime.utcnow().isoformat()
            artifact["source_search_discovered_count"] = len(discovered)
            artifact["source_search_partial_failures"] = len(errors)
            new_urls = [item["url"] for item in candidates]
            changed = new_urls != previous_urls
            artifact["source_search_result_changed"] = changed
            proposal.artifact = artifact
            proposal.source_status = "completed"
            proposal.revision = (proposal.revision or 1) + 1
            source_summary = (
                f"重新检索并更新为 {len(candidates)} 个候选仓库"
                if changed else f"已重新检索，当前 {len(candidates)} 个最佳候选排序未变化"
            )
            proposal.updated_at = datetime.utcnow()
            await _append_revision(
                db, proposal, source="resource_search",
                patch={
                    "candidate_sources": candidates,
                    "source_search_generation": generation,
                    "source_search_refreshed_at": artifact["source_search_refreshed_at"],
                },
                summary=source_summary,
            )
            task.status = "completed"
            task.result = {
                "proposal_id": proposal.id, "candidate_count": len(candidates),
                "discovered_count": len(discovered), "generation": generation,
                "changed": changed, "partial_failures": len(errors),
            }
            task.progress = {
                "current": 3, "total": 3,
                "message": "候选仓库已更新" if changed else "已重新检索，最佳候选未变化",
            }
            task.finished_at = datetime.utcnow()
        except Exception as exc:
            proposal.source_status = "failed"
            artifact = dict(proposal.artifact or {})
            artifact["source_search_last_error"] = str(exc)[:300]
            proposal.artifact = artifact
            task.status = "failed"
            task.error = {
                "code": "resource_search_failed", "message": str(exc)[:300],
                "guidance": "稍后可在提案中重试，项目提案本身不受影响。", "retryable": True,
            }
            task.finished_at = datetime.utcnow()
        await db.commit()
