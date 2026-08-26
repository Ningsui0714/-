import unittest

from backend.teaching_contract import (
    FORMAL_TEACHING_CONTRACTS,
    annotate_lesson_with_contract,
    annotate_resources_with_contract,
    audit_lesson_contract,
    build_contract_visual,
    build_lesson_visual,
    get_teaching_contract,
)
from backend.server import LearningApplication


class TeachingContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = get_teaching_contract("KN_JAVA_ENCAPSULATION")
        assert self.contract is not None

    def test_formal_contracts_have_atomic_concepts_and_checkable_outcomes(self):
        self.assertEqual(len(FORMAL_TEACHING_CONTRACTS), 7)
        for contract in FORMAL_TEACHING_CONTRACTS.values():
            self.assertGreaterEqual(len(contract["concepts"]), 3)
            self.assertGreaterEqual(len(contract["outcomes"]), 3)
            self.assertTrue(contract["source_bundle"]["version"])
            for outcome in contract["outcomes"]:
                self.assertTrue(outcome["completion_criteria"])
                self.assertEqual(outcome["check_requirement"]["minimum_items"], 1)

    def test_blocks_cover_contract_outcomes_and_receive_stable_ids(self):
        lesson = {
            "content_blocks": [
                {"type": "concept", "content": "封装限制内部状态访问。"},
                {"type": "steps", "items": ["字段设为 private", "提供受控方法"]},
                {"type": "warning", "content": "不能直接返回内部数组引用。"},
            ]
        }

        annotated = annotate_lesson_with_contract(lesson, self.contract)
        audit = audit_lesson_contract(annotated, self.contract)

        self.assertEqual(audit["status"], "passed")
        self.assertEqual(len(audit["covered_outcome_ids"]), 3)
        self.assertTrue(all(block["concept_ids"] for block in annotated["content_blocks"]))

    def test_audit_rejects_missing_learning_objective(self):
        annotated = annotate_lesson_with_contract(
            {"content_blocks": [{"type": "concept", "content": "只解释概念。"}]},
            self.contract,
        )

        audit = audit_lesson_contract(annotated, self.contract)

        self.assertEqual(audit["status"], "rejected")
        self.assertEqual(len(audit["missing_outcome_ids"]), 2)

    def test_audit_rejects_explicitly_excluded_scope(self):
        lesson = annotate_lesson_with_contract(
            {
                "content_blocks": [
                    {"type": "concept", "content": "封装限制访问。"},
                    {"type": "steps", "content": "通过方法控制修改。"},
                    {"type": "warning", "content": "不要暴露内部数组。"},
                    {"type": "example", "content": "接下来讲继承重写的完整规则。"},
                ]
            },
            self.contract,
        )

        audit = audit_lesson_contract(lesson, self.contract)

        self.assertEqual(audit["status"], "rejected")
        self.assertEqual(audit["scope_violations"], ["继承重写的完整规则"])

    def test_evidence_audit_includes_contract_gate(self):
        evidence_pack = {
            "required_sections": ["definition_and_boundary"],
            "evidence": [{"title": "Oracle", "source": "Oracle", "url": "https://docs.oracle.com/"}],
        }
        result = {
            "content_blocks": [{"type": "concept", "content": "封装", "source": "Oracle"}],
        }

        audit = LearningApplication._audit_lesson_evidence(
            LearningApplication.__new__(LearningApplication),
            result,
            evidence_pack,
            self.contract,
        )

        self.assertEqual(audit["status"], "rejected")
        self.assertEqual(audit["teaching_contract_audit"]["status"], "rejected")

    def test_visual_and_video_resources_have_different_evidence_status(self):
        lesson = annotate_lesson_with_contract(
            {
                "content_blocks": [
                    {"type": "concept", "content": "概念"},
                    {"type": "steps", "content": "步骤"},
                    {"type": "warning", "content": "误区"},
                ],
                "resources": [{"type": "video", "title": "相关视频", "url": "https://example.test/video"}],
            },
            self.contract,
        )

        resources = annotate_resources_with_contract(lesson, self.contract)["resources"]
        video = next(item for item in resources if item["type"] == "video")
        visual = next(item for item in resources if item["type"] == "image")

        self.assertEqual(video["coverage_status"], "candidate_unverified")
        self.assertFalse(video["transcript_verified"])
        self.assertEqual(visual["renderer"], "deterministic_svg")
        self.assertTrue(visual["url"].startswith("data:image/svg+xml;base64,"))
        self.assertEqual(build_contract_visual(self.contract)["ai_generated"], False)

    def test_generic_lesson_visual_uses_text_blocks_only(self):
        visual = build_lesson_visual({
            "status": "ok",
            "knowledge_point_id": "KN_CUSTOM",
            "lesson_title": "Python 变量",
            "content_blocks": [
                {"block_id": "B1", "type": "concept", "title": "核心概念", "content": "变量保存数据。"},
                {"block_id": "B2", "type": "example", "title": "最小示例", "content": "name = 'Ada'"},
            ],
        })
        self.assertIsNotNone(visual)
        assert visual is not None
        self.assertEqual(visual["renderer"], "deterministic_svg")
        self.assertEqual(visual["coverage_block_ids"], ["B1", "B2"])
        self.assertTrue(visual["url"].startswith("data:image/svg+xml;base64,"))

    def test_generic_lesson_visual_does_not_cover_missing_content(self):
        self.assertIsNone(build_lesson_visual({
            "status": "ok",
            "knowledge_point_id": "KN_CUSTOM",
            "lesson_title": "Python 变量",
            "content_blocks": [{"type": "notice", "title": "资料不足", "content": "暂无正文。"}],
        }))

    def test_generic_visual_infers_flowchart_and_outcome_coverage(self):
        visual = build_lesson_visual({
            "status": "ok",
            "lesson_title": "函数调用",
            "content_blocks": [
                {"block_id": "B1", "type": "concept", "title": "入口", "content": "定义函数。", "outcome_ids": ["OUT-1"]},
                {"block_id": "B2", "type": "steps", "title": "调用步骤", "content": "传入参数并执行。", "outcome_ids": ["OUT-2"]},
            ],
        })
        self.assertIsNotNone(visual)
        assert visual is not None
        self.assertEqual(visual["visual_kind"], "flowchart")
        self.assertEqual(visual["coverage_outcome_ids"], ["OUT-1", "OUT-2"])

    def test_backfill_updates_only_ready_lessons_with_text(self):
        class FakeStore:
            def __init__(self):
                self.saved = []

            def list_ready_project_lessons(self, limit=0):
                return [{
                    "project_id": "P1",
                    "student_id": "S1",
                    "knowledge_point_id": "KN_CUSTOM",
                    "lesson": {
                        "status": "ok",
                        "lesson_title": "自定义章节",
                        "content_blocks": [
                            {"block_id": "B1", "type": "concept", "title": "概念", "content": "定义"},
                            {"block_id": "B2", "type": "steps", "title": "步骤", "content": "操作"},
                        ],
                        "resources": [{"type": "video", "url": "https://example.test/video"}],
                    },
                }]

            def set_project_lesson_status(self, *args, **kwargs):
                self.saved.append((args, kwargs))

        application = LearningApplication.__new__(LearningApplication)
        application.store = FakeStore()
        summary = application.backfill_lesson_visuals()
        self.assertEqual(summary, {"scanned": 1, "updated": 1, "skipped": 0})
        saved_lesson = application.store.saved[0][1]["lesson"]
        self.assertTrue(any(item.get("type") == "image" for item in saved_lesson["resources"]))


if __name__ == "__main__":
    unittest.main()
