from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models.learning import (
    EvidenceEvent,
    MemoryClaim,
    MemoryEdge,
    MemoryFact,
    MemoryModule,
    MemoryNode,
    MemorySynthesisRun,
)
from app.services.auth import CurrentLearner, get_current_learner
from app.services.learning_runtime import record_event
from app.services.memory_graph import KERNEL_NAMES, NODE_TYPES, RELATION_TYPES, _add_edge


router = APIRouter(prefix="/memory", tags=["Inspectable Memory"])


class ClaimFeedbackRequest(BaseModel):
    action: Literal["confirm", "correct", "retract"]
    correction: str = Field(default="", max_length=2000)
    reason: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def correction_required(self):
        if self.action == "correct" and not self.correction.strip():
            raise ValueError("纠正声明时必须填写更正内容")
        return self


def _csv(value: str | None, allowed: tuple[str, ...]) -> list[str]:
    if not value:
        return []
    items = [item.strip() for item in value.split(",") if item.strip()]
    invalid = set(items) - set(allowed)
    if invalid:
        raise HTTPException(400, f"不支持的过滤值: {', '.join(sorted(invalid))}")
    return items


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


async def _serialize_nodes(db: AsyncSession, nodes: list[MemoryNode]) -> list[dict]:
    ids = [node.id for node in nodes]
    if not ids:
        return []
    facts = {
        item.node_id: item for item in (await db.execute(select(MemoryFact).where(
            MemoryFact.node_id.in_(ids),
        ))).scalars().all()
    }
    modules = {
        item.node_id: item for item in (await db.execute(select(MemoryModule).where(
            MemoryModule.node_id.in_(ids),
        ))).scalars().all()
    }
    claims = {
        item.node_id: item for item in (await db.execute(select(MemoryClaim).where(
            MemoryClaim.node_id.in_(ids),
        ))).scalars().all()
    }
    result = []
    for node in nodes:
        item = {
            "id": node.id,
            "type": node.node_type,
            "kernel": node.kernel_name,
            "subject": node.subject_key,
            "text": node.text,
            "payload": node.payload or {},
            "confidence": node.confidence or 0.0,
            "status": node.status,
            "valid_from": _iso(node.valid_from),
            "valid_to": _iso(node.valid_to),
            "occurred_at": _iso(node.occurred_at),
            "created_at": _iso(node.created_at),
        }
        fact = facts.get(node.id)
        if fact:
            item["fact"] = {
                "source_event_id": fact.source_event_id,
                "source_mutation_id": fact.source_mutation_id,
                "predicate": fact.predicate,
                "value": fact.object_value,
                "evidence_grade": fact.evidence_grade,
                "consumption_status": fact.consumption_status,
                "consumed_by_module_id": fact.consumed_by_module_id,
                "project_id": fact.project_id,
                "checkpoint_id": fact.checkpoint_id,
                "session_id": fact.session_id,
            }
        module = modules.get(node.id)
        if module:
            item["module"] = {
                "synthesis_run_id": module.synthesis_run_id,
                "module_type": module.module_type,
                "summary": module.summary,
                "time_start": _iso(module.time_start),
                "time_end": _iso(module.time_end),
                "immutable": bool(module.immutable),
            }
        claim = claims.get(node.id)
        if claim:
            item["claim"] = {
                "module_id": claim.module_node_id,
                "predicate": claim.predicate,
                "value": claim.value,
                "verification_status": claim.verification_status,
            }
        result.append(item)
    return result


async def _graph_payload(
    db: AsyncSession,
    learner_id: int,
    *,
    start: datetime | None,
    end: datetime | None,
    kernels: list[str],
    node_types: list[str],
    relations: list[str],
    statuses: list[str],
    project_id: int | None,
    subject: str | None,
    after_id: int | None,
    limit: int,
) -> dict:
    query = select(MemoryNode).where(MemoryNode.learner_id == learner_id)
    if start:
        query = query.where(MemoryNode.occurred_at >= start)
    if end:
        query = query.where(MemoryNode.occurred_at <= end)
    if kernels:
        query = query.where(MemoryNode.kernel_name.in_(kernels))
    if node_types:
        query = query.where(MemoryNode.node_type.in_(node_types))
    if statuses:
        query = query.where(MemoryNode.status.in_(statuses))
    if subject:
        query = query.where(MemoryNode.subject_key.contains(subject))
    if after_id:
        query = query.where(MemoryNode.id > after_id)
    if project_id is not None:
        fact_nodes = select(MemoryFact.node_id).where(MemoryFact.project_id == project_id)
        query = query.where(or_(
            MemoryNode.id.in_(fact_nodes),
            MemoryNode.subject_key == f"project:{project_id}",
            MemoryNode.payload["project_id"].as_integer() == project_id,
        ))
    nodes = list((await db.execute(
        query.order_by(MemoryNode.occurred_at.asc(), MemoryNode.id.asc()).limit(limit + 1)
    )).scalars().all())
    has_more = len(nodes) > limit
    nodes = nodes[:limit]
    node_ids = [node.id for node in nodes]
    edge_query = select(MemoryEdge).where(
        MemoryEdge.learner_id == learner_id,
        MemoryEdge.source_node_id.in_(node_ids),
        MemoryEdge.target_node_id.in_(node_ids),
    )
    if relations:
        edge_query = edge_query.where(MemoryEdge.relation_type.in_(relations))
    edges = list((await db.execute(
        edge_query.order_by(MemoryEdge.created_at.asc(), MemoryEdge.id.asc())
    )).scalars().all()) if node_ids else []
    return {
        "nodes": await _serialize_nodes(db, nodes),
        "edges": [{
            "id": edge.id,
            "source": edge.source_node_id,
            "target": edge.target_node_id,
            "relation": edge.relation_type,
            "origin": edge.origin,
            "confidence": edge.confidence,
            "payload": edge.payload or {},
        } for edge in edges],
        "page": {
            "limit": limit,
            "has_more": has_more,
            "next_after_id": nodes[-1].id if has_more and nodes else None,
        },
    }


