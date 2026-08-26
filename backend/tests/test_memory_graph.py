import asyncio
import uuid
from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db.database import async_session, init_db
from app.main import app
from app.models.learning import (
    EvidenceEvent,
    Learner,
    MemoryClaim,
    MemoryEdge,
    MemoryFact,
    MemoryModule,
    MemoryNode,
    MemorySynthesisRun,
)
from app.models.project import Checkpoint, Project, Roadmap
from app.services.learning_runtime import get_kernel_projection, record_event
from app.services.memory_graph import backfill_memory_graph, input_fingerprint
from app.services.memory_worker import (
    SynthesisClaimDraft,
    SynthesisDraft,
    _validate_draft,
    process_synthesis_run,
)


def _key(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def test_event_dual_write_creates_cross_kernel_facts_and_sparse_edges():
    async def scenario():
        await init_db()
        async with async_session() as db:
            learner = Learner(key=_key("memory-ledger"), display_name="Memory Ledger")
            db.add(learner)
            await db.flush()
            event = await record_event(
                db,
                learner_id=learner.id,
                event_type="registration_profile_completed",
                source="registration",
                payload={
                    "background": "Python",
                    "weekly_hours": 6,
                    "preferred_modes": ["practice"],
                    "career_goal": "机器学习工程师",
                    "career_goal_status": "confirmed",
                },
                provenance={"self_report": True},
            )
            await db.commit()
            fact_nodes = list((await db.execute(
                select(MemoryNode)
                .join(MemoryFact, MemoryFact.node_id == MemoryNode.id)
                .where(MemoryNode.learner_id == learner.id)
            )).scalars().all())
            same_event = list((await db.execute(select(MemoryEdge).where(
                MemoryEdge.learner_id == learner.id,
                MemoryEdge.relation_type == "SAME_EVENT",
            ))).scalars().all())
            await backfill_memory_graph(db)
            after_first = await db.scalar(select(func.count(MemoryNode.id)).where(
                MemoryNode.learner_id == learner.id,
            ))
            await backfill_memory_graph(db)
            await db.commit()
            after_second = await db.scalar(select(func.count(MemoryNode.id)).where(
                MemoryNode.learner_id == learner.id,
            ))
            return event, fact_nodes, same_event, after_first, after_second

    event, fact_nodes, same_event, after_first, after_second = asyncio.run(scenario())
    assert event.learner_seq == 1
    assert event.actor_type == "learner"
    assert event.occurred_at and event.created_at
    assert {node.kernel_name for node in fact_nodes} >= {"knowledge", "human", "value"}
    assert any(
        next(node for node in fact_nodes if node.id == edge.source_node_id).kernel_name
        != next(node for node in fact_nodes if node.id == edge.target_node_id).kernel_name
        for edge in same_event
    )
    assert after_first == after_second


def test_same_kernel_synthesis_has_complete_evidence_path_and_consumes_once():
    async def scenario():
        await init_db()
        async with async_session() as db:
            learner = Learner(key=_key("memory-synthesis"), display_name="Memory Synthesis")
            db.add(learner)
            await db.flush()
            project = Project(learner_id=learner.id, name="知识验证")
            db.add(project)
            await db.flush()
            roadmap = Roadmap(project_id=project.id, raw_json={})
            db.add(roadmap)
            await db.flush()
            checkpoint = Checkpoint(roadmap_id=roadmap.id, title="图模型", order=1)
            db.add(checkpoint)
            await db.flush()
            for item_id in (101, 102):
                await record_event(
                    db,
                    learner_id=learner.id,
                    project_id=project.id,
                    checkpoint_id=checkpoint.id,
                    event_type="concept_attempt_evaluated",
                    source="grader",
                    payload={
                        "item_id": item_id,
                        "concept_id": "graph-memory",
                        "question": f"题目 {item_id}",
                        "correct": True,
                        "independent": True,
                    },
                    confidence=0.95,
                )
            run = (await db.execute(select(MemorySynthesisRun).where(
                MemorySynthesisRun.learner_id == learner.id,
                MemorySynthesisRun.kernel_name == "knowledge",
                MemorySynthesisRun.subject_key == "concept:graph-memory",
            ).order_by(MemorySynthesisRun.id.desc()))).scalars().first()
            assert run is not None
            run.due_at = datetime.utcnow()
            await db.commit()
            run_id = run.id

        completed = await process_synthesis_run(run_id)
        assert completed and completed.status == "completed"
        async with async_session() as db:
            module = (await db.execute(
                select(MemoryModule).where(MemoryModule.synthesis_run_id == run_id)
            )).scalar_one()
            claims = list((await db.execute(select(MemoryClaim).where(
                MemoryClaim.module_node_id == module.node_id,
            ))).scalars().all())
            supports = list((await db.execute(select(MemoryEdge).where(
                MemoryEdge.target_node_id.in_([claim.node_id for claim in claims]),
                MemoryEdge.relation_type == "SUPPORTS",
            ))).scalars().all())
            facts = list((await db.execute(
                select(MemoryNode, MemoryFact)
                .join(MemoryFact, MemoryFact.node_id == MemoryNode.id)
                .where(MemoryFact.consumed_by_module_id == module.node_id)
            )).all())
            projection = await get_kernel_projection(db, learner.id)
            module_count_before = await db.scalar(select(func.count(MemoryModule.node_id)).where(
                MemoryModule.synthesis_run_id == run_id,
            ))
        await process_synthesis_run(run_id)
        async with async_session() as db:
            module_count_after = await db.scalar(select(func.count(MemoryModule.node_id)).where(
                MemoryModule.synthesis_run_id == run_id,
            ))
            return module, claims, supports, facts, projection, module_count_before, module_count_after

    module, claims, supports, facts, projection, before, after = asyncio.run(scenario())
    assert module.immutable is True
    assert claims
    assert {edge.target_node_id for edge in supports} == {claim.node_id for claim in claims}
    assert all(node.kernel_name == "knowledge" for node, _ in facts)
    assert all(fact.consumption_status == "consumed" for _, fact in facts)
    assert projection["knowledge"]["long_term"]["memory_graph_claims"]
    assert before == after == 1


def test_synthesis_validator_rejects_out_of_whitelist_and_unproven_mastery():
    run = MemorySynthesisRun(kernel_name="knowledge")
    node = MemoryNode(id=1, kernel_name="knowledge")
    fact = MemoryFact(node_id=1, source_event_id=10, evidence_grade="exposure_only")
    event = EvidenceEvent(id=10, event_type="lecture_viewed")
    draft = SynthesisDraft(
        summary="错误的合成",
        claims=[SynthesisClaimDraft(
            text="学习者已经掌握图记忆",
            predicate="knowledge.mastery",
            value=True,
            evidence_fact_ids=[1, 999],
        )],
    )
    errors = _validate_draft(run, draft, [(node, fact, event)])
    assert "claim_0_references_outside_whitelist" in errors
    assert "claim_0_insufficient_mastery_evidence" in errors


def test_cross_kernel_run_is_rejected_without_consuming_facts():
    async def scenario():
        await init_db()
        async with async_session() as db:
            learner = Learner(key=_key("memory-cross-kernel"), display_name="Cross Kernel")
            db.add(learner)
            await db.flush()
            await record_event(
                db,
                learner_id=learner.id,
                event_type="registration_profile_completed",
                source="registration",
                payload={"background": "零基础", "weekly_hours": 4, "preferred_modes": ["project"]},
                provenance={"self_report": True},
            )
            rows = list((await db.execute(
                select(MemoryNode, MemoryFact)
                .join(MemoryFact, MemoryFact.node_id == MemoryNode.id)
                .where(MemoryNode.learner_id == learner.id)
            )).all())
            human = next(row for row in rows if row[0].kernel_name == "human")
            knowledge = next(row for row in rows if row[0].kernel_name == "knowledge")
            ids = [human[0].id, knowledge[0].id]
            run = MemorySynthesisRun(
                learner_id=learner.id,
                kernel_name="human",
                subject_key=human[0].subject_key,
                status="queued",
                trigger_reason="test_cross_kernel",
                candidate_fact_ids=ids,
                input_fingerprint=input_fingerprint("human", human[0].subject_key, ids),
                due_at=datetime.utcnow(),
            )
            db.add(run)
            await db.commit()
            run_id = run.id
        result = await process_synthesis_run(run_id)
        async with async_session() as db:
            facts = list((await db.execute(select(MemoryFact).where(
                MemoryFact.node_id.in_(ids),
            ))).scalars().all())
        return result, facts

    result, facts = asyncio.run(scenario())
    assert result and result.status == "stale"
    assert all(fact.consumption_status == "eligible" for fact in facts)


def test_model_failure_releases_fact_reservations(monkeypatch):
    async def fail_model(*_args, **_kwargs):
        raise TimeoutError("synthetic timeout")

    monkeypatch.setattr("app.services.memory_worker._model_draft", fail_model)

    async def scenario():
        await init_db()
        async with async_session() as db:
            learner = Learner(key=_key("memory-failure"), display_name="Failure")
            db.add(learner)
            await db.flush()
            await record_event(
                db,
                learner_id=learner.id,
                event_type="user_message",
                source="user",
                payload={"text": "我想学习可解释记忆"},
                provenance={"self_report": True},
            )
            fact_node, fact = (await db.execute(
                select(MemoryNode, MemoryFact)
                .join(MemoryFact, MemoryFact.node_id == MemoryNode.id)
                .where(MemoryNode.learner_id == learner.id, MemoryNode.kernel_name == "value")
                .limit(1)
            )).one()
            run = MemorySynthesisRun(
                learner_id=learner.id,
                kernel_name="value",
                subject_key=fact_node.subject_key,
                status="queued",
                trigger_reason="failure_test",
                candidate_fact_ids=[fact_node.id],
                input_fingerprint=input_fingerprint("value", fact_node.subject_key, [fact_node.id]),
                due_at=datetime.utcnow(),
            )
            db.add(run)
            await db.commit()
            run_id, fact_id = run.id, fact.node_id
        result = await process_synthesis_run(run_id)
        async with async_session() as db:
            released = await db.get(MemoryFact, fact_id)
        return result, released

    result, fact = asyncio.run(scenario())
    assert result and result.status == "failed"
    assert fact.consumption_status == "eligible"
    assert fact.reservation_run_id is None


def test_memory_api_isolated_and_feedback_appends_history():
    username = _key("memory-api")
    with TestClient(app) as owner, TestClient(app) as outsider:
        registration = {
            "password": "learnflow-pass-123",
            "display_name": "Memory Owner",
            "education_stage": "undergraduate",
            "background": "Python",
            "focus_areas": ["人工智能"],
            "weekly_hours": 6,
            "preferred_modes": ["practice"],
            "career_goal": "学习科学研究者",
            "career_goal_status": "confirmed",
        }
        owner_result = owner.post("/api/auth/register", json={"username": username, **registration})
        outsider_result = outsider.post("/api/auth/register", json={
            "username": _key("memory-outsider"), **registration,
        })
        assert owner_result.status_code == outsider_result.status_code == 200
        learner_id = owner_result.json()["learner_id"]

        async def finish_immediate_runs():
            async with async_session() as db:
                run_ids = list((await db.execute(select(MemorySynthesisRun.id).where(
                    MemorySynthesisRun.learner_id == learner_id,
                    MemorySynthesisRun.status == "queued",
                ))).scalars().all())
            for run_id in run_ids:
                await process_synthesis_run(run_id)

        asyncio.run(finish_immediate_runs())
        claims = owner.get("/api/memory/graph", params={"node_types": "claim"})
        assert claims.status_code == 200
        claim_nodes = claims.json()["nodes"]
        assert claim_nodes
        claim = claim_nodes[0]
        assert outsider.get(f"/api/memory/nodes/{claim['id']}").status_code == 404

        detail_before = owner.get(f"/api/memory/nodes/{claim['id']}").json()
        feedback = owner.post(f"/api/memory/claims/{claim['id']}/feedback", json={
            "action": "correct",
            "correction": "我偏好先动手再阅读解释",
            "reason": "原声明粒度太粗",
        })
        assert feedback.status_code == 200
        assert feedback.json()["event_id"]
        detail_after = owner.get(f"/api/memory/nodes/{claim['id']}").json()
        assert detail_after["text"] == detail_before["text"]
        correction_fact = owner.get(f"/api/memory/nodes/{feedback.json()['fact_id']}").json()
        assert correction_fact["source_event"]["event_type"] == "memory_correction_added"
        assert any(item["relation"] == "CONTRADICTS" for item in correction_fact["relations"])
