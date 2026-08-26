"""Learner State Discovery 模块测试：Reducer / 幂等 / scope 隔离 / 状态机 / API。

覆盖任务书第 12 节五核集成验收与第 14 节质量目标：
- 每类重要交互先形成 EvidenceEvent 再产生 KernelMutation（before/after/version/reason/evidence ref）
- 幂等（同一 client_event_id 不重复计分）
- scope 隔离（learner / project）与 ownership
- 自适应选题（新投影影响下一轮）
- 提前结束 / 证据不足 / 连续跳过 / 含糊回答 / 辅助后答对 / 开放题不可靠评分
- 状态被后续证据纠正
- 记忆图谱派生与追溯
"""

import json
import os
import tempfile
import threading
import unittest
from pathlib import Path

from backend.learner_discovery import bank
from backend.learner_discovery.models import (
    EvidenceEvent,
    Scope,
)
from backend.learner_discovery.reducer import reduce_event
from backend.learner_discovery.kernels import default_kernel_state
from backend.learner_discovery.registry import EVENT_REGISTRY, KERNELS
from backend.learner_discovery.session import DiscoveryError, DiscoveryService
from backend.learner_discovery.store import DiscoveryStore
from backend.server import Settings, create_server

REQUIRED_EVENT_META = (
    "event_id", "description", "capability", "tool", "agent", "workbench",
    "scope", "evidence_role", "confidence", "kernel_targets", "idempotency_key",
    "provenance", "long_term_eligible", "reducer_rule",
)


def make_event(event_type, learner="STU-1", project="P-1", session="S-1", **payload):
    return EvidenceEvent(
        event_type=event_type,
        scope=Scope(learner_id=learner, project_id=project, session_id=session),
        payload=payload,
        kernel_targets=EVENT_REGISTRY[event_type]["kernel_targets"],
        evidence_role=EVENT_REGISTRY[event_type]["evidence_role"],
        confidence=EVENT_REGISTRY[event_type]["confidence"],
        client_event_id=f"{learner}-{event_type}-{session}-{abs(hash((event_type, str(payload)) ))}",
    )


def answer_current(svc, session_id, learner_id, client_event_id, correct=True, action="answer", assisted=False, transfer=False):
    view = svc.get_session(session_id, learner_id)
    ni = view["next_interaction"]
    assert ni["kind"] == "question", f"期望 question，实际 {ni['kind']}"
    q = bank.question_by_id(ni["content"]["question_id"])
    if correct:
        selected = q["answer"]
    else:
        selected = next(k for k in q["options"] if k != q["answer"])
    return svc.answer(session_id, learner_id, {
        "action": action,
        "selected": selected,
        "assisted": assisted,
        "transfer": transfer,
        "client_event_id": client_event_id,
    })


