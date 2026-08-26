from __future__ import annotations

from copy import deepcopy

import httpx
import pytest

from app.services.learning_task_plan_gateway import (
    LearningTaskPlanError,
    LearningTaskPlanGateway,
)


def _run() -> dict:
    run_id = "run_0123456789abcdef0123456789abcdef"
    fingerprint = "a" * 64
    return {
        "run_id": run_id,
        "phase": "CONTRACT_READY",
        "status": "active",
        "checkpoint_version": 1,
        "task_contract": {
            "raw_input": "Linux系统安装与基础配置",
            "input_level": "single_work_task",
            "semantic_fingerprint": fingerprint,
        },
        "plan": {
            "schema_version": "learning-work-task-plan-v1",
            "run_id": run_id,
            "plan_version": 1,
            "goal": "将Linux系统安装与基础配置转化为可验收的学习型工作任务。",
            "task_contract_fingerprint": fingerprint,
            "success_criteria": ["语义不变", "步骤可执行", "结果可验收"],
            "unknowns": [{
                "unknown_id": "operation_facts",
                "question": "实际作业顺序和验收点是什么？",
                "required_evidence": "official_or_upstream",
                "blocking": True,
            }],
            "work_packages": [
                {
                    "package_id": "wp_evidence",
                    "agent_role": "evidence_explorer",
                    "objective": "检索并验证任务所需的真实作业证据。",
                    "depends_on": [],
                    "allowed_tools": ["task_database", "evidence_verifier"],
                    "expected_artifact": "evidence_ledger",
                    "completion_condition": "任务事实均有可追溯来源和可信度。",
                },
                {
                    "package_id": "wp_candidates",
                    "agent_role": "candidate_planner",
                    "objective": "根据已验证证据形成候选任务步骤。",
                    "depends_on": ["wp_evidence"],
                    "allowed_tools": ["candidate_generator"],
                    "expected_artifact": "candidate_set",
                    "completion_condition": "至少一个候选具备动作产物和验收点。",
                },
            ],
            "repair_budget": 2,
            "stop_conditions": ["任务语义发生变化时停止。"],
        },
        "state": {
            "schema_version": "learning-work-task-agent-state-v1",
            "phase": "CONTRACT_READY",
        },
        "next_actions": ["审核并提交 TaskPlan"],
    }


@pytest.mark.asyncio
async def test_plan_gateway_creates_and_confirms_remote_plan():
    current = _run()
    calls: list[tuple[str, str]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal current
        calls.append((request.method, request.url.path))
        if request.method == "POST" and request.url.path.endswith("/runs"):
            return httpx.Response(200, json=current)
        if request.method == "GET":
            return httpx.Response(200, json=current)
        submitted = __import__("json").loads(request.content)["plan"]
        assert submitted["plan_version"] == 2
        current = deepcopy(current)
        current["phase"] = "PLAN_READY"
        current["checkpoint_version"] = 2
        current["plan"] = submitted
        return httpx.Response(200, json=current)

    gateway = LearningTaskPlanGateway(
        base_url="https://plan.example",
        transport=httpx.MockTransport(handler),
    )
    created = await gateway.create("Linux系统安装与基础配置")
    confirmed = await gateway.confirm(created["run_id"], expected_plan_version=1)

    assert created["phase"] == "CONTRACT_READY"
    assert confirmed["phase"] == "PLAN_READY"
    assert confirmed["plan"]["plan_version"] == 2
    assert calls[-1][0] == "POST"


@pytest.mark.asyncio
async def test_plan_gateway_rejects_hidden_or_invalid_plan_fields():
    invalid = _run()
    invalid["plan"]["reasoning"] = "hidden chain of thought"

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=invalid)

    gateway = LearningTaskPlanGateway(
        base_url="https://plan.example",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(LearningTaskPlanError, match="不符合契约"):
        await gateway.create("Linux系统安装与基础配置")


@pytest.mark.asyncio
async def test_plan_gateway_rejects_cyclic_work_packages():
    invalid = _run()
    invalid["plan"]["work_packages"][0]["depends_on"] = ["wp_candidates"]

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=invalid)

    gateway = LearningTaskPlanGateway(
        base_url="https://plan.example",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(LearningTaskPlanError, match="依赖存在环"):
        await gateway.create("Linux系统安装与基础配置")
