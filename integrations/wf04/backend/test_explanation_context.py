import unittest

from backend.explanation_context import (
    build_explanation_context,
    capability_pool_for_knowledge_type,
    explanation_context_hash,
    normalize_explanation_block,
)


class ExplanationContextTests(unittest.TestCase):
    def test_capability_pool_changes_with_knowledge_type(self):
        self.assertIn("code", capability_pool_for_knowledge_type("code"))
        self.assertIn("formula", capability_pool_for_knowledge_type("quantitative"))
        self.assertIn("diagram", capability_pool_for_knowledge_type("process"))
        self.assertNotIn("formula", capability_pool_for_knowledge_type("conceptual"))

    def test_context_has_scope_policy_and_hash(self):
        contract = {
            "teaching_contract_id": "TC-1",
            "contract_version": "v1",
            "knowledge_point_version": "pack-v1",
            "effective_at": "2026-01-01T00:00:00+08:00",
            "concepts": [{"concept_id": "C-1"}],
            "outcomes": [{"outcome_id": "O-1"}],
            "excluded_scope": ["扩展内容"],
            "immutable_facts": ["定义事实"],
            "personalization_boundary": {"allowed": ["例子"]},
        }
        context = build_explanation_context(
            {
                "learning_goal": {"goal_id": "G-1", "goal_name": "学习目标"},
                "current_knowledge_point": {
                    "knowledge_point_id": "KN-1",
                    "knowledge_point_name": "知识点",
                },
                "initial_assessment_context": {
                    "basis": "formal_initial_assessment",
                    "evidence": {"source_event_ids": ["EV-1"]},
                },
            },
            teaching_contract=contract,
        )
        self.assertEqual(context["required_outcome_ids"], ["O-1"])
        self.assertEqual(context["missing_outcome_ids"], ["O-1"])
        self.assertEqual(context["explanation_scope"]["required_concept_ids"], ["C-1"])
        self.assertIn("concept", context["explanation_policy"]["capability_pool"])
        self.assertEqual(len(context["context_hash"]), 24)
        self.assertEqual(context["context_hash"], explanation_context_hash(context))

    def test_hash_does_not_change_for_mastery_only(self):
        context = {
            "current_knowledge_point": {"knowledge_point_id": "KN-1"},
            "initial_assessment_context": {
                "evidence": {"source_event_ids": ["EV-1"], "mastery": 20}
            },
        }
        changed = {
            **context,
            "initial_assessment_context": {
                "evidence": {"source_event_ids": ["EV-1"], "mastery": 80}
            },
        }
        self.assertEqual(explanation_context_hash(context), explanation_context_hash(changed))

    def test_normalize_block_keeps_legacy_fields_and_adds_rich_aliases(self):
        normalized = normalize_explanation_block(
            {"type": "example", "title": "示例", "content": "内容", "source": "官方资料"}
        )
        self.assertEqual(normalized["block_type"], "example")
        self.assertEqual(normalized["schema_version"], "explanation-block-v1")
        self.assertEqual(normalized["source_refs"][0]["source"], "官方资料")
        self.assertEqual(normalized["coverage_outcome_ids"], [])


if __name__ == "__main__":
    unittest.main()