class RegistryAndReducerTests(unittest.TestCase):
    def test_registry_events_are_complete(self):
        self.assertGreaterEqual(len(EVENT_REGISTRY), 10)
        for event_type, meta in EVENT_REGISTRY.items():
            for key in REQUIRED_EVENT_META:
                self.assertIn(key, meta, f"{event_type} 缺少 {key}")
            for kernel in meta["kernel_targets"]:
                self.assertIn(kernel, KERNELS, f"{event_type} 目标 Kernel 非法：{kernel}")

    def test_reducer_correct_upgrades_and_practice(self):
        event = make_event("answer_submitted", question_id="D-CLASS-1",
                           knowledge_point_id="KN_JAVA_CLASS", correct=True, assisted=False)
        new_states, mutations = reduce_event(
            event,
            {"knowledge": default_kernel_state("knowledge"),
             "practice": default_kernel_state("practice")},
        )
        kc = new_states["knowledge"]["kcs"]["KN_JAVA_CLASS"]
        self.assertEqual(kc["status"], "verified_once")
        self.assertEqual(kc["evidence"]["distinct_independent_correct"], 1)
        self.assertEqual(new_states["practice"]["independence"]["KN_JAVA_CLASS"]["level"], "applied")
        kernels = {m["kernel"] for m in mutations}
        self.assertEqual(kernels, {"knowledge", "practice"})
        for mutation in mutations:
            self.assertTrue(mutation["reason"])
            self.assertEqual(mutation["evidence_ref"], event.event_id)
            self.assertIn("before", mutation)
            self.assertIn("after", mutation)

    def test_reducer_second_distinct_correct_stable(self):
        states = {"knowledge": default_kernel_state("knowledge"),
                  "practice": default_kernel_state("practice")}
        for i, qid in enumerate(["D-CLASS-1", "D-CLASS-2"]):
            event = make_event("answer_submitted", question_id=qid,
                               knowledge_point_id="KN_JAVA_CLASS", correct=True, assisted=False)
            states, _ = reduce_event(event, states)
        kc = states["knowledge"]["kcs"]["KN_JAVA_CLASS"]
        self.assertEqual(kc["status"], "stable")

    def test_reducer_wrong_downgrades_and_misconception(self):
        states = {"knowledge": default_kernel_state("knowledge"),
                  "practice": default_kernel_state("practice")}
        for qid in ["D-CLASS-1", "D-CLASS-2"]:
            event = make_event("answer_submitted", question_id=qid,
                               knowledge_point_id="KN_JAVA_CLASS", correct=True, assisted=False)
            states, _ = reduce_event(event, states)
        wrong = make_event("answer_submitted", question_id="D-CLASS-1",
                           knowledge_point_id="KN_JAVA_CLASS", correct=False,
                           assisted=False, misconception_id="CLASS_NEW_SYNTAX")
        states, _ = reduce_event(wrong, states)
        kc = states["knowledge"]["kcs"]["KN_JAVA_CLASS"]
        # 单次失误：stable 降级为 verified_once（重复错误模式才降为 candidate）
        self.assertEqual(kc["status"], "verified_once")
        self.assertEqual(len(kc["misconception_candidates"]), 1)
        self.assertEqual(kc["misconception_candidates"][0]["misconception_id"], "CLASS_NEW_SYNTAX")
        # 重复错误模式 -> candidate
        wrong2 = make_event("answer_submitted", question_id="D-CLASS-2",
                            knowledge_point_id="KN_JAVA_CLASS", correct=False,
                            assisted=False, misconception_id="CLASS_NEW_SYNTAX")
        states, _ = reduce_event(wrong2, states)
        kc = states["knowledge"]["kcs"]["KN_JAVA_CLASS"]
        self.assertEqual(kc["status"], "candidate")

    def test_reducer_skip_does_not_change_status(self):
        event = make_event("answer_skipped", question_id="D-CLASS-1",
                           knowledge_point_id="KN_JAVA_CLASS", question_index=0)
        states = {"knowledge": default_kernel_state("knowledge"),
                  "structure": default_kernel_state("structure")}
        new_states, _ = reduce_event(event, states)
        kc = new_states["knowledge"]["kcs"]["KN_JAVA_CLASS"]
        self.assertEqual(kc["status"], "untested")
        self.assertEqual(kc["evidence"]["skipped"], 1)

    def test_reducer_assisted_does_not_upgrade(self):
        event = make_event("assisted_success", question_id="D-CLASS-1",
                           knowledge_point_id="KN_JAVA_CLASS", correct=True, assisted=True)
        states = {"knowledge": default_kernel_state("knowledge"),
                  "practice": default_kernel_state("practice")}
        new_states, _ = reduce_event(event, states)
        kc = new_states["knowledge"]["kcs"]["KN_JAVA_CLASS"]
        self.assertEqual(kc["status"], "candidate")
        self.assertEqual(kc["evidence"]["assisted"], 1)
        self.assertEqual(new_states["practice"]["independence"]["KN_JAVA_CLASS"]["level"], "assisted")

    def test_reducer_goal_confirm_writes_value_and_structure(self):
        event = make_event("goal_confirmed", goal_id="GOAL-JAVA-001",
                           goal_label="完成 Java 面向对象成绩管理实训", text="想学Java")
        states = {"value": default_kernel_state("value"),
                  "structure": default_kernel_state("structure")}
        new_states, mutations = reduce_event(event, states)
        self.assertEqual(new_states["value"]["confirmed_goal"], "GOAL-JAVA-001")
        kernels = {m["kernel"] for m in mutations}
        self.assertEqual(kernels, {"value", "structure"})

    def test_reducer_preference_writes_human(self):
        event = make_event("preference_stated", mode="example_driven", kind="preference")
        new_states, _ = reduce_event(event, {"human": default_kernel_state("human")})
        self.assertEqual(new_states["human"]["preferences"][0]["mode"], "example_driven")
        self.assertEqual(new_states["human"]["preferences"][0]["status"], "candidate")

    def test_store_idempotent_client_event_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = DiscoveryStore(Path(tmp) / "t.db")
            event = make_event("answer_submitted", question_id="D-CLASS-1",
                               knowledge_point_id="KN_JAVA_CLASS", correct=True, assisted=False)
            self.assertTrue(store.save_event(event))
            duplicate = EvidenceEvent(
                event_type="answer_submitted",
                scope=event.scope,
                payload=event.payload,
                kernel_targets=event.kernel_targets,
                evidence_role=event.evidence_role,
                confidence=event.confidence,
                client_event_id=event.client_event_id,
            )
            self.assertFalse(store.save_event(duplicate))
            self.assertEqual(len(store.list_events("STU-1")), 1)

    def test_unregistered_event_rejected(self):
        event = EvidenceEvent(
            event_type="no_such_event",
            scope=Scope(learner_id="STU-1"),
            payload={},
            kernel_targets=["knowledge"],
            evidence_role="graded_attempt",
            confidence=1.0,
            client_event_id="unregistered-1",
        )
        with self.assertRaises(KeyError):
            reduce_event(event, {"knowledge": default_kernel_state("knowledge")})


