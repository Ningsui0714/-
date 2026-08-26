"""Structured context and block helpers for generated lesson explanations.

The helpers in this module keep the existing lesson API compatible while
making the explanation contract explicit.  They are intentionally deterministic:
the model may choose presentation, but the server owns scope, evidence and
cache identity.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any


EXPLANATION_CONTEXT_VERSION = "explanation-context-v1"
# v2：讲解正文已改为本地引擎生成（星火直连 + 确定性模板），旧缓存哈希失配后
# 自动置 queued 重新生成，避免复用星辰工作流时期的旧讲解。
EXPLANATION_GENERATOR_VERSION = "rich-blocks-v2"
EXPLANATION_BLOCK_SCHEMA_VERSION = "explanation-block-v1"


CAPABILITY_POOLS: dict[str, tuple[str, ...]] = {
    "conceptual": ("concept", "example", "steps", "warning", "check"),
    "code": ("concept", "code", "example", "steps", "warning", "workplace", "check"),
    "quantitative": ("concept", "formula", "example", "steps", "diagram", "warning", "check"),
    "process": ("concept", "steps", "diagram", "example", "warning", "check"),
    "comparison": ("concept", "comparison", "example", "warning", "check"),
    "tool": ("concept", "steps", "example", "diagram", "warning", "workplace", "check"),
    "practice": ("concept", "steps", "example", "workplace", "warning", "check"),
    "project": ("concept", "steps", "example", "workplace", "warning", "check"),
    "assessment": ("concept", "example", "warning", "check"),
}


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _source_refs(evidence_pack: dict[str, Any]) -> list[dict[str, str]]:
    references: list[dict[str, str]] = []
    for item in _as_list(evidence_pack.get("evidence")):
        if not isinstance(item, dict):
            continue
        reference = {
            "title": str(item.get("title") or item.get("source") or "").strip(),
            "source": str(item.get("source") or "").strip(),
            "url": str(item.get("url") or "").strip(),
            "verification_state": str(item.get("verification_state") or "").strip(),
        }
        if any(reference.values()):
            references.append(reference)
    return references


def capability_pool_for_knowledge_type(knowledge_type: str) -> list[str]:
    kind = str(knowledge_type or "conceptual").strip().lower()
    if kind in CAPABILITY_POOLS:
        return list(CAPABILITY_POOLS[kind])
    if "code" in kind or "编程" in kind:
        return list(CAPABILITY_POOLS["code"])
    if "流程" in kind or "process" in kind:
        return list(CAPABILITY_POOLS["process"])
    return list(CAPABILITY_POOLS["conceptual"])


def _stable_hash_payload(context: dict[str, Any]) -> dict[str, Any]:
    target = _as_dict(context.get("current_knowledge_point"))
    goal = _as_dict(context.get("learning_goal"))
    plan_step = _as_dict(context.get("plan_step"))
    assessment = _as_dict(context.get("initial_assessment_context"))
    evidence = _as_dict(assessment.get("evidence"))
    contract = _as_dict(context.get("teaching_contract"))
    source_refs = [
        {
            "title": str(item.get("title") or ""),
            "source": str(item.get("source") or ""),
            "url": str(item.get("url") or ""),
            "verification_state": str(item.get("verification_state") or ""),
        }
        for item in _as_list(context.get("source_refs"))
        if isinstance(item, dict)
    ]
    return {
        "context_version": EXPLANATION_CONTEXT_VERSION,
        "generator_version": EXPLANATION_GENERATOR_VERSION,
        "goal": {
            "goal_id": str(goal.get("goal_id") or ""),
            "goal_name": str(goal.get("goal_name") or ""),
            "constraints": goal.get("constraints") if isinstance(goal.get("constraints"), dict) else {},
        },
        "target": {
            "knowledge_point_id": str(target.get("knowledge_point_id") or ""),
            "knowledge_point_name": str(target.get("knowledge_point_name") or ""),
            "knowledge_type": str(target.get("knowledge_type") or ""),
        },
        "plan_step": {
            key: plan_step.get(key)
            for key in ("step_id", "learning_objective", "stage_id", "difficulty", "prerequisites")
            if key in plan_step
        },
        "assessment": {
            "basis": str(assessment.get("basis") or ""),
            "coverage_status": str(assessment.get("coverage_status") or ""),
            "evidence_status": str(evidence.get("evidence_status") or ""),
            "source_event_ids": sorted(str(item) for item in _as_list(evidence.get("source_event_ids"))),
            "error_focus": assessment.get("error_focus") if isinstance(assessment.get("error_focus"), dict) else {},
        },
        "learner_preferences": context.get("learner_preferences") if isinstance(context.get("learner_preferences"), dict) else {},
        "contract": {
            "teaching_contract_id": str(contract.get("teaching_contract_id") or ""),
            "contract_version": str(contract.get("contract_version") or ""),
            "knowledge_point_version": str(contract.get("knowledge_point_version") or ""),
            "effective_at": str(contract.get("effective_at") or ""),
        },
        "source_refs": sorted(source_refs, key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True)),
    }


def explanation_context_hash(context: dict[str, Any]) -> str:
    payload = json.dumps(
        _stable_hash_payload(context),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def build_explanation_context(
    context: dict[str, Any],
    *,
    teaching_contract: dict[str, Any] | None = None,
    evidence_pack: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return an explicit, serializable context for the explanation workflow."""
    built = deepcopy(context)
    if teaching_contract:
        built["teaching_contract"] = deepcopy(teaching_contract)
    if evidence_pack is not None:
        built["web_evidence_pack"] = deepcopy(evidence_pack)
        built["source_refs"] = _source_refs(evidence_pack)
    contract = _as_dict(built.get("teaching_contract"))
    target = _as_dict(built.get("current_knowledge_point"))
    outcomes = [item for item in _as_list(contract.get("outcomes")) if isinstance(item, dict)]
    built["explanation_context_version"] = EXPLANATION_CONTEXT_VERSION
    built["explanation_generator_version"] = EXPLANATION_GENERATOR_VERSION
    built["required_outcome_ids"] = [str(item.get("outcome_id") or "") for item in outcomes if item.get("outcome_id")]
    built["missing_outcome_ids"] = list(built["required_outcome_ids"])
    built["explanation_scope"] = {
        "required_concept_ids": [str(item.get("concept_id") or "") for item in _as_list(contract.get("concepts")) if isinstance(item, dict) and item.get("concept_id")],
        "excluded_scope": [str(item) for item in _as_list(contract.get("excluded_scope")) if str(item).strip()],
        "immutable_facts": [str(item) for item in _as_list(contract.get("immutable_facts")) if str(item).strip()],
    }
    built["explanation_policy"] = {
        "capability_pool": capability_pool_for_knowledge_type(str(target.get("knowledge_type") or "conceptual")),
        "allowed_block_types": capability_pool_for_knowledge_type(str(target.get("knowledge_type") or "conceptual")),
        "selection_rule": "优先覆盖必讲 outcome，再从能力池选择能补足当前缺失目标的区块；无可靠资料时不要强行生成该区块。",
        "route_content_owner": "learning_map_and_plan_brief",
        "practice_owner": "assessment_and_practice_modules",
        "personalization_boundary": _as_dict(contract.get("personalization_boundary")),
    }
    built["context_hash"] = explanation_context_hash(built)
    return built


