"""MemoryGraph：由 KernelState 派生 MemoryFact / MemoryModule / MemoryClaim。

派生视图不产生新事实；每条事实都带 evidence_refs 与 kernel_mutations 追溯链。
对应 docs/FIVE_KERNEL_MEMORY_GRAPH.md。

设计取舍：structure 核（会话位置/已见题）是瞬态进度信息，不进入长期记忆；
长期记忆由 knowledge / practice / value / human 四核派生。
"""

from __future__ import annotations

from typing import Any

from backend.learner_discovery.models import (
    KernelProjection,
    Scope,
    stable_id,
)

DURABLE_KERNELS = ("knowledge", "practice", "value", "human")


def _fact_id(kernel: str, subject: str, suffix: str, scope: Scope) -> str:
    return stable_id(
        "FACT",
        scope.learner_id or "",
        scope.project_id or "",
        kernel,
        subject,
        suffix,
    )


def build_facts(projection: KernelProjection) -> list[dict[str, Any]]:
    scope = projection.scope
    kernels = projection.kernels
    facts: list[dict[str, Any]] = []

    knowledge = kernels.get("knowledge", {})
    for kc_id, kc in knowledge.get("kcs", {}).items():
        status = kc.get("status", "untested")
        if status == "untested":
            continue
        evidence = kc.get("evidence", {})
        independent = int(evidence.get("distinct_independent_correct", 0) or 0)
        wrong = int(evidence.get("wrong", 0) or 0)
        assisted = int(evidence.get("assisted", 0) or 0)
        facts.append({
            "fact_id": _fact_id("knowledge", kc_id, status, scope),
            "kernel": "knowledge",
            "subject": kc_id,
            "claim": (
                f"知识点 {kc_id} 当前状态为 {status}："
                f"{independent} 道不同题独立正确、{wrong} 次答错、{assisted} 次辅助成功"
            ),
            "status": status,
            "confidence": float(kc.get("confidence", 0.0)),
            "evidence_refs": list(evidence.get("distinct_question_ids", [])),
        })
        for candidate in kc.get("misconception_candidates", []):
            facts.append({
                "fact_id": _fact_id(
                    "knowledge", kc_id,
                    "misconception_" + str(candidate.get("misconception_id", "x")), scope,
                ),
                "kernel": "knowledge",
                "subject": kc_id,
                "claim": f"误解候选 {candidate.get('misconception_id')}：出现 {candidate.get('count', 0)} 次",
                "status": "candidate",
                "confidence": 0.6,
                "evidence_refs": list(candidate.get("events", [])),
            })

    practice = kernels.get("practice", {})
    for kc_id, entry in practice.get("independence", {}).items():
        level = entry.get("level", "untested")
        if level == "untested":
            continue
        facts.append({
            "fact_id": _fact_id("practice", kc_id, level, scope),
            "kernel": "practice",
            "subject": kc_id,
            "claim": f"知识点 {kc_id} 独立性为 {level}",
            "status": level,
            "confidence": 0.7 if level in ("applied", "transferred") else 0.5,
            "evidence_refs": list(
                entry.get("independent_events", []) + entry.get("assisted_events", [])
                + entry.get("transfer_events", [])
            ),
        })

    value = kernels.get("value", {})
    confirmed = value.get("confirmed_goal")
    if confirmed:
        facts.append({
            "fact_id": _fact_id("value", confirmed, "confirmed", scope),
            "kernel": "value",
            "subject": confirmed,
            "claim": f"已确认学习目标 {confirmed}（{value.get('confirmed_goal_label') or ''}）",
            "status": "confirmed",
            "confidence": 0.8,
            "evidence_refs": [],
        })
    for candidate in value.get("goal_candidates", []):
        if candidate.get("confirmed"):
            continue
        facts.append({
            "fact_id": _fact_id("value", str(candidate.get("text", "goal"))[:24], "candidate", scope),
            "kernel": "value",
            "subject": "goal",
            "claim": f"目标候选：{candidate.get('text', '')}（待确认）",
            "status": "candidate",
            "confidence": 0.5,
            "evidence_refs": list(candidate.get("events", [])),
        })

    human = kernels.get("human", {})
    for preference in human.get("preferences", []):
        facts.append({
            "fact_id": _fact_id("human", str(preference.get("mode", "mode"))[:24], "preference", scope),
            "kernel": "human",
            "subject": "preference",
            "claim": f"偏好候选：{preference.get('mode', '')}（{preference.get('kind', 'preference')}）",
            "status": "candidate",
            "confidence": 0.6,
            "evidence_refs": list(preference.get("events", [])),
        })

    return facts