def new_service():
    directory = tempfile.TemporaryDirectory()
    service = DiscoveryService(Path(directory.name) / "discovery.db")
    return service, directory


class DiscoveryServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.svc = DiscoveryService(Path(self.tmp.name) / "discovery.db")
        self.learner = "STU-DISC-001"

    def tearDown(self):
        self.tmp.cleanup()

    def create(self, learner=None, project="PROJ-D-1", goal_candidate="想学Java面向对象", **kwargs):
        return self.svc.create_session(
            learner_id=learner or self.learner,
            project_id=project,
            goal_candidate=goal_candidate,
            desired_outcome="独立完成成绩管理实训",
            seed=20260811,
            **kwargs,
        )

    def confirm(self, session_id, learner=None):
        return self.svc.answer(session_id, learner or self.learner, {
            "action": "confirm",
            "goal_id": "GOAL-JAVA-001",
            "client_event_id": f"confirm-{session_id}",
        })

    def test_create_then_clarification_then_confirm(self):
        view = self.create()
        self.assertEqual(view["next_interaction"]["kind"], "clarification")
        session_id = view["session"]["session_id"]
        result = self.confirm(session_id)
        self.assertEqual(result["next_interaction"]["kind"], "question")
        self.assertEqual(result["observations"][0]["kernel"], "value")

    def test_adaptive_selection_changes_after_evidence(self):
        view = self.create()
        session_id = view["session"]["session_id"]
        self.confirm(session_id)
        first = self.svc.get_session(session_id, self.learner)
        first_qid = first["next_interaction"]["content"]["question_id"]
        first_kc = first["next_interaction"]["content"]["knowledge_point_id"]
        answer_current(self.svc, session_id, self.learner, "ans-1", correct=True)
        second = self.svc.get_session(session_id, self.learner)
        second_kc = second["next_interaction"]["content"]["knowledge_point_id"]
        # 证据改变投影后，下一轮不再重复同一知识点的主验证题
        self.assertNotEqual(second_kc, first_kc)

    def test_wrong_answer_triggers_probe_and_budget(self):
        view = self.create(policy={"followup_budget": 1, "interaction_budget": 6, "complete_coverage": 1.0})
        session_id = view["session"]["session_id"]
        self.confirm(session_id)
        first = self.svc.get_session(session_id, self.learner)
        qid = first["next_interaction"]["content"]["question_id"]
        q = bank.question_by_id(qid)
        wrong = next(k for k in q["options"] if k != q["answer"])
        r = self.svc.answer(session_id, self.learner, {
            "action": "answer", "selected": wrong, "client_event_id": "ans-wrong-1",
        })
        self.assertIn(r["next_interaction"]["kind"], ("reasoning_probe", "prerequisite_probe"))
        # 追问回答（开放题，无法可靠评分 -> need_review，不强行二分）
        r2 = self.svc.answer(session_id, self.learner, {
            "action": "probe_answer", "text": "我觉得应该是这样，但不确定", "client_event_id": "probe-1",
        })
        self.assertEqual(r2["next_interaction"]["kind"], "question")
        # 第二次答错：预算已用尽 -> 不再追问
        second = self.svc.get_session(session_id, self.learner)
        q2 = bank.question_by_id(second["next_interaction"]["content"]["question_id"])
        wrong2 = next(k for k in q2["options"] if k != q2["answer"])
        r3 = self.svc.answer(session_id, self.learner, {
            "action": "answer", "selected": wrong2, "client_event_id": "ans-wrong-2",
        })
        self.assertEqual(r3["next_interaction"]["kind"], "question")

    def test_consecutive_skips_stop_insufficient(self):
        view = self.create(policy={"skip_limit": 2, "interaction_budget": 6, "complete_coverage": 1.0})
        session_id = view["session"]["session_id"]
        self.confirm(session_id)
        r1 = self.svc.answer(session_id, self.learner, {"action": "skip", "client_event_id": "skip-1"})
        self.assertEqual(r1["next_interaction"]["kind"], "question")
        r2 = self.svc.answer(session_id, self.learner, {"action": "skip", "client_event_id": "skip-2"})
        self.assertEqual(r2["next_interaction"]["kind"], "complete")
        self.assertEqual(r2["next_interaction"]["content"]["status"], "insufficient_evidence")

    def test_early_complete_when_coverage_sufficient(self):
        view = self.create(policy={"interaction_budget": 12, "complete_coverage": 0.5})
        session_id = view["session"]["session_id"]
        self.confirm(session_id)
        # 连续答对 4 道不同知识点的题 -> 覆盖率 4/7 >= 0.5 提前结束
        results = []
        for i in range(6):
            r = answer_current(self.svc, session_id, self.learner, f"ok-{i}", correct=True)
            results.append(r)
            if r["next_interaction"]["kind"] == "complete":
                break
        final = results[-1]
        self.assertEqual(final["next_interaction"]["content"]["status"], "completed")
        self.assertEqual(final["recommended_next_action"], "begin_learning")

    def test_hazy_flows_to_clarification(self):
        view = self.create()
        session_id = view["session"]["session_id"]
        self.confirm(session_id)
        r = self.svc.answer(session_id, self.learner, {"action": "hazy", "client_event_id": "hazy-1"})
        self.assertEqual(r["next_interaction"]["kind"], "clarification")
        r2 = self.svc.answer(session_id, self.learner, {
            "action": "clarify", "text": "我其实不太确定，可能选 A 吧", "client_event_id": "hazy-clear-1",
        })
        self.assertEqual(r2["next_interaction"]["kind"], "question")

    def test_assisted_success_records_practice(self):
        view = self.create()
        session_id = view["session"]["session_id"]
        self.confirm(session_id)
        r = answer_current(self.svc, session_id, self.learner, "assisted-1", correct=True, assisted=True)
        self.assertEqual(r["observations"][0]["kernel"], "practice")
        self.assertEqual(r["observations"][0]["status"], "assisted")
        projection = self.svc.get_projection(session_id, self.learner)
        kc_id = r["next_interaction"]["content"]["knowledge_point_id"] if r["next_interaction"]["kind"] == "question" else None
        practice = projection["projection"]["kernels"]["practice"]["independence"]
        self.assertTrue(any(v["level"] == "assisted" for v in practice.values()))

    def test_scope_isolation_between_learners(self):
        view_a = self.create(learner="STU-A", project="PROJ-X")
        sid_a = view_a["session"]["session_id"]
        self.confirm(sid_a, learner="STU-A")
        answer_current(self.svc, sid_a, "STU-A", "a-1", correct=True)
        # 学习者 B 无法访问 A 的会话
        with self.assertRaises(DiscoveryError) as ctx:
            self.svc.get_session(sid_a, "STU-B")
        self.assertEqual(ctx.exception.code, "FORBIDDEN")
        # B 的投影不含 A 的证据
        view_b = self.create(learner="STU-B", project="PROJ-Y")
        sid_b = view_b["session"]["session_id"]
        projection_b = self.svc.get_projection(sid_b, "STU-B")
        self.assertEqual(projection_b["projection"]["kernels"]["knowledge"]["kcs"], {})

    def test_project_scope_isolation_same_learner(self):
        view_1 = self.create(project="PROJ-1")
        sid_1 = view_1["session"]["session_id"]
        self.confirm(sid_1)
        answer_current(self.svc, sid_1, self.learner, "p1-1", correct=True)
        view_2 = self.create(project="PROJ-2")
        sid_2 = view_2["session"]["session_id"]
        projection_2 = self.svc.get_projection(sid_2, self.learner)
        self.assertEqual(projection_2["projection"]["kernels"]["knowledge"]["kcs"], {})

    def test_idempotent_answer_replay(self):
        view = self.create()
        session_id = view["session"]["session_id"]
        self.confirm(session_id)
        r1 = answer_current(self.svc, session_id, self.learner, "same-id", correct=True)
        r2 = answer_current(self.svc, session_id, self.learner, "same-id", correct=True)
        self.assertEqual(r1["graded"]["correct"], r2["graded"]["correct"])
        events = self.svc.export_events(self.learner)
        answer_events = [e for e in events["events"] if e["event_type"] == "answer_submitted"]
        self.assertEqual(len(answer_events), 1)

    def test_correction_downgrades_status(self):
        view = self.create()
        session_id = view["session"]["session_id"]
        self.confirm(session_id)
        answer_current(self.svc, session_id, self.learner, "cor-1", correct=True)
        events = self.svc.export_events(self.learner)
        target = next(e for e in events["events"] if e["event_type"] == "answer_submitted")
        kc_id = target["payload"]["knowledge_point_id"]
        result = self.svc.correct_event(session_id, self.learner, {
            "target_event_id": target["event_id"], "reason": "当时误点了",
            "client_event_id": "correction-1",
        })
        self.assertEqual(result["recomputed_status"], "untested")
        kc = result["projection"]["kernels"]["knowledge"]["kcs"][kc_id]
        self.assertEqual(kc["status"], "untested")
        self.assertIn(target["event_id"], kc["corrected_event_ids"])

    def test_memory_graph_derived_and_traceable(self):
        view = self.create()
        session_id = view["session"]["session_id"]
        self.confirm(session_id)
        answer_current(self.svc, session_id, self.learner, "mg-1", correct=True)
        graph = self.svc.get_projection(session_id, self.learner)["memory_graph"]
        self.assertGreaterEqual(len(graph["facts"]), 3)
        self.assertGreaterEqual(len(graph["modules"]), 1)
        knowledge_facts = [f for f in graph["facts"] if f["kernel"] == "knowledge"]
        self.assertTrue(knowledge_facts)
        self.assertTrue(knowledge_facts[0]["evidence_refs"])

    def test_unknown_session_raises_404(self):
        with self.assertRaises(DiscoveryError) as ctx:
            self.svc.get_session("DISC-NOPE", self.learner)
        self.assertEqual(ctx.exception.code, "SESSION_NOT_FOUND")


