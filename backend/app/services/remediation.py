"""Deterministic remediation loop for evaluated learning attempts.

The module owns the product loop:

    wrong answer -> evidence-grounded explanation -> retry -> transfer variant
    -> evidence writeback

The LLM never chooses a teaching strategy here.  Strategy selection is a pure,
testable rule set driven by verified grader output and prior ineffective modes.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.learning import LearningAttempt, RemediationCase


DELIVERY_MODE_LABELS = {
    "contrast": "证据对照",
    "execution_trace": "执行追踪",
    "step_by_step": "分步拆解",
    "worked_example": "示例迁移",
}


def _text(value: Any, limit: int = 500) -> str:
    return str(value or "").strip()[:limit]


def _unique(values: list[Any]) -> list[str]:
    return list(dict.fromkeys(_text(value, 80) for value in values if _text(value, 80)))


def _unique_ids(values: list[Any]) -> list[int]:
    unique: list[int] = []
    for value in values:
        try:
            number = int(value)
        except (TypeError, ValueError):
            continue
        if number not in unique:
            unique.append(number)
    return unique


class RemediationStrategy:
    """Pure rules for choosing how to remediate an evaluated error."""

    CONCEPT_MODES = ("contrast", "step_by_step", "worked_example")
    EXERCISE_MODES = ("execution_trace", "step_by_step", "worked_example", "contrast")

    @classmethod
    def decide(
        cls,
        *,
        item_type: str,
        error_class: str,
        repeat_count: int = 1,
        ineffective_modes: list[str] | None = None,
        requested_mode: str | None = None,
    ) -> dict[str, Any]:
        candidates = list(
            cls.CONCEPT_MODES if item_type == "concept" else cls.EXERCISE_MODES
        )
        blocked = _unique(list(ineffective_modes or []))
        usable = [mode for mode in candidates if mode not in blocked] or candidates

        if requested_mode in candidates:
            preferred = requested_mode
            reason = "learner_requested_representation"
        elif error_class in {"runtime_error", "timeout", "exception"} and "execution_trace" in usable:
            preferred = "execution_trace"
            reason = "runtime_evidence_requires_trace"
        elif repeat_count > 1 and "step_by_step" in usable:
            preferred = "step_by_step"
            reason = "repeated_error_requires_decomposition"
        elif error_class in {"incomplete_model", "partial_coverage"} and "step_by_step" in usable:
            preferred = "step_by_step"
            reason = "partial_answer_requires_checklist"
        else:
            preferred = usable[0]
            reason = "first_available_evidence_fit"

        depth = "foundational" if repeat_count >= 3 else "guided" if repeat_count >= 2 else "concise"
        return {
            "policy_version": "remediation-v1",
            "strategy_code": f"{error_class}:{preferred}",
            "delivery_mode": preferred,
            "delivery_mode_label": DELIVERY_MODE_LABELS[preferred],
            "explanation_depth": depth,
            "reason_code": reason,
            "repeat_count": max(1, int(repeat_count)),
            "ineffective_modes": blocked,
            "candidate_modes": candidates,
            "decision_owner": "deterministic_policy",
        }


def _classify_error(item_type: str, evaluation: dict[str, Any]) -> tuple[str, str]:
    if item_type == "concept":
        expected = set(evaluation.get("answer_indexes") or [])
        actual = set(evaluation.get("user_answer_indexes") or [])
        if actual and actual < expected:
            return "incomplete_model", "遗漏必要条件"
        if actual - expected:
            return "concept_misconception", "错误概念辨析"
        return "concept_gap", "概念规则尚未稳定"

    results = list(evaluation.get("results") or [])
    if any(_text(item.get("stderr")) for item in results if isinstance(item, dict)):
        return "runtime_error", "运行时行为与预期不一致"
    passed = int(evaluation.get("passed") or 0)
    total = int(evaluation.get("total") or 0)
    if passed and total and passed < total:
        return "partial_coverage", "边界条件覆盖不足"
    if total == 0:
        return "missing_verification", "缺少可执行验证"
    return "output_mismatch", "输出与测试契约不一致"


def _build_evidence(
    item_type: str,
    item_snapshot: dict[str, Any],
    evaluation: dict[str, Any],
) -> dict[str, Any]:
    if item_type == "concept":
        options = list(item_snapshot.get("options") or [])
        expected_indexes = [int(index) for index in evaluation.get("answer_indexes") or []]
        actual_indexes = [int(index) for index in evaluation.get("user_answer_indexes") or []]
        return {
            "question": _text(item_snapshot.get("question"), 1500),
            "expected_indexes": expected_indexes,
            "actual_indexes": actual_indexes,
            "expected": [options[index] for index in expected_indexes if 0 <= index < len(options)],
            "actual": [options[index] for index in actual_indexes if 0 <= index < len(options)],
            "base_explanation": _text(item_snapshot.get("explanation"), 2000),
            "source_chunk_ids": list(item_snapshot.get("source_chunk_ids") or []),
            "assessment_meta": dict(item_snapshot.get("assessment_meta") or {}),
            "grader": "exact_match",
        }

    failures = [
        {
            "input": _text(item.get("input"), 200),
            "expected": _text(item.get("expected"), 300),
            "actual": _text(item.get("actual"), 300),
            "stderr": _text(item.get("stderr"), 500),
        }
        for item in list(evaluation.get("results") or [])
        if isinstance(item, dict) and not item.get("passed")
    ][:4]
    return {
        "title": _text(item_snapshot.get("title"), 300),
        "task": _text(item_snapshot.get("description"), 2000),
        "failed_cases": failures,
        "passed": int(evaluation.get("passed") or 0),
        "total": int(evaluation.get("total") or 0),
        "hints": [_text(item, 500) for item in list(item_snapshot.get("hints") or [])[:3]],
        "assessment_meta": dict(item_snapshot.get("assessment_meta") or {}),
        "grader": _text(item_snapshot.get("judge_mode") or "test_cases"),
    }


def _evidence_summary(evidence: dict[str, Any], item_type: str) -> tuple[str, str]:
    if item_type == "concept":
        actual = "、".join(evidence.get("actual") or []) or "未形成有效选择"
        expected = "、".join(evidence.get("expected") or []) or "题目给定的正确条件"
        return actual, expected
    failure = next(iter(evidence.get("failed_cases") or []), {})
    actual = _text(failure.get("stderr") or failure.get("actual") or "测试未通过")
    expected = _text(failure.get("expected") or "满足测试契约")
    return actual, expected


def _build_explanation(
    *, case_id: int | None, item_type: str, error_class: str,
    misconception_tag: str, evidence: dict[str, Any], strategy: dict[str, Any],
) -> dict[str, Any]:
    actual, expected = _evidence_summary(evidence, item_type)
    mode = strategy["delivery_mode"]
    base = _text(evidence.get("base_explanation"), 1200)

    if mode == "step_by_step":
        sections = [
            {"title": "1. 锁定证据", "content": f"本轮可核验现象是：{actual}。"},
            {"title": "2. 对照契约", "content": f"题目或测试要求的是：{expected}。"},
            {"title": "3. 修正规则", "content": base or f"先只修正「{misconception_tag}」对应的判断，再检查其他路径。"},
            {"title": "4. 独立重做", "content": "关闭讲解后重新作答；只有独立通过才形成掌握证据。"},
        ]
    elif mode == "worked_example":
        sections = [
            {"title": "已知示例", "content": f"把当前失败样例当作最小示例：实际为「{actual}」。"},
            {"title": "示例目标", "content": f"同一输入下，目标结果应为「{expected}」。"},
            {"title": "迁移提示", "content": base or "先说明规则为什么成立，再把同一规则迁移回原题。"},
        ]
    elif mode == "execution_trace":
        failure = next(iter(evidence.get("failed_cases") or []), {})
        sections = [
            {"title": "失败入口", "content": f"输入：{_text(failure.get('input')) or '当前失败用例'}"},
            {"title": "执行结果", "content": f"程序得到：{actual}"},
            {"title": "预期出口", "content": f"测试要求：{expected}"},
            {"title": "最小修正", "content": "沿输入→分支→输出逐步核对，只修改首次出现分歧的判断。"},
        ]
    else:
        sections = [
            {"title": "你的答案/结果", "content": actual},
            {"title": "正确要求", "content": expected},
            {"title": "差异根因", "content": base or f"当前证据符合「{misconception_tag}」，先修正这一条规则。"},
            {"title": "下一步", "content": "先重做原题；通过后再做变式，验证不是记住答案。"},
        ]

    return {
        "case_id": case_id,
        "generated_by": "deterministic_remediation_renderer",
        "policy_version": strategy["policy_version"],
        "delivery_mode": mode,
        "delivery_mode_label": DELIVERY_MODE_LABELS[mode],
        "error_class": error_class,
        "misconception_tag": misconception_tag,
        "sections": sections,
        "created_at": datetime.utcnow().isoformat(),
    }


def _fingerprint(item_type: str, item_id: int | None, evidence: dict[str, Any]) -> str:
    raw = json.dumps(
        {"item_type": item_type, "item_id": item_id, "evidence": evidence},
        ensure_ascii=False, sort_keys=True, default=str,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def create_remediation_case(
    db: AsyncSession,
    *,
    attempt: LearningAttempt,
    evidence_event_id: int,
    item_snapshot: dict[str, Any],
    evaluation: dict[str, Any],
) -> RemediationCase:
    existing = (await db.execute(select(RemediationCase).where(
        RemediationCase.source_attempt_id == attempt.id,
    ))).scalar_one_or_none()
    if existing:
        return existing

    error_class, misconception_tag = _classify_error(attempt.item_type, evaluation)
    evidence = _build_evidence(attempt.item_type, item_snapshot, evaluation)
    repeat_count = int((await db.execute(select(func.count(RemediationCase.id)).where(
        RemediationCase.learner_id == attempt.learner_id,
        RemediationCase.item_type == attempt.item_type,
        RemediationCase.item_id == attempt.item_id,
    ))).scalar_one() or 0) + 1
    recent_ineffective = (await db.execute(
        select(RemediationCase.ineffective_modes)
        .where(RemediationCase.learner_id == attempt.learner_id)
        .order_by(RemediationCase.updated_at.desc())
        .limit(8)
    )).scalars().all()
    known_ineffective = _unique([
        mode for modes in recent_ineffective for mode in list(modes or [])
    ])
    strategy = RemediationStrategy.decide(
        item_type=attempt.item_type,
        error_class=error_class,
        repeat_count=repeat_count,
        ineffective_modes=known_ineffective,
    )
    remediation = RemediationCase(
        learner_id=attempt.learner_id,
        project_id=attempt.project_id,
        checkpoint_id=attempt.checkpoint_id,
        source_attempt_id=attempt.id,
        item_type=attempt.item_type,
        item_id=attempt.item_id,
        status="explaining",
        error_fingerprint=_fingerprint(attempt.item_type, attempt.item_id, evidence),
        error_class=error_class,
        misconception_tag=misconception_tag,
        evidence=evidence,
        evidence_event_ids=[evidence_event_id],
        strategy=strategy,
        current_delivery_mode=strategy["delivery_mode"],
        ineffective_modes=known_ineffective,
        explanation_history=[],
    )
    db.add(remediation)
    await db.flush()
    explanation = _build_explanation(
        case_id=remediation.id, item_type=attempt.item_type,
        error_class=error_class, misconception_tag=misconception_tag,
        evidence=evidence, strategy=strategy,
    )
    remediation.explanation_history = [explanation]
    attempt.remediation_case_id = remediation.id
    attempt.attempt_role = "original"

    from app.services.learning_runtime import record_event
    started_event = await record_event(
        db,
        learner_id=attempt.learner_id,
        project_id=attempt.project_id,
        checkpoint_id=attempt.checkpoint_id,
        event_type="remediation_started",
        source="assessment",
        payload={
            "case_id": remediation.id,
            "attempt_id": attempt.id,
            "item_type": attempt.item_type,
            "item_id": attempt.item_id,
            "error_class": error_class,
            "misconception_tag": misconception_tag,
            "delivery_mode": strategy["delivery_mode"],
            "source_evidence_id": evidence_event_id,
        },
        provenance={"policy": "remediation-v1", "decision_owner": "deterministic_policy"},
        client_event_id=f"remediation:{remediation.id}:started",
    )
    remediation.evidence_event_ids = _unique_ids([
        *list(remediation.evidence_event_ids or []), started_event.id,
    ])
    return remediation


async def load_owned_case(
    db: AsyncSession, learner_id: int, case_id: int,
) -> RemediationCase | None:
    return (await db.execute(select(RemediationCase).where(
        RemediationCase.id == case_id,
        RemediationCase.learner_id == learner_id,
    ))).scalar_one_or_none()


async def request_explanation_mode(
    db: AsyncSession,
    *,
    remediation: RemediationCase,
    action: str,
) -> RemediationCase:
    requested = {
        "steps": "step_by_step",
        "example": "worked_example",
    }.get(action)
    blocked = list(remediation.ineffective_modes or [])
    previous = remediation.current_delivery_mode
    if action == "switch" and previous not in blocked:
        blocked.append(previous)

    retry_count = int((await db.execute(select(func.count(LearningAttempt.id)).where(
        LearningAttempt.remediation_case_id == remediation.id,
        LearningAttempt.attempt_role == "retry",
    ))).scalar_one() or 0)
    strategy = RemediationStrategy.decide(
        item_type=remediation.item_type,
        error_class=remediation.error_class,
        repeat_count=max(1, retry_count + 1),
        ineffective_modes=blocked,
        requested_mode=requested,
    )
    explanation = _build_explanation(
        case_id=remediation.id,
        item_type=remediation.item_type,
        error_class=remediation.error_class,
        misconception_tag=remediation.misconception_tag,
        evidence=dict(remediation.evidence or {}),
        strategy=strategy,
    )
    remediation.ineffective_modes = blocked
    remediation.strategy = strategy
    remediation.current_delivery_mode = strategy["delivery_mode"]
    remediation.explanation_history = [
        *list(remediation.explanation_history or []), explanation,
    ][-12:]
    remediation.status = "explaining"
    remediation.updated_at = datetime.utcnow()

    from app.services.learning_runtime import record_event
    recorded_ids: list[int] = []
    if action == "switch":
        rejected_event = await record_event(
            db, learner_id=remediation.learner_id,
            project_id=remediation.project_id, checkpoint_id=remediation.checkpoint_id,
            event_type="remediation_mode_rejected", source="ui",
            payload={"case_id": remediation.id, "ineffective_mode": previous,
                     "next_mode": strategy["delivery_mode"]},
            provenance={"explicit_user_action": "switch_explanation"},
            client_event_id=f"remediation:{remediation.id}:mode-rejected:{len(blocked)}",
        )
        recorded_ids.append(rejected_event.id)
    explanation_event = await record_event(
        db, learner_id=remediation.learner_id,
        project_id=remediation.project_id, checkpoint_id=remediation.checkpoint_id,
        event_type="remediation_explanation_requested", source="ui",
        payload={"case_id": remediation.id, "action": action,
                 "delivery_mode": strategy["delivery_mode"]},
        provenance={"policy": "remediation-v1"},
        client_event_id=(
            f"remediation:{remediation.id}:explanation:"
            f"{len(remediation.explanation_history or [])}:{action}"
        ),
    )
    remediation.evidence_event_ids = _unique_ids([
        *list(remediation.evidence_event_ids or []), *recorded_ids, explanation_event.id,
    ])
    return remediation


def _make_variant(remediation: RemediationCase) -> dict[str, Any]:
    evidence = dict(remediation.evidence or {})
    variant_contract = dict(
        (evidence.get("assessment_meta") or {}).get("variant") or {}
    )
    if remediation.item_type == "concept":
        contract_options = list(variant_contract.get("options") or [])
        contract_answers = [
            int(index) for index in variant_contract.get("answer_indexes") or []
            if str(index).lstrip("-").isdigit()
        ]
        if (
            variant_contract.get("type") == "concept_choice"
            and len(contract_options) >= 2
            and contract_answers
            and all(0 <= index < len(contract_options) for index in contract_answers)
        ):
            return {
                "type": "concept_choice",
                "prompt": _text(variant_contract.get("prompt"), 1500),
                "options": [_text(option, 500) for option in contract_options],
                "answer_indexes": sorted(set(contract_answers)),
                "multiple": len(set(contract_answers)) > 1,
            }
        options = list(evidence.get("expected") or []) + list(evidence.get("actual") or [])
        options = list(dict.fromkeys(_text(item, 500) for item in options if _text(item, 500)))
        if len(options) < 2:
            options = ["满足题目中的完整条件", "只满足部分条件"]
        # Deterministic rotation avoids leaking the original option position.
        rotated = options[1:] + options[:1]
        correct_text = set(evidence.get("expected") or [options[0]])
        answer_indexes = [index for index, option in enumerate(rotated) if option in correct_text]
        return {
            "type": "concept_choice",
            "prompt": f"变式验证：换一个选项顺序，重新判断——{evidence.get('question', '')}",
            "options": rotated,
            "answer_indexes": answer_indexes or [len(rotated) - 1],
            "multiple": len(answer_indexes) > 1,
        }

    if variant_contract.get("type") == "predict_output" and _text(variant_contract.get("expected")):
        return {
            "type": "predict_output",
            "prompt": _text(variant_contract.get("prompt"), 1500),
            "input": _text(variant_contract.get("input"), 300),
            "expected": _text(variant_contract.get("expected"), 300),
            "answer_format": "text",
        }
    failure = next(iter(evidence.get("failed_cases") or []), {})
    expected = _text(failure.get("expected") or "满足原测试契约", 300)
    return {
        "type": "predict_output",
        "prompt": "变式验证：先不运行程序，根据修正后的规则预测这个边界输入的正确输出。",
        "input": _text(failure.get("input") or "原失败边界输入", 300),
        "expected": expected,
        "answer_format": "text",
    }


async def ensure_variant(remediation: RemediationCase) -> RemediationCase:
    if not remediation.variant_payload:
        remediation.variant_payload = _make_variant(remediation)
    remediation.status = "variant_ready"
    remediation.updated_at = datetime.utcnow()
    return remediation


async def apply_retry_result(
    db: AsyncSession,
    *,
    remediation: RemediationCase,
    attempt: LearningAttempt,
    passed: bool,
    evidence_event_id: int,
) -> RemediationCase:
    attempt.remediation_case_id = remediation.id
    attempt.attempt_role = "retry"
    remediation.retry_attempt_id = attempt.id
    remediation.evidence_event_ids = _unique_ids([
        *list(remediation.evidence_event_ids or []), evidence_event_id,
    ])
    remediation.updated_at = datetime.utcnow()

    from app.services.learning_runtime import record_event
    retry_event = await record_event(
        db, learner_id=remediation.learner_id,
        project_id=remediation.project_id, checkpoint_id=remediation.checkpoint_id,
        event_type="remediation_retry_evaluated", source="assessment",
        payload={"case_id": remediation.id, "attempt_id": attempt.id,
                 "passed": bool(passed), "delivery_mode": remediation.current_delivery_mode,
                 "source_evidence_id": evidence_event_id},
        confidence=0.95,
        provenance={"grader": "existing_assessment_pipeline"},
        client_event_id=f"remediation:{remediation.id}:retry:{attempt.id}",
    )
    remediation.evidence_event_ids = _unique_ids([
        *list(remediation.evidence_event_ids or []), retry_event.id,
    ])
    if passed:
        await ensure_variant(remediation)
        return remediation

    blocked = list(remediation.ineffective_modes or [])
    if remediation.current_delivery_mode not in blocked:
        blocked.append(remediation.current_delivery_mode)
    remediation.ineffective_modes = blocked
    strategy = RemediationStrategy.decide(
        item_type=remediation.item_type,
        error_class=remediation.error_class,
        repeat_count=len([
            attempt for attempt in list(remediation.explanation_history or [])
        ]) + 1,
        ineffective_modes=blocked,
    )
    remediation.strategy = strategy
    remediation.current_delivery_mode = strategy["delivery_mode"]
    remediation.explanation_history = [
        *list(remediation.explanation_history or []),
        _build_explanation(
            case_id=remediation.id, item_type=remediation.item_type,
            error_class=remediation.error_class,
            misconception_tag=remediation.misconception_tag,
            evidence=dict(remediation.evidence or {}), strategy=strategy,
        ),
    ][-12:]
    remediation.status = "explaining"
    rejected_event = await record_event(
        db, learner_id=remediation.learner_id,
        project_id=remediation.project_id, checkpoint_id=remediation.checkpoint_id,
        event_type="remediation_mode_rejected", source="assessment",
        payload={"case_id": remediation.id,
                 "ineffective_mode": blocked[-1] if blocked else "",
                 "next_mode": strategy["delivery_mode"],
                 "reason": "failed_retry"},
        provenance={"inferred_from": "graded_failed_retry"},
        client_event_id=f"remediation:{remediation.id}:retry-failed-mode:{attempt.id}",
    )
    remediation.evidence_event_ids = _unique_ids([
        *list(remediation.evidence_event_ids or []), rejected_event.id,
    ])
    return remediation


def _public_variant(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value for key, value in dict(payload or {}).items()
        if key not in {"answer_indexes", "expected"}
    }


async def submit_variant(
    db: AsyncSession,
    *,
    remediation: RemediationCase,
    submission: dict[str, Any],
) -> tuple[RemediationCase, dict[str, Any]]:
    await ensure_variant(remediation)
    variant = dict(remediation.variant_payload or {})
    if variant.get("type") == "concept_choice":
        expected = sorted(int(index) for index in variant.get("answer_indexes") or [])
        actual = sorted(int(index) for index in submission.get("answer_indexes") or [])
        correct = bool(actual) and actual == expected
        stored_result = {"correct": correct, "answer_indexes": expected,
                         "user_answer_indexes": actual}
        public_result = {"correct": correct, "user_answer_indexes": actual}
    else:
        expected_text = _text(variant.get("expected"), 300)
        actual_text = _text(submission.get("answer_text"), 300)
        normalize = lambda value: " ".join(value.split()).casefold()
        correct = bool(actual_text) and normalize(actual_text) == normalize(expected_text)
        stored_result = {"correct": correct, "expected": expected_text, "actual": actual_text}
        public_result = {"correct": correct, "actual": actual_text}

    from app.services.learning_runtime import create_attempt, record_event
    attempt = await create_attempt(
        db, learner_id=remediation.learner_id,
        checkpoint_id=remediation.checkpoint_id,
        item_type="remediation_variant", item_id=remediation.id,
        submission=submission, result=stored_result, assistance_level="none",
    )
    attempt.remediation_case_id = remediation.id
    attempt.attempt_role = "variant"
    remediation.variant_attempt_id = attempt.id
    remediation.status = "completed" if correct else "variant_ready"
    remediation.completed_at = datetime.utcnow() if correct else None
    remediation.updated_at = datetime.utcnow()
    event = await record_event(
        db, learner_id=remediation.learner_id,
        project_id=remediation.project_id, checkpoint_id=remediation.checkpoint_id,
        event_type="remediation_variant_evaluated", source="assessment",
        payload={"case_id": remediation.id, "attempt_id": attempt.id,
                 "correct": correct, "variant_type": variant.get("type")},
        confidence=0.95,
        provenance={"grader": "deterministic_variant_contract"},
        client_event_id=f"remediation:{remediation.id}:variant:{attempt.id}",
    )
    remediation.evidence_event_ids = _unique_ids([
        *list(remediation.evidence_event_ids or []), event.id,
    ])
    if correct:
        completed = await record_event(
            db, learner_id=remediation.learner_id,
            project_id=remediation.project_id, checkpoint_id=remediation.checkpoint_id,
            event_type="remediation_completed", source="assessment",
            payload={"case_id": remediation.id,
                     "source_attempt_id": remediation.source_attempt_id,
                     "retry_attempt_id": remediation.retry_attempt_id,
                     "variant_attempt_id": attempt.id,
                     "delivery_mode": remediation.current_delivery_mode,
                     "evidence_event_ids": remediation.evidence_event_ids},
            confidence=1.0,
            provenance={"loop": "wrong-explain-retry-variant-writeback"},
            client_event_id=f"remediation:{remediation.id}:completed",
        )
        remediation.evidence_event_ids = _unique_ids([
            *list(remediation.evidence_event_ids or []), completed.id,
        ])
        from app.services.review import schedule_after_remediation
        await schedule_after_remediation(db, remediation)
    else:
        from app.services.review import mark_remediation_pending
        await mark_remediation_pending(db, remediation)
    return remediation, public_result


def _public_evidence(payload: dict[str, Any]) -> dict[str, Any]:
    result = dict(payload or {})
    assessment_meta = dict(result.get("assessment_meta") or {})
    assessment_meta.pop("variant", None)
    if assessment_meta:
        result["assessment_meta"] = assessment_meta
    else:
        result.pop("assessment_meta", None)
    return result


def serialize_case(remediation: RemediationCase) -> dict[str, Any]:
    history = list(remediation.explanation_history or [])
    return {
        "id": remediation.id,
        "status": remediation.status,
        "item_type": remediation.item_type,
        "item_id": remediation.item_id,
        "source_attempt_id": remediation.source_attempt_id,
        "error_class": remediation.error_class,
        "misconception_tag": remediation.misconception_tag,
        "evidence": _public_evidence(dict(remediation.evidence or {})),
        "evidence_event_ids": list(remediation.evidence_event_ids or []),
        "strategy": dict(remediation.strategy or {}),
        "current_delivery_mode": remediation.current_delivery_mode,
        "ineffective_modes": list(remediation.ineffective_modes or []),
        "explanation": history[-1] if history else {},
        "explanation_count": len(history),
        "retry_attempt_id": remediation.retry_attempt_id,
        "variant_attempt_id": remediation.variant_attempt_id,
        "variant": _public_variant(dict(remediation.variant_payload or {})),
        "available_actions": {
            "switch": remediation.status != "completed",
            "steps": remediation.status != "completed",
            "example": remediation.status != "completed",
            "retry": remediation.status not in {"completed", "variant_ready"},
            "variant": remediation.status in {"variant_ready", "completed"},
        },
        "created_at": remediation.created_at.isoformat() if remediation.created_at else None,
        "completed_at": remediation.completed_at.isoformat() if remediation.completed_at else None,
    }
