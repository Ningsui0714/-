"""Evidence ledger and deterministic five-kernel runtime.

The ledger is the source of truth. Kernel rows are materialized projections
that can always be rebuilt from evidence.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Iterable

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.learning import (
    AgentSession, Learner, EvidenceEvent, LearningAttempt, KernelState,
    KernelMutation, MemoryArchive,
)
from app.models.project import Project, Roadmap, Checkpoint, Lecture
from app.services.architecture_registry import (
    KERNEL_NAMES,
    SEMANTIC_MEMORY_KEYS,
    normalize_event_provenance,
)


LOCAL_LEARNER_KEY = "local-default"

PUBLIC_EVENT_TYPES = {
    "project_selected", "checkpoint_entered", "lecture_viewed",
    "hint_requested", "code_review_requested", "learning_feedback",
}


async def get_default_learner(db: AsyncSession) -> Learner:
    learner = (await db.execute(
        select(Learner).where(Learner.key == LOCAL_LEARNER_KEY)
    )).scalar_one_or_none()
    if learner:
        return learner
    learner = Learner(key=LOCAL_LEARNER_KEY, display_name="本地学习者")
    db.add(learner)
    await db.flush()
    await ensure_kernel_states(db, learner.id)
    return learner


async def ensure_kernel_states(db: AsyncSession, learner_id: int):
    existing = set((await db.execute(
        select(KernelState.kernel_name).where(KernelState.learner_id == learner_id)
    )).scalars().all())
    for name in KERNEL_NAMES:
        if name not in existing:
            db.add(KernelState(
                learner_id=learner_id,
                kernel_name=name,
                short_term={}, long_term={}, action_chain=[], evidence_refs=[],
                confidence=0.0, version=1,
            ))
    await db.flush()


def context_id(project_id: int | None, checkpoint_id: int | None, session_id: int | None = None) -> str:
    parts = []
    if project_id is not None:
        parts.append(f"project:{project_id}")
    if checkpoint_id is not None:
        parts.append(f"checkpoint:{checkpoint_id}")
    if session_id is not None:
        parts.append(f"session:{session_id}")
    return "/".join(parts) or "global"


async def record_event(
    db: AsyncSession,
    *,
    learner_id: int | None = None,
    event_type: str,
    source: str,
    project_id: int | None = None,
    checkpoint_id: int | None = None,
    session_id: int | None = None,
    payload: dict | None = None,
    confidence: float = 1.0,
    provenance: dict | None = None,
    client_event_id: str | None = None,
    artifact_refs: list | None = None,
    occurred_at: datetime | None = None,
    actor_type: str | None = None,
) -> EvidenceEvent:
    if learner_id is None:
        learner_id = (await get_default_learner(db)).id
    await ensure_kernel_states(db, learner_id)

    if project_id is not None:
        owner = (await db.execute(select(Project.id).where(
            Project.id == project_id, Project.learner_id == learner_id,
        ))).scalar_one_or_none()
        if not owner:
            raise ValueError("项目不属于当前学习者")
    if checkpoint_id is not None:
        owner = (await db.execute(
            select(Checkpoint.id)
            .join(Roadmap, Roadmap.id == Checkpoint.roadmap_id)
            .join(Project, Project.id == Roadmap.project_id)
            .where(
                Checkpoint.id == checkpoint_id,
                Project.learner_id == learner_id,
            )
        )).scalar_one_or_none()
        if not owner:
            raise ValueError("检查点不属于当前学习者")
    if session_id is not None:
        owner = (await db.execute(select(AgentSession.id).where(
            AgentSession.id == session_id,
            AgentSession.learner_id == learner_id,
        ))).scalar_one_or_none()
        if not owner:
            raise ValueError("Tutor 会话不属于当前学习者")

    if client_event_id:
        scoped_event_id = f"{learner_id}:{client_event_id}"
        existing = (await db.execute(
            select(EvidenceEvent).where(
                EvidenceEvent.learner_id == learner_id,
                EvidenceEvent.client_event_id.in_([scoped_event_id, client_event_id]),
            )
        )).scalar_one_or_none()
        if existing:
            return existing
        client_event_id = scoped_event_id

    from app.services.memory_graph import actor_type_for_source, next_learner_sequence

    recorded_at = datetime.utcnow()
    event = EvidenceEvent(
        learner_id=learner_id,
        project_id=project_id,
        checkpoint_id=checkpoint_id,
        session_id=session_id,
        event_type=event_type,
        source=source,
        context_id=context_id(project_id, checkpoint_id, session_id),
        payload=payload or {},
        artifact_refs=artifact_refs or [],
        confidence=max(0.0, min(float(confidence), 1.0)),
        provenance=normalize_event_provenance(event_type, source, provenance),
        client_event_id=client_event_id,
        occurred_at=occurred_at or recorded_at,
        learner_seq=await next_learner_sequence(db, learner_id),
        actor_type=actor_type or actor_type_for_source(source),
        created_at=recorded_at,
    )
    db.add(event)
    await db.flush()
    await _reduce_event(db, event)
    return event


async def _kernel(db: AsyncSession, learner_id: int, name: str) -> KernelState:
    state = (await db.execute(
        select(KernelState).where(
            KernelState.learner_id == learner_id,
            KernelState.kernel_name == name,
        )
    )).scalar_one()
    return state


async def _apply_patch(
    db: AsyncSession,
    event: EvidenceEvent,
    kernel_name: str,
    short_patch: dict,
    reason: str,
    *,
    long_patch: dict | None = None,
):
    state = await _kernel(db, event.learner_id, kernel_name)
    before = state.version or 1
    short_term = dict(state.short_term or {})
    short_term.update(short_patch)
    long_term = dict(state.long_term or {})
    if long_patch:
        long_term.update(long_patch)
    chain = list(state.action_chain or [])
    chain.append({
        "event_id": event.id,
        "type": event.event_type,
        "at": event.created_at.isoformat() if event.created_at else datetime.utcnow().isoformat(),
    })
    refs = list(state.evidence_refs or [])
    refs.append(event.id)
    state.short_term = short_term
    state.long_term = long_term
    state.action_chain = chain[-20:]
    state.evidence_refs = refs[-100:]
    state.confidence = round(min(1.0, max(state.confidence or 0.0, event.confidence or 0.0)), 3)
    state.version = before + 1
    state.updated_at = datetime.utcnow()
    mutation = KernelMutation(
        learner_id=event.learner_id,
        event_id=event.id,
        kernel_name=kernel_name,
        mutation_type="long_term" if long_patch else "short_term",
        status="applied",
        patch={"short_term": short_patch, "long_term": long_patch or {}},
        reason=reason,
        before_version=before,
        after_version=state.version,
    )
    db.add(mutation)
    await db.flush()

    from app.services.memory_graph import create_facts_for_mutation
    await create_facts_for_mutation(db, event, mutation)


async def _reduce_event(db: AsyncSession, event: EvidenceEvent):
    p = dict(event.payload or {})
    et = event.event_type

    if et in {
        "memory_correction_confirmed",
        "memory_correction_added",
        "memory_correction_retracted",
    }:
        kernel_name = p.get("kernel_name")
        if kernel_name in KERNEL_NAMES:
            await _apply_patch(
                db, event, kernel_name,
                {"memory_feedback": {
                    "claim_id": p.get("claim_id"),
                    "action": p.get("action"),
                    "correction": p.get("correction", ""),
                }},
                "学习者对可检查记忆声明提交了追加式反馈",
            )
        return

    if et == "registration_profile_completed":
        await _apply_patch(
            db, event, "knowledge",
            {"declared_background": p.get("background", ""), "self_report_only": True},
            "注册资料记录学习起点，不构成掌握证据",
        )
        await _apply_patch(
            db, event, "human",
            {"weekly_hours": p.get("weekly_hours"), "preferred_modes": p.get("preferred_modes", [])},
            "用户明确填写了稳定的学习节奏与形式偏好",
            long_patch={"learning_preferences": {
                "weekly_hours": p.get("weekly_hours"),
                "preferred_modes": p.get("preferred_modes", []),
            }},
        )
        value_long = {"focus_areas": p.get("focus_areas", [])}
        if p.get("career_goal") and p.get("career_goal_status") == "confirmed":
            value_long["career_goal"] = p.get("career_goal")
        await _apply_patch(
            db, event, "value",
            {"focus_areas": p.get("focus_areas", []),
             "career_goal_candidate": p.get("career_goal", "")},
            "注册资料记录关注方向与职业目标自述",
            long_patch=value_long,
        )
        return

    if et == "career_goal_confirmed":
        await _apply_patch(
            db, event, "value",
            {"career_goal_candidate": p.get("career_goal", ""), "career_goal_status": "confirmed"},
            "高置信度职业理想事件进入长期价值记忆",
            long_patch={"career_goal": p.get("career_goal", "")},
        )
        return

    if et == "profile_updated":
        if "background" in p:
            await _apply_patch(
                db, event, "knowledge",
                {"declared_background": p.get("background", ""), "self_report_only": True},
                "用户更新了自述基础，不构成掌握证据",
            )
        if "weekly_hours" in p or "preferred_modes" in p:
            preferences = {
                "weekly_hours": p.get("weekly_hours"),
                "preferred_modes": p.get("preferred_modes", []),
            }
            await _apply_patch(
                db, event, "human", preferences,
                "用户更新了学习节奏与形式偏好",
                long_patch={"learning_preferences": preferences},
            )
        if "focus_areas" in p:
            await _apply_patch(
                db, event, "value", {"focus_areas": p.get("focus_areas", [])},
                "用户更新了关注方向",
                long_patch={"focus_areas": p.get("focus_areas", [])},
            )
        return

    if et in {
        "project_proposal_created", "project_proposal_revised",
        "project_proposal_user_edited", "project_proposal_reopened",
        "project_proposal_dismissed",
    }:
        proposal_id = p.get("proposal_id")
        status = "dismissed" if et == "project_proposal_dismissed" else "active"
        await _apply_patch(
            db, event, "structure",
            {"active_proposal_id": proposal_id, "proposal_status": status},
            "项目提案只更新候选结构，不直接创建长期项目",
        )
        if p.get("learning_goal"):
            await _apply_patch(
                db, event, "value",
                {"goal_candidate": p.get("learning_goal"),
                 "proposal_id": proposal_id, "goal_status": status},
                "长期目标在用户接受前保持为候选",
            )
        if p.get("practice_goal"):
            await _apply_patch(
                db, event, "practice",
                {"artifact_candidate": p.get("practice_goal"), "proposal_id": proposal_id},
                "记录项目实践产物候选",
            )
        if p.get("learner_start"):
            await _apply_patch(
                db, event, "knowledge",
                {"declared_starting_point": p.get("learner_start")},
                "用户基础作为提案适配信息，不作为掌握证明",
            )
        if p.get("estimated_effort"):
            await _apply_patch(
                db, event, "human",
                {"proposal_pace": p.get("estimated_effort")},
                "提案节奏用于短期教学适配",
            )
        return

    if et in {"project_created", "project_selected", "project_imported"}:
        project_id = event.project_id or p.get("project_id")
        project = (await db.execute(select(Project).where(
            Project.id == project_id,
            Project.learner_id == event.learner_id,
        ))).scalar_one_or_none() if project_id else None
        long_patch = None
        if et in {"project_created", "project_imported"} and project_id:
            state = await _kernel(db, event.learner_id, "structure")
            graph = dict((state.long_term or {}).get("project_graph") or {})
            graph[str(project_id)] = {
                "name": p.get("name", ""),
                "description": p.get("description", ""),
            }
            long_patch = {"project_graph": graph}
        await _apply_patch(
            db, event, "structure",
            {"active_project_id": project_id, "active_checkpoint_id": None,
             "current_task": "进入学习项目",
             "path_position": {
                 "project_id": project_id,
                 "project_name": project.name if project else p.get("name", ""),
                 "level": "project",
             }},
            "项目上下文发生变化", long_patch=long_patch,
        )
        return

    if et in {"source_added", "source_processing", "source_processed", "source_failed"}:
        patch = {
            "active_project_id": event.project_id,
            "current_task": "处理学习来源",
            "current_blocker": p.get("error", "") if et == "source_failed" else "",
        }
        await _apply_patch(db, event, "structure", patch, "学习来源状态更新")
        await _apply_patch(
            db, event, "practice",
            {"artifact_state": et, "recent_feedback": p.get("status", et)},
            "来源形成可执行学习材料",
        )
        return

    if et == "checkpoint_entered":
        checkpoint = (await db.execute(
            select(Checkpoint)
            .join(Roadmap, Roadmap.id == Checkpoint.roadmap_id)
            .join(Project, Project.id == Roadmap.project_id)
            .where(
                Checkpoint.id == event.checkpoint_id,
                Project.learner_id == event.learner_id,
            )
        )).scalar_one_or_none()
        roadmap = await db.get(Roadmap, checkpoint.roadmap_id) if checkpoint else None
        project = await db.get(Project, roadmap.project_id) if roadmap else None
        structure = await _kernel(db, event.learner_id, "structure")
        previous_checkpoint_id = (structure.short_term or {}).get("active_checkpoint_id")
        previous_checkpoint = None
        if previous_checkpoint_id and previous_checkpoint_id != event.checkpoint_id:
            previous_checkpoint = (await db.execute(
                select(Checkpoint)
                .join(Roadmap, Roadmap.id == Checkpoint.roadmap_id)
                .join(Project, Project.id == Roadmap.project_id)
                .where(
                    Checkpoint.id == previous_checkpoint_id,
                    Project.learner_id == event.learner_id,
                )
            )).scalar_one_or_none()
        prerequisite_ids = list((checkpoint.prerequisites or []) if checkpoint else [])
        prerequisite_rows = []
        if prerequisite_ids:
            prerequisite_rows = (await db.execute(
                select(Checkpoint)
                .join(Roadmap, Roadmap.id == Checkpoint.roadmap_id)
                .join(Project, Project.id == Roadmap.project_id)
                .where(
                    Checkpoint.id.in_(prerequisite_ids),
                    Project.learner_id == event.learner_id,
                )
            )).scalars().all()
        prerequisite_map = {item.id: item for item in prerequisite_rows}
        title = checkpoint.title if checkpoint else p.get("title", "当前检查点")
        path_position = {
            "project_id": event.project_id,
            "project_name": project.name if project else "",
            "checkpoint_id": event.checkpoint_id,
            "checkpoint_title": title,
            "checkpoint_order": checkpoint.order if checkpoint else None,
            "level": "checkpoint",
        }
        patch = {
            "active_project_id": event.project_id,
            "active_checkpoint_id": event.checkpoint_id,
            "current_task": title,
            "path_position": path_position,
            "resume_anchor": {
                "checkpoint_id": event.checkpoint_id,
                "checkpoint_title": title,
                "note": f"返回时从「{title}」继续",
            },
        }
        if prerequisite_ids:
            patch["path_dependencies"] = [
                {
                    "checkpoint_id": checkpoint_id,
                    "title": prerequisite_map.get(checkpoint_id).title
                    if prerequisite_map.get(checkpoint_id) else f"检查点 {checkpoint_id}",
                }
                for checkpoint_id in prerequisite_ids
            ]
        if previous_checkpoint:
            patch["focus_transition"] = {
                "from_checkpoint_id": previous_checkpoint.id,
                "from_title": previous_checkpoint.title,
                "to_checkpoint_id": event.checkpoint_id,
                "to_title": title,
                "reason": "学习位置切换",
            }
        await _apply_patch(
            db, event, "structure", patch,
            "记录学习路径位置、依赖与返回线索",
        )
        return

    if et in {"lecture_generated", "lecture_viewed"}:
        await _apply_patch(
            db, event, "knowledge",
            {"active_concepts": p.get("concepts", []),
             "last_explanation": "讲义已生成" if et == "lecture_generated" else "讲义已阅读",
             "exposure_only": True},
            "讲义只形成接触证据，不代表掌握",
        )
        return

    if et == "user_message":
        text = str(p.get("text", ""))
        lower = text.lower()
        if any(word in text for word in ("不懂", "没懂", "困惑", "为什么", "不会")):
            await _apply_patch(
                db, event, "knowledge",
                {"pending_question": text[:500], "knowledge_gap": text[:500]},
                "用户表达了待澄清的知识疑问；疑问不等于误解",
            )
        if any(word in text for word in ("太难", "烦", "崩溃", "跟不上", "累")):
            await _apply_patch(
                db, event, "human",
                {"affect": "frustrated", "cognitive_load": 0.85,
                 "frustration": 0.8,
                 "transient_expires_at": (datetime.utcnow() + timedelta(hours=2)).isoformat()},
                "用户表达了短期学习负荷",
            )
        if any(word in text for word in ("想学", "目标", "为了", "计划", "掌握")) or "i want to learn" in lower:
            await _apply_patch(
                db, event, "value",
                {"current_priority": text[:500], "current_motivation": "explicit"},
                "用户表达了当前学习目标",
            )
        if text.strip() in {"懂了", "明白了", "会了", "got it", "understood"}:
            await _apply_patch(
                db, event, "knowledge",
                {"last_acknowledgement": text.strip(), "mastery_unchanged": True},
                "自我确认是低置信度反馈，不晋级掌握",
            )
        return

    if et in {"hint_requested", "code_review_requested", "explanation_requested"}:
        level = "hint" if et == "hint_requested" else "guided"
        await _apply_patch(
            db, event, "practice",
            {"assistance_level": level, "recent_feedback": et},
            "记录当前尝试的辅助程度",
        )
        return

    if et == "remediation_started":
        await _apply_patch(
            db, event, "knowledge",
            {
                "active_remediation_case_id": p.get("case_id"),
                "pending_question": p.get("misconception_tag") or "答错后需要纠错",
                "recent_misconception": {
                    "tag": p.get("misconception_tag", ""),
                    "error_class": p.get("error_class", ""),
                    "item_id": p.get("item_id"),
                    "source_evidence_id": p.get("source_evidence_id"),
                },
            },
            "已验证的错误启动显式纠错闭环",
        )
        await _apply_patch(
            db, event, "practice",
            {
                "remediation_status": "explaining",
                "remediation_case_id": p.get("case_id"),
                "recent_feedback": p.get("delivery_mode", ""),
            },
            "纠错案例进入证据讲解阶段",
        )
        return

    if et == "remediation_mode_rejected":
        human = await _kernel(db, event.learner_id, "human")
        ineffective = list((human.short_term or {}).get("ineffective_explanation_modes") or [])
        mode = p.get("ineffective_mode")
        if mode and mode not in ineffective:
            ineffective.append(mode)
        await _apply_patch(
            db, event, "human",
            {
                "ineffective_explanation_modes": ineffective[-8:],
                "last_requested_explanation_mode": p.get("next_mode", ""),
            },
            "学习者明确要求换一种讲法，记录当前上下文中的无效表征",
        )
        return

    if et == "remediation_explanation_requested":
        await _apply_patch(
            db, event, "practice",
            {
                "remediation_status": "explaining",
                "remediation_case_id": p.get("case_id"),
                "assistance_level": "guided",
                "recent_feedback": p.get("delivery_mode", ""),
            },
            "记录纠错讲解的显式表征选择",
        )
        return

    if et == "remediation_retry_evaluated":
        passed = bool(p.get("passed"))
        await _apply_patch(
            db, event, "practice",
            {
                "remediation_status": "variant_ready" if passed else "explaining",
                "remediation_case_id": p.get("case_id"),
                "current_attempt": p.get("attempt_id"),
                "recent_feedback": "retry_passed" if passed else "retry_failed",
            },
            "原题重做结果回写纠错闭环",
        )
        if passed:
            await _apply_patch(
                db, event, "knowledge",
                {"pending_question": "", "remediation_retry_verified": True},
                "原题重做通过，但仍需变式验证后闭环",
            )
        return

    if et == "remediation_variant_evaluated":
        correct = bool(p.get("correct"))
        await _apply_patch(
            db, event, "practice",
            {
                "remediation_status": "completed" if correct else "variant_ready",
                "remediation_case_id": p.get("case_id"),
                "current_attempt": p.get("attempt_id"),
                "recent_feedback": "variant_passed" if correct else "variant_failed",
            },
            "变式作答验证纠错规则是否可迁移",
        )
        return

    if et == "remediation_completed":
        await _apply_patch(
            db, event, "knowledge",
            {
                "active_remediation_case_id": None,
                "pending_question": "",
                "last_completed_remediation": {
                    "case_id": p.get("case_id"),
                    "evidence_event_ids": p.get("evidence_event_ids", []),
                },
            },
            "原题重做与变式均通过，纠错闭环形成可追溯证据",
        )
        await _apply_patch(
            db, event, "human",
            {"last_effective_explanation_mode": p.get("delivery_mode", "")},
            "成功完成纠错与迁移，保留本次有效讲法证据",
        )
        await _apply_patch(
            db, event, "practice",
            {"remediation_status": "completed",
             "remediation_case_id": p.get("case_id"),
             "remediation_evidence_event_ids": p.get("evidence_event_ids", [])},
            "显式纠错闭环完成并回写实践证据",
        )
        return

    if et == "review_attempt_evaluated":
        passed = bool(p.get("passed"))
        outcome = str(p.get("outcome") or ("correct" if passed else "incorrect"))
        independent = bool(p.get("independent", True))
        item_type = str(p.get("source_item_type") or p.get("item_type") or "concept")
        item_id = p.get("item_id")
        if item_id is None:
            return
        item_key = f"{item_type}:{item_id}"

        from app.services.review import stable_review_events
        matching = await stable_review_events(
            db, event.learner_id, item_type, int(item_id),
        )
        spaced_stable = bool(matching)

        knowledge = await _kernel(db, event.learner_id, "knowledge")
        retention = dict((knowledge.short_term or {}).get("retention_status") or {})
        retention[item_key] = {
            "status": (
                "spaced_stable" if spaced_stable
                else "retrieved" if passed and independent
                else "retrieved_with_support" if passed
                else "retrieval_gap" if outcome == "unknown"
                else "needs_review"
            ),
            "attempt_id": p.get("attempt_id"),
            "evidence_id": event.id,
            "question_form": p.get("question_form", "original"),
            "checkpoint_id": event.checkpoint_id,
        }
        recent_errors = list((knowledge.short_term or {}).get("recent_errors") or [])
        error_ref = f"{item_type}:{item_id}"
        if passed:
            recent_errors = [value for value in recent_errors if value != error_ref]
        elif error_ref not in recent_errors:
            recent_errors.append(error_ref)
        short_patch = {
            "retention_status": retention,
            "recent_errors": recent_errors[-12:],
        }
        if not passed:
            short_patch["pending_question"] = (
                "本轮未能提取答案，需要重新学习" if outcome == "unknown"
                else p.get("prompt", "复习题答错，需要纠错")
            )
        long_patch = None
        if spaced_stable:
            mastery = dict((knowledge.long_term or {}).get("mastery") or {})
            mastery[f"review:{item_key}"] = {
                "level": "stable",
                "policy_version": "review-policy-v1",
                "evidence_ids": [row.id for row in matching[-10:]],
            }
            long_patch = {"mastery": mastery}
        await _apply_patch(
            db, event, "knowledge", short_patch,
            "间隔检索结果更新知识保持状态",
            long_patch=long_patch,
        )

        practice = await _kernel(db, event.learner_id, "practice")
        review_history = dict((practice.short_term or {}).get("review_history") or {})
        review_history[item_key] = {
            "attempt_id": p.get("attempt_id"),
            "outcome": outcome,
            "assistance_level": p.get("assistance_level", "none"),
            "question_form": p.get("question_form", "original"),
            "evidence_id": event.id,
        }
        practice_long = None
        if spaced_stable:
            proof_chain = dict((practice.long_term or {}).get("proof_chain") or {})
            proof_chain[f"review:{item_key}"] = {
                "event_id": event.id,
                "checkpoint_id": event.checkpoint_id,
                "kind": "spaced_independent_transfer",
                "evidence_ids": [row.id for row in matching[-10:]],
            }
            practice_long = {"proof_chain": proof_chain}
        await _apply_patch(
            db, event, "practice",
            {
                "current_attempt": p.get("attempt_id"),
                "assistance_level": p.get("assistance_level", "none"),
                "recent_feedback": f"review_{outcome}",
                "review_history": review_history,
            },
            "复习尝试记录独立性、辅助程度与题目形式",
            long_patch=practice_long,
        )
        return

    if et == "concept_attempt_evaluated":
        correct = bool(p.get("correct"))
        independent = bool(p.get("independent", True))
        knowledge_state = await _kernel(db, event.learner_id, "knowledge")
        concept_understanding = dict(
            (knowledge_state.short_term or {}).get("concept_understanding") or {}
        )
        item_key = f"item:{p.get('item_id')}"
        concept_understanding[item_key] = {
            "status": (
                "verified_once" if correct and independent
                else "correct_with_support" if correct
                else "needs_review"
            ),
            "question": p.get("question", ""),
            "checkpoint_id": event.checkpoint_id,
            "evidence_id": event.id,
        }
        recent_errors = list((knowledge_state.short_term or {}).get("recent_errors") or [])
        item_id = p.get("item_id")
        if correct:
            recent_errors = [item for item in recent_errors if item != item_id]
        elif item_id not in recent_errors:
            recent_errors.append(item_id)
        patch = {
            "concept_understanding": concept_understanding,
            "recent_errors": recent_errors[-8:],
        }
        if not correct:
            patch["pending_question"] = p.get("question", "概念题答错")
        long_patch = None
        if correct and independent:
            rows = (await db.execute(select(EvidenceEvent).where(
                EvidenceEvent.learner_id == event.learner_id,
                EvidenceEvent.checkpoint_id == event.checkpoint_id,
                EvidenceEvent.event_type == "concept_attempt_evaluated",
            ))).scalars().all()
            distinct_items = {
                (row.payload or {}).get("item_id") for row in rows
                if (row.payload or {}).get("correct") and (row.payload or {}).get("independent", True)
            }
            if len({x for x in distinct_items if x is not None}) >= 2:
                mastery = dict((knowledge_state.long_term or {}).get("mastery") or {})
                mastery[f"checkpoint:{event.checkpoint_id}"] = {
                    "level": "stable", "evidence_ids": [row.id for row in rows[-10:]],
                }
                concept_understanding[item_key]["status"] = "stable"
                long_patch = {"mastery": mastery}
        await _apply_patch(db, event, "knowledge", patch, "概念评估结果", long_patch=long_patch)
        return

    if et == "exercise_attempt_evaluated":
        passed = bool(p.get("passed"))
        independent = p.get("assistance_level", "none") == "none"
        long_patch = None
        if passed and independent:
            state = await _kernel(db, event.learner_id, "practice")
            proof_chain = dict((state.long_term or {}).get("proof_chain") or {})
            proof_chain[f"exercise:{p.get('item_id')}"] = {
                "event_id": event.id, "checkpoint_id": event.checkpoint_id,
                "kind": "independent_success",
            }
            long_patch = {"proof_chain": proof_chain}
        await _apply_patch(
            db, event, "practice",
            {"current_attempt": p.get("attempt_id"),
             "artifact_state": "passed" if passed else "failed",
             "assistance_level": p.get("assistance_level", "none"),
             "recent_feedback": p.get("feedback", "")},
            "实践评估结果", long_patch=long_patch,
        )
        return

    if et == "transfer_attempt_evaluated":
        passed = bool(p.get("passed"))
        independent = p.get("assistance_level", "none") == "none"
        high_confidence = (event.confidence or 0.0) >= 0.9
        if passed and independent and high_confidence:
            knowledge = await _kernel(db, event.learner_id, "knowledge")
            mastery = dict((knowledge.long_term or {}).get("mastery") or {})
            mastery[f"checkpoint:{event.checkpoint_id}"] = {
                "level": "stable",
                "evidence_ids": [event.id],
                "kind": "high_confidence_transfer",
            }
            await _apply_patch(
                db, event, "knowledge",
                {"pending_question": "", "transfer_verified": True},
                "高置信度迁移任务形成掌握证据",
                long_patch={"mastery": mastery},
            )
            practice = await _kernel(db, event.learner_id, "practice")
            proof_chain = dict((practice.long_term or {}).get("proof_chain") or {})
            proof_chain[f"transfer:{event.id}"] = {
                "event_id": event.id,
                "checkpoint_id": event.checkpoint_id,
                "kind": "high_confidence_transfer",
            }
            await _apply_patch(
                db, event, "practice",
                {"artifact_state": "passed", "assistance_level": "none"},
                "独立迁移任务形成实践证据",
                long_patch={"proof_chain": proof_chain},
            )
        return

    if et in {"tool_failed", "task_failed"}:
        await _apply_patch(
            db, event, "structure",
            {"current_blocker": p.get("message", "工具执行失败")},
            "工具失败形成当前阻塞",
        )


async def apply_semantic_observations(
    db: AsyncSession,
    event: EvidenceEvent,
    observations: Iterable[dict[str, Any]],
):
    """Apply validated LLM observations to short-term state only."""
    for observation in list(observations or [])[:5]:
        kernel_name = observation.get("kernel")
        patch = observation.get("short_term")
        if kernel_name not in KERNEL_NAMES or not isinstance(patch, dict):
            continue
        allowed_keys = SEMANTIC_MEMORY_KEYS[kernel_name]
        safe_patch = {
            str(key)[:80]: value for key, value in list(patch.items())[:8]
            if key in allowed_keys
        }
        if not safe_patch:
            continue
        await _apply_patch(
            db, event, kernel_name, safe_patch,
            str(observation.get("reason") or "Tutor 语义观察")[:500],
        )


async def create_attempt(
    db: AsyncSession,
    *,
    learner_id: int | None = None,
    checkpoint_id: int,
    item_type: str,
    item_id: int | None,
    submission: dict,
    result: dict,
    assistance_level: str = "none",
    attempt_role: str = "original",
    status: str = "evaluated",
    client_submission_id: str | None = None,
) -> LearningAttempt:
    if learner_id is None:
        learner_id = (await get_default_learner(db)).id
    checkpoint = (await db.execute(
        select(Checkpoint)
        .join(Roadmap, Roadmap.id == Checkpoint.roadmap_id)
        .join(Project, Project.id == Roadmap.project_id)
        .where(
            Checkpoint.id == checkpoint_id,
            Project.learner_id == learner_id,
        )
    )).scalar_one_or_none()
    if not checkpoint:
        raise ValueError("检查点不属于当前学习者")
    roadmap = await db.get(Roadmap, checkpoint.roadmap_id) if checkpoint else None
    now = datetime.utcnow()
    attempt = LearningAttempt(
        learner_id=learner_id,
        project_id=roadmap.project_id if roadmap else None,
        checkpoint_id=checkpoint_id,
        item_type=item_type,
        item_id=item_id,
        status=status,
        submission=submission,
        result=result,
        assistance_level=assistance_level,
        attempt_role=attempt_role,
        client_submission_id=client_submission_id,
        submitted_at=now,
        evaluated_at=now,
    )
    db.add(attempt)
    await db.flush()
    return attempt


async def evaluate_checkpoint_status(
    db: AsyncSession, checkpoint_id: int, learner_id: int | None = None,
) -> str:
    checkpoint_query = select(Checkpoint).where(Checkpoint.id == checkpoint_id)
    if learner_id is not None:
        checkpoint_query = (
            checkpoint_query
            .join(Roadmap, Roadmap.id == Checkpoint.roadmap_id)
            .join(Project, Project.id == Roadmap.project_id)
            .where(Project.learner_id == learner_id)
        )
    checkpoint = (await db.execute(checkpoint_query)).scalar_one_or_none()
    if not checkpoint:
        return "not_started"
    progress = dict(checkpoint.progress or {})
    attempt_filters = [
            LearningAttempt.checkpoint_id == checkpoint_id,
            LearningAttempt.status == "evaluated",
    ]
    if learner_id is not None:
        attempt_filters.append(LearningAttempt.learner_id == learner_id)
    attempts = (await db.execute(select(LearningAttempt).where(*attempt_filters))).scalars().all()
    independent = [attempt for attempt in attempts if attempt.assistance_level == "none"]
    knowledge_verified = any(
        attempt.item_type == "concept" and bool((attempt.result or {}).get("correct"))
        for attempt in independent
    )
    practice_verified = any(
        attempt.item_type == "exercise"
        and int((attempt.result or {}).get("total") or 0) > 0
        and int((attempt.result or {}).get("passed") or 0) == int((attempt.result or {}).get("total") or 0)
        for attempt in independent
    )
    transfer_filters = [
        EvidenceEvent.checkpoint_id == checkpoint_id,
        EvidenceEvent.event_type == "transfer_attempt_evaluated",
        EvidenceEvent.confidence >= 0.9,
    ]
    if learner_id is not None:
        transfer_filters.append(EvidenceEvent.learner_id == learner_id)
    transfer = (await db.execute(select(EvidenceEvent).where(*transfer_filters))).scalars().all()
    transfer_verified = any(
        bool((event.payload or {}).get("passed"))
        and (event.payload or {}).get("assistance_level", "none") == "none"
        for event in transfer
    )
    lecture = (await db.execute(
        select(Lecture.id).where(Lecture.checkpoint_id == checkpoint_id)
    )).scalar_one_or_none()

    if (knowledge_verified and practice_verified) or transfer_verified:
        checkpoint.learning_status = "completed"
        checkpoint.completed = True
    elif checkpoint.legacy_completed:
        checkpoint.learning_status = "verification_due"
    elif lecture or progress or attempts:
        checkpoint.learning_status = "in_progress"
    else:
        checkpoint.learning_status = checkpoint.learning_status or "not_started"
    return checkpoint.learning_status


async def get_kernel_projection(db: AsyncSession, learner_id: int | None = None) -> dict:
    if learner_id is None:
        learner_id = (await get_default_learner(db)).id
    await ensure_kernel_states(db, learner_id)
    states = (await db.execute(
        select(KernelState).where(KernelState.learner_id == learner_id)
    )).scalars().all()
    archives = (await db.execute(select(MemoryArchive).where(
        MemoryArchive.learner_id == learner_id,
        MemoryArchive.status == "archived",
    ))).scalars().all()
    archived_paths = {
        (item.kernel_name, item.memory_scope, item.memory_key) for item in archives
    }
    now = datetime.utcnow()
    result = {}
    from app.services.memory_graph import active_module_claims, recent_atomic_facts
    for state in states:
        short = dict(state.short_term or {})
        long = dict(state.long_term or {})
        for kernel_name, scope, key in archived_paths:
            if kernel_name != state.kernel_name:
                continue
            (short if scope == "short_term" else long).pop(key, None)
        if state.kernel_name == "human" and short.get("transient_expires_at"):
            try:
                if datetime.fromisoformat(short["transient_expires_at"]) < now:
                    for key in ("affect", "cognitive_load", "attention", "frustration"):
                        short.pop(key, None)
            except (TypeError, ValueError):
                pass
        recent_facts = await recent_atomic_facts(db, learner_id, state.kernel_name)
        module_claims = await active_module_claims(
            db, learner_id, kernel_name=state.kernel_name, limit=30,
        )
        if recent_facts:
            short["memory_graph_recent_facts"] = recent_facts
        if module_claims:
            long["memory_graph_claims"] = module_claims
        result[state.kernel_name] = {
            "short_term": short,
            "long_term": long,
            "confidence": state.confidence or 0.0,
        }
    for kernel_name in KERNEL_NAMES:
        result.setdefault(kernel_name, {
            "short_term": {}, "long_term": {}, "confidence": 0.0,
        })

    # Historical versions stored goals under structure. Keep the evidence but
    # expose it through the canonical value dimension from now on.
    for scope in ("short_term", "long_term"):
        legacy_goal = result["structure"][scope].pop("current_goal", None)
        if legacy_goal and "current_goal" not in result["value"][scope]:
            result["value"][scope]["current_goal"] = legacy_goal

    # Apply archive paths again after canonicalization so a newly archived
    # value:current_goal does not reappear from a legacy structure row.
    for kernel_name, scope, key in archived_paths:
        result.get(kernel_name, {}).get(scope, {}).pop(key, None)
    return result


async def get_state_summary(
    db: AsyncSession,
    project_id: int | None = None,
    checkpoint_id: int | None = None,
    *,
    learner_id: int | None = None,
) -> dict:
    if learner_id is None:
        learner_id = (await get_default_learner(db)).id
    projection = await get_kernel_projection(db, learner_id)
    structure = projection.get("structure", {}).get("short_term", {})
    value = projection.get("value", {}).get("short_term", {})
    active_project_id = project_id or structure.get("active_project_id")
    active_checkpoint_id = checkpoint_id or structure.get("active_checkpoint_id")
    project = (await db.execute(select(Project).where(
        Project.id == active_project_id, Project.learner_id == learner_id,
    ))).scalar_one_or_none() if active_project_id else None
    if not project:
        active_project_id = None
    checkpoint = (await db.execute(
        select(Checkpoint)
        .join(Roadmap, Roadmap.id == Checkpoint.roadmap_id)
        .join(Project, Project.id == Roadmap.project_id)
        .where(
            Checkpoint.id == active_checkpoint_id,
            Project.learner_id == learner_id,
        )
    )).scalar_one_or_none() if active_checkpoint_id else None
    counts = {"total": 0, "completed": 0, "verification_due": 0}
    if active_project_id:
        rows = (await db.execute(
            select(Checkpoint.learning_status, func.count(Checkpoint.id))
            .join(Roadmap, Roadmap.id == Checkpoint.roadmap_id)
            .where(Roadmap.project_id == active_project_id, Checkpoint.archived.is_(False))
            .group_by(Checkpoint.learning_status)
        )).all()
        for status, count in rows:
            counts["total"] += count
            if status == "completed":
                counts["completed"] = count
            elif status == "verification_due":
                counts["verification_due"] = count
    stage = "自由学习"
    if checkpoint:
        stage = checkpoint.learning_status or "in_progress"
    elif project:
        stage = "项目学习"
    return {
        "stage": stage,
        "active_project": {"id": project.id, "name": project.name} if project else None,
        "active_checkpoint": {
            "id": checkpoint.id, "title": checkpoint.title,
            "status": checkpoint.learning_status or "not_started",
        } if checkpoint else None,
        "progress": counts,
        "blocker": structure.get("current_blocker", ""),
        "current_goal": (
            value.get("current_goal")
            or value.get("current_priority")
            or value.get("goal_candidate")
            or ""
        ),
    }