class DiscoveryApiTests(unittest.TestCase):
    """HTTP 层集成测试（mock 模式、真实请求）。"""

    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        settings = Settings(
            host="127.0.0.1",
            port=0,
            database_path=Path(self.temporary_directory.name) / "test.db",
            xingchen_mode="mock",
            api_url="",
            api_key="",
            api_secret="",
            auth_header="Authorization",
            auth_scheme="Bearer",
            flow_id="",
            input_key="AGENT_USER_INPUT",
            request_style="workflow_v1",
            request_timeout=5,
            seed_demo=False,
        )
        self.server = create_server(settings)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"
        self.learner_id = "STU-API-001"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temporary_directory.cleanup()

    def request_json(self, method, path, payload=None, timeout=5):
        import urllib.error
        import urllib.request

        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + path,
            data=body,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            return json.loads(error.read().decode("utf-8") or "{}")

    def create_session(self):
        return self.request_json("POST", "/api/discovery/sessions", {
            "learner_id": self.learner_id,
            "project_id": None,
            "goal_candidate": "想学 Java 面向对象",
            "desired_outcome": "独立完成成绩管理实训",
            "policy": {"interaction_budget": 6, "complete_coverage": 1.0},
        })

    def test_api_create_and_get_session(self):
        created = self.create_session()
        self.assertEqual(created["status"], "ok")
        session_id = created["session"]["session_id"]
        detail = self.request_json("GET", f"/api/discovery/sessions/{session_id}?learner_id={self.learner_id}")
        self.assertEqual(detail["session"]["session_id"], session_id)
        self.assertEqual(detail["next_interaction"]["kind"], "clarification")

    def test_api_confirm_answer_and_projection(self):
        created = self.create_session()
        session_id = created["session"]["session_id"]
        confirm = self.request_json("POST", f"/api/discovery/sessions/{session_id}/answer", {
            "learner_id": self.learner_id,
            "action": "confirm",
            "goal_id": "GOAL-JAVA-001",
            "client_event_id": "api-confirm",
        })
        self.assertEqual(confirm["next_interaction"]["kind"], "question")
        qid = confirm["next_interaction"]["content"]["question_id"]
        q = bank.question_by_id(qid)
        answer = self.request_json("POST", f"/api/discovery/sessions/{session_id}/answer", {
            "learner_id": self.learner_id,
            "action": "answer",
            "selected": q["answer"],
            "client_event_id": "api-answer-1",
        })
        self.assertTrue(answer["graded"]["correct"])
        projection = self.request_json(
            "GET", f"/api/discovery/sessions/{session_id}/projection?learner_id={self.learner_id}"
        )
        self.assertIn("projection", projection)
        self.assertIn("memory_graph", projection)
        self.assertEqual(projection["projection"]["scope"]["learner_id"], self.learner_id)

    def test_api_correct_and_events(self):
        created = self.create_session()
        session_id = created["session"]["session_id"]
        self.request_json("POST", f"/api/discovery/sessions/{session_id}/answer", {
            "learner_id": self.learner_id,
            "action": "confirm",
            "goal_id": "GOAL-JAVA-001",
            "client_event_id": "api-confirm-2",
        })
        exported = self.request_json("GET", f"/api/learners/{self.learner_id}/discovery/events")
        self.assertGreaterEqual(exported["total"], 3)

    def test_api_unknown_session_404(self):
        result = self.request_json(
            "GET", f"/api/discovery/sessions/DISC-NOPE?learner_id={self.learner_id}"
        )
        self.assertEqual(result.get("error_code"), "SESSION_NOT_FOUND")

    def test_api_forbidden_learner(self):
        created = self.create_session()
        session_id = created["session"]["session_id"]
        result = self.request_json(
            "GET", f"/api/discovery/sessions/{session_id}?learner_id=STU-INTRUDER"
        )
        self.assertEqual(result.get("error_code"), "FORBIDDEN")


if __name__ == "__main__":
    unittest.main()
