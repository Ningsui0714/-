import json
import os
import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse
import urllib.error
import urllib.request
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from backend.domain import LearningDomainStore, StudentModelCache
from backend.server import (
    ApiError,
    GatewayError,
    KnowledgeCache,
    MaterialKnowledgeGateway,
    Settings,
    StrategyEngine,
    VideoSearchGateway,
    XingchenGateway,
    create_server,
    demo_upstream_payload,
)


def _wrong_answer_for(question: dict) -> str:
    """构造一个必然错误的作答，兼容全部题型（choice/judgment/multiple_choice/fill_blank/practical）。"""
    question_type = str(question.get("question_type") or "choice")
    options = question.get("options") or {}
    expected = str(question.get("answer") or "")
    if question_type in {"choice", "judgment"}:
        return next((key for key in options if key != expected), "a")
    if question_type == "multiple_choice":
        expected_keys = {
            value.strip()
            for value in expected.replace("，", ",").split(",")
            if value.strip()
        }
        return next((key for key in options if key not in expected_keys), "a")
    return "错误答案"


class BackendIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        settings = Settings(
            host="127.0.0.1",
            port=0,
            database_path=Path(self.temporary_directory.name) / "test.db",
            xingchen_mode="mock",
            api_url="",
            api_key="",
            api_secret="",
            auth_header="Authorization",
            auth_scheme="Bearer",
            flow_id="",
            input_key="AGENT_USER_INPUT",
            request_style="workflow_v1",
            request_timeout=5,
            seed_demo=False,
        )
        self.server = create_server(settings)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temporary_directory.cleanup()

    def request_json(self, method, path, payload=None, timeout=5):
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + path,
            data=body,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def test_empty_xingchen_input_key_uses_standard_default(self):
        with patch.dict(os.environ, {"XINGCHEN_INPUT_KEY": ""}):
            settings = Settings.from_env(host="127.0.0.1", port=4173)

        self.assertEqual(settings.input_key, "AGENT_USER_INPUT")

    def test_content_llm_settings_prefer_generic_deepseek_configuration(self):
        with patch.dict(os.environ, {
            "CONTENT_LLM_API_BASE": "https://api.deepseek.com/chat/completions",
            "CONTENT_LLM_API_KEY": "test-deepseek-key",
            "CONTENT_LLM_MODEL": "deepseek-v4-flash",
            "SPARK_API_BASE": "https://legacy.example/v1/chat/completions",
            "SPARK_API_KEY": "legacy-key",
            "SPARK_MODEL": "legacy-model",
        }):
            settings = Settings.from_env(host="127.0.0.1", port=4173)

        self.assertEqual(
            settings.spark_api_base,
            "https://api.deepseek.com/chat/completions",
        )
        self.assertEqual(settings.spark_api_key, "test-deepseek-key")
        self.assertEqual(settings.spark_model, "deepseek-v4-flash")

    def test_unified_learning_context_overrides_assessment_route(self):
        application = self.server.RequestHandlerClass.application
        context = {
            "student_id": "STU-CONTRACT-001",
            "session_id": "SESSION-CONTRACT-001",
            # This is inherited from the original failed assessment. A later
            # learning action must never be sent down the remediation branch.
            "route_type": "error_remediation",
            "event_type": "check_feedback",
            "selected_answer": "b",
            "check_result": {
                "status": "correct",
                "selected_answer": "b",
                "feedback": "练习题作答正确",
            },
            "current_knowledge_point": {
                "knowledge_point_id": "KN_JAVA_ENCAPSULATION",
                "knowledge_point_name": "封装与访问控制",
                "mastery": 42,
            },
            "learning_path": {
                "items": [
                    {
                        "knowledge_point_id": "KN_JAVA_ENCAPSULATION",
                        "knowledge_point_name": "封装与访问控制",
                        "status": "current",
                    }
                ]
            },
        }
        application._prepare_learning_workflow_context(context, {})

        self.assertEqual(context["route_type"], "resume_learning")
        self.assertEqual(context["workflow_mode"], "learning")
        self.assertEqual(context["learner_action"], "check_answer")
        self.assertEqual(
            context["learning_target"]["knowledge_point_id"], "KN_JAVA_ENCAPSULATION"
        )
        self.assertEqual(context["learning_state"]["learner_answer"], "b")

    def test_next_lesson_context_replaces_the_completed_target(self):
        application = self.server.RequestHandlerClass.application
        context = {
            "event_type": "continue_learning",
            "current_knowledge_point": {
                "knowledge_point_id": "KN_JAVA_INHERITANCE",
                "knowledge_point_name": "继承与方法重写",
            },
            "learning_target": {
                "knowledge_point_id": "KN_JAVA_ENCAPSULATION",
                "knowledge_point_name": "封装与访问控制",
            },
            "learning_path": {
                "items": [{
                    "knowledge_point_id": "KN_JAVA_INHERITANCE",
                    "knowledge_point_name": "继承与方法重写",
                    "status": "current",
                }]
            },
        }

        application._prepare_learning_workflow_context(context, {})

        self.assertEqual(context["route_type"], "resume_learning")
        self.assertEqual(
            context["learning_target"]["knowledge_point_id"], "KN_JAVA_INHERITANCE"
        )
        self.assertEqual(
            context["learning_target"]["knowledge_point_name"], "继承与方法重写"
        )

    def test_unified_learning_package_renders_as_a_lesson(self):
        application = self.server.RequestHandlerClass.application
        result = application._normalize_learning_result(
            {
                "status": "ok",
                "workflow_mode": "learning",
                "learning_strategy_json": json.dumps({
                    "strategy_code": "worked_example",
                    "explanation_depth": "guided",
                }),
                "learning_target_json": json.dumps({
                    "knowledge_point_id": "KN_JAVA_ENCAPSULATION",
                    "knowledge_point_name": "封装与访问控制",
                }),
                "personalized_explanation": "平均分的分子和分母必须来自同一个有效成绩集合。",
                "micro_example": "先筛选有效成绩，再用有效成绩总和除以有效成绩数量。",
                "common_misconception": "不能把缺考记录计入分母。",
                "workplace_application": "成绩报表和考勤统计都应先统一统计口径。",
                "understanding_check": {
                    "question": "缺考不参与平均分时，分母应是什么？",
                    "expected_key_points": ["有效成绩数量"],
                },
            },
            {"learning_target": {"knowledge_point_id": "KN_JAVA_ENCAPSULATION"}},
        )

        self.assertEqual(result["lesson_title"], "封装与访问控制")
        self.assertEqual(result["teaching_plan"]["primary_mode"], "interactive_document")
        self.assertGreaterEqual(len(result["content_blocks"]), 3)
        self.assertEqual(result["check_request"]["expected_key_points"], ["有效成绩数量"])

    def test_end_to_end_workflow_routes(self):
        health = self.request_json("GET", "/api/health")
        self.assertEqual(health["status"], "ok")
        self.assertFalse(health["material_knowledge_enabled"])
        self.assertEqual(health["material_knowledge_status"], "disabled")

        upstream_payload = demo_upstream_payload()
        upstream_payload["event_id"] = "TEST-E2E-UPSTREAM-001"
        upstream = self.request_json(
            "POST", "/api/upstream/assessment-result", upstream_payload
        )
        self.assertEqual(upstream["status"], "accepted")
        self.assertEqual(upstream["dispatched"]["learning"]["status"], "ok")
        self.assertEqual(upstream["dispatched"]["review"]["status"], "ok")

        switched = self.request_json(
            "POST",
            "/api/workflows/learning",
            {
                "student_id": "STU-DEMO-001",
                "session_id": "DEMO-SESSION-001",
                "event_type": "switch_explanation",
                "previous_mode": "interactive_document",
            },
        )
        self.assertEqual(switched["status"], "ok")
        self.assertNotEqual(switched["teaching_plan"]["primary_mode"], "interactive_document")

        checked = self.request_json(
            "POST",
            "/api/workflows/learning",
            {
                "student_id": "STU-DEMO-001",
                "session_id": "DEMO-SESSION-001",
                "event_type": "check_feedback",
                "passed": True,
                "selected_answer": "b",
            },
        )
        checked_items = checked["learning_path"]["items"]
        current_item = next(
            item for item in checked_items if item["knowledge_point_id"] == "KN_JAVA_ENCAPSULATION"
        )
        next_item = next(
            item for item in checked_items if item["knowledge_point_id"] == "KN_JAVA_INHERITANCE"
        )
        self.assertEqual(current_item["status"], "completed")
        self.assertEqual(next_item["status"], "current")
        # 7 节点路径：完成 1 个节点后进度约 (1+0.4)/7 ≈ 20%
        self.assertGreater(checked["path_update"]["progress"], 20)
        self.assertEqual(checked["workflow_mode"], "learning")
        self.assertEqual(checked["knowledge_point_id"], "KN_JAVA_INHERITANCE")
        self.assertTrue(checked["content_blocks"])

        missing = demo_upstream_payload()
        missing["attempt_id"] = "DEMO-MISSING-001"
        missing["question_snapshot"] = {"question_id": "Q-MISSING"}
        clarification = self.request_json("POST", "/api/workflows/review", missing)
        self.assertEqual(clarification["status"], "needs_clarification")

        resumed = self.request_json(
            "POST",
            "/api/workflows/review/resume",
            {
                "student_id": "STU-DEMO-001",
                "session_id": "DEMO-SESSION-001",
                "resume_token": clarification["resume_token"],
                "clarification_reply": "请排除缺考记录后计算有效成绩平均分。",
            },
        )
        self.assertEqual(resumed["status"], "ok")

        reused = self.request_json(
            "POST",
            "/api/workflows/review/resume",
            {
                "student_id": "STU-DEMO-001",
                "session_id": "DEMO-SESSION-001",
                "resume_token": clarification["resume_token"],
                "clarification_reply": "无法提供",
            },
        )
        self.assertEqual(reused["status"], "fatal_internal")
        self.assertEqual(reused["error_code"], "INVALID_RESUME_TOKEN")

        second_missing = demo_upstream_payload()
        second_missing["attempt_id"] = "DEMO-MISSING-STOP-001"
        second_missing["question_snapshot"] = {"question_id": "Q-MISSING-STOP"}
        second_clarification = self.request_json("POST", "/api/workflows/review", second_missing)
        stopped = self.request_json(
            "POST",
            "/api/workflows/review/resume",
            {
                "student_id": "STU-DEMO-001",
                "session_id": "DEMO-SESSION-001",
                "resume_token": second_clarification["resume_token"],
                "clarification_reply": "无法提供",
            },
        )
        self.assertEqual(stopped["status"], "ended_by_user")

        bootstrap = self.request_json("GET", "/api/bootstrap?student_id=STU-DEMO-001")
        self.assertTrue(bootstrap["has_upstream"])
        self.assertEqual(bootstrap["latest_learning_result"]["workflow_mode"], "learning")

    def test_domain_apis_and_practice_flow(self):
        upstream_payload = demo_upstream_payload()
        upstream_payload["event_id"] = "TEST-DOMAIN-UPSTREAM-001"
        self.request_json("POST", "/api/upstream/assessment-result", upstream_payload)
        bootstrap = self.request_json("GET", "/api/bootstrap?student_id=STU-DEMO-001")
        review = bootstrap["latest_review_result"]
        self.assertTrue(review["explanation_session_id"])
        self.assertTrue(review["question_instance_id"])

        profile = self.request_json("GET", "/api/students/STU-DEMO-001/profile")
        self.assertEqual(profile["profile"]["student_id"], "STU-DEMO-001")

        notifications = self.request_json("GET", "/api/students/STU-DEMO-001/notifications")
        self.assertGreaterEqual(notifications["unread_count"], 1)
        notice_id = notifications["items"][0]["notification_id"]
        marked = self.request_json(
            "POST",
            f"/api/students/STU-DEMO-001/notifications/{notice_id}/read",
            {},
        )
        self.assertTrue(marked["updated"])

        saved_settings = self.request_json(
            "POST",
            "/api/students/STU-DEMO-001/settings",
            {
                "preferred_delivery_mode": "text",
                "explanation_depth": "concise",
                "reduced_motion": True,
            },
        )
        self.assertEqual(saved_settings["settings"]["preferred_delivery_mode"], "text")
        self.assertTrue(saved_settings["settings"]["reduced_motion"])

        favorite = self.request_json(
            "POST",
            "/api/students/STU-DEMO-001/favorites",
            {
                "knowledge_point_id": "KN_JAVA_ENCAPSULATION",
                "title": "封装与访问控制",
                "favorite": True,
            },
        )
        self.assertTrue(favorite["favorite"])

        alternative = self.request_json(
            "POST",
            "/api/explanations",
            {
                "student_id": "STU-DEMO-001",
                "session_id": "DEMO-SESSION-001",
                "scene": "re_explain",
                "source_explanation_session_id": review["explanation_session_id"],
                "question_instance_id": review["question_instance_id"],
                "attempt_id": review["attempt_id"],
                "requested_delivery_mode": "video",
            },
        )
        self.assertEqual(alternative["status"], "ok")
        self.assertEqual(alternative["scene"], "re_explain")
        self.assertEqual(alternative["delivery_mode"], "video_interactive")
        self.assertNotEqual(
            alternative["explanation_session_id"], review["explanation_session_id"]
        )

        sources = self.request_json(
            "GET",
            f"/api/explanations/{alternative['explanation_session_id']}/sources?student_id=STU-DEMO-001",
        )
        self.assertTrue(sources["items"])
        self.assertIn("verification_state", sources["items"][0])

        practice = self.request_json(
            "POST",
            "/api/practice/questions",
            {
                "student_id": "STU-DEMO-001",
                "session_id": "DEMO-SESSION-001",
                "mode": "variant",
                "source_question_instance_id": review["question_instance_id"],
                "task_instance_id": review["task_instance_id"],
                "knowledge_point_id": "KN_JAVA_ENCAPSULATION",
            },
        )
        question = practice["question"]
        self.assertEqual(question["answer_schema"]["type"], "text")

        attempt = self.request_json(
            "POST",
            f"/api/question-instances/{question['question_instance_id']}/attempts",
            {
                "student_id": "STU-DEMO-001",
                "session_id": "DEMO-SESSION-001",
                "answer": "80",
            },
        )
        self.assertFalse(attempt["correct"])
        self.assertEqual(attempt["evaluation"]["evaluation_status"], "incorrect")

        correct_practice = self.request_json(
            "POST",
            "/api/practice/questions",
            {
                "student_id": "STU-DEMO-001",
                "session_id": "DEMO-SESSION-001",
                "mode": "variant",
                "source_question_instance_id": review["question_instance_id"],
                "task_instance_id": review["task_instance_id"],
                "knowledge_point_id": "KN_JAVA_ENCAPSULATION",
            },
        )
        correct_attempt = self.request_json(
            "POST",
            f"/api/question-instances/{correct_practice['question']['question_instance_id']}/attempts",
            {
                "student_id": "STU-DEMO-001",
                "session_id": "DEMO-SESSION-001",
                "answer": "通过 getScores() 返回只读副本，setScores() 校验 null 与越界",
            },
        )
        self.assertTrue(correct_attempt["correct"])
        self.assertEqual(correct_attempt["learning_result"]["status"], "ok")
        self.assertEqual(correct_attempt["learning_result"]["workflow_mode"], "learning")
        self.assertTrue(correct_attempt["learning_result"]["content_blocks"])

        correction_request = {
            "student_id": "STU-DEMO-001",
            "session_id": "DEMO-SESSION-001",
            "scene": "error_correction",
            **attempt["explanation_input"],
        }
        correction = self.request_json("POST", "/api/explanations", correction_request)
        self.assertEqual(correction["status"], "ok")
        self.assertEqual(correction["question_instance_id"], question["question_instance_id"])

        records = self.request_json("GET", "/api/students/STU-DEMO-001/records")
        self.assertTrue(records["explanations"])
        self.assertTrue(records["attempts"])

        reserved = self.request_json(
            "POST",
            "/api/explanations",
            {
                "student_id": "STU-DEMO-001",
                "session_id": "DEMO-SESSION-001",
                "scene": "stage_error",
            },
        )
        self.assertEqual(reserved["status"], "not_implemented")
        self.assertEqual(reserved["code"], "SCENE_NOT_READY")

    def test_learning_state_transitions_preserve_progress_and_update_mastery(self):
        student_id = "STU-STATE-TRANSITIONS-001"
        session_id = "SESSION-STATE-TRANSITIONS-001"
        upstream_payload = demo_upstream_payload()
        upstream_payload.update(
            {
                "event_id": "TEST-STATE-TRANSITIONS-UPSTREAM-001",
                "student_id": student_id,
                "session_id": session_id,
                "attempt_id": "ATTEMPT-STATE-TRANSITIONS-001",
            }
        )
        self.request_json("POST", "/api/upstream/assessment-result", upstream_payload)

        initial_state = self.request_json(
            "GET", f"/api/students/{student_id}/learning-state"
        )
        initial_items = initial_state["learning_path"]["items"]
        initial_statuses = {
            item["knowledge_point_id"]: item["status"] for item in initial_items
        }
        initial_mastery = {
            item["knowledge_point_id"]: item["mastery"] for item in initial_items
        }

        switched = self.request_json(
            "POST",
            "/api/workflows/learning",
            {
                "student_id": student_id,
                "session_id": session_id,
                "event_type": "switch_explanation",
                "previous_mode": "interactive_document",
            },
        )
        self.assertEqual(
            {
                item["knowledge_point_id"]: item["status"]
                for item in switched["learning_path"]["items"]
            },
            initial_statuses,
        )

        failed = self.request_json(
            "POST",
            "/api/workflows/learning",
            {
                "student_id": student_id,
                "session_id": session_id,
                "event_type": "check_feedback",
                "passed": False,
            },
        )
        failed_items = {
            item["knowledge_point_id"]: item
            for item in failed["learning_path"]["items"]
        }
        self.assertEqual(
            {key: item["status"] for key, item in failed_items.items()},
            initial_statuses,
        )
        self.assertEqual(
            failed_items["KN_JAVA_ENCAPSULATION"]["mastery"],
            initial_mastery["KN_JAVA_ENCAPSULATION"] - 10,
        )

        passed = self.request_json(
            "POST",
            "/api/workflows/learning",
            {
                "student_id": student_id,
                "session_id": session_id,
                "event_type": "check_feedback",
                "selected_answer": "b",
            },
        )
        passed_items = {
            item["knowledge_point_id"]: item
            for item in passed["learning_path"]["items"]
        }
        self.assertEqual(passed_items["KN_JAVA_ENCAPSULATION"]["status"], "completed")
        self.assertEqual(passed_items["KN_JAVA_INHERITANCE"]["status"], "current")
        self.assertEqual(
            passed_items["KN_JAVA_ENCAPSULATION"]["mastery"],
            initial_mastery["KN_JAVA_ENCAPSULATION"] + 10,
        )

        # 7 节点路径：依次完成剩余 6 个节点后才是 completed_all
        completed = None
        for _ in range(6):
            completed = self.request_json(
                "POST",
                "/api/workflows/learning",
                {
                    "student_id": student_id,
                    "session_id": session_id,
                    "event_type": "check_feedback",
                    "selected_answer": "b",
                },
            )
        self.assertTrue(
            all(item["status"] == "completed" for item in completed["learning_path"]["items"])
        )
        self.assertEqual(completed["path_update"]["progress"], 100)
        self.assertEqual(completed["path_update"]["current_status"], "completed_all")
        self.assertEqual(completed["path_update"]["next_knowledge_point_id"], "")

        before_practice = self.request_json(
            "GET", f"/api/students/{student_id}/learning-state"
        )
        before_history_count = len(before_practice["teaching_history"]["events"])
        before_practice_mastery = next(
            item["mastery"]
            for item in before_practice["learning_path"]["items"]
            if item["knowledge_point_id"] == "KN_JAVA_ENCAPSULATION"
        )
        practice = self.request_json(
            "POST",
            "/api/practice/questions",
            {
                "student_id": student_id,
                "session_id": session_id,
                "mode": "variant",
                "knowledge_point_id": "KN_JAVA_ENCAPSULATION",
            },
        )
        wrong_attempt = self.request_json(
            "POST",
            f"/api/question-instances/{practice['question']['question_instance_id']}/attempts",
            {
                "student_id": student_id,
                "session_id": session_id,
                "answer": "0",
            },
        )
        self.assertFalse(wrong_attempt["correct"])
        self.assertEqual(wrong_attempt["learning_result"]["status"], "ok")
        after_practice = self.request_json(
            "GET", f"/api/students/{student_id}/learning-state"
        )
        self.assertEqual(
            len(after_practice["teaching_history"]["events"]),
            before_history_count + 1,
        )
        after_practice_mastery = next(
            item["mastery"]
            for item in after_practice["learning_path"]["items"]
            if item["knowledge_point_id"] == "KN_JAVA_ENCAPSULATION"
        )
        self.assertEqual(after_practice_mastery, before_practice_mastery - 10)

    def test_re_explain_requires_a_valid_source_session(self):
        application = self.server.RequestHandlerClass.application
        with self.assertRaises(ApiError) as missing_context:
            application.run_explanation(
                {
                    "student_id": "STU-REEXPLAIN-001",
                    "session_id": "SESSION-REEXPLAIN-001",
                    "scene": "re_explain",
                }
            )
        self.assertEqual(missing_context.exception.status_code, 400)
        self.assertEqual(
            missing_context.exception.code,
            "MISSING_SOURCE_EXPLANATION_SESSION",
        )

        with self.assertRaises(ApiError) as unknown_context:
            application.run_explanation(
                {
                    "student_id": "STU-REEXPLAIN-001",
                    "session_id": "SESSION-REEXPLAIN-001",
                    "scene": "re_explain",
                    "source_explanation_session_id": "EXPLAIN-NOT-FOUND",
                }
            )
        self.assertEqual(unknown_context.exception.status_code, 404)
        self.assertEqual(unknown_context.exception.code, "SOURCE_EXPLANATION_NOT_FOUND")

    def test_duplicate_upstream_event_is_not_dispatched_twice(self):
        payload = demo_upstream_payload()
        payload.update(
            {
                "event_id": "TEST-IDEMPOTENT-UPSTREAM-001",
                "student_id": "STU-IDEMPOTENT-001",
                "session_id": "SESSION-IDEMPOTENT-001",
                "attempt_id": "ATTEMPT-IDEMPOTENT-001",
            }
        )
        application = self.server.RequestHandlerClass.application
        with (
            patch.object(application, "run_learning", wraps=application.run_learning) as learning,
            patch.object(application, "run_review", wraps=application.run_review) as review,
        ):
            accepted = self.request_json(
                "POST", "/api/upstream/assessment-result", payload
            )
            duplicate = self.request_json(
                "POST", "/api/upstream/assessment-result", payload
            )

        self.assertEqual(accepted["status"], "accepted")
        self.assertEqual(duplicate["status"], "duplicate")
        self.assertEqual(duplicate["event_id"], payload["event_id"])
        self.assertEqual(duplicate["student_id"], payload["student_id"])
        self.assertEqual(duplicate["dispatched"], {})
        self.assertEqual(learning.call_count, 1)
        self.assertEqual(review.call_count, 1)

    def test_stream_returns_sse_error_event_for_missing_session(self):
        # SSE 契约：会话不存在时后端应返回 200 + event:error 帧，而不是裸 JSON 500
        url = (
            self.base_url
            + "/api/explanations/EXPLAIN-MISSING-STREAM/stream?student_id=STU-DEMO-001"
        )
        request = urllib.request.Request(url)
        with urllib.request.urlopen(request, timeout=5) as response:
            body = response.read().decode("utf-8")
        self.assertIn("event: error", body)
        self.assertIn("EXPLANATION_NOT_FOUND", body)
        self.assertNotIn("event: done", body, "error 事件后不应出现 done 事件")

    def test_check_feedback_ignores_client_passed_and_judges_server_side(self):
        # P1-3 回归：客户端伪造 passed=true 或 passed:"false" 均不影响服务端判定，
        # 判定只依赖 selected_answer 与服务端答案注册表
        student_id = "STU-CHECK-JUDGE-001"
        session_id = "SESSION-CHECK-JUDGE-001"
        upstream_payload = demo_upstream_payload()
        upstream_payload.update(
            {
                "event_id": "TEST-CHECK-JUDGE-UPSTREAM-001",
                "student_id": student_id,
                "session_id": session_id,
                "attempt_id": "ATTEMPT-CHECK-JUDGE-001",
            }
        )
        self.request_json("POST", "/api/upstream/assessment-result", upstream_payload)

        # 错误答案 + 伪造 passed=true → 服务端判定未通过
        forged = self.request_json(
            "POST",
            "/api/workflows/learning",
            {
                "student_id": student_id,
                "session_id": session_id,
                "event_type": "check_feedback",
                "passed": True,
                "selected_answer": "a",
            },
        )
        self.assertEqual(forged["check_feedback"]["passed"], False)
        agg = next(
            item for item in forged["learning_path"]["items"]
            if item["knowledge_point_id"] == "KN_JAVA_ENCAPSULATION"
        )
        self.assertEqual(agg["status"], "current", "伪造 passed 不应推进路径")

        # 字符串 "false"（旧真值 bug）不应产生异常，且服务端仍按答案判定
        strange = self.request_json(
            "POST",
            "/api/workflows/learning",
            {
                "student_id": student_id,
                "session_id": session_id,
                "event_type": "check_feedback",
                "passed": "false",
                "selected_answer": "b",
            },
        )
        self.assertEqual(strange["check_feedback"]["passed"], True)
        self.assertEqual(strange["path_update"]["current_status"], "completed")

    def test_failed_workflow_does_not_overwrite_successful_state(self):
        # P1-4 回归：工作流返回 system_retryable 时，不得覆盖已成功的
        # latest_learning_result / teaching_history / 路径状态
        student_id = "STU-FAIL-STATE-001"
        session_id = "SESSION-FAIL-STATE-001"
        upstream_payload = demo_upstream_payload()
        upstream_payload.update(
            {
                "event_id": "TEST-FAIL-STATE-UPSTREAM-001",
                "student_id": student_id,
                "session_id": session_id,
                "attempt_id": "ATTEMPT-FAIL-STATE-001",
            }
        )
        self.request_json("POST", "/api/upstream/assessment-result", upstream_payload)
        application = self.server.RequestHandlerClass.application

        ok = self.request_json(
            "POST",
            "/api/workflows/learning",
            {
                "student_id": student_id,
                "session_id": session_id,
                "event_type": "check_feedback",
                "selected_answer": "b",
            },
        )
        self.assertEqual(ok["check_feedback"]["passed"], True)

        # 注入失败的工作流返回
        original = application.local_engine.generate_learning_lesson

        def failing_engine(workflow_payload, context):
            return {
                "status": "system_retryable",
                "workflow_mode": "learning",
                "user_message": "内容生成暂时失败",
            }

        before_events = len(
            application.store.get_student_state(student_id)["teaching_history"]["events"]
        )
        application.local_engine.generate_learning_lesson = failing_engine
        try:
            failed = self.request_json(
                "POST",
                "/api/workflows/learning",
                {
                    "student_id": student_id,
                    "session_id": session_id,
                    "event_type": "check_feedback",
                    "selected_answer": "b",
                },
            )
        finally:
            application.local_engine.generate_learning_lesson = original

        self.assertEqual(failed["status"], "system_retryable")
        state = application.store.get_student_state(student_id)
        self.assertEqual(
            state["latest_learning_result"]["status"],
            "ok",
            "失败结果不应覆盖已成功的 latest_learning_result",
        )
        # 失败调用不得追加教学历史事件
        after_events = len(state["teaching_history"]["events"])
        self.assertEqual(after_events, before_events, "失败工作流不应追加教学历史")

    def test_resume_token_binding_rejects_cross_student_workflow_token(self):
        # P1-6 回归：远程工作流格式令牌（zlib+base64 自包含）内嵌身份与请求不符时拒绝
        import base64 as _b64
        import zlib as _zlib

        def make_workflow_token(student, session):
            payload = {
                "version": 1,
                "pending_field": "question_snapshot.question_text",
                "data": {"student_id": student, "session_id": session},
            }
            packed = _zlib.compress(
                json.dumps(payload, ensure_ascii=False).encode("utf-8"), 9
            )
            return _b64.urlsafe_b64encode(packed).decode("ascii").rstrip("=")

        forged = make_workflow_token("STU-OTHER-001", "SESSION-OTHER-001")
        with self.assertRaises(urllib.error.HTTPError) as context:
            self.request_json(
                "POST",
                "/api/workflows/review/resume",
                {
                    "student_id": "STU-DEMO-001",
                    "session_id": "SESSION-DEMO-001",
                    "resume_token": forged,
                    "clarification_reply": "补充题目描述",
                },
            )
        self.assertEqual(context.exception.code, 403)
        body = json.loads(context.exception.read().decode("utf-8"))
        self.assertEqual(body["error_code"], "INVALID_RESUME_TOKEN")

        # 身份匹配的工作流令牌可继续走 mock 校验（mock 令牌不可解码时跳过该层校验）
        matching = make_workflow_token("STU-DEMO-001", "SESSION-DEMO-001")
        outcome = self.request_json(
            "POST",
            "/api/workflows/review/resume",
            {
                "student_id": "STU-DEMO-001",
                "session_id": "SESSION-DEMO-001",
                "resume_token": matching,
                "clarification_reply": "补充题目描述",
            },
        )
        self.assertEqual(
            outcome["status"],
            "fatal_internal",
            "身份匹配的令牌通过后端校验层，mock 层对其未知格式给出致命错误",
        )

    def test_completed_all_does_not_trigger_continuation_workflow(self):
        # 回归保护：路径全部完成后不得再触发续节工作流调用（只返回 completed_all 状态）
        student_id = "STU-COMPLETED-ALL-001"
        session_id = "SESSION-COMPLETED-ALL-001"
        upstream_payload = demo_upstream_payload()
        upstream_payload.update(
            {
                "event_id": "TEST-COMPLETED-ALL-UPSTREAM-001",
                "student_id": student_id,
                "session_id": session_id,
                "attempt_id": "ATTEMPT-COMPLETED-ALL-001",
            }
        )
        self.request_json("POST", "/api/upstream/assessment-result", upstream_payload)
        application = self.server.RequestHandlerClass.application
        with patch.object(application, "run_learning", wraps=application.run_learning) as learning:
            # 7 节点路径：完成剩余 6 个节点，最后一次应返回 completed_all 且无续节调用
            last = None
            for index in range(6):
                last = self.request_json(
                    "POST",
                    "/api/workflows/learning",
                    {
                        "student_id": student_id,
                        "session_id": session_id,
                        "event_type": "check_feedback",
                        "selected_answer": "b",
                    },
                )
                if index == 0:
                    self.assertEqual(last["path_update"]["current_status"], "completed")
        self.assertEqual(last["path_update"]["current_status"], "completed_all")
        self.assertEqual(last["path_update"]["next_knowledge_point_id"], "")
        # 每次 check 只应调用 1 次工作流（mock 直接返回下一节内容），全部完成时无续节调用
        self.assertEqual(learning.call_count, 6)

    def test_resume_token_is_bound_to_student_and_session(self):
        missing = demo_upstream_payload()
        missing.update(
            {
                "student_id": "STU-TOKEN-OWNER-001",
                "session_id": "SESSION-TOKEN-OWNER-001",
                "attempt_id": "ATTEMPT-TOKEN-OWNER-001",
                "question_snapshot": {"question_id": "Q-TOKEN-OWNER-001"},
            }
        )
        clarification = self.request_json("POST", "/api/workflows/review", missing)
        self.assertEqual(clarification["status"], "needs_clarification")

        rejected = self.request_json(
            "POST",
            "/api/workflows/review/resume",
            {
                "student_id": "STU-TOKEN-OTHER-001",
                "session_id": "SESSION-TOKEN-OTHER-001",
                "resume_token": clarification["resume_token"],
                "clarification_reply": "尝试读取其他学生的恢复上下文",
            },
        )
        self.assertEqual(rejected["status"], "fatal_internal")
        self.assertEqual(rejected["error_code"], "INVALID_RESUME_TOKEN")

        resumed = self.request_json(
            "POST",
            "/api/workflows/review/resume",
            {
                "student_id": "STU-TOKEN-OWNER-001",
                "session_id": "SESSION-TOKEN-OWNER-001",
                "resume_token": clarification["resume_token"],
                "clarification_reply": "缺考不计入有效成绩平均分的分母。",
            },
        )
        self.assertEqual(resumed["status"], "ok")

    def test_resume_payload_restores_learning_context(self):
        # resume 分支必须把 validated_evaluation / question_snapshot / current_attempt
        # 从上游上下文恢复，否则 remote 模式策略决策与知识检索全部退化
        application = self.server.RequestHandlerClass.application
        captured = {}

        def spy(context):
            captured["context"] = dict(context)
            return original(context)

        original = application._remediation_workflow_payload
        application._remediation_workflow_payload = spy
        try:
            missing = demo_upstream_payload()
            missing.update(
                {
                    "student_id": "STU-RESUME-CTX-001",
                    "session_id": "SESSION-RESUME-CTX-001",
                    "attempt_id": "ATTEMPT-RESUME-CTX-001",
                    "question_snapshot": {"question_id": "Q-RESUME-CTX-001"},
                }
            )
            # 真实链路：上游测验系统先提交结果，state.upstream_payload 才有学情数据
            self.request_json("POST", "/api/upstream/assessment-result", missing)
            clarification = self.request_json("POST", "/api/workflows/review", missing)
            self.assertEqual(clarification["status"], "needs_clarification")
            resumed = self.request_json(
                "POST",
                "/api/workflows/review/resume",
                {
                    "student_id": "STU-RESUME-CTX-001",
                    "session_id": "SESSION-RESUME-CTX-001",
                    "resume_token": clarification["resume_token"],
                    "clarification_reply": "缺考记录不应计入分母。",
                },
            )
            self.assertEqual(resumed["status"], "ok")
        finally:
            application._remediation_workflow_payload = original

        context = captured["context"]
        error_points = (context.get("validated_evaluation") or {}).get("error_points") or []
        self.assertTrue(error_points, "resume 上下文应包含 validated_evaluation.error_points")
        self.assertTrue(context.get("question_snapshot"), "resume 上下文应包含 question_snapshot")
        self.assertTrue(context.get("current_attempt"), "resume 上下文应包含 current_attempt")

    def test_api_authentication_cors_and_internal_error_response(self):
        base_settings = self.server.RequestHandlerClass.application.settings
        secure_settings = replace(
            base_settings,
            port=0,
            database_path=Path(self.temporary_directory.name) / "secure-http.db",
            allowed_origins=("http://allowed.example",),
            api_token="test-api-token",
        )
        secure_server = create_server(secure_settings)
        secure_thread = threading.Thread(
            target=secure_server.serve_forever, daemon=True
        )
        secure_thread.start()
        secure_url = f"http://127.0.0.1:{secure_server.server_port}"

        def secure_request(path, headers=None, method="GET", payload=None):
            request_headers = dict(headers or {})
            body = None
            if payload is not None:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                request_headers["Content-Type"] = "application/json"
            request = urllib.request.Request(
                secure_url + path,
                data=body,
                method=method,
                headers=request_headers,
            )
            try:
                with urllib.request.urlopen(request, timeout=5) as response:
                    response_body = response.read()
                    return (
                        response.status,
                        json.loads(response_body.decode("utf-8")) if response_body else {},
                        response.headers,
                    )
            except urllib.error.HTTPError as error:
                return (
                    error.code,
                    json.loads(error.read().decode("utf-8")),
                    error.headers,
                )

        try:
            health_status, _, health_headers = secure_request(
                "/api/health", {"Origin": "http://allowed.example"}
            )
            self.assertEqual(health_status, 200)
            self.assertEqual(
                health_headers.get("Access-Control-Allow-Origin"),
                "http://allowed.example",
            )

            options_status, _, options_headers = secure_request(
                "/api/workflows/learning",
                {
                    "Origin": "http://allowed.example",
                    "Access-Control-Request-Method": "POST",
                },
                method="OPTIONS",
            )
            self.assertEqual(options_status, 204)
            self.assertEqual(
                options_headers.get("Access-Control-Allow-Origin"),
                "http://allowed.example",
            )

            unauthorized_status, unauthorized, _ = secure_request(
                "/api/bootstrap?student_id=STU-SECURE-001",
                {"Origin": "http://allowed.example"},
            )
            self.assertEqual(unauthorized_status, 401)
            self.assertEqual(unauthorized["error_code"], "UNAUTHORIZED")

            authorized_status, authorized, _ = secure_request(
                "/api/bootstrap?student_id=STU-SECURE-001",
                {
                    "Origin": "http://allowed.example",
                    "Authorization": "Bearer test-api-token",
                },
            )
            self.assertEqual(authorized_status, 200)
            self.assertEqual(authorized["status"], "ok")

            forbidden_status, forbidden, forbidden_headers = secure_request(
                "/api/bootstrap?student_id=STU-SECURE-001",
                {
                    "Origin": "http://blocked.example",
                    "Authorization": "Bearer test-api-token",
                },
            )
            self.assertEqual(forbidden_status, 403)
            self.assertEqual(forbidden["error_code"], "ORIGIN_NOT_ALLOWED")
            self.assertIsNone(forbidden_headers.get("Access-Control-Allow-Origin"))

            application = secure_server.RequestHandlerClass.application
            with patch.object(
                application,
                "bootstrap",
                side_effect=RuntimeError("private database detail"),
            ):
                failure_status, failure, _ = secure_request(
                    "/api/bootstrap?student_id=STU-SECURE-001",
                    {"Authorization": "Bearer test-api-token"},
                )
            self.assertEqual(failure_status, 500)
            self.assertEqual(failure["user_message"], "服务器内部错误，请稍后重试")
            self.assertNotIn("private database detail", json.dumps(failure))

            with patch.object(
                application,
                "run_learning",
                side_effect=GatewayError("private workflow response"),
            ):
                gateway_status, gateway_failure, _ = secure_request(
                    "/api/workflows/learning",
                    {"Authorization": "Bearer test-api-token"},
                    method="POST",
                    payload={
                        "student_id": "STU-SECURE-001",
                        "session_id": "SESSION-SECURE-001",
                    },
                )
            self.assertEqual(gateway_status, 502)
            self.assertEqual(
                gateway_failure["user_message"],
                "讲解服务暂时不可用，请稍后重试",
            )
            self.assertNotIn("private workflow response", json.dumps(gateway_failure))
        finally:
            secure_server.shutdown()
            secure_server.server_close()
            secure_thread.join(timeout=5)

        with self.assertRaisesRegex(ValueError, "APP_API_TOKEN"):
            create_server(
                replace(
                    base_settings,
                    host="0.0.0.0",
                    port=0,
                    database_path=Path(self.temporary_directory.name) / "unsafe-http.db",
                    api_token="",
                )
            )

    def test_static_frontend_is_served(self):
        # 根路径 = agent 主入口
        request = urllib.request.Request(self.base_url + "/", method="GET")
        with urllib.request.urlopen(request, timeout=5) as response:
            html = response.read().decode("utf-8")
        self.assertIn("知行课径 Agent", html)
        self.assertIn("project-tree", html)
        # 旧版学习中心保留在 /index.html
        request = urllib.request.Request(self.base_url + "/index.html", method="GET")
        with urllib.request.urlopen(request, timeout=5) as response:
            legacy = response.read().decode("utf-8")
        self.assertIn("个性化学习中心", legacy)
        self.assertIn("api.js", legacy)

    def test_remote_xingchen_request_contract(self):
        settings = Settings(
            host="127.0.0.1",
            port=0,
            database_path=Path(self.temporary_directory.name) / "remote.db",
            xingchen_mode="remote",
            api_url="https://xingchen-api.xf-yun.com/workflow/v1/chat/completions",
            api_key="api-key",
            api_secret="api-secret",
            auth_header="Authorization",
            auth_scheme="Bearer",
            flow_id="unified-flow-id",
            input_key="AGENT_USER_INPUT",
            request_style="workflow_v1",
            request_timeout=5,
            seed_demo=False,
        )
        response_payload = {
            "code": 0,
            "message": "Success",
            "choices": [{
                "delta": {
                    "role": "assistant",
                    "content": json.dumps({
                        "status": "ok",
                        "workflow_mode": "learning",
                        "content_blocks": [],
                    }, ensure_ascii=False),
                },
                "finish_reason": "stop",
            }],
        }

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exception_type, exception, traceback):
                return False

            def read(self):
                return json.dumps(response_payload, ensure_ascii=False).encode("utf-8")

        captured = {}

        def fake_urlopen(request, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return FakeResponse()

        gateway = XingchenGateway(settings)
        workflow_input = {
            "student_id": "STU-REMOTE-001",
            "session_id": "SESSION-REMOTE-001",
            "event_type": "initialize_learning",
        }
        with patch("backend.server.urllib.request.urlopen", fake_urlopen):
            result = gateway.invoke("learning", workflow_input)

        request = captured["request"]
        request_body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(request.full_url, settings.api_url)
        self.assertEqual(request.get_header("Authorization"), "Bearer api-key:api-secret")
        self.assertEqual(request_body["flow_id"], "unified-flow-id")
        self.assertEqual(request_body["uid"], "STU-REMOTE-001")
        self.assertFalse(request_body["stream"])
        self.assertEqual(
            captured["timeout"], XingchenGateway.LEARNING_REQUEST_TIMEOUT_SECONDS
        )
        self.assertEqual(
            json.loads(request_body["parameters"]["AGENT_USER_INPUT"]),
            workflow_input,
        )
        self.assertEqual(result["workflow_mode"], "learning")

        missing_flow_gateway = XingchenGateway(replace(settings, flow_id=""))
        self.assertFalse(missing_flow_gateway.remote_ready())
        with self.assertRaisesRegex(GatewayError, "XINGCHEN_WF04_FLOW_ID"):
            missing_flow_gateway.invoke_wf04_workflow(
                {"student_id": "STU-REMOTE-001", "action": "generate_question"}
            )

    def test_kimi_knowledge_workflows_use_numeric_outer_uid(self):
        settings = Settings(
            host="127.0.0.1",
            port=0,
            database_path=Path(self.temporary_directory.name) / "knowledge-remote.db",
            xingchen_mode="remote",
            api_url="https://xingchen-api.xf-yun.com/workflow/v1/chat/completions",
            api_key="api-key",
            api_secret="api-secret",
            auth_header="Authorization",
            auth_scheme="Bearer",
            flow_id="unified-flow-id",
            input_key="AGENT_USER_INPUT",
            request_style="workflow_v1",
            request_timeout=5,
            seed_demo=False,
            knowledge_planning_flow_id="knowledge-planning-flow-id",
            knowledge_audit_flow_id="knowledge-audit-flow-id",
        )

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exception_type, exception, traceback):
                return False

            def read(self):
                return json.dumps({
                    "code": 0,
                    "choices": [{"delta": {"content": json.dumps({
                        "status": "ok", "message": "ok",
                    })}}],
                }).encode("utf-8")

        request_bodies = []

        def fake_urlopen(request, timeout):
            request_bodies.append(json.loads(request.data.decode("utf-8")))
            return FakeResponse()

        planning_payload = {"student_id": "STU-E2E-001", "knowledge_point": {}}
        audit_payload = {"student_id": "5803659", "evidence": []}
        gateway = XingchenGateway(settings)
        with patch("backend.server.urllib.request.urlopen", fake_urlopen):
            gateway.invoke_knowledge_planning_workflow(planning_payload)
            gateway.invoke_knowledge_planning_workflow(planning_payload)
            gateway.invoke_knowledge_audit_workflow(audit_payload)

        self.assertEqual(request_bodies[0]["flow_id"], "knowledge-planning-flow-id")
        self.assertRegex(request_bodies[0]["uid"], r"^[0-9]+$")
        self.assertEqual(request_bodies[0]["uid"], request_bodies[1]["uid"])
        self.assertEqual(request_bodies[2]["uid"], "5803659")
        self.assertEqual(
            json.loads(request_bodies[0]["parameters"]["AGENT_USER_INPUT"]),
            planning_payload,
        )
        self.assertEqual(
            json.loads(request_bodies[2]["parameters"]["AGENT_USER_INPUT"]),
            audit_payload,
        )

    def test_wf04_request_includes_workflow_extension(self):
        settings = Settings(
            host="127.0.0.1",
            port=0,
            database_path=Path(self.temporary_directory.name) / "wf04-remote.db",
            xingchen_mode="remote",
            api_url="https://generic.example.invalid/workflow",
            api_key="api-key",
            api_secret="api-secret",
            auth_header="Authorization",
            auth_scheme="Bearer",
            flow_id="",
            input_key="AGENT_USER_INPUT",
            request_style="workflow_v1",
            request_timeout=5,
            seed_demo=False,
            wf04_flow_id="wf04-flow-id",
            wf04_api_url="https://xingchen-api.xf-yun.com/workflow/v1/chat/completions",
            wf04_api_key="wf04-api-key",
            wf04_api_secret="wf04-api-secret",
        )
        captured = {}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exception_type, exception, traceback):
                return False

            def read(self):
                return json.dumps({
                    "code": 0,
                    "choices": [{"delta": {"content": json.dumps({
                        "status": "ok",
                        "workflow_mode": "wf04_training_evaluation",
                        "action": "generate_question",
                        "public_question": {},
                    })}}],
                }).encode("utf-8")

        def fake_urlopen(request, timeout):
            captured["request"] = request
            captured["body"] = json.loads(request.data.decode("utf-8"))
            return FakeResponse()

        with patch("backend.server.urllib.request.urlopen", fake_urlopen):
            XingchenGateway(settings).invoke_wf04_workflow({
                "student_id": "STU-WF04-001",
                "action": "generate_question",
            })

        self.assertEqual(captured["body"]["flow_id"], "wf04-flow-id")
        self.assertEqual(
            captured["request"].full_url,
            "https://xingchen-api.xf-yun.com/workflow/v1/chat/completions",
        )
        self.assertEqual(
            captured["request"].get_header("Authorization"),
            "Bearer wf04-api-key:wf04-api-secret",
        )
        self.assertEqual(
            captured["body"]["ext"],
            {"caller": "workflow"},
        )

    def test_wf04_retries_21600_with_the_same_request_payload(self):
        settings = Settings(
            host="127.0.0.1", port=0,
            database_path=Path(self.temporary_directory.name) / "wf04-retry.db",
            xingchen_mode="remote",
            api_url="https://xingchen-api.xf-yun.com/workflow/v1/chat/completions",
            api_key="api-key", api_secret="api-secret", auth_header="Authorization",
            auth_scheme="Bearer", flow_id="", input_key="AGENT_USER_INPUT",
            request_style="workflow_v1", request_timeout=5, seed_demo=False,
            wf04_flow_id="wf04-flow-id",
        )
        calls = []
        responses = [
            {"code": 21600, "message": "Code execution failed"},
            {"code": 0, "choices": [{"delta": {"content": json.dumps({
                "status": "ok", "workflow_mode": "wf04_training_evaluation",
                "action": "generate_question", "public_question": {},
            })}}]},
        ]

        class FakeResponse:
            def __init__(self, payload):
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, exception_type, exception, traceback):
                return False

            def read(self):
                return json.dumps(self.payload).encode("utf-8")

        def fake_urlopen(request, timeout):
            calls.append(json.loads(request.data.decode("utf-8")))
            return FakeResponse(responses[len(calls) - 1])

        workflow_input = {
            "student_id": "STU-WF04-RETRY", "request_id": "REQ-WF04-RETRY",
            "action": "generate_question", "requested_question_type": "short_answer",
        }
        with patch("backend.server.urllib.request.urlopen", fake_urlopen):
            result = XingchenGateway(settings).invoke_wf04_workflow(workflow_input)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0], calls[1])
        self.assertEqual(
            json.loads(calls[0]["parameters"]["AGENT_USER_INPUT"]), workflow_input
        )

    def test_wf04_falls_back_to_local_template_after_21600_retries_exhausted(self):
        # 21600 代码执行失败会重试（最多 3 次请求），重试耗尽后不再上抛，
        # 而是降级为本地确定性模板，保证测评仍可出题。
        settings = Settings(
            host="127.0.0.1", port=0,
            database_path=Path(self.temporary_directory.name) / "wf04-retry-exhausted.db",
            xingchen_mode="remote",
            api_url="https://xingchen-api.xf-yun.com/workflow/v1/chat/completions",
            api_key="api-key", api_secret="api-secret", auth_header="Authorization",
            auth_scheme="Bearer", flow_id="", input_key="AGENT_USER_INPUT",
            request_style="workflow_v1", request_timeout=5, seed_demo=False,
            wf04_flow_id="wf04-flow-id",
        )
        calls = []

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exception_type, exception, traceback):
                return False

            def read(self):
                return b'{"code": 21600, "message": "Code execution failed"}'

        def fake_urlopen(request, timeout):
            calls.append(json.loads(request.data.decode("utf-8")))
            return FakeResponse()

        with patch("backend.server.urllib.request.urlopen", fake_urlopen):
            result = XingchenGateway(settings).invoke_wf04_workflow({
                "student_id": "STU-WF04-RETRY", "request_id": "REQ-WF04-RETRY",
                "action": "generate_question",
            })

        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[0], calls[1])
        self.assertEqual(calls[1], calls[2])
        self.assertEqual(result["workflow_mode"], "wf04_training_evaluation")
        self.assertEqual(result["status"], "ok")
        self.assertIn("question_spec", result)
        self.assertIn("public_question", result)

    def test_wf04_falls_back_to_local_without_retrying_other_platform_errors(self):
        # 非 21600 的平台错误（如鉴权/授权 20373）不重试，直接降级为本地确定性模板，
        # 而不是让测评预生成题单长期停留在"题单充实中"。
        settings = Settings(
            host="127.0.0.1", port=0,
            database_path=Path(self.temporary_directory.name) / "wf04-non-retry.db",
            xingchen_mode="remote",
            api_url="https://xingchen-api.xf-yun.com/workflow/v1/chat/completions",
            api_key="api-key", api_secret="api-secret", auth_header="Authorization",
            auth_scheme="Bearer", flow_id="", input_key="AGENT_USER_INPUT",
            request_style="workflow_v1", request_timeout=5, seed_demo=False,
            wf04_flow_id="wf04-flow-id",
        )
        calls = []

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exception_type, exception, traceback):
                return False

            def read(self):
                return b'{"code": 21601, "message": "Other platform error"}'

        def fake_urlopen(request, timeout):
            calls.append(request)
            return FakeResponse()

        with patch("backend.server.urllib.request.urlopen", fake_urlopen):
            result = XingchenGateway(settings).invoke_wf04_workflow({
                "student_id": "STU-WF04-NON-RETRY", "action": "generate_question",
            })

        self.assertEqual(len(calls), 1)
        self.assertEqual(result["workflow_mode"], "wf04_training_evaluation")
        self.assertEqual(result["status"], "ok")
        self.assertIn("question_spec", result)
        self.assertIn("public_question", result)

    def test_remote_gateway_recovers_fragmented_result_package(self):
        settings = Settings(
            host="127.0.0.1",
            port=0,
            database_path=Path(self.temporary_directory.name) / "fragmented-remote.db",
            xingchen_mode="remote",
            api_url="https://xingchen-api.xf-yun.com/workflow/v1/chat/completions",
            api_key="api-key",
            api_secret="api-secret",
            auth_header="Authorization",
            auth_scheme="Bearer",
            flow_id="unified-flow-id",
            input_key="AGENT_USER_INPUT",
            request_style="workflow_v1",
            request_timeout=5,
            seed_demo=False,
        )
        final_result = json.dumps({
            "status": "ok",
            "workflow_mode": "learning",
            "personalized_explanation": "可渲染的讲解内容",
        }, ensure_ascii=False)
        response_texts = iter([
            json.dumps({
                "code": 0,
                "choices": [{"delta": {"content": "{\"phase\":\"generating\"}"}}],
            }, ensure_ascii=False),
            json.dumps({
                "code": 0,
                "choices": [{"delta": {"content": (
                    "进度信息 "
                    + json.dumps({"phase": "validating"}, ensure_ascii=False)
                    + " 最终结果 "
                    + json.dumps({"final_result_json": final_result}, ensure_ascii=False)
                )}}],
            }, ensure_ascii=False),
        ])

        class FakeResponse:
            def __init__(self, content):
                self.content = content

            def __enter__(self):
                return self

            def __exit__(self, exception_type, exception, traceback):
                return False

            def read(self):
                return self.content.encode("utf-8")

        calls = []

        def fake_urlopen(request, timeout):
            calls.append((request, timeout))
            return FakeResponse(next(response_texts))

        gateway = XingchenGateway(settings)
        with patch("backend.server.urllib.request.urlopen", fake_urlopen):
            result = gateway.invoke("learning", {"student_id": "STU-REMOTE-002"})

        self.assertEqual(len(calls), 2)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["personalized_explanation"], "可渲染的讲解内容")

    def test_remote_gateway_extracts_all_split_workflow_result_shapes(self):
        gateway = self.server.RequestHandlerClass.application.gateway
        result_shapes = {
            "learning_path": {"items": []},
            "learning_goal": {"goal_name": "Java 竞赛备赛"},
            "recommendations": [],
            "questions": [],
            "message": "继续练习封装与访问控制。",
        }

        for result_key, result_value in result_shapes.items():
            with self.subTest(result_key=result_key):
                expected = {"status": "ok", result_key: result_value}
                payload = {
                    "choices": [
                        {
                            "delta": {
                                "content": json.dumps(
                                    {"result_json": json.dumps(expected, ensure_ascii=False)},
                                    ensure_ascii=False,
                                )
                            }
                        }
                    ]
                }

                self.assertEqual(gateway._extract_result(payload), expected)

    def test_student_model_cache_tracks_refresh_interval(self):
        database = Path(self.temporary_directory.name) / "student-model-cache.db"
        cache = StudentModelCache(database)
        self.assertTrue(cache.should_refresh("STU-MODEL-001"))

        for _ in range(3):
            cache.increment_event("STU-MODEL-001")
        cache.save_model(
            "STU-MODEL-001",
            {"learning_style": "balanced", "pace_factor": 1.0},
            {"same_error_threshold": 2},
        )
        status = cache.status("STU-MODEL-001")
        self.assertTrue(status["has_profile"])
        self.assertEqual(status["events_since_profile"], 0)
        self.assertFalse(status["needs_refresh"])

        for _ in range(5):
            cache.increment_event("STU-MODEL-001")
        self.assertTrue(cache.should_refresh("STU-MODEL-001"))
        self.assertEqual(cache.status("STU-MODEL-001")["events_since_profile"], 5)

    def test_strategy_engine_and_knowledge_cache(self):
        model = {
            "effective_modes": {"execution_trace": 0.9, "worked_example": 0.4},
            "ineffective_modes": ["analogy"],
            "misconception_tags": ["统计口径混淆"],
            "pace_factor": 0.7,
            "strategy_defaults": {"same_error_threshold": 2},
        }
        learning = StrategyEngine.decide_learning_strategy(
            "first", "code", 20, ["analogy"], model
        )
        self.assertEqual(learning["preferred_representation"], "execution_trace")
        self.assertEqual(learning["explanation_depth"], "foundational")

        remediation = StrategyEngine.decide_remediation_strategy(
            "incorrect", "calculation", 35, 2, 2, 0, [], model
        )
        self.assertEqual(remediation["strategy_code"], "alternative_representation")
        self.assertEqual(remediation["preferred_representation"], "execution_trace")

        cache = KnowledgeCache(ttl_seconds=300)
        self.assertIsNone(cache.get("KN-001:first"))
        cache.set("KN-001:first", "经过校验的知识依据")
        self.assertEqual(cache.get("KN-001:first"), "经过校验的知识依据")

    def test_profile_admin_endpoints(self):
        refreshed = self.request_json(
            "POST",
            "/api/admin/refresh-profile",
            {"student_id": "STU-PROFILE-ADMIN-001"},
        )
        self.assertEqual(refreshed["status"], "ok")
        self.assertIn("learning_style", refreshed["student_model"])

        status = self.request_json(
            "GET", "/api/admin/profile-status?student_id=STU-PROFILE-ADMIN-001"
        )
        self.assertTrue(status["has_profile"])
        self.assertFalse(status["needs_refresh"])
        self.assertEqual(status["events_since_profile"], 0)

    def test_remote_gateway_routes_three_flow_ids(self):
        settings = Settings(
            host="127.0.0.1",
            port=0,
            database_path=Path(self.temporary_directory.name) / "three-flow-remote.db",
            xingchen_mode="remote",
            api_url="https://xingchen-api.xf-yun.com/workflow/v1/chat/completions",
            api_key="api-key",
            api_secret="api-secret",
            auth_header="Authorization",
            auth_scheme="Bearer",
            flow_id="legacy-flow-id",
            input_key="AGENT_USER_INPUT",
            request_style="workflow_v1",
            request_timeout=5,
            seed_demo=False,
            profile_flow_id="profile-flow-id",
            learning_flow_id="learning-flow-id",
            remediation_flow_id="remediation-flow-id",
        )
        captured_flow_ids = []

        class FakeResponse:
            def __init__(self, content):
                self.content = content

            def __enter__(self):
                return self

            def __exit__(self, exception_type, exception, traceback):
                return False

            def read(self):
                return self.content

        def fake_urlopen(request, timeout):
            request_body = json.loads(request.data.decode("utf-8"))
            flow_id = request_body["flow_id"]
            captured_flow_ids.append(flow_id)
            if flow_id == "profile-flow-id":
                result = {
                    "status": "ok",
                    "student_model": {"learning_style": "balanced"},
                    "strategy_defaults": {"same_error_threshold": 2},
                }
            elif flow_id == "learning-flow-id":
                result = {"status": "ok", "content_blocks": []}
            else:
                result = {"status": "ok", "personalized_explanation": "纠错讲解"}
            response = {"code": 0, "choices": [{"delta": {"content": json.dumps(result)}}]}
            return FakeResponse(json.dumps(response).encode("utf-8"))

        gateway = XingchenGateway(settings)
        with patch("backend.server.urllib.request.urlopen", fake_urlopen):
            gateway.invoke_profile_workflow({"student_id": "STU-THREE-001"})
            gateway.invoke_learning_workflow({"student_id": "STU-THREE-001"})
            gateway.invoke_remediation_workflow({"student_id": "STU-THREE-001"})

        self.assertEqual(
            captured_flow_ids,
            ["profile-flow-id", "learning-flow-id", "remediation-flow-id"],
        )

    def test_material_knowledge_gateway_uses_exported_query_contract(self):
        captured = {}

        class MaterialHandler(BaseHTTPRequestHandler):
            def do_POST(self):
                parsed = urlparse(self.path)
                captured.update(parse_qs(parsed.query, keep_blank_values=True))
                body = json.dumps(
                    {
                        "resources": "资料中的封装说明",
                        "return_memory": "不应写入学习者画像",
                    },
                    ensure_ascii=False,
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, _format, *_args):
                return

        plugin_server = ThreadingHTTPServer(("127.0.0.1", 0), MaterialHandler)
        plugin_thread = threading.Thread(
            target=plugin_server.serve_forever, daemon=True
        )
        plugin_thread.start()
        try:
            settings = replace(
                self.server.RequestHandlerClass.application.settings,
                material_knowledge_enabled=True,
                material_knowledge_url=(
                    f"http://127.0.0.1:{plugin_server.server_port}/material"
                ),
                material_knowledge_request_type="0",
            )
            gateway = MaterialKnowledgeGateway(settings)
            result = gateway.query("解释封装", input_source="课程讲义")
        finally:
            plugin_server.shutdown()
            plugin_server.server_close()
            plugin_thread.join(timeout=5)

        self.assertEqual(gateway.status, "ready")
        self.assertEqual(captured["input_request"], ["解释封装"])
        self.assertEqual(captured["input_source"], ["课程讲义"])
        self.assertEqual(captured["input_memory"], [""])
        self.assertEqual(captured["request_type"], ["0"])
        self.assertEqual(result["resources"], "资料中的封装说明")
        self.assertEqual(result["return_memory"], "不应写入学习者画像")
        blocked = MaterialKnowledgeGateway(
            replace(
                settings,
                material_knowledge_url="http://101.35.40.125:8000",
                material_knowledge_allow_insecure_http=False,
            )
        )
        self.assertEqual(blocked.status, "insecure_transport_blocked")
        self.assertFalse(blocked.enabled)

    def test_document_search_returns_trusted_official_docs(self):
        settings = Settings(
            host="127.0.0.1",
            port=0,
            database_path=Path(self.temporary_directory.name) / "doc.db",
            xingchen_mode="mock",
            api_url="",
            api_key="",
            api_secret="",
            auth_header="Authorization",
            auth_scheme="Bearer",
            flow_id="",
            input_key="AGENT_USER_INPUT",
            request_style="workflow_v1",
            request_timeout=5,
            seed_demo=False,
            video_search_mode="bing_rss",
            video_search_url="https://www.bing.com/search?format=rss&q={query}",
            video_search_timeout=5,
            video_search_max_results=2,
            video_search_cache_seconds=60,
        )
        rss = """<?xml version="1.0" encoding="utf-8"?>
        <rss version="2.0"><channel>
          <item>
            <title>Python 官方教程：数据结构</title>
            <link>https://docs.python.org/3/tutorial/datastructures.html</link>
            <description>列表、字典等内置数据结构的官方说明与示例。</description>
          </item>
          <item>
            <title>非白名单站点</title>
            <link>https://example.com/notes.html</link>
            <description>不在文档白名单中，不应进入文档板块。</description>
          </item>
        </channel></rss>""".encode("utf-8")

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exception_type, exception, traceback):
                return False

            def read(self, size=-1):
                return rss if size < 0 else rss[:size]

        captured = {}

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["timeout"] = timeout
            return FakeResponse()

        gateway = VideoSearchGateway(settings)
        self.assertTrue(gateway.doc_enabled)
        payload = {
            "event_type": "request_video",
            "current_knowledge_point": {
                "knowledge_point_id": "KN_JAVA_ENCAPSULATION",
                "knowledge_point_name": "封装与访问控制",
            },
            "learning_goal": {"goal_name": "完成 Python 成绩统计实训"},
        }
        with patch("backend.server.urllib.request.urlopen", fake_urlopen):
            result = gateway.search_documents("learning", payload)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(result["results"][0]["type"], "document")
        self.assertEqual(result["results"][0]["source"], "docs.python.org")
        self.assertIn("docs.python.org", result["results"][0]["url"])
        self.assertTrue(result["results"][0]["content"])
        self.assertIn("官方文档", unquote(captured["url"]))

        disabled = Settings(
            host="127.0.0.1",
            port=0,
            database_path=Path(self.temporary_directory.name) / "doc-off.db",
            xingchen_mode="mock",
            api_url="",
            api_key="",
            api_secret="",
            auth_header="Authorization",
            auth_scheme="Bearer",
            flow_id="",
            input_key="AGENT_USER_INPUT",
            request_style="workflow_v1",
            request_timeout=5,
            seed_demo=False,
            video_search_mode="bing_rss",
            doc_search_mode="off",
            video_search_url="https://www.bing.com/search?format=rss&q={query}",
        )
        self.assertFalse(VideoSearchGateway(disabled).doc_enabled)


    def test_learning_result_merges_video_and_document_resources(self):
        application = self.server.RequestHandlerClass.application
        context = {
            "student_id": "STU-MEDIA-001",
            "session_id": "SESSION-MEDIA-001",
            "event_type": "initialize_learning",
            "current_knowledge_point": {
                "knowledge_point_id": "KN-MEDIA-001",
                "knowledge_point_name": "列表推导式",
            },
            "learning_goal": {"goal_id": "GOAL-MEDIA-001", "goal_name": "完成 Python 实训"},
            "web_search_context": {
                "status": "ok",
                "provider": "bing_rss",
                "query": "列表推导式",
                "results": [
                    {
                        "type": "video",
                        "title": "列表推导式演示",
                        "url": "https://www.bilibili.com/video/BV1Media001",
                        "source": "哔哩哔哩",
                        "source_domain": "bilibili.com",
                        "embed_url": "https://player.bilibili.com/player.html?bvid=BV1Media001",
                        "content": "通过示例演示列表推导式。",
                    },
                    {
                        "type": "document",
                        "title": "Python 官方教程：数据结构",
                        "url": "https://docs.python.org/3/tutorial/datastructures.html",
                        "source": "docs.python.org",
                        "source_domain": "docs.python.org",
                        "content": "列表、字典等内置数据结构的官方说明。",
                    },
                ],
            },
        }
        result = {"status": "ok", "workflow_mode": "learning", "content_blocks": [], "resources": []}
        normalized = application._normalize_learning_result(result, context)
        types = {item.get("type") for item in normalized["resources"]}
        self.assertIn("video", types)
        self.assertIn("document", types)
        self.assertEqual(normalized["resource_gap"], "")
        source_titles = [item.get("title") for item in normalized["sources"]]
        self.assertIn("哔哩哔哩", source_titles)
        self.assertIn("docs.python.org", source_titles)


    def test_online_video_search_keeps_source_and_embed_url(self):
        settings = Settings(
            host="127.0.0.1",
            port=0,
            database_path=Path(self.temporary_directory.name) / "video.db",
            xingchen_mode="mock",
            api_url="",
            api_key="",
            api_secret="",
            auth_header="Authorization",
            auth_scheme="Bearer",
            flow_id="",
            input_key="AGENT_USER_INPUT",
            request_style="workflow_v1",
            request_timeout=5,
            seed_demo=False,
            video_search_mode="bing_rss",
            video_search_url="https://www.bing.com/search?format=rss&q={query}",
            video_search_timeout=5,
            video_search_max_results=2,
            video_search_cache_seconds=60,
        )
        rss = """<?xml version="1.0" encoding="utf-8"?>
        <rss version="2.0"><channel>
          <item>
            <title>Python 平均分与有效成绩教学</title>
            <link>https://www.bilibili.com/video/BV1Debug123</link>
            <description>通过列表筛选、有效记录数量和平均数公式演示 Python 成绩统计过程。</description>
          </item>
          <item>
            <title>无关视频</title>
            <link>https://example.com/video/1</link>
            <description>不在视频来源白名单中。</description>
          </item>
        </channel></rss>""".encode("utf-8")

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exception_type, exception, traceback):
                return False

            def read(self, size=-1):
                return rss if size < 0 else rss[:size]

        captured = {}

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["timeout"] = timeout
            return FakeResponse()

        gateway = VideoSearchGateway(settings)
        payload = {
            "event_type": "request_video",
            "current_knowledge_point": {
                "knowledge_point_id": "KN_JAVA_ENCAPSULATION",
                "knowledge_point_name": "封装与访问控制",
            },
            "learning_goal": {"goal_name": "完成 Python 成绩统计实训"},
        }
        with patch("backend.server.urllib.request.urlopen", fake_urlopen):
            result = gateway.search("learning", payload)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(result["results"][0]["source"], "哔哩哔哩")
        self.assertIn("player.bilibili.com", result["results"][0]["embed_url"])
        self.assertIn("q=", captured["url"])
        self.assertEqual(captured["timeout"], 5)


    def test_workflow_knowledge_unavailable_is_surfaced_safely(self):
        application = self.server.RequestHandlerClass.application
        context = {
            "student_id": "STU-GAP-001",
            "session_id": "SESSION-GAP-001",
            "event_type": "initialize_learning",
            "current_knowledge_point": {
                "knowledge_point_id": "KN-GAP-001",
                "knowledge_point_name": "未知知识点",
                "knowledge_type": "conceptual",
                "mastery": 30,
            },
            "learning_goal": {"goal_id": "GOAL-GAP-001", "goal_name": "完成实训目标"},
        }
        with patch.object(
            application.local_engine,
            "generate_learning_lesson",
            return_value={
                "status": "knowledge_unavailable",
                "workflow_mode": "learning",
                "web_search_query": "未知知识点 原理",
            },
        ):
            result = application.run_learning(context)
        self.assertEqual(result["status"], "knowledge_unavailable")
        self.assertTrue(result["knowledge_gap"])
        self.assertTrue(result["user_message"])

    def test_workflow_web_search_context_json_merges_into_sources(self):
        application = self.server.RequestHandlerClass.application
        context = {
            "student_id": "STU-WEB-SRC-001",
            "session_id": "SESSION-WEB-SRC-001",
            "event_type": "initialize_learning",
            "current_knowledge_point": {
                "knowledge_point_id": "KN-WEB-SRC-001",
                "knowledge_point_name": "列表推导式",
                "knowledge_type": "conceptual",
                "mastery": 30,
            },
            "learning_goal": {"goal_id": "GOAL-WEB-SRC-001", "goal_name": "完成 Python 实训"},
        }
        with patch.object(
            application.local_engine,
            "generate_learning_lesson",
            return_value={
                "status": "ok",
                "workflow_mode": "learning",
                "content_blocks": [
                    {
                        "type": "concept",
                        "title": "核心概念",
                        "content": "列表推导式按可迭代对象生成列表。",
                        "source": "Python 官方文档",
                    }
                ],
                "web_search_context_json": (
                    "{\"results\":[{\"type\":\"web\",\"title\":\"Python 官方教程\","
                    "\"url\":\"https://docs.python.org/3/tutorial/introduction.html\","
                    "\"snippet\":\"官方入门教程\"}]}"
                ),
            },
        ):
            result = application.run_learning(context)
        self.assertEqual(result["status"], "ok")
        titles = [item.get("title") for item in result["sources"]]
        self.assertIn("Python 官方教程", titles)
        document_titles = [
            item.get("title")
            for item in result["resources"]
            if item.get("type") == "document"
        ]
        self.assertIn("Python 官方教程", document_titles)

    def test_portrait_endpoint_aggregates_nine_blocks(self):
        payload = demo_upstream_payload()
        self.request_json("POST", "/api/upstream/assessment-result", payload)
        portrait = self.request_json("GET", "/api/students/STU-DEMO-001/portrait")
        self.assertEqual(portrait["status"], "ok")
        self.assertEqual(len(portrait["abilities"]["dimensions"]), 6)
        self.assertGreaterEqual(len(portrait["knowledge_mastery"]["nodes"]), 1)
        self.assertTrue(portrait["behavior"]["heatmap"])
        self.assertTrue(portrait["behavior"]["badges"])
        self.assertTrue(portrait["comparison"]["me"])
        self.assertIn("kpi", portrait["identity"])
        # 画像数字溯源：data_evidence 为来源事件列表
        self.assertIn("data_evidence", portrait)
        self.assertTrue(all("type" in e and "title" in e for e in portrait["data_evidence"]))

    def test_portrait_aligns_learner_state_v1_schema(self):
        """画像接口对齐 LearnerState v1：summary / misconceptions 细分 / 证据字段。"""
        self.request_json("POST", "/api/upstream/assessment-result", demo_upstream_payload())
        portrait = self.request_json("GET", "/api/students/STU-DEMO-001/portrait")
        self.assertEqual(portrait["status"], "ok")

        # schema_version + summary（进度/掌握 KC 数/30 天活跃/连续天数）
        self.assertEqual(portrait.get("schema_version"), "1.0")
        summary = portrait.get("summary", {})
        self.assertIn("overall_mastery", summary)
        self.assertIn("mastered_kc_count", summary)
        self.assertIn("activity_count_30d", summary)
        self.assertIn("streak_days", summary)

        # knowledge 节点：confidence/trend/is_estimated 如实 null，evidence 字段存在
        nodes = portrait["knowledge_mastery"]["nodes"]
        self.assertTrue(nodes, "画像节点不应为空")
        for node in nodes:
            self.assertIn("evidence_count", node)
            self.assertIn("last_evidence_at", node)
            self.assertIn("status", node)
            self.assertIsNone(node.get("confidence"))
            self.assertIsNone(node.get("trend"))

        # misconceptions 细分：错误卡映射（kc_id/misconception_id/occurrence_count）
        misconceptions = portrait["misconceptions"]["items"]
        self.assertIn("misconceptions", portrait)
        if portrait["weak_points"]["error_breakdown"]:
            self.assertGreaterEqual(len(misconceptions), 1)
            for item in misconceptions:
                self.assertTrue(item["kc_id"])
                self.assertTrue(item["misconception_id"])
                self.assertIn("type", item)
                self.assertGreaterEqual(item["occurrence_count"], 1)

        # metadata / history_quality
        self.assertEqual(portrait["metadata"]["profile_version"], "1.0")
        self.assertIn("history_quality", portrait)

    def test_portrait_consumes_workflow_ability_scores_and_style_distribution(self):
        refreshed = self.request_json(
            "POST",
            "/api/admin/refresh-profile",
            {"student_id": "STU-PORTRAIT-WORKFLOW-001"},
        )
        self.assertEqual(refreshed["status"], "ok")
        ability_scores = refreshed["student_model"]["ability_scores"]
        self.assertEqual(
            list(ability_scores),
            ["理解能力", "应用能力", "推理能力", "表达能力", "复盘能力", "迁移能力"],
        )
        for entry in ability_scores.values():
            self.assertGreaterEqual(entry["score"], 0)
            self.assertLessEqual(entry["score"], 100)
            self.assertGreaterEqual(entry["confidence"], 0.0)
            self.assertLessEqual(entry["confidence"], 1.0)
        saved_distribution = refreshed["student_model"]["learning_style_distribution"]
        self.assertEqual(
            list(saved_distribution),
            ["visual", "auditory", "kinesthetic", "reading"],
        )

        portrait = self.request_json(
            "GET", "/api/students/STU-PORTRAIT-WORKFLOW-001/portrait"
        )
        self.assertFalse(portrait["abilities"]["is_fallback"])
        workflow_by_name = {name: entry["score"] for name, entry in ability_scores.items()}
        for dimension in portrait["abilities"]["dimensions"]:
            self.assertEqual(dimension["score"], workflow_by_name[dimension["name"]])
            self.assertIn("confidence", dimension)
        distribution = portrait["learning_style"]
        for key in ("visual", "auditory", "kinesthetic", "reading"):
            self.assertAlmostEqual(distribution[key], saved_distribution[key], places=2)
        total = sum(distribution[key] for key in ("visual", "auditory", "kinesthetic", "reading"))
        self.assertAlmostEqual(total, 1.0, places=2)

    def test_portrait_does_not_fabricate_abilities_when_scores_missing(self):
        portrait = self.request_json(
            "GET", "/api/students/STU-PORTRAIT-FALLBACK-001/portrait"
        )
        self.assertFalse(portrait["abilities"]["is_fallback"])
        self.assertEqual(portrait["abilities"]["dimensions"], [])
        self.assertIsNone(portrait["identity"]["kpi"]["overall_mastery"])

    def test_review_stream_sections_carry_evidence(self):
        application = self.server.RequestHandlerClass.application
        kind, sections = application._explanation_sections(
            {
                "workflow_mode": "review",
                "explanation_steps": [
                    {
                        "title": "归因",
                        "content": "平均分分母用了全部人数。",
                        "evidence": "错因：统计口径混淆（error_points 归因）",
                    }
                ],
            }
        )
        self.assertEqual(kind, "review")
        self.assertEqual(sections[0]["evidence"], "错因：统计口径混淆（error_points 归因）")

    def test_explanation_ask_follow_up(self):
        upstream = self.request_json(
            "POST", "/api/upstream/assessment-result", demo_upstream_payload()
        )
        session_id = upstream["dispatched"]["learning"]["explanation_session_id"]
        vague = self.request_json(
            "POST",
            f"/api/explanations/{session_id}/ask",
            {
                "student_id": "STU-DEMO-001",
                "selection": "",
                "question": "\u8fd9\u4e2a\u600e\u4e48\u5f04",
                "history": [],
            },
        )
        self.assertEqual(vague["status"], "ok")
        self.assertTrue(vague["clarification"])
        selection = "\u6838\u5fc3\u89c4\u5219"
        detailed = self.request_json(
            "POST",
            f"/api/explanations/{session_id}/ask",
            {
                "student_id": "STU-DEMO-001",
                "selection": selection,
                "question": "\u4e3a\u4ec0\u4e48\u5148\u786e\u5b9a\u6570\u636e\u8303\u56f4",
                "history": [],
            },
        )
        self.assertEqual(detailed["status"], "ok")
        self.assertIn(selection, detailed["answer"])
        self.assertTrue(detailed["follow_up_questions"])
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request_json(
                "POST",
                f"/api/explanations/{session_id}/ask",
                {"student_id": "STU-OTHER-001", "selection": "", "question": "x", "history": []},
            )
        self.assertEqual(error.exception.code, 404)

    def test_explanation_stream_sections_then_eof(self):
        upstream = self.request_json(
            "POST", "/api/upstream/assessment-result", demo_upstream_payload()
        )
        session_id = upstream["dispatched"]["learning"]["explanation_session_id"]
        request = urllib.request.Request(
            f"{self.base_url}/api/explanations/{session_id}/stream?student_id=STU-DEMO-001"
        )
        with urllib.request.urlopen(request, timeout=6) as response:
            self.assertEqual(response.headers.get("Content-Type", ""), "text/event-stream; charset=utf-8")
            data = b""
            while True:
                chunk = response.read(2048)
                if not chunk:
                    break
                data += chunk
        text = data.decode("utf-8")
        self.assertIn("event: status", text)
        self.assertIn("event: section", text)
        self.assertIn("event: done", text)
    def test_knowledge_search_endpoint_and_seed_count(self):
        application = self.server.RequestHandlerClass.application
        # 知识库 ≥50 条（比赛硬要求），当前 56 条
        self.assertGreaterEqual(application.domain.knowledge_count(), 50)
        result = self.request_json(
            "GET",
            "/api/knowledge/search?q=%E5%B0%81%E8%A3%85&limit=5",
        )
        self.assertEqual(result["status"], "ok")
        self.assertGreaterEqual(result["total"], 1)
        self.assertTrue(all(item.get("source") for item in result["items"]))
        filtered = self.request_json(
            "GET",
            "/api/knowledge/search?q=%E5%B0%81%E8%A3%85&knowledge_point_id=KN_JAVA_ENCAPSULATION&action=warning",
        )
        self.assertGreaterEqual(filtered["total"], 1)
        self.assertTrue(
            all(
                item["knowledge_point_id"] == "KN_JAVA_ENCAPSULATION"
                for item in filtered["items"]
            )
        )

    def test_growth_endpoint_returns_real_data(self):
        # 成长轨迹：KPI/徽章/能力对比/时间线全部来自真实数据（非静态假数据）
        growth = self.request_json(
            "GET",
            "/api/students/STU-GROWTH-001/growth",
        )
        self.assertEqual(growth["status"], "ok")
        self.assertIn("kpi", growth)
        self.assertIn("badges", growth)
        self.assertIn("timeline", growth)
        self.assertIn("ability_comparison", growth)
        # KPI 字段完整且为数值
        kpi = growth["kpi"]
        for key in ("nodes_total", "avg_mastery", "badges_earned", "diagnosis_rounds"):
            self.assertIn(key, kpi)
            self.assertIsInstance(kpi[key], int)
        # 徽章为规则计算（earned 布尔）
        self.assertTrue(all("earned" in b for b in growth["badges"]))

    def test_chat_endpoint_clarification_and_rag(self):
        # 模糊提问 → 澄清选项（比赛硬要求：模糊提问澄清）
        vague = self.request_json(
            "POST",
            "/api/chat",
            {"student_id": "STU-CHAT-001", "session_id": "S-CHAT-001", "message": "这个怎么弄"},
        )
        self.assertEqual(vague["status"], "needs_clarification")
        self.assertGreaterEqual(len(vague.get("clarify_options", [])), 2)
        # 明确提问 → 知识库 RAG 回答 + AI 生成标识 + 来源
        clear = self.request_json(
            "POST",
            "/api/chat",
            {"student_id": "STU-CHAT-001", "session_id": "S-CHAT-001", "message": "成绩统计时缺考怎么排除"},
        )
        self.assertEqual(clear["status"], "ok")
        self.assertTrue(clear.get("answer"))
        self.assertIn("ai_generated", clear)
        self.assertGreaterEqual(len(clear.get("sources", [])), 1)

    def test_chat_multi_turn_reference_resolution(self):
        """多轮上下文：第二问"那 getter 方法呢"应承接第一问"封装是什么"的语境。"""
        student = "STU-MT-001"
        first = self.request_json(
            "POST",
            "/api/chat",
            {"student_id": student, "session_id": "S-MT-001", "message": "封装是什么"},
        )
        self.assertEqual(first["status"], "ok")
        second = self.request_json(
            "POST",
            "/api/chat",
            {"student_id": student, "session_id": "S-MT-001", "message": "那 getter 方法呢"},
        )
        self.assertEqual(second["status"], "ok")
        self.assertIn("session_id", second)
        # 指代消解后命中封装语境（而非泛泛查询）
        combined = second["answer"] + "".join(s.get("title", "") for s in second["sources"])
        self.assertTrue(
            "封装" in combined or "getter" in combined.lower() or "private" in combined.lower(),
            f"第二问未承接上文语境：{second['answer'][:60]}",
        )

    def test_chat_web_search_fallback(self):
        """知识库未命中 + 白名单联网检索开启 → 返回联网结果与白名单来源。"""
        application = self.server.RequestHandlerClass.application
        fake_results = {
            "status": "ok",
            "provider": "bing_rss",
            "query": "如何配置数据库连接池 官方文档 标准 (site:...)",
            "results": [
                {
                    "type": "document",
                    "title": "JDBC 连接池官方指南",
                    "url": "https://learn.microsoft.com/zh-cn/java/api/connection-pool",
                    "source": "Microsoft 官方文档",
                    "source_domain": "learn.microsoft.com",
                    "snippet": "连接池管理数据库连接，减少重复建连开销…",
                    "content": "连接池管理数据库连接，减少重复建连开销…",
                    "provider": "Bing RSS",
                }
            ],
        }
        from unittest.mock import PropertyMock, patch

        with (
            patch.object(application.domain, "search_knowledge", return_value=[]),
            patch.object(
                type(application.video_search),
                "doc_enabled",
                new_callable=PropertyMock,
                return_value=True,
            ),
            patch.object(
                application.video_search, "search_documents", return_value=fake_results
            ),
        ):
            result = self.request_json(
                "POST",
                "/api/chat",
                {"student_id": "STU-WEB-001", "message": "如何配置数据库连接池"},
            )
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result.get("web_searched"))
        self.assertIn("联网检索", result["answer"])
        self.assertIn("learn.microsoft.com", result["answer"])
        self.assertTrue(result["sources"], "联网来源不应为空")
        self.assertTrue(
            all(item.get("verification_state") == "whitelisted" for item in result["sources"])
        )

    def test_chat_web_search_disabled_keeps_fallback(self):
        """默认 off 模式（doc_enabled=False）→ 不联网，维持"未检索到"文案。"""
        application = self.server.RequestHandlerClass.application
        from unittest.mock import patch

        with patch.object(application.domain, "search_knowledge", return_value=[]):
            result = self.request_json(
                "POST",
                "/api/chat",
                {"student_id": "STU-WEB-002", "message": "如何配置数据库连接池"},
            )
        self.assertEqual(result["status"], "ok")
        self.assertFalse(result.get("web_searched", False))
        self.assertIn("暂未检索到", result["answer"])
        self.assertEqual(result["sources"], [])

    def test_chat_web_search_failure_falls_back(self):
        """联网检索失败（断网）→ 自动降级，维持"未检索到"文案，不报错。"""
        application = self.server.RequestHandlerClass.application
        from unittest.mock import PropertyMock, patch

        with (
            patch.object(application.domain, "search_knowledge", return_value=[]),
            patch.object(
                type(application.video_search),
                "doc_enabled",
                new_callable=PropertyMock,
                return_value=True,
            ),
            patch.object(
                application.video_search,
                "search_documents",
                return_value={
                    "status": "search_failed",
                    "provider": "bing_rss",
                    "results": [],
                    "error": "timed out",
                },
            ),
        ):
            result = self.request_json(
                "POST",
                "/api/chat",
                {"student_id": "STU-WEB-003", "message": "如何配置数据库连接池"},
            )
        self.assertEqual(result["status"], "ok")
        self.assertFalse(result.get("web_searched", False))
        self.assertIn("暂未检索到", result["answer"])

    def test_learning_kb_text_rag_and_source_references(self):
        application = self.server.RequestHandlerClass.application
        context = {
            "student_id": "STU-KB-001",
            "session_id": "SESSION-KB-001",
            "event_type": "initialize_learning",
            "current_knowledge_point": {
                "knowledge_point_id": "KN_JAVA_ENCAPSULATION",
                "knowledge_point_name": "封装与访问控制",
                "knowledge_type": "conceptual",
                "mastery": 35,
            },
            "learning_goal": {
                "goal_id": "GOAL-KB-001",
                "goal_name": "完成 Java 面向对象成绩管理实训",
            },
        }
        kb_text = application._knowledge_text(context, "learning", "concept")
        self.assertIn("来源：", kb_text)
        self.assertIn("封装", kb_text)
        result = application.run_learning(context)
        self.assertEqual(result["status"], "ok")
        sources = self.request_json(
            "GET",
            f"/api/explanations/{result['explanation_session_id']}/sources?student_id=STU-KB-001",
        )
        titles = [item["title"] for item in sources["items"]]
        self.assertTrue(
            any(
                "Java 核心技术" in title or "Oracle Java 教程" in title
                for title in titles
            ),
            titles,
        )

    def test_follow_up_uses_knowledge_base(self):
        application = self.server.RequestHandlerClass.application
        context = {
            "student_id": "STU-KB-002",
            "session_id": "SESSION-KB-002",
            "event_type": "initialize_learning",
            "current_knowledge_point": {
                "knowledge_point_id": "KN_JAVA_EXCEPTION",
                "knowledge_point_name": "异常处理",
                "knowledge_type": "code",
                "mastery": 40,
            },
            "learning_goal": {"goal_id": "GOAL-KB-002", "goal_name": "完成 Java 面向对象成绩管理实训"},
        }
        result = application.run_learning(context)
        session_id = result["explanation_session_id"]
        reply = self.request_json(
            "POST",
            f"/api/explanations/{session_id}/ask",
            {
                "student_id": "STU-KB-002",
                "selection": "异常",
                "question": "异常处理有哪些易错点",
                "history": [],
            },
        )
        self.assertEqual(reply["status"], "ok")
        self.assertIn("知识库依据", reply["answer"])
        self.assertTrue(reply["kb_sources"])
        self.assertTrue(any(item.get("source") for item in reply["kb_sources"]))

    def test_goal_engine_normalization_and_path(self):
        from backend.goal_engine import (
            build_learning_path,
            list_goals,
            normalize_goal,
            path_for_learning_goal,
        )

        # 口语化目标归一化
        self.assertEqual(normalize_goal("GOAL-JAVA-001")["goal_id"], "GOAL-JAVA-001")
        self.assertEqual(
            normalize_goal("完成 Java 面向对象成绩管理实训")["goal_id"], "GOAL-JAVA-001"
        )
        self.assertEqual(normalize_goal("我想学 java 的类和对象")["goal_id"], "GOAL-JAVA-001")
        self.assertIsNone(normalize_goal("学 Python 数据分析"))
        # 目标 -> 路径（依赖排序，首节点 current）
        path = build_learning_path("GOAL-JAVA-001")
        self.assertEqual(len(path["items"]), 7)
        self.assertEqual(path["items"][0]["knowledge_point_id"], "KN_JAVA_CLASS")
        self.assertEqual(path["items"][0]["status"], "current")
        order = {item["knowledge_point_id"]: index for index, item in enumerate(path["items"])}
        self.assertLess(order["KN_JAVA_CLASS"], order["KN_JAVA_ENCAPSULATION"])
        self.assertLess(order["KN_JAVA_ENCAPSULATION"], order["KN_JAVA_INHERITANCE"])
        self.assertLess(order["KN_JAVA_INHERITANCE"], order["KN_JAVA_POLYMORPHISM"])
        self.assertLess(order["KN_JAVA_EXCEPTION"], order["KN_JAVA_IO"])
        # 未匹配目标 -> None（OOV 兜底）
        self.assertIsNone(path_for_learning_goal({"goal_name": "随便学点"}))
        self.assertTrue(list_goals())

    def test_goal_driven_learning_without_diagnostic(self):
        # 方向4：只有学习目标、无上游诊断时，按目标图谱生成路径并开始讲解
        result = self.request_json(
            "POST",
            "/api/workflows/learning",
            {
                "student_id": "STU-GOAL-001",
                "session_id": "SESSION-GOAL-001",
                "event_type": "initialize_learning",
                "learning_goal": {
                    "goal_id": "GOAL-JAVA-001",
                    "goal_type": "course",
                    "goal_name": "完成 Java 面向对象成绩管理实训",
                },
            },
        )
        self.assertEqual(result["status"], "ok")
        items = (result.get("learning_path") or {}).get("items") or []
        self.assertEqual(len(items), 7)
        self.assertEqual(items[0]["knowledge_point_id"], "KN_JAVA_CLASS")
        self.assertEqual(items[0]["status"], "current")
        self.assertEqual(items[1]["status"], "pending")
        self.assertEqual(result.get("knowledge_point_id"), "KN_JAVA_CLASS")
        self.assertTrue(
            any(
                block.get("source") == "学习目标图谱"
                for block in result.get("content_blocks", [])
            )
        )

    def test_upstream_dispatch_with_goal_only(self):
        # 方向4：上游只带学习目标（无测评弱项）也会触发目标驱动学习
        payload = {
            "event_id": "TEST-GOAL-UPSTREAM-001",
            "student_id": "STU-GOAL-UP-001",
            "session_id": "SESSION-GOAL-UP-001",
            "attempt_id": "ATTEMPT-GOAL-001",
            "route_type": "goal_driven",
            "learning_goal": {
                "goal_id": "GOAL-JAVA-001",
                "goal_type": "course",
                "goal_name": "完成 Java 面向对象成绩管理实训",
            },
        }
        upstream = self.request_json("POST", "/api/upstream/assessment-result", payload)
        self.assertEqual(upstream["status"], "accepted")
        learning = upstream.get("dispatched", {}).get("learning", {})
        self.assertEqual(learning.get("status"), "ok")
        items = (learning.get("learning_path") or {}).get("items") or []
        self.assertEqual(len(items), 7)
        self.assertEqual(items[0]["knowledge_point_id"], "KN_JAVA_CLASS")

    def test_goal_driven_path_advances_on_check_feedback(self):
        # 方向4：目标驱动路径在答对理解检查后推进到下一节点
        student_id = "STU-GOAL-ADV-001"
        session_id = "SESSION-GOAL-ADV-001"
        started = self.request_json(
            "POST",
            "/api/workflows/learning",
            {
                "student_id": student_id,
                "session_id": session_id,
                "event_type": "initialize_learning",
                "learning_goal": {
                    "goal_id": "GOAL-JAVA-001",
                    "goal_type": "course",
                    "goal_name": "完成 Java 面向对象成绩管理实训",
                },
            },
        )
        self.assertEqual(started["status"], "ok")
        self.assertEqual(started["knowledge_point_id"], "KN_JAVA_CLASS")
        self.assertEqual(started["learning_path"]["items"][0]["status"], "current")

        checked = self.request_json(
            "POST",
            "/api/workflows/learning",
            {
                "student_id": student_id,
                "session_id": session_id,
                "event_type": "check_feedback",
                "selected_answer": "b",
            },
        )
        self.assertEqual(checked["status"], "ok")
        items = {item["knowledge_point_id"]: item for item in checked["learning_path"]["items"]}
        self.assertEqual(items["KN_JAVA_CLASS"]["status"], "completed")
        self.assertEqual(items["KN_JAVA_CLASS"]["mastery"], 20)
        self.assertEqual(items["KN_JAVA_ENCAPSULATION"]["status"], "current")
        self.assertEqual(checked["knowledge_point_id"], "KN_JAVA_ENCAPSULATION")
        # 目标流从 0 开始，完成 1/7 节点后进度为 round(100/7)=14
        self.assertEqual(checked["path_update"]["progress"], 14)

    def test_diagnosis_flow_judges_and_updates_mastery(self) -> None:
        """诊断：目标取样、服务端判题、答错归因、掌握度更新。"""
        self.request_json("POST", "/api/demo/seed", None)
        start = self.request_json(
            "POST",
            "/api/diagnosis/start",
            {
                "student_id": "STU-DEMO-001",
                "session_id": "DEMO-SESSION-001",
                "goal": "competition",
            },
        )
        self.assertEqual(start["status"], "ok")
        self.assertEqual(start["total"], 14)
        self.assertTrue(start["questions"])
        # 答案不得泄露给前端
        for question in start["questions"]:
            self.assertNotIn("answer", question)
            self.assertNotIn("explanation", question)
            self.assertIn("knowledge_point_id", question)

        # 从服务端状态取首题答案，先故意答错
        state = self.request_json(
            "GET", "/api/bootstrap?student_id=STU-DEMO-001"
        )
        diagnosis = self.server.RequestHandlerClass.application.store.get_student_state(
            "STU-DEMO-001"
        )["diagnosis_session"]
        first = diagnosis["questions"][0]
        wrong_choice = _wrong_answer_for(first)
        answered = self.request_json(
            "POST",
            "/api/diagnosis/answer",
            {
                "student_id": "STU-DEMO-001",
                "session_id": "DEMO-SESSION-001",
                "selected": wrong_choice,
            },
        )
        self.assertFalse(answered["correct"])
        self.assertTrue(answered["explanation"])

        # 剩余题目全部答对，完成归因
        bank = {
            q["id"]: q
            for q in __import__("backend.server", fromlist=["DIAGNOSIS_BANK"]).DIAGNOSIS_BANK
        }
        final: dict = {}
        for question in diagnosis["questions"][1:]:
            final = self.request_json(
                "POST",
                "/api/diagnosis/answer",
                {
                    "student_id": "STU-DEMO-001",
                    "session_id": "DEMO-SESSION-001",
                    "selected": bank[question["question_id"]]["answer"],
                },
            )
        self.assertEqual(final["status"], "completed")
        self.assertEqual(final["stats"]["correct"], 13)
        self.assertEqual(final["stats"]["wrong"], 1)
        self.assertTrue(final["summary"]["weak_points"])
        wrong_kp = final["summary"]["weak_points"][0]["knowledge_point_id"]
        self.assertEqual(wrong_kp, first["knowledge_point_id"])
        # 掌握度应下降（原 82 - 12 = 70）
        path = self.request_json(
            "GET", "/api/bootstrap?student_id=STU-DEMO-001"
        ).get("learning_path") or {}
        items = {item["knowledge_point_id"]: item for item in path.get("items", [])}
        self.assertLess(items[wrong_kp]["mastery"], 82)

    def test_diagnosis_weak_points_carry_error_card_attribution(self) -> None:
        """诊断归因字段来自错误卡配置（P1-3）：weak_points 带 error_type / misconception_tag / root_cause。"""
        self.request_json("POST", "/api/demo/seed", None)
        start = self.request_json(
            "POST",
            "/api/diagnosis/start",
            {
                "student_id": "STU-ATTR-001",
                "session_id": "ATTR-SESSION-001",
                "goal": "daily",
            },
        )
        self.assertEqual(start["status"], "ok")
        diagnosis = self.server.RequestHandlerClass.application.store.get_student_state(
            "STU-ATTR-001"
        )["diagnosis_session"]
        first = diagnosis["questions"][0]
        wrong_choice = _wrong_answer_for(first)
        self.request_json(
            "POST",
            "/api/diagnosis/answer",
            {
                "student_id": "STU-ATTR-001",
                "session_id": "ATTR-SESSION-001",
                "selected": wrong_choice,
            },
        )
        bank = {
            q["id"]: q
            for q in __import__("backend.server", fromlist=["DIAGNOSIS_BANK"]).DIAGNOSIS_BANK
        }
        final: dict = {}
        for question in diagnosis["questions"][1:]:
            final = self.request_json(
                "POST",
                "/api/diagnosis/answer",
                {
                    "student_id": "STU-ATTR-001",
                    "session_id": "ATTR-SESSION-001",
                    "selected": bank[question["question_id"]]["answer"],
                },
            )
        self.assertEqual(final["status"], "completed")
        point = final["summary"]["weak_points"][0]
        self.assertTrue(point["error_id"])
        self.assertTrue(point["error_type"])
        self.assertTrue(point["misconception_tag"])
        self.assertTrue(point["root_cause"])

    def test_diagnosis_accepts_four_option_question(self) -> None:
        """落差4修复：学习者形态支持 4 选项题（工作流生成 3-4 选项均合法）。"""
        self.request_json("POST", "/api/demo/seed", None)
        start = self.request_json(
            "POST",
            "/api/diagnosis/start",
            {
                "student_id": "STU-OPT4-001",
                "session_id": "OPT4-SESSION-001",
                "goal": "daily",
            },
        )
        self.assertEqual(start["status"], "ok")
        application = self.server.RequestHandlerClass.application
        state = application.store.get_student_state("STU-OPT4-001")
        session = state["diagnosis_session"]
        session["questions"][0] = {
            "question_id": "GEN-OPT4-001",
            "knowledge_point_id": "KN_JAVA_CLASS",
            "knowledge_point_name": "类的定义与对象创建",
            "title": "四选项题",
            "options": {"a": "1", "b": "2", "c": "3", "d": "4"},
            "answer": "d",
            "explanation": "解析",
            "difficulty": 1,
        }
        application.store.save_student_state("STU-OPT4-001", state)
        answered = self.request_json(
            "POST",
            "/api/diagnosis/answer",
            {
                "student_id": "STU-OPT4-001",
                "session_id": "OPT4-SESSION-001",
                "selected": "d",
            },
        )
        self.assertTrue(answered["correct"])

    def test_diagnosis_writeback_feeds_next_round_by_weak_point(self) -> None:
        """落差5+1修复：归因回写 upstream_payload，复测出题按薄弱点优先。"""
        self.request_json("POST", "/api/demo/seed", None)
        application = self.server.RequestHandlerClass.application
        start = self.request_json(
            "POST",
            "/api/diagnosis/start",
            {
                "student_id": "STU-WB-001",
                "session_id": "WB-SESSION-001",
                "goal": "daily",
            },
        )
        self.assertIn("provider", start)
        diagnosis = application.store.get_student_state("STU-WB-001")[
            "diagnosis_session"
        ]
        first = diagnosis["questions"][0]
        wrong_choice = _wrong_answer_for(first)
        self.request_json(
            "POST",
            "/api/diagnosis/answer",
            {
                "student_id": "STU-WB-001",
                "session_id": "WB-SESSION-001",
                "selected": wrong_choice,
            },
        )
        bank = {
            q["id"]: q
            for q in __import__("backend.server", fromlist=["DIAGNOSIS_BANK"]).DIAGNOSIS_BANK
        }
        final: dict = {}
        for question in diagnosis["questions"][1:]:
            final = self.request_json(
                "POST",
                "/api/diagnosis/answer",
                {
                    "student_id": "STU-WB-001",
                    "session_id": "WB-SESSION-001",
                    "selected": bank[question["question_id"]]["answer"],
                },
            )
        self.assertEqual(final["status"], "completed")
        weak_points = application.store.get_student_state("STU-WB-001")[
            "upstream_payload"
        ]["diagnostic_result"]["weak_points"]
        self.assertTrue(weak_points)
        weak_kp = weak_points[0]["knowledge_point_id"]
        # 复测：出题按薄弱点优先（复用题/工作流生成均薄弱点排前）
        second = self.request_json(
            "POST",
            "/api/diagnosis/start",
            {
                "student_id": "STU-WB-001",
                "session_id": "WB-SESSION-001",
                "goal": "daily",
            },
        )
        self.assertEqual(
            second["questions"][0]["knowledge_point_id"], weak_kp
        )

    def test_diagnosis_reuses_persisted_generated_questions(self) -> None:
        """落差3修复：生成题入库后，后续诊断优先复用（provider=workflow_reuse）。"""
        self.request_json("POST", "/api/demo/seed", None)
        first = self.request_json(
            "POST",
            "/api/diagnosis/start",
            {
                "student_id": "STU-REUSE-001",
                "session_id": "REUSE-SESSION-001",
                "goal": "daily",
            },
        )
        first_ids = {q["question_id"] for q in first["questions"]}
        second = self.request_json(
            "POST",
            "/api/diagnosis/start",
            {
                "student_id": "STU-REUSE-001",
                "session_id": "REUSE-SESSION-001",
                "goal": "daily",
            },
        )
        self.assertEqual(second["provider"], "workflow_reuse")
        second_ids = {q["question_id"] for q in second["questions"]}
        self.assertTrue(second_ids & first_ids)

    def test_code_run_executes_and_timeouts(self) -> None:
        """本地代码执行：Python 运行、Java 编译错误、死循环超时。"""
        run = self.request_json(
            "POST",
            "/api/code/run",
            {
                "student_id": "STU-DEMO-001",
                "session_id": "DEMO-SESSION-001",
                "language": "python",
                "code": "print(1 + 1)",
            },
        )
        self.assertEqual(run["status"], "ok")
        self.assertIn("2", run["output"])

        java_ok = self.request_json(
            "POST",
            "/api/code/run",
            {
                "student_id": "STU-DEMO-001",
                "session_id": "DEMO-SESSION-001",
                "language": "java",
                "code": 'System.out.println("avg=" + (90 + 60) / 2.0);',
            },
        )
        self.assertEqual(java_ok["status"], "ok")
        self.assertIn("avg=75.0", java_ok["output"])

        timeout = self.request_json(
            "POST",
            "/api/code/run",
            {
                "student_id": "STU-DEMO-001",
                "session_id": "DEMO-SESSION-001",
                "language": "python",
                "code": "while True:\n    pass",
            },
            timeout=8,
        )
        self.assertEqual(timeout["status"], "timeout")




    def test_bank_answer_records_attempt_and_updates_mastery(self) -> None:
        """??????? + attempts ???mode=bank?+ ??????? +20/-10?E-2??"""
        self.request_json("POST", "/api/demo/seed", None)
        bank = {
            q["id"]: q
            for q in __import__("backend.server", fromlist=["DIAGNOSIS_BANK"]).DIAGNOSIS_BANK
        }
        first_id = next(iter(bank))
        question = bank[first_id]
        kp_id = question["knowledge_point_id"]
        correct_answer = question["answer"]

        def mastery_of(kp: str) -> int:
            state = self.request_json("GET", "/api/bootstrap?student_id=STU-DEMO-001")
            items = state.get("learning_path", {}).get("items", []) or []
            for item in items:
                if item.get("knowledge_point_id") == kp:
                    return int(item.get("mastery", 0) or 0)
            return -1

        before = mastery_of(kp_id)
        self.assertGreaterEqual(before, 0)

        # ???+20 ???
        ok = self.request_json(
            "POST",
            "/api/bank/answer",
            {
                "student_id": "STU-DEMO-001",
                "session_id": "DEMO-SESSION-001",
                "question_id": first_id,
                "answer": correct_answer,
            },
        )
        self.assertTrue(ok["correct"])
        self.assertTrue(ok["attempt_id"])
        self.assertEqual(mastery_of(kp_id), min(100, before + 20))

        # ???????????? -10 ???
        wrong = "a" if correct_answer != "a" else "b"
        bad = self.request_json(
            "POST",
            "/api/bank/answer",
            {
                "student_id": "STU-DEMO-001",
                "session_id": "DEMO-SESSION-001",
                "question_id": first_id,
                "answer": wrong,
            },
        )
        self.assertFalse(bad["correct"])
        self.assertEqual(mastery_of(kp_id), max(0, min(100, before + 20) - 10))

        # attempts ?????mode=bank ??????
        records = self.request_json(
            "GET", "/api/students/STU-DEMO-001/records"
        )
        bank_attempts = [
            entry
            for entry in records.get("attempts", [])
            if entry.get("mode") == "bank" and entry.get("source_question_id") == first_id
        ]
        self.assertGreaterEqual(len(bank_attempts), 2)
        statuses = {entry.get("status") for entry in bank_attempts}
        self.assertIn("correct", statuses)
        self.assertIn("incorrect", statuses)

    def test_diagnosis_answer_persists_attempt_with_mode(self) -> None:
        """?????????????? attempts?mode=diagnosis?????/?????"""
        self.request_json("POST", "/api/demo/seed", None)
        start = self.request_json(
            "POST",
            "/api/diagnosis/start",
            {
                "student_id": "STU-DEMO-001",
                "session_id": "DEMO-SESSION-001",
                "goal": "competition",
            },
        )
        self.assertEqual(start["status"], "ok")
        diagnosis = self.server.RequestHandlerClass.application.store.get_student_state(
            "STU-DEMO-001"
        )["diagnosis_session"]
        first = diagnosis["questions"][0]
        wrong = _wrong_answer_for(first)
        answered = self.request_json(
            "POST",
            "/api/diagnosis/answer",
            {
                "student_id": "STU-DEMO-001",
                "session_id": "DEMO-SESSION-001",
                "selected": wrong,
            },
        )
        self.assertFalse(answered["correct"])
        records = self.request_json(
            "GET", "/api/students/STU-DEMO-001/records"
        )
        diagnosis_attempts = [
            entry
            for entry in records.get("attempts", [])
            if entry.get("mode") == "diagnosis"
            and entry.get("source_question_id") == first["question_id"]
        ]
        self.assertEqual(len(diagnosis_attempts), 1)
        self.assertEqual(diagnosis_attempts[0]["status"], "incorrect")