def normalize_explanation_block(block: dict[str, Any]) -> dict[str, Any]:
    """Add Rich Block aliases without removing legacy fields."""
    normalized = dict(block)
    block_type = str(normalized.get("block_type") or normalized.get("type") or "content").strip().lower()
    normalized.setdefault("type", block_type)
    normalized["block_type"] = block_type
    normalized.setdefault("title", "")
    normalized.setdefault("content", str(normalized.get("markdown") or ""))
    if not isinstance(normalized.get("data"), dict):
        normalized["data"] = {
            key: normalized[key]
            for key in ("items", "code", "language", "formula", "steps", "claims", "check")
            if key in normalized
        }
    if not isinstance(normalized.get("source_refs"), list):
        source = str(normalized.get("source") or "").strip()
        normalized["source_refs"] = [{"source": source}] if source else []
    normalized.setdefault("coverage_concept_ids", list(_as_list(normalized.get("concept_ids"))))
    normalized.setdefault("coverage_outcome_ids", list(_as_list(normalized.get("outcome_ids"))))
    normalized.setdefault("schema_version", EXPLANATION_BLOCK_SCHEMA_VERSION)
    return normalized


def normalize_explanation_blocks(blocks: list[Any]) -> list[dict[str, Any]]:
    return [normalize_explanation_block(block) for block in blocks if isinstance(block, dict)]
