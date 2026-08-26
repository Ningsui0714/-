import unittest

from backend.dialogue_understanding import understand_turn


class DialogueUnderstandingTests(unittest.TestCase):
    def test_mixed_question_goal_and_self_report_are_preserved(self):
        result = understand_turn(
            "我零基础，先解释一下 Python 变量，再帮我规划 Python 学习"
        )
        self.assertEqual(result["primary_intent"], "knowledge_question")
        self.assertIn("goal_discovery", result["secondary_intents"])
        self.assertEqual(result["topic"]["subject"], "python")
        self.assertTrue(result["learner_claims"])
        self.assertEqual(
            result["learner_claims"][0]["verification_state"], "unverified"
        )

    def test_data_type_is_foundation_not_data_analysis(self):
        result = understand_turn("我想学习 Python 数据类型基础")
        self.assertEqual(result["topic"]["subject"], "python")
        self.assertEqual(result["topic"]["learning_scope"], "foundation")

    def test_explicit_data_analysis_stays_data_analysis(self):
        result = understand_turn("我想用 Python 和 Pandas 完成销售数据分析看板")
        self.assertEqual(result["topic"]["learning_scope"], "data_analysis")

    def test_project_goal_extracts_outcome_and_time(self):
        result = understand_turn("我想用 Python 做销售数据看板，每周 6 小时，准备 3 个月完成")
        self.assertEqual(result["primary_intent"], "create_project")
        self.assertEqual(result["goal"]["goal_type"], "project")
        self.assertEqual(result["goal"]["target_outcome"], "销售数据看板")
        self.assertEqual(result["goal"]["application_scenario"], "data_analysis")
        self.assertEqual(result["goal"]["constraints"]["weekly_time"], "6小时")
        self.assertEqual(result["goal"]["constraints"]["duration"], "3个月")

    def test_job_goal_is_distinct_from_course_learning(self):
        result = understand_turn("我想转行做后端开发，半年内找到工作")
        self.assertEqual(result["goal"]["goal_type"], "job")
        self.assertEqual(result["goal"]["target_outcome"], "后端开发，半年内找到工作")
        self.assertIn("current_level", result["goal"]["missing_information"])

    def test_certification_and_competition_are_separate_goal_types(self):
        certification = understand_turn("我准备考软考，想系统学习 Java")
        competition = understand_turn("我想参加程序设计竞赛，提升算法能力")
        self.assertEqual(certification["goal"]["goal_type"], "certification")
        self.assertEqual(competition["goal"]["goal_type"], "competition")

    def test_remedial_goal_is_not_treated_as_new_course(self):
        result = understand_turn("我想补 Python 循环和函数基础，总是做错题")
        self.assertEqual(result["goal"]["goal_type"], "remedial")
        self.assertEqual(result["topic"]["subject"], "python")

    def test_knowledge_question_has_no_false_target_outcome(self):
        result = understand_turn("Python 的列表和元组有什么区别？")
        self.assertEqual(result["primary_intent"], "knowledge_question")
        self.assertEqual(result["goal"]["target_outcome"], "")
        self.assertEqual(result["goal"]["missing_information"], [])

    def test_common_subjects_and_job_deadline_are_normalized(self):
        result = understand_turn("我想转行做后端开发，半年内找到工作")
        self.assertEqual(result["topic"]["subject"], "")
        self.assertEqual(result["goal"]["constraints"]["duration"], "半年")
        sql = understand_turn("我想系统学习 SQL，之后能独立设计数据库")
        self.assertEqual(sql["topic"]["subject"], "sql")
        self.assertEqual(sql["goal"]["goal_type"], "course")

    def test_project_markers_cover_build_and_training_requests(self):
        result = understand_turn("我需要用机器学习训练一个图像分类模型")
        self.assertEqual(result["primary_intent"], "create_project")
        self.assertEqual(result["goal"]["goal_type"], "project")
        self.assertEqual(result["goal"]["application_scenario"], "machine_learning")