def build_claims(
    projection: KernelProjection, facts: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    scope = projection.scope
    kernels = projection.kernels
    knowledge = kernels.get("knowledge", {})
    practice = kernels.get("practice", {})
    claims: list[dict[str, Any]] = []

    stable_kcs = [
        kc_id for kc_id, kc in knowledge.get("kcs", {}).items()
        if kc.get("status") == "stable"
    ]
    if stable_kcs:
        claims.append({
            "claim_id": stable_id("CLAIM", scope.learner_id or "", scope.project_id or "", "begin_learning"),
            "kernel": "knowledge",
            "statement": f"已有多道独立正确证据的知识点（{len(stable_kcs)} 个），建议进入应用练习。",
            "status": "active",
            "fact_ids": [_fact_id("knowledge", kc_id, "stable", scope) for kc_id in stable_kcs],
            "evidence_trace": [],
        })

    misconception_kcs = [
        kc_id for kc_id, kc in knowledge.get("kcs", {}).items()
        if kc.get("misconception_candidates")
    ]
    if misconception_kcs:
        claims.append({
            "claim_id": stable_id("CLAIM", scope.learner_id or "", scope.project_id or "", "remediation"),
            "kernel": "knowledge",
            "statement": f"检测到误解候选（{len(misconception_kcs)} 个知识点），建议先纠错再继续。",
            "status": "active",
            "fact_ids": [
                _fact_id("knowledge", kc_id, "candidate", scope) for kc_id in misconception_kcs
            ],
            "evidence_trace": [],
        })

    candidate_kcs = [
        kc_id for kc_id, kc in knowledge.get("kcs", {}).items()
        if kc.get("status") == "candidate"
    ]
    verified_or_stable = [
        kc_id for kc_id, kc in knowledge.get("kcs", {}).items()
        if kc.get("status") in ("verified_once", "stable")
    ]
    if candidate_kcs and not verified_or_stable:
        claims.append({
            "claim_id": stable_id("CLAIM", scope.learner_id or "", scope.project_id or "", "insufficient"),
            "kernel": "knowledge",
            "statement": "证据不足：仅有候选/错误证据，建议继续摸底或进入学习后补证。",
            "status": "active",
            "fact_ids": [_fact_id("knowledge", kc_id, "candidate", scope) for kc_id in candidate_kcs],
            "evidence_trace": [],
        })

    assisted_practice = [
        kc_id for kc_id, entry in practice.get("independence", {}).items()
        if entry.get("level") == "assisted"
    ]
    if assisted_practice:
        claims.append({
            "claim_id": stable_id("CLAIM", scope.learner_id or "", scope.project_id or "", "assisted"),
            "kernel": "practice",
            "statement": f"{len(assisted_practice)} 个知识点仅在辅助下成功，未达到独立实践水平。",
            "status": "active",
            "fact_ids": [_fact_id("practice", kc_id, "assisted", scope) for kc_id in assisted_practice],
            "evidence_trace": [],
        })

    return claims


def build_modules(
    projection: KernelProjection, facts: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    scope = projection.scope
    by_kernel: dict[str, list[dict[str, Any]]] = {}
    for fact in facts:
        by_kernel.setdefault(str(fact["kernel"]), []).append(fact)
    modules: list[dict[str, Any]] = []
    for kernel in DURABLE_KERNELS:
        items = by_kernel.get(kernel, [])
        if not items:
            continue
        modules.append({
            "module_id": stable_id("MOD", scope.learner_id or "", scope.project_id or "", kernel),
            "kernel": kernel,
            "summary": {
                "fact_count": len(items),
                "top_claims": [f["claim"] for f in items[:3]],
                "avg_confidence": round(
                    sum(float(f.get("confidence", 0.0)) for f in items) / len(items), 3
                ),
            },
        })
    return modules


def build_memory_graph(projection: KernelProjection) -> dict[str, Any]:
    """从投影派生完整 Memory Graph（facts/modules/claims）。"""
    facts = build_facts(projection)
    modules = build_modules(projection, facts)
    claims = build_claims(projection, facts)
    return {"facts": facts, "modules": modules, "claims": claims}