@router.get("/graph")
async def get_memory_graph(
    start: datetime | None = None,
    end: datetime | None = None,
    kernels: str | None = None,
    node_types: str | None = None,
    relations: str | None = None,
    statuses: str | None = None,
    project_id: int | None = None,
    subject: str | None = None,
    after_id: int | None = None,
    limit: int = Query(300, ge=1, le=300),
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    return await _graph_payload(
        db, current.learner.id,
        start=start, end=end,
        kernels=_csv(kernels, KERNEL_NAMES),
        node_types=_csv(node_types, NODE_TYPES),
        relations=_csv(relations, RELATION_TYPES),
        statuses=[item.strip() for item in statuses.split(",") if item.strip()] if statuses else [],
        project_id=project_id, subject=subject, after_id=after_id, limit=limit,
    )


@router.get("/timeline")
async def get_memory_timeline(
    start: datetime | None = None,
    end: datetime | None = None,
    kernels: str | None = None,
    after_id: int | None = None,
    limit: int = Query(100, ge=1, le=300),
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    payload = await _graph_payload(
        db, current.learner.id,
        start=start, end=end, kernels=_csv(kernels, KERNEL_NAMES),
        node_types=[], relations=[], statuses=[], project_id=None, subject=None,
        after_id=after_id, limit=limit,
    )
    payload.pop("edges", None)
    return payload


@router.get("/nodes/{node_id}")
async def get_memory_node(
    node_id: int,
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    node = (await db.execute(select(MemoryNode).where(
        MemoryNode.id == node_id,
        MemoryNode.learner_id == current.learner.id,
    ))).scalar_one_or_none()
    if not node:
        raise HTTPException(404, "Memory node not found")
    serialized = (await _serialize_nodes(db, [node]))[0]
    edges = (await db.execute(select(MemoryEdge).where(
        MemoryEdge.learner_id == current.learner.id,
        or_(MemoryEdge.source_node_id == node.id, MemoryEdge.target_node_id == node.id),
    ).order_by(MemoryEdge.created_at.asc()))).scalars().all()
    neighbor_ids = {
        edge.target_node_id if edge.source_node_id == node.id else edge.source_node_id
        for edge in edges
    }
    neighbors = list((await db.execute(select(MemoryNode).where(
        MemoryNode.learner_id == current.learner.id,
        MemoryNode.id.in_(neighbor_ids),
    ))).scalars().all()) if neighbor_ids else []
    serialized["relations"] = [{
        "edge_id": edge.id,
        "direction": "out" if edge.source_node_id == node.id else "in",
        "relation": edge.relation_type,
        "node_id": edge.target_node_id if edge.source_node_id == node.id else edge.source_node_id,
        "origin": edge.origin,
        "confidence": edge.confidence,
    } for edge in edges]
    serialized["neighbors"] = await _serialize_nodes(db, neighbors)

    fact = await db.get(MemoryFact, node.id)
    if fact:
        event = (await db.execute(select(EvidenceEvent).where(
            EvidenceEvent.id == fact.source_event_id,
            EvidenceEvent.learner_id == current.learner.id,
        ))).scalar_one_or_none()
        if event:
            serialized["source_event"] = {
                "id": event.id,
                "learner_seq": event.learner_seq,
                "event_type": event.event_type,
                "source": event.source,
                "actor_type": event.actor_type,
                "payload": event.payload or {},
                "provenance": event.provenance or {},
                "confidence": event.confidence,
                "occurred_at": _iso(event.occurred_at),
                "recorded_at": _iso(event.created_at),
            }
    module = await db.get(MemoryModule, node.id)
    if module:
        claim_nodes = list((await db.execute(
            select(MemoryNode)
            .join(MemoryClaim, MemoryClaim.node_id == MemoryNode.id)
            .where(MemoryClaim.module_node_id == node.id)
            .order_by(MemoryClaim.claim_ordinal.asc())
        )).scalars().all())
        serialized["claims"] = await _serialize_nodes(db, claim_nodes)
        run = await db.get(MemorySynthesisRun, module.synthesis_run_id) if module.synthesis_run_id else None
        if run:
            serialized["synthesis_run"] = _run_view(run)
    claim = await db.get(MemoryClaim, node.id)
    if claim:
        support_edges = (await db.execute(select(MemoryEdge).where(
            MemoryEdge.learner_id == current.learner.id,
            MemoryEdge.target_node_id == node.id,
            MemoryEdge.relation_type == "SUPPORTS",
        ))).scalars().all()
        fact_ids = [edge.source_node_id for edge in support_edges]
        evidence_nodes = list((await db.execute(select(MemoryNode).where(
            MemoryNode.learner_id == current.learner.id,
            MemoryNode.id.in_(fact_ids),
        ))).scalars().all()) if fact_ids else []
        serialized["evidence_facts"] = await _serialize_nodes(db, evidence_nodes)
    return serialized


def _run_view(run: MemorySynthesisRun) -> dict:
    return {
        "id": run.id,
        "kernel": run.kernel_name,
        "subject": run.subject_key,
        "status": run.status,
        "trigger_reason": run.trigger_reason,
        "candidate_fact_ids": run.candidate_fact_ids or [],
        "input_fingerprint": run.input_fingerprint,
        "prompt_version": run.prompt_version,
        "model_name": run.model_name,
        "raw_output": run.raw_output or {},
        "validation_errors": run.validation_errors or [],
        "usage": run.usage or {},
        "attempt_count": run.attempt_count or 0,
        "due_at": _iso(run.due_at),
        "started_at": _iso(run.started_at),
        "finished_at": _iso(run.finished_at),
        "created_at": _iso(run.created_at),
    }


@router.get("/consolidations")
async def get_consolidations(
    status: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    query = select(MemorySynthesisRun).where(
        MemorySynthesisRun.learner_id == current.learner.id,
    )
    if status:
        query = query.where(MemorySynthesisRun.status == status)
    runs = (await db.execute(
        query.order_by(MemorySynthesisRun.created_at.desc()).limit(limit)
    )).scalars().all()
    return {"runs": [_run_view(run) for run in runs]}


@router.post("/claims/{claim_id}/feedback")
async def submit_claim_feedback(
    claim_id: int,
    data: ClaimFeedbackRequest,
    current: CurrentLearner = Depends(get_current_learner),
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(
        select(MemoryNode, MemoryClaim)
        .join(MemoryClaim, MemoryClaim.node_id == MemoryNode.id)
        .where(
            MemoryNode.id == claim_id,
            MemoryNode.learner_id == current.learner.id,
            MemoryNode.node_type == "claim",
        )
    )).first()
    if not row:
        raise HTTPException(404, "Memory claim not found")
    claim_node, claim = row
    event_type = {
        "confirm": "memory_correction_confirmed",
        "correct": "memory_correction_added",
        "retract": "memory_correction_retracted",
    }[data.action]
    payload = dict(claim_node.payload or {})
    event = await record_event(
        db,
        learner_id=current.learner.id,
        event_type=event_type,
        source="user",
        project_id=payload.get("project_id"),
        payload={
            "claim_id": claim_id,
            "module_id": claim.module_node_id,
            "kernel_name": claim_node.kernel_name,
            "memory_subject_key": claim_node.subject_key,
            "action": data.action,
            "correction": data.correction.strip(),
            "reason": data.reason.strip(),
            "previous_claim": claim_node.text,
        },
        confidence=1.0,
        provenance={"self_report": True, "append_only_feedback": True},
        client_event_id=f"claim-feedback:{claim_id}:{data.action}:{int(datetime.utcnow().timestamp() * 1000)}",
    )
    correction_fact = (await db.execute(
        select(MemoryNode)
        .join(MemoryFact, MemoryFact.node_id == MemoryNode.id)
        .where(MemoryFact.source_event_id == event.id)
        .order_by(MemoryNode.id.desc())
        .limit(1)
    )).scalar_one_or_none()
    if correction_fact:
        await _add_edge(
            db,
            learner_id=current.learner.id,
            source_node_id=correction_fact.id,
            target_node_id=claim_id,
            relation_type="SUPPORTS" if data.action == "confirm" else "CONTRADICTS",
            origin="learner_feedback",
            confidence=1.0,
            event_id=event.id,
        )
    if data.action == "retract":
        claim_node.status = "challenged"
    await db.commit()
    queued = (await db.execute(select(MemorySynthesisRun).where(
        MemorySynthesisRun.learner_id == current.learner.id,
        MemorySynthesisRun.kernel_name == claim_node.kernel_name,
        MemorySynthesisRun.subject_key == claim_node.subject_key,
        MemorySynthesisRun.status == "queued",
    ).order_by(MemorySynthesisRun.id.desc()).limit(1))).scalar_one_or_none()
    return {
        "event_id": event.id,
        "fact_id": correction_fact.id if correction_fact else None,
        "queued_consolidation_id": queued.id if queued else None,
        "status": "queued",
    }

