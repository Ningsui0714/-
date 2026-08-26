import unittest

from backend.learning_path_workflow import (
    build_daily_schedule,
    compile_learning_path,
    validate_plan_delivery,
)


class LearningPathWorkflowTests(unittest.TestCase):
    def test_compiles_explicit_dag_without_stage_derived_dependencies(self):
        items = [
            {
                "knowledge_point_id": "TARGET",
                "knowledge_point_name": "完成展示项目",
                "knowledge_type": "project",
                "prerequisites": ["CORE"],
            },
            {
                "knowledge_point_id": "CORE",
                "knowledge_point_name": "核心实现",
                "knowledge_type": "code",
                "prerequisites": ["BASE"],
            },
            {
                "knowledge_point_id": "BASE",
                "knowledge_point_name": "基础环境",
                "knowledge_type": "conceptual",
                "prerequisites": [],
            },
            {
                "knowledge_point_id": "OPTIONAL",
                "knowledge_point_name": "扩展工具",
                "knowledge_type": "code",
                "prerequisites": [],
            },
        ]

        compiled = compile_learning_path(items)
        by_id = {item["knowledge_point_id"]: item for item in compiled}

        self.assertEqual([item["knowledge_point_id"] for item in compiled], ["BASE", "CORE", "TARGET", "OPTIONAL"])
        self.assertEqual(by_id["CORE"]["prerequisites"], ["BASE"])
        self.assertEqual(by_id["OPTIONAL"]["prerequisites"], [])
        self.assertEqual(by_id["BASE"]["stage_id"], "foundation")
        self.assertEqual(by_id["CORE"]["stage_id"], "core")
        self.assertEqual(by_id["TARGET"]["stage_id"], "application")

    def test_rejects_cycle(self):
        with self.assertRaisesRegex(ValueError, "环路"):
            compile_learning_path(
                [
                    {"knowledge_point_id": "A", "prerequisites": ["B"]},
                    {"knowledge_point_id": "B", "prerequisites": ["A"]},
                ]
            )

    def test_dependent_node_never_precedes_its_practice_prerequisite_stage(self):
        compiled = compile_learning_path(
            [
                {
                    "knowledge_point_id": "BASE",
                    "knowledge_type": "conceptual",
                    "prerequisites": [],
                },
                {
                    "knowledge_point_id": "PRACTICE",
                    "knowledge_type": "practice",
                    "prerequisites": ["BASE"],
                },
                {
                    "knowledge_point_id": "VERIFY",
                    "knowledge_type": "conceptual",
                    "prerequisites": ["PRACTICE"],
                },
            ]
        )
        by_id = {item["knowledge_point_id"]: item for item in compiled}

        self.assertGreaterEqual(
            by_id["VERIFY"]["stage_order"],
            by_id["PRACTICE"]["stage_order"],
        )

    def test_daily_schedule_covers_steps_without_exceeding_budget(self):
        plan = {
            "target_knowledge_point_ids": ["TARGET"],
            "stages": [
                {
                    "stage_id": "foundation",
                    "steps": [
                        {
                            "step_id": "S-BASE",
                            "knowledge_point_id": "BASE",
                            "knowledge_point_name": "基础环境",
                            "learning_objective": "能够配置并运行基础环境",
                            "estimated_minutes": 35,
                            "stage_order": 1,
                            "prerequisites": [],
                        }
                    ],
                },
                {
                    "stage_id": "core",
                    "steps": [
                        {
                            "step_id": "S-CORE",
                            "knowledge_point_id": "CORE",
                            "knowledge_point_name": "核心实现",
                            "learning_objective": "能够实现核心业务逻辑",
                            "estimated_minutes": 45,
                            "stage_order": 2,
                            "prerequisites": ["BASE"],
                        }
                    ],
                },
                {
                    "stage_id": "application",
                    "steps": [
                        {
                            "step_id": "S-TARGET",
                            "knowledge_point_id": "TARGET",
                            "knowledge_point_name": "成果项目",
                            "learning_objective": "能够完成并验证目标项目",
                            "estimated_minutes": 40,
                            "stage_order": 3,
                            "is_target": True,
                            "prerequisites": ["CORE"],
                        }
                    ],
                },
            ],
        }
        schedule = build_daily_schedule(
            plan, duration_days=3, daily_minutes=45
        )
        plan["time_budget"] = {
            "constraint_applied": True,
            "constraint_met": True,
            "duration_days": 3,
            "daily_minutes": 45,
        }
        plan["daily_schedule"] = schedule

        self.assertEqual(len(schedule), 3)
        self.assertTrue(all(day["planned_minutes"] <= 45 for day in schedule))
        self.assertEqual(
            sum(task["minutes"] for day in schedule for task in day["tasks"]),
            120,
        )
        self.assertEqual(validate_plan_delivery(plan), [])

    def test_delivery_validation_rejects_reverse_prerequisite_order(self):
        plan = {
            "stages": [
                {
                    "steps": [
                        {
                            "knowledge_point_id": "TARGET",
                            "learning_objective": "能够完成目标成果",
                            "stage_order": 1,
                            "prerequisites": ["BASE"],
                            "is_target": True,
                        },
                        {
                            "knowledge_point_id": "BASE",
                            "learning_objective": "能够完成基础准备",
                            "stage_order": 2,
                            "prerequisites": [],
                        },
                    ]
                }
            ]
        }

        errors = validate_plan_delivery(plan)
        self.assertTrue(any("前置知识未排" in error for error in errors))
        self.assertTrue(any("前置知识阶段晚于" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
