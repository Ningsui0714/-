from __future__ import annotations

from copy import deepcopy

import pytest

from app.services.learning_task_plan_orchestrator import (
    build_planning_analysis,
    replan_analysis,
)


def _run() -> dict:
    run_id = "run_1234567890abcdef1234567890abcdef"
    fingerprint = "c" * 64
    packages = [
        ("wp_contract", "task_contract_compiler", [], "task_contract"),
        ("wp_evidence", "evidence_explorer", ["wp_contract"], "evidence_ledger"),
        ("wp_candidates", "candidate_planner", ["wp_contract", "wp_evidence"], "candidate_set"),
        ("wp_review", "critic_committee", ["wp_candidates"], "critic_report"),
        ("wp_publish", "artifact_publisher", ["wp_review"], "delivery_bundle"),
    ]
    return {
        "schema_version": "learning-work-task-agent-state-v1",
        "run_id": run_id,
        "phase": "EVIDENCE_READY",
        "status": "active",
        "checkpoint_version": 2,
        "task_contract": {
            "raw_input": "部署企业园区网络并完成连通性验收",
            "input_level": "single_work_task",
            "semantic_fingerprint": fingerprint,
        },
        "plan": {
            "schema_version": "learning-work-task-plan-v1",
            "run_id": run_id,
            "plan_version": 2,
            "goal": "将企业园区网络部署任务转化为可执行、可验收的学习型工作任务。",
            "task_contract_fingerprint": fingerprint,
            "success_criteria": ["语义不变", "步骤可执行", "结果可验收"],
            "unknowns": [],
            "work_packages": [{
                "package_id": package_id,
                "agent_role": role,
                "objective": f"完成 {package_id} 对应的受控规划活动。",
                "depends_on": dependencies,
                "allowed_tools": ["task_database"],
                "expected_artifact": artifact,
                "completion_condition": f"{artifact} 已生成并通过结构校验。",
            } for package_id, role, dependencies, artifact in packages],
            "repair_budget": 2,
            "stop_conditions": ["出现安全或权限冲突时停止并请求人工确认。"],
        },
        "state": {
            "phase": "EVIDENCE_READY",
            "evidence_ledger": {
                "status": "ready",
                "entries": [
                    {"evidence_id": "ev_network_01", "source": "official-standard"},
                    {"evidence_id": "ev_network_02", "source": "task-database"},
                ],
            },
            "learning_task_plan": {
                "task_steps": [
                    {
                        "step_id": "step_01",
                        "title": "核对部署条件",
                        "objective": "核对拓扑、设备、地址规划和安全边界。",
                        "depends_on": [],
                        "expected_artifact": "部署前检查表",
                        "completion_condition": "设备与地址规划均通过检查。",
                        "knowledge_point_ids": ["kp_topology"],
                        "skill_point_ids": ["sp_precheck"],
                        "source_refs": ["ev_network_01"],
                    },
                    {
                        "step_id": "step_02",
                        "title": "完成网络配置",
                        "objective": "按规划完成设备连接与网络参数配置。",
                        "depends_on": ["step_01"],
                        "expected_artifact": "设备配置记录",
                        "completion_condition": "配置与地址规划保持一致。",
                        "knowledge_point_ids": ["kp_addressing"],
                        "skill_point_ids": ["sp_configure"],
                        "source_refs": ["ev_network_02"],
                    },
                    {
                        "step_id": "step_03",
                        "title": "执行连通性验收",
                        "objective": "执行端到端连通性与关键服务检查。",
                        "depends_on": ["step_02"],
                        "expected_artifact": "连通性测试记录",
                        "completion_condition": "全部必测路径达到验收阈值。",
                        "knowledge_point_ids": ["kp_connectivity"],
                        "skill_point_ids": ["sp_verify"],
                        "source_refs": ["ev_network_01"],
                    },
                    {
                        "step_id": "step_04",
                        "title": "整理交付证据",
                        "objective": "汇总部署记录、配置和验收结论。",
                        "depends_on": ["step_03"],
                        "expected_artifact": "任务交付包",
                        "completion_condition": "交付包可追溯到每个任务步骤。",
                        "knowledge_point_ids": ["kp_delivery"],
                        "skill_point_ids": ["sp_document"],
                        "source_refs": ["ev_network_02"],
                    },
                ],
            },
        },
        "next_actions": ["生成学习型任务候选"],
    }