class DiagnosisBankAndErrorCardsTests(unittest.TestCase):
    """P1-2 题库数据驱动 / P1-3 错误卡查表化的单元测试。"""

    def test_diagnosis_bank_questions_carry_knowledge_point_id(self) -> None:
        from backend.data.diagnosis_bank import DIAGNOSIS_BANK

        self.assertGreaterEqual(len(DIAGNOSIS_BANK), 14)
        for question in DIAGNOSIS_BANK:
            self.assertTrue(question["id"])
            self.assertTrue(question["knowledge_point_id"])
            self.assertIn("answer", question)
            self.assertIn("explanation", question)

    def test_select_diagnosis_questions_respects_goal_and_size(self) -> None:
        from backend.data.diagnosis_bank import (
            DIAGNOSIS_GOALS,
            select_diagnosis_questions,
        )

        competition = select_diagnosis_questions("competition")
        certification = select_diagnosis_questions("certification")
        daily = select_diagnosis_questions("daily")

        self.assertEqual(len(competition), DIAGNOSIS_GOALS["competition"]["size"])
        self.assertEqual(len(certification), DIAGNOSIS_GOALS["certification"]["size"])
        self.assertEqual(len(daily), DIAGNOSIS_GOALS["daily"]["size"])
        # 目标专属题只出现在对应目标的取样结果中
        competition_ids = {q["id"] for q in competition}
        certification_ids = {q["id"] for q in certification}
        daily_ids = {q["id"] for q in daily}
        self.assertIn("D-COMP-1", competition_ids)
        self.assertNotIn("D-COMP-1", certification_ids)
        self.assertIn("D-CERT-1", certification_ids)
        self.assertNotIn("D-CERT-1", competition_ids)
        self.assertIn("D-DAILY-1", daily_ids)
        # 每知识点至少出现一次
        kps = {q["knowledge_point_id"] for q in competition}
        self.assertEqual(
            kps,
            {
                "KN_JAVA_CLASS",
                "KN_JAVA_ENCAPSULATION",
                "KN_JAVA_INHERITANCE",
                "KN_JAVA_POLYMORPHISM",
                "KN_JAVA_COLLECTION",
                "KN_JAVA_EXCEPTION",
                "KN_JAVA_IO",
            },
        )

    def test_variant_practice_templates_from_error_cards(self) -> None:
        from backend.data.error_cards import (
            DEFAULT_VARIANT_PRACTICE,
            variant_practice_for,
        )

        encapsulation = variant_practice_for("KN_JAVA_ENCAPSULATION")
        self.assertEqual(encapsulation["title"], "封装变式题：getter/setter")
        self.assertIn("getScores()", encapsulation["expected_answer"])

        inheritance = variant_practice_for("KN_JAVA_INHERITANCE")
        self.assertEqual(inheritance["title"], "继承变式题：重写 averageScore")
        self.assertIn("super.averageScore()", inheritance["expected_answer"])

        # 未配置变式模板的知识点走通用模板
        generic = variant_practice_for("KN_JAVA_IO")
        self.assertEqual(generic, DEFAULT_VARIANT_PRACTICE)
        # 未知知识点同样走通用模板，不抛异常
        unknown = variant_practice_for("KN_UNKNOWN")
        self.assertEqual(unknown, DEFAULT_VARIANT_PRACTICE)

    def test_default_error_card_provides_attribution_fields(self) -> None:
        from backend.data.error_cards import default_error_card_for

        card = default_error_card_for("KN_JAVA_ENCAPSULATION")
        self.assertEqual(card["error_id"], "ENCAP_EXPOSED_ARRAY_REF")
        self.assertTrue(card["error_type"])
        self.assertTrue(card["misconception_tag"])
        self.assertTrue(card["root_cause"])
        self.assertEqual(default_error_card_for("KN_UNKNOWN"), {})


class KnowledgeGovernanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "governance.db"
        self.domain = LearningDomainStore(self.database_path)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def stage_source(self, document_id: str = "DOC-GOV-001") -> dict:
        return self.domain.stage_source_document({
            "document_id": document_id,
            "title": "Python 官方教程",
            "source_type": "official_document",
            "source_url": "https://docs.python.org/zh-cn/3/tutorial/",
            "authority": "Python Software Foundation",
            "valid_year": "2026",
            "region": "global",
            "content_hash": "a" * 64,
        })

    def test_old_knowledge_table_migrates_idempotently(self) -> None:
        legacy_path = Path(self.temporary_directory.name) / "legacy.db"
        with closing(sqlite3.connect(legacy_path)) as connection:
            connection.executescript(
                """
                CREATE TABLE knowledge_entries (
                    rowid INTEGER PRIMARY KEY AUTOINCREMENT,
                    entry_id TEXT NOT NULL UNIQUE,
                    knowledge_point_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    category TEXT NOT NULL,
                    content TEXT NOT NULL,
                    source TEXT NOT NULL,
                    source_type TEXT NOT NULL DEFAULT 'document',
                    document_id TEXT NOT NULL DEFAULT '',
                    locator TEXT NOT NULL DEFAULT '',
                    safety INTEGER NOT NULL DEFAULT 0,
                    job_role TEXT NOT NULL DEFAULT '',
                    action TEXT NOT NULL DEFAULT '',
                    keywords TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                INSERT INTO knowledge_entries(
                    entry_id, knowledge_point_id, title, category, content,
                    source, created_at
                ) VALUES (
                    'KN-LEGACY-001', 'KN_LEGACY', '旧库迁移测试', 'concept',
                    '旧版知识内容', '已核实旧资料', '2026-01-01T00:00:00+00:00'
                );
                """
            )

        migrated = LearningDomainStore(legacy_path)
        LearningDomainStore(legacy_path)

        with closing(sqlite3.connect(legacy_path)) as connection:
            columns = {
                row[1] for row in connection.execute(
                    "PRAGMA table_info(knowledge_entries)"
                ).fetchall()
            }
            status = connection.execute(
                "SELECT review_status FROM knowledge_entries "
                "WHERE entry_id = 'KN-LEGACY-001'"
            ).fetchone()[0]
        self.assertTrue({
            "published_at", "fetched_at", "authority", "valid_year",
            "region", "content_hash", "review_status", "reviewed_at",
            "reviewed_by",
        }.issubset(columns))
        self.assertEqual(status, "approved")
        self.assertEqual(
            migrated.search_knowledge(query="旧库迁移测试")[0]["entry_id"],
            "KN-LEGACY-001",
        )

    def test_candidate_defaults_to_pending_and_is_not_published(self) -> None:
        source = self.stage_source()
        candidate = self.domain.stage_knowledge_candidate({
            "knowledge_point_id": "KN_PYTHON_LIST",
            "title": "列表推导式候选条目",
            "category": "concept",
            "content": "列表推导式用于从可迭代对象构造新列表。",
            "document_id": source["document_id"],
            "locator": "5.1.3 节",
        })

        self.assertEqual(source["review_status"], "pending")
        self.assertEqual(candidate["review_status"], "pending")
        self.assertEqual(
            self.domain.list_knowledge_candidates("pending")[0]["candidate_id"],
            candidate["candidate_id"],
        )
        self.assertFalse(
            any(
                item["title"] == candidate["title"]
                for item in self.domain.search_knowledge(
                    query="列表推导式候选条目", limit=20
                )
            )
        )

    def test_candidate_review_requires_approved_source_and_valid_transition(self) -> None:
        source = self.stage_source()
        candidate = self.domain.stage_knowledge_candidate({
            "knowledge_point_id": "KN_PYTHON_SOURCE_GOVERNANCE",
            "title": "来源约束候选条目",
            "category": "concept",
            "content": "只有来源审核通过后，候选资料才可通过审核。",
            "document_id": source["document_id"],
            "locator": "审核发布测试段落",
        })

        with self.assertRaisesRegex(ValueError, "来源文档审核通过"):
            self.domain.review_knowledge_candidate(
                candidate["candidate_id"], "approved", "reviewer-001"
            )
        self.domain.review_source_document(
            source["document_id"], "approved", "reviewer-001"
        )
        approved = self.domain.review_knowledge_candidate(
            candidate["candidate_id"], "approved", "reviewer-001"
        )
        self.assertEqual(approved["review_status"], "approved")
        published = self.domain.search_knowledge(
            query="来源约束候选条目", limit=20
        )
        self.assertEqual(len(published), 1)
        self.assertTrue(published[0]["entry_id"].startswith("KN-CAND-"))
        self.assertEqual(
            published[0]["knowledge_point_id"],
            "KN_PYTHON_SOURCE_GOVERNANCE",
        )
        self.assertEqual(published[0]["source"], source["title"])
        self.assertEqual(published[0]["source_type"], source["source_type"])
        self.assertEqual(published[0]["document_id"], source["document_id"])
        self.assertEqual(published[0]["locator"], "审核发布测试段落")
        self.assertEqual(published[0]["reviewed_by"], "reviewer-001")
        published_count = self.domain.knowledge_count()
        self.domain.review_knowledge_candidate(
            candidate["candidate_id"], "approved", "reviewer-001"
        )
        self.assertEqual(self.domain.knowledge_count(), published_count)
        self.assertEqual(
            self.domain.search_knowledge(
                query="来源约束候选条目", limit=20
            )[0]["entry_id"],
            published[0]["entry_id"],
        )
        with self.assertRaisesRegex(ValueError, "不允许的审核状态转换"):
            self.domain.review_knowledge_candidate(
                candidate["candidate_id"], "rejected", "reviewer-001"
            )

    def test_ai_generated_candidate_cannot_be_approved(self) -> None:
        source = self.stage_source("DOC-GOV-AI-001")
        self.domain.review_source_document(
            source["document_id"], "approved", "reviewer-001"
        )
        candidate = self.domain.stage_knowledge_candidate({
            "title": "AI 生成候选条目",
            "category": "concept",
            "content": "这段内容由模型生成，只能留在候选区。",
            "document_id": source["document_id"],
            "ai_generated": True,
        })

        with self.assertRaisesRegex(ValueError, "AI 生成候选"):
            self.domain.review_knowledge_candidate(
                candidate["candidate_id"], "approved", "reviewer-001"
            )
        pending = self.domain.list_knowledge_candidates("pending")
        self.assertTrue(pending[0]["ai_generated"])

    def test_source_content_change_requires_candidate_review_again(self) -> None:
        source = self.stage_source("DOC-GOV-CHANGE-001")
        self.domain.review_source_document(
            source["document_id"], "approved", "reviewer-001"
        )
        candidate = self.domain.stage_knowledge_candidate({
            "title": "会随来源变化的候选条目",
            "category": "concept",
            "content": "候选内容来自当前版本的来源文档。",
            "document_id": source["document_id"],
        })
        self.domain.review_knowledge_candidate(
            candidate["candidate_id"], "approved", "reviewer-001"
        )
        published = self.domain.search_knowledge(
            query="会随来源变化的候选条目", limit=20
        )[0]

        changed_source = self.domain.stage_source_document({
            "document_id": source["document_id"],
            "title": source["title"],
            "source_type": source["source_type"],
            "content_hash": "b" * 64,
        })
        changed_candidate = self.domain.list_knowledge_candidates(
            "needs_update"
        )[0]

        self.assertEqual(changed_source["review_status"], "needs_update")
        self.assertEqual(changed_source["reviewed_by"], "")
        self.assertEqual(changed_candidate["candidate_id"], candidate["candidate_id"])
        self.assertEqual(changed_candidate["reviewed_by"], "")
        self.assertFalse(
            any(
                item["title"] == "会随来源变化的候选条目"
                for item in self.domain.search_knowledge(
                    query="会随来源变化的候选条目", limit=20
                )
            )
        )
        with closing(sqlite3.connect(self.database_path)) as connection:
            published_status = connection.execute(
                "SELECT review_status FROM knowledge_entries WHERE entry_id = ?",
                (published["entry_id"],),
            ).fetchone()[0]
        self.assertEqual(published_status, "needs_update")

        self.domain.review_source_document(
            source["document_id"], "approved", "reviewer-002"
        )
        self.domain.review_knowledge_candidate(
            candidate["candidate_id"], "approved", "reviewer-002"
        )
        republished = self.domain.search_knowledge(
            query="会随来源变化的候选条目", limit=20
        )[0]
        self.assertEqual(republished["entry_id"], published["entry_id"])
        self.assertEqual(republished["reviewed_by"], "reviewer-002")

    def test_initialization_backfills_legacy_approved_candidate(self) -> None:
        source = self.stage_source("DOC-GOV-BACKFILL-001")
        self.domain.review_source_document(
            source["document_id"], "approved", "reviewer-001"
        )
        candidate = self.domain.stage_knowledge_candidate({
            "knowledge_point_id": "KN_PYTHON_BACKFILL",
            "title": "历史审核候选补发布",
            "category": "concept",
            "content": "旧版本只记录审核状态，没有创建正式知识条目。",
            "document_id": source["document_id"],
            "locator": "历史审核记录",
        })
        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.execute(
                """
                UPDATE knowledge_candidates
                SET review_status = 'approved', reviewed_at = ?, reviewed_by = ?
                WHERE candidate_id = ?
                """,
                (
                    "2026-08-14T00:00:00+00:00",
                    "legacy-reviewer",
                    candidate["candidate_id"],
                ),
            )
            connection.commit()

        reloaded = LearningDomainStore(self.database_path)
        published = reloaded.search_knowledge(
            query="历史审核候选补发布", limit=20
        )
        self.assertEqual(len(published), 1)
        self.assertEqual(published[0]["reviewed_by"], "legacy-reviewer")


if __name__ == "__main__":
    unittest.main()
