from app.services.action_board import ACTION_BOARD
from app.services.architecture_registry import (
    AGENTS,
    CAPABILITY_OWNERS,
    EVENTS,
    KERNEL_NAMES,
    SKILLS,
    TOOLS,
    WORKBENCHES,
    normalize_event_provenance,
    registry_manifest,
    validate_registry,
)


def test_registry_has_three_agents_five_kernels_and_no_drift():
    assert len(AGENTS) == 3
    assert KERNEL_NAMES == ("structure", "knowledge", "human", "value", "practice")
    assert set(ACTION_BOARD) == set(CAPABILITY_OWNERS)
    assert validate_registry() == []
    manifest = registry_manifest()
    assert manifest["validation_errors"] == []
    assert len(manifest["digest"]) == 64


def test_remediation_events_have_standard_authority_provenance():
    expected = {
        "remediation_started",
        "remediation_mode_rejected",
        "remediation_explanation_requested",
        "remediation_retry_evaluated",
        "remediation_variant_evaluated",
        "remediation_completed",
    }
    assert expected <= set(EVENTS)
    provenance = normalize_event_provenance(
        "remediation_completed", "assessment", {"provider": "local"},
    )
    assert provenance["owner_agent"] == "practice_agent"
    assert provenance["tool"] == "deterministic_assessment"
    assert provenance["kernel_targets"] == ["knowledge", "human", "practice"]
    assert provenance["provider"] == "local"


def test_background_task_events_are_registered_with_their_actual_authority():
    assert {"source_processed", "assessment_generated", "task_completed", "task_failed"} <= set(EVENTS)
    assert normalize_event_provenance("source_processed", "task", {})["kernel_targets"] == [
        "structure", "practice",
    ]
    assert normalize_event_provenance("assessment_generated", "task", {})["kernel_targets"] == []
    failure = normalize_event_provenance("task_failed", "task", {})
    assert failure["tool"] == "task_runtime"
    assert failure["kernel_targets"] == ["structure"]


def test_learning_work_task_events_are_zero_kernel_adapter_events():
    expected = {
        "learning_work_task_plan_created",
        "learning_work_task_plan_confirmed",
        "learning_work_task_plan_replanned",
        "learning_work_task_generated",
        "learning_work_task_generation_follow_up",
        "learning_work_task_review_submitted",
        "personalized_learning_handoff_opened",
        "personalized_learning_result_received",
    }
    assert expected <= set(EVENTS)
    for event_type in expected:
        provenance = normalize_event_provenance(
            event_type, "learning_task_conversion", {"provider": "xunfei-xingchen"},
        )
        assert provenance["kernel_targets"] == []
        assert provenance["tool"] == "learning_task_conversion_gateway"

    assert "plan_learning_work_task" in ACTION_BOARD
    assert "learning_work_task_plan" in WORKBENCHES
    assert CAPABILITY_OWNERS["plan_learning_work_task"] == (
        "learning_design_agent",
        "learning_task_conversion_gateway",
        "learning_work_task_plan",
    )


def test_review_workbench_is_registered_without_new_kernel_writer():
    assert "review" in WORKBENCHES
    assert "spaced_review" in SKILLS
    assert "review_scheduler" in TOOLS
    assert {
        "plan_review_queue", "evaluate_review_attempt", "manage_review_item",
    } <= set(ACTION_BOARD)
    assert CAPABILITY_OWNERS["plan_review_queue"][0] == "tutor_agent"
    assert CAPABILITY_OWNERS["evaluate_review_attempt"][0] == "practice_agent"
    assert EVENTS["review_attempt_evaluated"].kernel_targets == (
        "knowledge", "practice",
    )
    for event_type in {
        "review_item_skipped", "review_item_deferred",
        "review_item_suspended", "review_item_resumed",
    }:
        assert EVENTS[event_type].kernel_targets == ()
    assert {
        tool.id for tool in TOOLS.values() if tool.writes_kernels
    } == {"five_kernel_reducer"}