def test_builds_hierarchy_candidates_critics_and_critical_path():
    analysis = build_planning_analysis(_run())

    assert analysis["schema_version"] == "learning-work-task-planning-analysis-v3"
    assert analysis["planning_status"] == "ready_for_confirmation"
    assert analysis["decision"]["code"] == "SELECT_CANDIDATE"
    assert len(analysis["candidates"]) == 3
    assert len(analysis["critics"]) == 6
    assert analysis["critical_path"] == [
        "step_01", "step_02", "step_03", "step_04",
    ]
    assert analysis["metrics"]["hierarchy_nodes"] >= 18
    assert all(candidate["hard_gate_passed"] for candidate in analysis["candidates"])
    assert [stage["sequence"] for stage in analysis["stages"]] == [1, 2, 3, 4, 5, 6]
    assert analysis["stages"][0]["stage_id"] == "task_contract"
    assert analysis["stages"][2]["stage_id"] == "evidence_search_planning"
    assert analysis["stages"][3]["stage_id"] == "evidence_grounded_task_planning"
    assert analysis["stages"][3]["status"] == "completed"
    assert analysis["stages"][4]["status"] == "ready"
    assert analysis["stages"][5]["status"] == "pending"
    assert analysis["metrics"]["stage_substep_count"] >= 180
    assert all(len(stage["substeps"]) >= 16 for stage in analysis["stages"])
    assert all(
        any(item["depends_on"] for item in stage["substeps"])
        for stage in analysis["stages"]
    )
    assert all(
        item["status"] == "pending"
        and item["observation_state"] == "not_observed"
        for item in analysis["execution_checklist"]
    )
    assert len(analysis["handoff_artifacts"]) == 5
    assert all(item["status"] == "planned" for item in analysis["handoff_artifacts"])
    assert analysis["evidence_semantics"] == "operational_only"


def test_missing_evidence_prevents_learning_task_plan_generation():
    run = _run()
    run["plan"]["unknowns"] = [{
        "unknown_id": "acceptance",
        "question": "现场最终采用什么连通性验收阈值？",
        "required_evidence": "official_or_upstream",
        "blocking": True,
    }]
    run["state"].pop("evidence_ledger")
    run["state"].pop("learning_task_plan")

    analysis = build_planning_analysis(run)

    assert analysis["planning_status"] == "needs_evidence"
    assert analysis["decision"]["code"] == "REQUEST_EVIDENCE"
    assert analysis["decision"]["selected_candidate_id"] is None
    assert analysis["hierarchy"] == []
    assert analysis["candidates"] == []
    assert analysis["critics"] == []
    assert analysis["stages"][1]["status"] == "completed"
    assert analysis["stages"][2]["status"] == "completed"
    assert analysis["stages"][3]["status"] == "blocked"
    assert analysis["stages"][4]["status"] == "blocked"
    assert analysis["stages"][5]["status"] == "not_started"
    assert analysis["metrics"]["stage_substep_count"] >= 140
    assert len(analysis["stages"][3]["substeps"]) >= 30


def test_evidence_search_stage_excludes_candidate_and_compiler_tools():
    run = _run()
    for package in run["plan"]["work_packages"]:
        if package["agent_role"] == "evidence_explorer":
            package["allowed_tools"] = [
                "task_database", "knowledge_base_pro", "official_web",
                "evidence_verifier",
            ]
        else:
            package["allowed_tools"] = [
                "candidate_generator", "candidate_critic", "task_compiler",
            ]

    analysis = build_planning_analysis(run)
    search_stage = analysis["stages"][2]
    labels = {item["label"] for item in search_stage["substeps"]}

    assert {"任务库", "知识库 Pro", "权威 Web", "证据校验器"} <= labels
    assert "候选生成器" not in labels
    assert "候选评审器" not in labels
    assert "任务编译器" not in labels


def test_local_replan_only_changes_target_and_descendants():
    run = _run()
    analysis = build_planning_analysis(run)

    revised = replan_analysis(
        run,
        analysis,
        target_package_id="step_03",
        failure_code="mapping_conflict",
        observation="知识技能映射与真实作业步骤不一致，需要局部重算。",
        expected_analysis_version=1,
    )

    revision = revised["revision_history"][-1]
    assert revised["analysis_version"] == 2
    assert revised["planning_status"] == "replanned_not_executed"
    assert revised["repair_budget_remaining"] == 1
    assert revision["affected_package_ids"] == [
        "step_03", "step_04",
    ]
    assert revision["preserved_package_ids"] == ["step_01", "step_02"]
    assert revised["decision"]["code"] == "SELECT_CANDIDATE"
    finalize_stage = next(
        item for item in revised["stages"]
        if item["stage_id"] == "critic_finalize"
    )
    assert finalize_stage["status"] == "ready"
    assert finalize_stage["substeps"][-1]["output_ref"] == revision["revision_id"]
    assert all(
        item["status"] == "pending"
        for item in revised["execution_checklist"]
    )

    with pytest.raises(ValueError, match="版本已变化"):
        replan_analysis(
            deepcopy(run),
            revised,
            target_package_id="step_03",
            failure_code="mapping_conflict",
            observation="重复提交旧版本。",
            expected_analysis_version=1,
        )
