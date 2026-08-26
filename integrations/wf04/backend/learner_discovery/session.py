"""发现会话状态机与对外服务（DiscoveryService）。

状态机：created -> clarifying(目标确认) -> diagnosing(选题) <-> probing(追问)
        -> completed | insufficient_evidence | stopped
每次有效交互：行为 -> EvidenceEvent -> Reducer -> KernelMutation -> KernelState
        -> MemoryGraph 重建 -> 基于新投影重新决策下一轮。
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from backend.learner_discovery import bank
from backend.learner_discovery.models import (
    EvidenceEvent,
    KernelProjection,
    NextInteraction,
    Observation,
    Scope,
    SessionPolicy,
    new_id,
    utc_now,
)
from backend.learner_discovery.reducer import reduce_event
from backend.learner_discovery.kernels import (
    default_kc_state,
    default_kernel_state,
    projection_for,
)
from backend.learner_discovery.memory_graph import build_memory_graph
from backend.learner_discovery.registry import require_registered
from backend.learner_discovery.selector import decide_next, recommended_action
from backend.learner_discovery.store import DiscoveryStore
from backend.learner_discovery.validator import validate_answer_input

KERNELS_ALL = ("structure", "knowledge", "human", "value", "practice")


class DiscoveryError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class DiscoveryService:
    def __init__(self, database_path: Path | str):
        self.store = DiscoveryStore(database_path)
        self._lock = threading.RLock()

    def _require_session(self, session_id: str) -> dict[str, Any]:
        session = self.store.load_session(session_id)
        if not session:
            raise DiscoveryError("SESSION_NOT_FOUND", "发现会话不存在")
        return session

    # ------------------------------------------------------------------
    # 会话创建
    # ------------------------------------------------------------------

    def create_session(
        self,
        learner_id: str,
        project_id: str | None = None,
        checkpoint_id: str | None = None,
        goal_candidate: str = "",
        desired_outcome: str = "",
        goal_id: str | None = None,
        seed: int | None = None,
        policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        learner_id = str(learner_id or "").strip()
        if not learner_id:
            raise DiscoveryError("MISSING_LEARNER_ID", "learner_id 不能为空")
        session_id = new_id("DISC")
        session_scope = Scope(
            learner_id=learner_id,
            project_id=project_id,
            checkpoint_id=checkpoint_id,
            session_id=session_id,
        )
        policy_kwargs = {
            k: v for k, v in (policy or {}).items()
            if k in SessionPolicy.__dataclass_fields__ and k != "seed"
        }
        resolved_policy = SessionPolicy(
            seed=int(seed if seed is not None else (policy or {}).get("seed", 20260811)),
            **policy_kwargs,
        )
        session = {
            "session_id": session_id,
            "learner_id": learner_id,
            "project_id": project_id,
            "checkpoint_id": checkpoint_id,
            "status": "created",
            "seed": resolved_policy.seed,
            "policy": resolved_policy.as_dict(),
            "state": {
                "phase": "goal_clarification",
                "goal_id": goal_id,
                "goal_candidate": goal_candidate,
                "desired_outcome": desired_outcome,
                "interaction_count": 0,
                "followup_used": 0,
                "consecutive_skips": 0,
                "seen_question_ids": [],
                "pending_followup": None,
                "current_question": None,
                "responses": {},
                "started_at": utc_now(),
                "completed_at": None,
                "outcome": None,
                "recommended_next_action": "continue_discovery",
            },
            "created_at": utc_now(),
        }
        self.store.save_session(session)

        # 事件：会话开始 + 目标候选（如提供）
        self._record_event(EvidenceEvent(
            event_type="discovery_session_started",
            scope=session_scope,
            payload={"phase": "goal_clarification"},
            kernel_targets=["structure"],
            evidence_role="interaction_log",
            confidence=1.0,
            client_event_id=f"start-{session_id}",
            provenance={"policy_version": "v1"},
        ), session)
        if str(goal_candidate or "").strip():
            self._record_event(EvidenceEvent(
                event_type="goal_candidate_stated",
                scope=session_scope,
                payload={"text": goal_candidate, "desired_outcome": desired_outcome},
                kernel_targets=["value"],
                evidence_role="self_reported",
                confidence=0.5,
                client_event_id=f"candidate-{session_id}",
                provenance={"policy_version": "v1"},
            ), session)

        projection = self._load_projection(session_scope)
        session = self.store.load_session(session_id) or session
        next_interaction = decide_next(
            projection, session["state"], resolved_policy.as_dict(), goal_id
        )
        session["state"]["next_interaction"] = next_interaction.as_dict()
        if next_interaction.kind == "question":
            self._prepare_question(session, session["state"], next_interaction)
        self.store.save_session(session)
        return self._session_view(session, projection)

    # ------------------------------------------------------------------
    # 作答
    # ------------------------------------------------------------------

    def answer(
        self, session_id: str, learner_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        with self._lock:
            session = self._require_session(session_id)
            self._check_ownership(session, learner_id)
            ok, problems = validate_answer_input(payload)
            if not ok:
                raise DiscoveryError("INVALID_INPUT", "；".join(problems))
            client_event_id = str(payload.get("client_event_id") or "").strip()
            state = dict(session["state"])
            responses = state.setdefault("responses", {})
            if client_event_id in responses:
                # 完全幂等：重复提交返回首次结果
                return dict(responses[client_event_id])

            self._check_budget(session, state)
            action = str(payload.get("action") or "answer").strip().lower()
            raw_next = state.get("next_interaction")
            if not raw_next:
                raise DiscoveryError("SESSION_NOT_READY", "会话尚未准备好下一轮交互")
            # 计数前置：decide_next 需要看到本次交互后的预算/跳过计数
            state["interaction_count"] = int(state.get("interaction_count", 0) or 0) + 1
            if action == "skip":
                state["consecutive_skips"] = int(state.get("consecutive_skips", 0) or 0) + 1
            else:
                state["consecutive_skips"] = 0
            next_interaction = NextInteraction(
                kind=str(raw_next.get("kind") or ""),
                purpose=str(raw_next.get("purpose") or ""),
                content=raw_next.get("content") or {},
            )
            if next_interaction.kind == "clarification":
                result = self._handle_clarification(session, state, payload)
            elif next_interaction.kind == "question":
                result = self._handle_question(session, state, payload)
            elif next_interaction.kind in ("reasoning_probe", "prerequisite_probe"):
                result = self._handle_probe(session, state, payload, next_interaction)
            elif next_interaction.kind == "complete":
                result = self._finalize(session, state, "completed")
            else:
                raise DiscoveryError("INVALID_STATE", f"未知的下一轮交互：{next_interaction.kind}")

            session["state"] = state
            self.store.save_session(session)
            response = self._answer_view(session, state, result)
            state["responses"][client_event_id] = response
            session["state"] = state
            self.store.save_session(session)
            return dict(response)

    # ------------------------------------------------------------------
    # 内部处理
    # ------------------------------------------------------------------

    def _handle_clarification(
        self, session: dict[str, Any], state: dict[str, Any], payload: dict[str, Any]
    ) -> dict[str, Any]:
        action = str(payload.get("action") or "confirm").strip().lower()
        scope = self._session_scope(session)
        # 含糊回答后的澄清（区别于目标澄清）
        pending = state.get("pending_followup") or {}
        if pending.get("kind") == "clarification":
            question = pending.get("question") or {}
            kc_id = str(question.get("knowledge_point_id") or "")
            text = str(payload.get("text") or "").strip()
            self._record_event(EvidenceEvent(
                event_type="reasoning_explained",
                scope=scope,
                payload={
                    "question_id": str(question.get("question_id") or ""),
                    "knowledge_point_id": kc_id,
                    "explanation": text,
                    "matches_rubric": None,
                    "probe_kind": "hazy_clarification",
                },
                kernel_targets=["knowledge"],
                evidence_role="self_reported",
                confidence=0.6,
                client_event_id=str(payload.get("client_event_id") or ""),
                provenance={"rubric_version": "v1", "policy_version": "v1"},
            ), session)
            state["followup_used"] = int(state.get("followup_used", 0) or 0) + 1
            state["pending_followup"] = None
            projection = self._load_projection(scope)
            observations = [Observation(
                kernel="knowledge", subject=kc_id,
                claim="含糊回答已澄清：解释保留待复查（need_review）",
                status="unknown", confidence=0.3,
            ).as_dict()]
            next_interaction = decide_next(
                projection, state, session["policy"], state.get("goal_id")
            )
            if next_interaction.kind == "question":
                self._prepare_question(session, state, next_interaction)
            state["next_interaction"] = next_interaction.as_dict()
            return {
                "kind": "clarification_answered",
                "graded": None,
                "observations": observations,
                "uncertainties": self._uncertainties(projection, state),
                "next_interaction": next_interaction.as_dict(),
                "recommended_next_action": "continue_discovery",
            }
        text = str(payload.get("text") or state.get("goal_candidate") or "").strip()
        desired_outcome = str(payload.get("desired_outcome") or state.get("desired_outcome") or "").strip()
        if action == "clarify":
            self._record_event(EvidenceEvent(
                event_type="goal_clarified",
                scope=scope,
                payload={"text": text, "desired_outcome": desired_outcome},
                kernel_targets=["value"],
                evidence_role="self_reported",
                confidence=0.6,
                client_event_id=str(payload.get("client_event_id") or ""),
                provenance={"policy_version": "v1"},
            ), session)
            state["goal_candidate"] = text
            state["desired_outcome"] = desired_outcome
            projection = self._load_projection(scope)
            next_interaction = decide_next(
                projection, state, session["policy"], state.get("goal_id")
            )
            state["next_interaction"] = next_interaction.as_dict()
            return {
                "kind": "clarification",
                "graded": None,
                "observations": [],
                "uncertainties": self._uncertainties(projection, state),
                "next_interaction": next_interaction.as_dict(),
                "recommended_next_action": "continue_discovery",
            }

        # 默认视为确认
        goal_id = str(payload.get("goal_id") or state.get("goal_id") or "").strip()
        if not goal_id:
            goal_id = self._infer_goal_id(text)
        state["goal_id"] = goal_id
        state["phase"] = "diagnosing"
        self._record_event(EvidenceEvent(
            event_type="goal_confirmed",
            scope=scope,
            payload={
                "goal_id": goal_id,
                "goal_label": bank.goal_label_for(goal_id),
                "text": text,
                "desired_outcome": desired_outcome,
            },
            kernel_targets=["value", "structure"],
            evidence_role="self_reported",
            confidence=0.8,
            client_event_id=str(payload.get("client_event_id") or ""),
            provenance={"policy_version": "v1"},
        ), session)
        projection = self._load_projection(scope)
        observations = [Observation(
            kernel="value",
            subject=goal_id,
            claim=f"目标已确认：{bank.goal_label_for(goal_id)}",
            status="confirmed",
            confidence=0.8,
        ).as_dict()]
        next_interaction = decide_next(
            projection, state, session["policy"], goal_id
        )
        if next_interaction.kind == "question":
            self._prepare_question(session, state, next_interaction)
        state["next_interaction"] = next_interaction.as_dict()
        return {
            "kind": "confirmation",
            "graded": None,
            "observations": observations,
            "uncertainties": self._uncertainties(projection, state),
            "next_interaction": next_interaction.as_dict(),
            "recommended_next_action": "continue_discovery",
        }

    def _handle_question(
        self, session: dict[str, Any], state: dict[str, Any], payload: dict[str, Any]
    ) -> dict[str, Any]:
        action = str(payload.get("action") or "answer").strip().lower()
        scope = self._session_scope(session)
        current = state.get("current_question") or {}
        question_id = str(current.get("question_id") or "")
        kc_id = str(current.get("knowledge_point_id") or "")
        if not question_id or not kc_id:
            raise DiscoveryError("NO_ACTIVE_QUESTION", "当前没有可作答的题目")

        if action == "skip":
            self._record_event(EvidenceEvent(
                event_type="answer_skipped",
                scope=scope,
                payload={
                    "question_id": question_id,
                    "knowledge_point_id": kc_id,
                    "question_index": int(state.get("interaction_count", 0) or 0),
                },
                kernel_targets=["knowledge", "structure"],
                evidence_role="skipped",
                confidence=1.0,
                client_event_id=str(payload.get("client_event_id") or ""),
                provenance={"question_id": question_id, "question_version": "v1",
                            "grading_version": "v1", "policy_version": "v1"},
            ), session)
            state["current_question"] = None
            projection = self._load_projection(scope)
            observations = [Observation(
                kernel="knowledge", subject=kc_id,
                claim="跳过本题：记录未作答，不视为知识错误",
                status="unknown", confidence=0.0,
                evidence_refs=[],
            ).as_dict()]
            return self._next_after_answer(session, state, projection, observations, graded=None)

        if action == "hazy":
            self._record_event(EvidenceEvent(
                event_type="answer_hazy",
                scope=scope,
                payload={"question_id": question_id, "knowledge_point_id": kc_id},
                kernel_targets=["knowledge"],
                evidence_role="ungraded_hazy",
                confidence=0.3,
                client_event_id=str(payload.get("client_event_id") or ""),
                provenance={"question_id": question_id, "question_version": "v1",
                            "grading_version": "v1", "policy_version": "v1"},
            ), session)
            state["current_question"] = None
            state["pending_followup"] = {
                "kind": "clarification",
                "question": current,
                "kc_id": kc_id,
            }
            projection = self._load_projection(scope)
            observations = [Observation(
                kernel="knowledge", subject=kc_id,
                claim="含糊回答：标记不确定性，等待澄清",
                status="unknown", confidence=0.3,
                evidence_refs=[],
            ).as_dict()]
            next_interaction = NextInteraction(
                kind="clarification",
                purpose="澄清含糊回答，避免把不确定性误判为错误",
                content={
                    "question_id": question_id,
                    "knowledge_point_id": kc_id,
                    "prompt": "你的回答比较含糊，能再明确说明一下吗？（也可选择跳过）",
                },
            )
            state["next_interaction"] = next_interaction.as_dict()
            return {
                "kind": "hazy",
                "graded": None,
                "observations": observations,
                "uncertainties": self._uncertainties(projection, state),
                "next_interaction": next_interaction.as_dict(),
                "recommended_next_action": "continue_discovery",
            }

        # 正常作答（支持 assisted）
        selected = str(payload.get("selected") or "").strip().lower()
        assisted = bool(payload.get("assisted"))
        expected = str(current.get("answer") or "").strip().lower()
        correct = bool(expected) and selected == expected
        misconception_id = ""
        if not correct:
            misconception_id = bank.misconception_id_for(kc_id, selected, expected)
        transfer = bool(payload.get("transfer"))
        self._record_event(EvidenceEvent(
            event_type="answer_submitted",
            scope=scope,
            payload={
                "question_id": question_id,
                "knowledge_point_id": kc_id,
                "knowledge_point_name": current.get("knowledge_point_name", ""),
                "correct": correct,
                "assisted": assisted,
                "transfer": transfer,
                "selected": selected,
                "expected": expected,
                "misconception_id": misconception_id,
            },
            kernel_targets=["knowledge", "practice"],
            evidence_role="graded_attempt",
            confidence=1.0,
            client_event_id=str(payload.get("client_event_id") or ""),
            artifact_refs=[question_id],
            provenance={"question_id": question_id, "question_version": "v1",
                        "grading_version": "v1", "policy_version": "v1"},
        ), session)
        state["current_question"] = None
        projection = self._load_projection(scope)
        kc = projection.kernels["knowledge"].get("kcs", {}).get(kc_id, {})
        practice = projection.kernels["practice"].get("independence", {}).get(kc_id, {})
        observations = []
        if correct and not assisted:
            observations.append(Observation(
                kernel="knowledge", subject=kc_id,
                claim=f"独立答对：{kc.get('status', 'candidate')}（{kc.get('evidence', {}).get('distinct_independent_correct', 0)} 道不同题）",
                status=kc.get("status", "candidate"),
                confidence=float(kc.get("confidence", 0.0)),
            ).as_dict())
            observations.append(Observation(
                kernel="practice", subject=kc_id,
                claim=f"独立完成：独立性 -> {practice.get('level', 'untested')}",
                status=practice.get("level", "untested"),
                confidence=0.7,
            ).as_dict())
        elif correct and assisted:
            observations.append(Observation(
                kernel="practice", subject=kc_id,
                claim="辅助后成功：支持'在帮助下可以完成'，不视为独立掌握",
                status="assisted",
                confidence=0.5,
            ).as_dict())
        else:
            observations.append(Observation(
                kernel="knowledge", subject=kc_id,
                claim=f"答错：记录错误证据（{misconception_id or '无特定误解'}）",
                status=kc.get("status", "untested"),
                confidence=0.6,
            ).as_dict())

        # 答错且追问预算未用尽 -> 生成追问
        followup_used = int(state.get("followup_used", 0) or 0)
        if (not correct) and followup_used < int(session["policy"].get("followup_budget", 2)):
            prerequisites = self._prerequisites(kc_id)
            untested_prereq = [
                p for p in prerequisites
                if projection.kernels["knowledge"].get("kcs", {}).get(p, {}).get("status", "untested") == "untested"
            ]
            state["pending_followup"] = {
                "kind": "prerequisite_probe" if untested_prereq else "reasoning_probe",
                "question": current,
                "kc_id": kc_id,
                "prerequisites": untested_prereq,
            }
        else:
            state["pending_followup"] = None

        graded = {
            "correct": correct,
            "selected": selected,
            "answer": expected,
            "explanation": current.get("explanation", ""),
            "assisted": assisted,
        }
        return self._next_after_answer(session, state, projection, observations, graded=graded)

    def _handle_probe(
        self, session: dict[str, Any], state: dict[str, Any], payload: dict[str, Any],
        interaction: NextInteraction,
    ) -> dict[str, Any]:
        scope = self._session_scope(session)
        pending = state.get("pending_followup") or {}
        question = pending.get("question") or {}
        kc_id = str(question.get("knowledge_point_id") or "")
        text = str(payload.get("text") or "").strip()
        matches = payload.get("matches_rubric")
        if not text:
            raise DiscoveryError("INVALID_INPUT", "追问需要回答文本")
        # 开放题/理由：无法可靠评分时如实标记 need_review（matches_rubric=None）
        self._record_event(EvidenceEvent(
            event_type="reasoning_explained",
            scope=scope,
            payload={
                "question_id": str(question.get("question_id") or ""),
                "knowledge_point_id": kc_id,
                "explanation": text,
                "matches_rubric": matches,
                "probe_kind": interaction.kind,
            },
            kernel_targets=["knowledge"],
            evidence_role="self_reported",
            confidence=0.6,
            client_event_id=str(payload.get("client_event_id") or ""),
            provenance={"rubric_version": "v1", "policy_version": "v1"},
        ), session)
        state["followup_used"] = int(state.get("followup_used", 0) or 0) + 1
        state["pending_followup"] = None
        projection = self._load_projection(scope)
        kc = projection.kernels["knowledge"].get("kcs", {}).get(kc_id, {})
        observations = [Observation(
            kernel="knowledge", subject=kc_id,
            claim=(
                "解释与 Rubric 匹配：支持理解证据"
                if matches is True else
                "解释无法可靠判定：保留原始回答待复查（need_review）"
            ),
            status=kc.get("status", "untested"),
            confidence=float(kc.get("confidence", 0.0)),
        ).as_dict()]
        return self._next_after_answer(session, state, projection, observations, graded=None)

    def _next_after_answer(
        self, session: dict[str, Any], state: dict[str, Any],
        projection: KernelProjection, observations: list[dict[str, Any]],
        graded: dict[str, Any] | None,
    ) -> dict[str, Any]:
        next_interaction = decide_next(
            projection, state, session["policy"], state.get("goal_id")
        )
        if next_interaction.kind == "question":
            self._prepare_question(session, state, next_interaction)
        state["next_interaction"] = next_interaction.as_dict()
        if next_interaction.kind == "complete":
            return self._finalize(session, state, str(next_interaction.content.get("status") or "completed"))
        return {
            "kind": "answer",
            "graded": graded,
            "observations": observations,
            "uncertainties": self._uncertainties(projection, state),
            "next_interaction": next_interaction.as_dict(),
            "recommended_next_action": "continue_discovery",
        }

    def _finalize(
        self, session: dict[str, Any], state: dict[str, Any], outcome: str
    ) -> dict[str, Any]:
        scope = self._session_scope(session)
        self._record_event(EvidenceEvent(
            event_type="discovery_session_completed",
            scope=scope,
            payload={"status": outcome, "reason": (state.get("next_interaction") or {}).get("content", {}).get("reason", "")},
            kernel_targets=["structure"],
            evidence_role="interaction_log",
            confidence=1.0,
            client_event_id=f"complete-{session['session_id']}-{outcome}",
            provenance={"policy_version": "v1"},
        ), session)
        state["phase"] = "done"
        state["completed_at"] = utc_now()
        state["outcome"] = outcome
        projection = self._load_projection(scope)
        action = recommended_action(outcome, projection)
        state["recommended_next_action"] = action
        return {
            "kind": "complete",
            "graded": None,
            "observations": [],
            "uncertainties": self._uncertainties(projection, state),
            "next_interaction": NextInteraction(
                kind="complete",
                purpose="发现会话结束",
                content={"status": outcome, "recommended_next_action": action},
            ).as_dict(),
            "recommended_next_action": action,
        }

    # ------------------------------------------------------------------
    # 事件记录（唯一写路径）
    # ------------------------------------------------------------------

    def _record_event(self, event: EvidenceEvent, session: dict[str, Any]) -> dict[str, Any]:
        require_registered(event.event_type)
        if self.store.get_event_by_client_id(event.scope.learner_id, event.client_event_id):
            return {}
        inserted = self.store.save_event(event)
        if not inserted:
            return {}
        scope = event.scope
        state_by_kernel: dict[str, dict[str, Any]] = {}
        versions: dict[str, int] = {}
        for kernel in event.kernel_targets:
            kernel_scope = Scope(
                learner_id=scope.learner_id,
                project_id=scope.project_id,
                checkpoint_id=scope.checkpoint_id,
                session_id=scope.session_id if kernel == "structure" else None,
            )
            base, version = self.store.load_kernel_state(kernel_scope, kernel)
            state_by_kernel[kernel] = base or default_kernel_state(kernel)
            versions[kernel] = version
        new_states, mutations = reduce_event(event, state_by_kernel, session.get("policy") or {})
        mutation_by_kernel: dict[str, list[dict[str, Any]]] = {}
        for mutation in mutations:
            mutation_by_kernel.setdefault(mutation["kernel"], []).append(mutation)
        for kernel, kernel_mutations in mutation_by_kernel.items():
            kernel_scope = Scope(
                learner_id=scope.learner_id,
                project_id=scope.project_id,
                checkpoint_id=scope.checkpoint_id,
                session_id=scope.session_id if kernel == "structure" else None,
            )
            next_version = versions.get(kernel, 0) + 1
            for i, mutation in enumerate(kernel_mutations):
                mutation["version"] = next_version + i
                mutation["mutation_id"] = new_id("MUT")
                self.store.append_mutation(mutation, kernel_scope)
            self.store.save_kernel_state(
                kernel_scope, kernel, new_states[kernel], next_version + len(kernel_mutations) - 1
            )
        self._rebuild_memory_graph(Scope(
            learner_id=scope.learner_id,
            project_id=scope.project_id,
            checkpoint_id=scope.checkpoint_id,
            session_id=scope.session_id,
        ))
        return event.as_dict()

    # ------------------------------------------------------------------
    # 投影 / 查询
    # ------------------------------------------------------------------

    def _load_projection(self, scope: Scope) -> KernelProjection:
        states: dict[str, dict[str, Any]] = {}
        versions: dict[str, int] = {}
        for kernel in KERNELS_ALL:
            kernel_scope = Scope(
                learner_id=scope.learner_id,
                project_id=scope.project_id,
                checkpoint_id=scope.checkpoint_id,
                session_id=scope.session_id if kernel == "structure" else None,
            )
            state, version = self.store.load_kernel_state(kernel_scope, kernel)
            states[kernel] = state or default_kernel_state(kernel)
            versions[kernel] = version
        recent = self.store.recent_events(scope.learner_id, scope.project_id, limit=20)
        return projection_for(scope, states, versions, recent)

    def _rebuild_memory_graph(self, scope: Scope) -> None:
        projection = self._load_projection(scope)
        graph = build_memory_graph(projection)
        project_scope = Scope(learner_id=scope.learner_id, project_id=scope.project_id)
        self.store.replace_memory_for_scope(project_scope, graph["facts"], graph["modules"], graph["claims"])

    def get_session(self, session_id: str, learner_id: str) -> dict[str, Any]:
        session = self._require_session(session_id)
        self._check_ownership(session, learner_id)
        projection = self._load_projection(self._session_scope(session))
        return self._session_view(session, projection)

    def get_projection(self, session_id: str, learner_id: str) -> dict[str, Any]:
        session = self._require_session(session_id)
        self._check_ownership(session, learner_id)
        projection = self._load_projection(self._session_scope(session))
        graph = build_memory_graph(projection)
        return {
            "projection": projection.as_dict(),
            "memory_graph": graph,
            "uncertainties": self._uncertainties(projection, session["state"]),
        }

    def export_events(self, learner_id: str, session_id: str | None = None) -> dict[str, Any]:
        events = self.store.list_events(learner_id, session_id=session_id)
        return {"status": "ok", "learner_id": learner_id, "events": events, "total": len(events)}

    def list_sessions(self, learner_id: str) -> dict[str, Any]:
        return {"status": "ok", "sessions": self.store.list_sessions(learner_id)}

    # ------------------------------------------------------------------
    # 纠正
    # ------------------------------------------------------------------

    def correct_event(
        self, session_id: str, learner_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        with self._lock:
            session = self._require_session(session_id)
            self._check_ownership(session, learner_id)
            target_event_id = str(payload.get("target_event_id") or "").strip()
            reason = str(payload.get("reason") or "用户纠正").strip()
            client_event_id = str(payload.get("client_event_id") or f"correct-{target_event_id}")
            if not target_event_id:
                raise DiscoveryError("INVALID_INPUT", "target_event_id 不能为空")
            target = self.store.get_event(target_event_id)
            if not target or target["scope"]["learner_id"] != learner_id:
                raise DiscoveryError("EVENT_NOT_FOUND", "目标事件不存在或不属于该学习者")
            if self.store.get_event_by_client_id(learner_id, client_event_id):
                return {"status": "ok", "idempotent": True, "session_id": session_id}

            kc_id = str(target["payload"].get("knowledge_point_id") or target["payload"].get("kc_id") or "").strip()
            if not kc_id:
                raise DiscoveryError("INVALID_INPUT", "目标事件没有绑定知识点，无法纠正")

            recomputed = self._recompute_kc(learner_id, session.get("project_id"), kc_id,
                                            exclude_event_id=target_event_id, policy=session["policy"])
            scope = self._session_scope(session)
            self._record_event(EvidenceEvent(
                event_type="evidence_correction",
                scope=scope,
                payload={
                    "target_event_id": target_event_id,
                    "knowledge_point_id": kc_id,
                    "recomputed": recomputed,
                    "reason": reason,
                },
                kernel_targets=["knowledge", "practice"],
                evidence_role="self_reported",
                confidence=0.9,
                client_event_id=client_event_id,
                provenance={"policy_version": "v1"},
            ), session)
            projection = self._load_projection(scope)
            return {
                "status": "ok",
                "session_id": session_id,
                "corrected_event_id": target_event_id,
                "kc_id": kc_id,
                "recomputed_status": recomputed.get("status"),
                "projection": projection.as_dict(),
                "memory_graph": build_memory_graph(projection),
            }

    def _recompute_kc(
        self, learner_id: str, project_id: str | None, kc_id: str,
        exclude_event_id: str, policy: dict[str, Any],
    ) -> dict[str, Any]:
        """重放该 KC 的全部证据（剔除被纠正事件），重算知识状态。"""
        events = self.store.list_events(learner_id, limit=500)
        state = default_kernel_state("knowledge")
        state["kcs"][kc_id] = default_kc_state(kc_id)
        for raw in events:
            if raw["event_id"] == exclude_event_id:
                continue
            if str(raw["payload"].get("knowledge_point_id") or "") != kc_id:
                continue
            if raw["event_type"] not in ("answer_submitted", "answer_skipped", "answer_hazy",
                                         "reasoning_explained", "assisted_success"):
                continue
            event = self._event_from_dict(raw)
            new_states, _ = reduce_event(event, {"knowledge": state}, policy)
            state = new_states["knowledge"]
        return state["kcs"].get(kc_id, default_kc_state(kc_id))

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------

    def _session_scope(self, session: dict[str, Any]) -> Scope:
        return Scope(
            learner_id=session["learner_id"],
            project_id=session.get("project_id"),
            checkpoint_id=session.get("checkpoint_id"),
            session_id=session["session_id"],
        )

    @staticmethod
    def _event_from_dict(raw: dict[str, Any]) -> EvidenceEvent:
        return EvidenceEvent(
            event_type=raw["event_type"],
            scope=Scope(**raw["scope"]),
            payload=raw["payload"],
            kernel_targets=raw["kernel_targets"],
            evidence_role=raw["evidence_role"],
            confidence=raw["confidence"],
            client_event_id=raw["client_event_id"],
            event_id=raw["event_id"],
            artifact_refs=raw["artifact_refs"],
            provenance=raw["provenance"],
            created_at=raw["created_at"],
        )

    def _prepare_question(
        self, session: dict[str, Any], state: dict[str, Any],
        next_interaction: NextInteraction,
    ) -> None:
        content = next_interaction.content
        kc_id = str(content.get("knowledge_point_id") or "")
        question = bank.pick_question(
            kc_id, state.get("goal_id"), state.get("seen_question_ids", []),
            int(session.get("seed", 20260811)),
        )
        if question is None:
            return
        frozen = {
            "question_id": str(question.get("id") or question.get("question_id") or ""),
            "knowledge_point_id": kc_id,
            "knowledge_point_name": question.get("knowledge_point_name") or bank.knowledge_point_name(kc_id),
            "title": question.get("title", ""),
            "options": question.get("options", {}),
            "difficulty": question.get("difficulty", 1),
            "answer": str(question.get("answer", "")).strip().lower(),
            "explanation": question.get("explanation", ""),
            "question_version": "v1",
        }
        state["current_question"] = frozen
        seen = list(state.setdefault("seen_question_ids", []))
        if frozen["question_id"] and frozen["question_id"] not in seen:
            seen.append(frozen["question_id"])
        state["seen_question_ids"] = seen
        next_interaction.content = bank.question_public(frozen)
        # question_presented 事件（structure 位置）
        self._record_event(EvidenceEvent(
            event_type="question_presented",
            scope=self._session_scope(session),
            payload={
                "question_id": frozen["question_id"],
                "question_index": int(state.get("interaction_count", 0) or 0),
                "total_questions": int(session["policy"].get("interaction_budget", 8)),
                "phase": state.get("phase", "diagnosing"),
            },
            kernel_targets=["structure"],
            evidence_role="interaction_log",
            confidence=1.0,
            client_event_id=f"present-{session['session_id']}-{frozen['question_id']}",
            provenance={"question_version": "v1", "policy_version": "v1"},
        ), session)

    def _uncertainties(
        self, projection: KernelProjection, state: dict[str, Any]
    ) -> list[dict[str, Any]]:
        knowledge = projection.kernels.get("knowledge", {})
        kc_ids = bank.list_knowledge_point_ids(state.get("goal_id"))
        uncertainties: list[dict[str, Any]] = []
        for kc_id in kc_ids:
            kc = knowledge.get("kcs", {}).get(kc_id) or {}
            status = kc.get("status", "untested")
            if status in ("untested", "candidate"):
                reason = "只有自述或低置信度证据" if status == "candidate" else "尚无评分证据"
                uncertainties.append({
                    "kernel": "knowledge",
                    "subject": kc_id,
                    "reason": reason,
                    "priority": round(1.0 if status == "untested" else 0.8, 2),
                })
        return uncertainties

    def _prerequisites(self, kc_id: str) -> list[str]:
        try:
            from backend.data.goal_graph import DEPENDENCIES
        except Exception:
            from data.goal_graph import DEPENDENCIES
        return list(DEPENDENCIES.get(kc_id, []))

    @staticmethod
    def _infer_goal_id(text: str) -> str:
        lowered = str(text or "").lower()
        if any(keyword in lowered for keyword in ("竞赛", "大赛", "competition", "备赛", "赛项")):
            return "GOAL-JAVA-COMPETITION"
        if any(keyword in lowered for keyword in ("认证", "1+x", "证书", "cert")):
            return "GOAL-JAVA-CERT"
        if any(keyword in lowered for keyword in ("成绩", "对象", "类", "实训", "java", "面向对象")):
            return "GOAL-JAVA-001"
        return "GOAL-JAVA-DAILY"

    def _check_budget(self, session: dict[str, Any], state: dict[str, Any]) -> None:
        if state.get("phase") == "done":
            raise DiscoveryError("SESSION_FINISHED", "发现会话已结束")
        started = state.get("started_at") or session.get("created_at") or ""
        if started:
            try:
                from datetime import datetime
                parsed = datetime.fromisoformat(started.replace("Z", "+00:00"))
                now = datetime.now(parsed.tzinfo)
                elapsed = (now - parsed).total_seconds()
                if elapsed > int(session["policy"].get("time_budget_seconds", 180)):
                    raise DiscoveryError("TIME_BUDGET_EXHAUSTED", "会话超过时间预算，请新建会话")
            except ValueError:
                pass

    @staticmethod
    def _check_ownership(session: dict[str, Any], learner_id: str) -> None:
        if str(session.get("learner_id", "")) != str(learner_id or ""):
            raise DiscoveryError("FORBIDDEN", "学习者与会话不匹配")

    # ------------------------------------------------------------------
    # 视图
    # ------------------------------------------------------------------

    def _session_view(
        self, session: dict[str, Any], projection: KernelProjection
    ) -> dict[str, Any]:
        state = session["state"]
        return {
            "status": "ok",
            "session": {
                "session_id": session["session_id"],
                "learner_id": session["learner_id"],
                "project_id": session.get("project_id"),
                "status": session["status"],
                "phase": state.get("phase"),
                "seed": session.get("seed"),
                "policy": session.get("policy"),
                "goal_id": state.get("goal_id"),
                "goal_candidate": state.get("goal_candidate"),
                "desired_outcome": state.get("desired_outcome"),
                "outcome": state.get("outcome"),
                "recommended_next_action": state.get("recommended_next_action"),
                "created_at": session.get("created_at"),
                "updated_at": session.get("updated_at"),
            },
            "next_interaction": state.get("next_interaction"),
            "kernel_versions": projection.versions,
            "uncertainties": self._uncertainties(projection, state),
            "observations": state.get("observations", []),
        }

    @staticmethod
    def _answer_view(
        session: dict[str, Any], state: dict[str, Any], result: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            "status": "ok",
            "session_id": session["session_id"],
            "session_status": state.get("outcome") or ("completed" if state.get("phase") == "done" else "active"),
            "phase": state.get("phase"),
            "graded": result.get("graded"),
            "observations": result.get("observations", []),
            "uncertainties": result.get("uncertainties", []),
            "next_interaction": result.get("next_interaction"),
            "recommended_next_action": result.get("recommended_next_action", "continue_discovery"),
        }
