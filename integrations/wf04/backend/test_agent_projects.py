"""项目层（agent 形态）接口集成测试：创建/列表/详情/测评/讲解。

与 test_backend.py 同风格：临时 DB + mock 模式 + 真实 HTTP 请求。
"""

import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from backend.learning_map import build_learning_map
from backend.plan_brief import build_plan_brief
from backend.plan_context import build_plan_context, classify_knowledge_points
from backend.server import Settings, create_server
from backend.server import ApiError, GatewayError, LearningApplication


class AgentProjectApiTests(unittest.TestCase):
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
        self.student_id = "STU-AGENT-001"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temporary_directory.cleanup()

    def request_json(self, method, path, payload=None, timeout=5):
        import urllib.request

        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + path,
            data=body,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def create_project(self, text):
        return self.request_json(
            "POST", "/api/projects", {"student_id": self.student_id, "text": text}
        )

    def test_learning_task_handoff_creates_idempotent_three_stage_project(self):
        handoff = {
            "schema_version": "learning-task-knowledge-to-personalized-learning-v1",
            "entry_id": "ple_scoped_vlan_001",
            "source": {
                "source_system": "learning-work-task-conversion",
                "task_card_id": "ltc_network_001",
            },
            "task_context": {
                "work_task_id": "work_network_001",
                "enterprise_task_name": "配置园区网络",
                "teaching_task_name": "完成 VLAN 划分与连通性验收",
            },
            "focus": {
                "knowledge_point": {
                    "knowledge_id": "kp_vlan",
                    "name": "VLAN 与 802.1Q",
                },
                "source_steps": [{
                    "step_id": "step_config",
                    "name": "配置交换机端口",
                    "action": "创建 VLAN 并配置端口模式",
                    "deliverable": "交换机配置记录",
                    "check": "终端连通性测试通过",
                }],
                "strongly_related_skills": [{
                    "skill_id": "skill_vlan_config",
                    "name": "VLAN 配置与核验",
                }],
                "relationships": [{
                    "relation_id": "rel_vlan_001",
                    "step_id": "step_config",
                    "knowledge_id": "kp_vlan",
                    "skill_ids": ["skill_vlan_config"],
                }],
            },
            "feedback_contract": {
                "schema_version": "personalized-learning-to-task-conversion-feedback-v1",
            },
        }
        payload = {"student_id": self.student_id, "handoff": handoff}
        application = self.server.RequestHandlerClass.application

        first = application.import_learning_task_knowledge(payload)
        second = application.import_learning_task_knowledge(payload)

        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        self.assertEqual(first["project_id"], second["project_id"])
        self.assertEqual(first["knowledge_point_id"], "kp_vlan")
        self.assertIn("agent.html?student_id=", first["redirect_url"])
        self.assertIn("knowledge_point_id=kp_vlan", first["redirect_url"])
        self.assertIn("entry_id=ple_scoped_vlan_001", first["redirect_url"])
        self.assertEqual(first["assessment"]["status"], "ready")
        self.assertFalse(first["assessment"]["formal_evidence"])
        self.assertEqual(
            first["content_generation"]["provider"], "deterministic_template",
        )

        detail = application.get_project({
            "project_id": first["project_id"],
            "student_id": self.student_id,
        })["project"]
        path = detail["learning_path"]["items"]
        self.assertEqual(path[0]["knowledge_point_id"], "kp_vlan")
        self.assertEqual(
            {item["stage_id"] for item in path},
            {"foundation", "core", "application"},
        )
        self.assertTrue(path[-1]["is_target"])
        self.assertEqual(
            [stage["stage_id"] for stage in detail["learning_plan"]["stages"]],
            ["foundation", "core", "application"],
        )
        stored_state = application.store.get_project(first["project_id"])["state"]
        self.assertEqual(stored_state["initial_assessment_state"], "awaiting_practice")
        started = application.project_assessment_start({
            "student_id": self.student_id,
            "project_id": first["project_id"],
            "assessment_type": "provisional_self_check",
            "knowledge_point_id": "kp_vlan",
        })
        self.assertEqual(started["assessment_type"], "provisional_self_check")
        self.assertGreater(started["total"], 0)

    def set_zero_foundation_intake(self, project_id):
        return self.request_json(
            "POST",
            f"/api/projects/{project_id}/assessments/intake",
            {
                "student_id": self.student_id,
                "self_reported_level": "zero_foundation",
                "claimed_knowledge_point_ids": [],
            },
        )

    def test_create_project_matches_graph_goal(self):
        result = self.create_project("我想系统掌握 Java 面向对象编程")
        self.assertEqual(result["status"], "ok")
        project = result["project"]
        self.assertEqual(project["status"], "created")
        self.assertEqual(project["diagnosis_state"], "not_started")
        self.assertEqual(project["planning_state"], "ready")
        self.assertIn("project_id", project)

    def test_supported_goal_preserves_user_constraints(self):
        result = self.create_project(
            "我想在两个月内掌握 Java 面向对象，并能独立完成学生成绩管理系统"
        )
        project = result["project"]
        self.assertIn("两个月内", project["goal_name"])
        self.assertEqual(project["planning_state"], "ready")
        self.assertEqual(project["goal_constraints"]["estimated_days"], 60)
        self.assertIn("学生成绩管理系统", project["goal_constraints"]["target_outcome"])

    def test_learning_path_uses_explicit_prerequisite_graph_for_stages(self):
        project = self.create_project("我想系统掌握 Java 面向对象编程")["project"]
        detail = self.request_json(
            "GET", f"/api/projects/{project['project_id']}?student_id={self.student_id}"
        )["project"]
        path_by_id = {
            item["knowledge_point_id"]: item
            for item in detail["learning_path"]["items"]
        }
        self.assertEqual(path_by_id["KN_JAVA_CLASS"]["stage_id"], "foundation")
        self.assertEqual(
            path_by_id["KN_JAVA_INHERITANCE"]["prerequisites"],
            ["KN_JAVA_ENCAPSULATION"],
        )
        self.assertEqual(path_by_id["KN_JAVA_COLLECTION"]["stage_id"], "core")
        self.assertEqual(path_by_id["KN_JAVA_EXCEPTION"]["stage_id"], "core")
        self.assertEqual(path_by_id["KN_JAVA_IO"]["stage_id"], "application")

        steps = {
            step["knowledge_point_id"]: step
            for stage in detail["learning_plan"]["stages"]
            for step in stage["steps"]
        }
        self.assertEqual(steps["KN_JAVA_COLLECTION"]["stage_id"], "core")
        self.assertEqual(steps["KN_JAVA_IO"]["stage_id"], "application")

    def test_python_foundation_goal_uses_foundation_candidate_path(self):
        result = self.create_project("我想学习 Python 基础知识，零基础")
        project = result["project"]
        self.assertEqual(project["support_level"], "generated_scaffold")
        self.assertEqual(project["goal_constraints"]["learning_scope"], "foundation")
        detail = self.request_json(
            "GET",
            f"/api/projects/{project['project_id']}?student_id={self.student_id}",
        )["project"]
        names = [item["knowledge_point_name"] for item in detail["learning_path"]["items"]]
        self.assertIn("Python 安装、解释器与第一个程序", names)
        self.assertIn("变量、数据类型与类型转换", names)
        self.assertFalse(any("Pandas" in name or "NumPy" in name for name in names))
        path_items = detail["learning_path"]["items"]
        self.assertEqual(path_items[0]["stage_id"], "foundation")
        self.assertEqual(path_items[-1]["stage_id"], "application")
        self.assertTrue(path_items[-1]["is_target"])

    def test_umbrella_domain_requires_direction_before_project_creation(self):
        result = self.create_project("我想学习嵌入式，零基础")
        self.assertEqual(result["status"], "needs_clarification")
        self.assertEqual(result["reason"], "domain_direction_required")
        self.assertEqual(result["missing_fields"], ["learning_direction"])
        self.assertIn("单片机", result["clarification"])
        projects = self.request_json(
            "GET", f"/api/projects?student_id={self.student_id}"
        )["projects"]
        self.assertEqual(projects, [])

    def test_embedded_mcu_candidate_path_uses_domain_prerequisites(self):
        project = self.create_project(
            "我是零基础，想学习嵌入式 STM32 单片机，并完成温湿度采集项目"
        )["project"]
        self.assertEqual(project["support_level"], "generated_scaffold")
        detail = self.request_json(
            "GET", f"/api/projects/{project['project_id']}?student_id={self.student_id}"
        )["project"]
        path = detail["learning_path"]
        names = [item["knowledge_point_name"] for item in path["items"]]
        self.assertIn("计算机使用、开发环境与 C 语言入门", names)
        self.assertIn("基础电路、数字逻辑与安全操作", names)
        self.assertIn("UART、I2C 与 SPI 通信", names)
        self.assertNotIn("学习嵌入式关键对象与专业词汇", names)
        self.assertEqual(path["planning_provider"], "local_candidate_taxonomy")
        self.assertTrue(
            all(item["goal_connection"] and item["learning_outcome"]
                for item in detail["goal_knowledge_points"])
        )
        self.assertEqual(path["items"][0]["stage_id"], "foundation")
        self.assertTrue(path["items"][-1]["is_target"])

    def test_clear_cross_domain_goal_creates_candidate_path(self):
        result = self.create_project("六周内掌握 Python 数据分析并完成销售数据看板")
        self.assertEqual(result["status"], "ok")
        project = result["project"]
        self.assertIn("Python 数据分析", project["goal_name"])
        self.assertEqual(project["planning_state"], "ready")
        self.assertEqual(project["support_level"], "generated_scaffold")
        self.assertEqual(project["assessment_state"], "question_sources_pending")
        self.assertEqual(project["goal_constraints"]["estimated_days"], 42)
        detail = self.request_json(
            "GET",
            f"/api/projects/{project['project_id']}?student_id={self.student_id}",
        )["project"]
        self.assertGreaterEqual(len(detail["learning_path"]["items"]), 3)
        names = [item["knowledge_point_name"] for item in detail["learning_path"]["items"]]
        self.assertTrue(any("Pandas" in name for name in names))
        self.assertTrue(any("看板" in name for name in names))
        center = self.request_json(
            "GET",
            f"/api/projects/{project['project_id']}/assessments?student_id={self.student_id}",
        )
        self.assertTrue(center["assessment_available"])
        self.assertFalse(center["formal_assessment_available"])
        self.assertEqual(center["catalog"], [])
        self.assertEqual(
            len(center["practice_sheets"]), len(detail["goal_knowledge_points"])
        )
        self.assertTrue(
            all(
                item["assessment_type"] == "provisional_self_check"
                for item in center["practice_sheets"]
            )
        )
        with self.assertRaises(Exception):
            self.request_json(
                "POST",
                f"/api/projects/{project['project_id']}/assessments/start",
                {"student_id": self.student_id, "assessment_type": "initial_diagnostic"},
            )

    def test_c_language_goal_uses_language_knowledge_path(self):
        project = self.create_project("我想学习c语言")["project"]
        self.assertEqual(project["support_level"], "generated_scaffold")
        detail = self.request_json(
            "GET", f"/api/projects/{project['project_id']}?student_id={self.student_id}"
        )["project"]
        names = [item["knowledge_point_name"] for item in detail["learning_path"]["items"]]
        self.assertEqual(len(detail["goal_knowledge_points"]), 17)
        self.assertTrue(any("函数" in name for name in names))
        self.assertTrue(any("数组" in name for name in names))
        self.assertTrue(any("指针" in name for name in names))
        self.assertTrue(any("数组与指针" in name for name in names))
        self.assertTrue(any("动态内存" in name for name in names))
        self.assertTrue(any("结构体" in name for name in names))
        self.assertTrue(any("链表" in name for name in names))
        self.assertFalse(any("目标拆解与验收标准" in name for name in names))

    def test_learning_plan_has_fixed_stages_and_stable_knowledge_references(self):
        project = self.create_project("我想系统掌握 Java 面向对象编程")["project"]
        project_id = project["project_id"]
        detail = self.request_json(
            "GET", f"/api/projects/{project_id}?student_id={self.student_id}"
        )["project"]
        plan = self.request_json(
            "GET", f"/api/projects/{project_id}/plan?student_id={self.student_id}"
        )["learning_plan"]
        self.assertEqual(
            [stage["stage_id"] for stage in plan["stages"]],
            ["foundation", "core", "application"],
        )
        plan_point_ids = {
            step["knowledge_point_id"]
            for stage in plan["stages"]
            for step in stage["steps"]
        }
        goal_point_ids = {
            item["knowledge_point_id"] for item in detail["goal_knowledge_points"]
        }
        self.assertEqual(plan_point_ids, goal_point_ids)
        self.assertTrue(
            all(
                not step["knowledge_point_id"].startswith("knowledge-")
                for stage in plan["stages"]
                for step in stage["steps"]
            )
        )
        self.assertEqual(plan["progress"], 0)

    def test_completing_plan_step_never_changes_mastery(self):
        project = self.create_project("我想系统掌握 Java 面向对象编程")["project"]
        project_id = project["project_id"]
        detail = self.request_json(
            "GET", f"/api/projects/{project_id}?student_id={self.student_id}"
        )["project"]
        before = {
            item["knowledge_point_id"]: item["mastery"]
            for item in detail["learning_path"]["items"]
        }
        plan = detail["learning_plan"]
        first_step = next(
            step for stage in plan["stages"] for step in stage["steps"]
        )
        updated = self.request_json(
            "POST",
            f"/api/projects/{project_id}/plan/steps/{first_step['step_id']}",
            {"student_id": self.student_id, "status": "completed"},
        )
        self.assertEqual(updated["learning_plan"]["progress"], round(100 / len(before)))
        after = self.request_json(
            "GET", f"/api/projects/{project_id}?student_id={self.student_id}"
        )["project"]
        self.assertEqual(
            {item["knowledge_point_id"]: item["mastery"] for item in after["learning_path"]["items"]},
            before,
        )

    def test_formal_assessment_updates_plan_context_but_not_plan_completion(self):
        project = self.create_project("我想系统掌握 Java 面向对象编程")["project"]
        project_id = project["project_id"]
        detail = self.request_json(
            "GET", f"/api/projects/{project_id}?student_id={self.student_id}"
        )["project"]
        target = detail["learning_path"]["items"][0]
        started = self.request_json(
            "POST",
            f"/api/projects/{project_id}/assessments/start",
            {
                "student_id": self.student_id,
                "assessment_type": "stage_check",
                "knowledge_point_id": target["knowledge_point_id"],
            },
        )
        session = self.server.RequestHandlerClass.application.store.get_project(project_id)["state"]["assessment_session"]
        for question in session["questions"]:
            self.request_json(
                "POST",
                f"/api/projects/{project_id}/assessments/answer",
                {
                    "student_id": self.student_id,
                    "assessment_id": started["assessment_id"],
                    "answer": question["answer"],
                },
            )
        plan = self.request_json(
            "GET", f"/api/projects/{project_id}/plan?student_id={self.student_id}"
        )["learning_plan"]
        known = {item["knowledge_point_id"] for item in plan["context"]["known"]}
        self.assertIn(target["knowledge_point_id"], known)
        target_step = next(
            step
            for stage in plan["stages"]
            for step in stage["steps"]
            if step["knowledge_point_id"] == target["knowledge_point_id"]
        )
        self.assertEqual(target_step["status"], "not_started")
        self.assertEqual(target_step["adaptation_mode"], "verified_fast_track")

    def test_legacy_c_project_recovers_complete_practice_scope(self):
        project = self.create_project("我想学习c语言")["project"]
        project_id = project["project_id"]
        application = self.server.RequestHandlerClass.application
        stored = application.store.get_project(project_id)
        state = stored["state"]
        legacy_names = [
            "C 语言程序结构、编译与运行",
            "数据类型、运算符与输入输出",
            "分支、循环与程序流程控制",
            "函数、参数传递与变量作用域",
            "数组、字符数组与字符串处理",
            "指针、地址与动态内存管理",
            "结构体、枚举与自定义类型",
            "文件操作、调试与 C 语言综合实战",
        ]
        state["goal_knowledge_points"] = [
            {
                "knowledge_point_id": f"KN-LEGACY-C-{index}",
                "knowledge_point_name": name,
                "knowledge_type": "code",
                "recommended_order": index,
                "source_status": "candidate",
            }
            for index, name in enumerate(legacy_names, start=1)
        ]
        state["learning_path"]["items"] = state["goal_knowledge_points"]
        application.store.save_project_state(project_id, state)

        center = self.request_json(
            "GET",
            f"/api/projects/{project_id}/assessments?student_id={self.student_id}",
        )
        names = [item["knowledge_point_name"] for item in center["practice_sheets"]]
        self.assertEqual(center["goal_knowledge_point_count"], 17)
        self.assertEqual(len(center["practice_sheets"]), 17)
        self.assertTrue(any("数组与指针" in name for name in names))
        self.assertTrue(any("链表" in name for name in names))

    def test_candidate_path_nodes_explain_goal_relationship(self):
        project = self.create_project("六周内掌握 Python 数据分析并完成销售数据看板")['project']
        detail = self.request_json(
            "GET", f"/api/projects/{project['project_id']}?student_id={self.student_id}"
        )["project"]
        items = detail["learning_path"]["items"]
        self.assertTrue(items)
        self.assertEqual(detail["learning_path"]["candidate_schema_version"], 2)
        self.assertTrue(all(item.get("goal_connection") for item in items))
        self.assertTrue(all(item.get("learning_outcome") for item in items))
        self.assertTrue(all(item.get("video_context_keywords") for item in items))
        generic_markers = ("目标拆解", "基础概念与术语", "核心原理与方法", "分步任务训练")
        self.assertFalse(any(
            marker in item["knowledge_point_name"]
            for item in items
            for marker in generic_markers
        ))

    def test_local_candidate_fallback_templates_pass_validation(self):
        application = self.server.RequestHandlerClass.application
        generic_markers = (
            "目标拆解", "验收标准", "基础概念与术语", "核心原理与方法",
            "典型案例分步练习", "综合应用任务", "成果检验与复盘",
            "重点模块专项学习", "薄弱项专项训练", "分步任务训练",
        )
        # 已收录领域：本地候选知识图谱（local_candidate_taxonomy）生成且通过校验
        cases = (
            ("AWS 认证", "certification", "三个月内备考 AWS 认证"),
            ("学习 Python 数据分析", "course", "学习 Python 数据分析并完成销售看板"),
        )
        for goal_name, goal_type, text in cases:
            with self.subTest(goal_type=goal_type):
                nodes, provider = application._plan_custom_goal_nodes(
                    goal_name,
                    goal_type,
                    text,
                    {},
                    prefer_remote=False,
                )
                self.assertEqual(provider, "local_candidate_taxonomy")
                self.assertGreaterEqual(len(nodes), 4)
                self.assertFalse(any(
                    marker in node["knowledge_point_name"]
                    for node in nodes
                    for marker in generic_markers
                ))
        # 未收录领域：拒绝用泛化模板冒充领域前置知识，应抛 GatewayError 而非生成
        unknown_cases = (
            ("学习供应链管理", "course", "学习供应链管理"),
            ("完成校园资产盘点", "project", "完成校园资产盘点"),
        )
        for goal_name, goal_type, text in unknown_cases:
            with self.subTest(goal_type=f"unknown-{goal_type}"):
                with self.assertRaises(GatewayError):
                    application._plan_custom_goal_nodes(
                        goal_name,
                        goal_type,
                        text,
                        {},
                        prefer_remote=False,
                    )

    def test_remote_candidate_planner_accepts_validated_dynamic_graph(self):
        application = self.server.RequestHandlerClass.application
        gateway = application.gateway
        original_settings = gateway.settings
        original_invoke = gateway.invoke_chat_workflow
        gateway.settings = Settings(**{**gateway.settings.__dict__, "xingchen_mode": "remote"})
        planner_payload = {
            "domain_keywords": ["无人机", "航拍", "校园宣传片"],
            "nodes": [
                {
                    "node_key": "flight-safety",
                    "knowledge_point_name": "无人机飞行安全与空域规范",
                    "knowledge_type": "conceptual",
                    "prerequisites": [],
                    "goal_connection": "安全合规飞行是完成校园宣传片航拍素材的前提。",
                    "learning_outcome": "能够列出校园航拍前的安全检查清单。",
                    "video_context_keywords": ["无人机", "飞行安全"],
                },
                {
                    "node_key": "camera-motion",
                    "knowledge_point_name": "航拍运镜与构图",
                    "knowledge_type": "practice",
                    "prerequisites": ["flight-safety"],
                    "goal_connection": "稳定运镜和构图直接决定校园宣传片画面的表达质量。",
                    "learning_outcome": "能够完成三种服务校园宣传片叙事的航拍镜头。",
                    "video_context_keywords": ["无人机航拍", "运镜构图"],
                },
                {
                    "node_key": "storyboard",
                    "knowledge_point_name": "校园宣传片航拍分镜设计",
                    "knowledge_type": "practice",
                    "prerequisites": ["camera-motion"],
                    "goal_connection": "分镜把校园宣传主题转化为可执行的航拍镜头顺序。",
                    "learning_outcome": "能够提交一份校园宣传片航拍分镜表。",
                    "video_context_keywords": ["校园宣传片", "航拍分镜"],
                },
                {
                    "node_key": "final-film",
                    "knowledge_point_name": "校园宣传片航拍素材剪辑",
                    "knowledge_type": "project",
                    "prerequisites": ["storyboard"],
                    "goal_connection": "剪辑将航拍素材整合为最终校园宣传片成果。",
                    "learning_outcome": "能够输出一段结构完整的校园航拍宣传片。",
                    "video_context_keywords": ["校园宣传片", "航拍剪辑"],
                },
            ],
        }
        gateway.invoke_chat_workflow = lambda payload: {
            "status": "ok", "answer": json.dumps(planner_payload, ensure_ascii=False)
        }
        original_queue = application._queue_project_lesson_generation
        application._queue_project_lesson_generation = lambda *_args, **_kwargs: True
        try:
            project = self.create_project("学习无人机航拍并独立完成校园宣传片")["project"]
            detail = self.request_json(
                "GET", f"/api/projects/{project['project_id']}?student_id={self.student_id}"
            )["project"]
        finally:
            application._queue_project_lesson_generation = original_queue
            gateway.invoke_chat_workflow = original_invoke
            gateway.settings = original_settings
        names = [item["knowledge_point_name"] for item in detail["learning_path"]["items"]]
        self.assertEqual(names[0], "无人机飞行安全与空域规范")
        self.assertIn("校园宣传片航拍分镜设计", names)
        self.assertEqual(detail["learning_path"]["planning_provider"], "ai_candidate_graph")

    def test_candidate_planner_rejects_generic_or_cyclic_graph(self):
        application = self.server.RequestHandlerClass.application
        with self.assertRaises(Exception):
            application._validate_candidate_nodes(
                [
                    {
                        "node_key": f"node-{index}",
                        "knowledge_point_name": "基础概念与术语" if index == 1 else f"具体知识点{index}",
                        "knowledge_type": "conceptual",
                        "prerequisites": ["node-4"] if index == 1 else [f"node-{index - 1}"],
                        "goal_connection": "该知识点直接服务于无人机航拍目标。",
                        "learning_outcome": "能够完成一个可检查的航拍任务。",
                    }
                    for index in range(1, 5)
                ],
                "学习无人机航拍",
                ["无人机", "航拍"],
            )

    def test_candidate_planner_rejects_each_unrelated_node(self):
        application = self.server.RequestHandlerClass.application
        goal_name = "学习无人机航拍并完成校园宣传片"
        goal_keywords = application._candidate_goal_keywords(
            goal_name,
            goal_name,
            ["无人机", "航拍", "校园宣传片", "烘焙"],
        )
        self.assertIn("航拍", goal_keywords)
        self.assertNotIn("烘焙", goal_keywords)
        nodes = [
            {
                "node_key": "flight-safety",
                "knowledge_point_name": "无人机飞行安全与空域规范",
                "knowledge_type": "conceptual",
                "prerequisites": [],
                "goal_connection": "安全飞行是完成无人机航拍任务的直接前提。",
                "learning_outcome": "能够完成航拍前安全检查。",
            },
            {
                "node_key": "dessert-plating",
                "knowledge_point_name": "西点烘焙与甜品摆盘",
                "knowledge_type": "practice",
                "prerequisites": ["flight-safety"],
                "goal_connection": "烘焙和摆盘用于完成甜品展示作品。",
                "learning_outcome": "能够完成一份甜品摆盘作品。",
            },
            {
                "node_key": "storyboard",
                "knowledge_point_name": "校园宣传片航拍分镜",
                "knowledge_type": "practice",
                "prerequisites": ["dessert-plating"],
                "goal_connection": "航拍分镜用于规划无人机镜头顺序。",
                "learning_outcome": "能够提交一份航拍分镜表。",
            },
            {
                "node_key": "final-film",
                "knowledge_point_name": "校园宣传片航拍剪辑",
                "knowledge_type": "project",
                "prerequisites": ["storyboard"],
                "goal_connection": "航拍剪辑用于输出最终校园宣传片。",
                "learning_outcome": "能够输出完整的校园航拍宣传片。",
            },
        ]

        with self.assertRaisesRegex(Exception, "西点烘焙与甜品摆盘"):
            application._validate_candidate_nodes(
                nodes,
                goal_name,
                goal_keywords,
                [*goal_keywords, "烘焙"],
            )

    def test_candidate_project_provisional_self_check_never_updates_profile(self):
        project = self.create_project(
            "六周内掌握 Python 数据分析并完成销售数据看板"
        )["project"]
        project_id = project["project_id"]
        before = self.request_json(
            "GET", f"/api/projects/{project_id}?student_id={self.student_id}"
        )["project"]
        mastery_before = [item["mastery"] for item in before["learning_path"]["items"]]
        started = self.request_json(
            "POST",
            f"/api/projects/{project_id}/assessments/start",
            {
                "student_id": self.student_id,
                "assessment_type": "provisional_self_check",
            },
        )
        self.assertEqual(started["stakes"], "low")
        self.assertEqual(started["provider"], "wf04_api")
        self.assertEqual(len(started["questions"]), 12)
        self.assertEqual(
            {question["question_type"] for question in started["questions"]},
            {"choice", "multiple_choice", "judgment", "fill_blank", "short_answer", "practical"},
        )
        self.assertTrue(
            all(question["quality_status"] == "validated" for question in started["questions"])
        )
        self.assertTrue(all(question["source_type"] == "wf04_api" for question in started["questions"]))
        self.assertTrue(all("answer" not in question for question in started["questions"]))
        self.assertTrue(all("rubric" not in question for question in started["questions"]))
        session = self.server.RequestHandlerClass.application.store.get_project(
            project_id
        )["state"]["assessment_session"]
        completed = None
        for question in session["questions"]:
            completed = self.request_json(
                "POST",
                f"/api/projects/{project_id}/assessments/answer",
                {
                    "student_id": self.student_id,
                    "assessment_id": started["assessment_id"],
                    "answer": question["answer"],
                },
            )
        self.assertEqual(completed["status"], "completed")
        self.assertFalse(completed["summary"]["formal_evidence"])
        self.assertEqual(completed["summary"]["evidence_count"], 0)
        evidence = self.request_json(
            "GET",
            f"/api/projects/{project_id}/assessments/{started['assessment_id']}/evidence?student_id={self.student_id}",
        )["events"]
        self.assertEqual(evidence, [])
        after = self.request_json(
            "GET", f"/api/projects/{project_id}?student_id={self.student_id}"
        )["project"]
        self.assertEqual(
            [item["mastery"] for item in after["learning_path"]["items"]],
            mastery_before,
        )

    def test_question_contract_rejects_unknown_type_instead_of_choice(self):
        with self.assertRaisesRegex(ApiError, "不支持的题型") as raised:
            LearningApplication._question_contract({"question_type": "essay_v2"})
        self.assertEqual(raised.exception.code, "UNSUPPORTED_QUESTION_TYPE")

    def test_wf04_quality_gate_rejects_generic_learning_evidence_question(self):
        request = {
            "action": "generate_question", "student_id": self.student_id,
            "project_id": "PROJ-QUALITY", "task_instance_id": "ASSESSMENT-QUALITY-1",
            "request_id": "REQ-QUALITY", "knowledge_point": {
                "knowledge_point_id": "KP-HTML-STRUCTURE", "knowledge_point_name": "HTML 页面结构",
            },
            "requested_question_type": "choice",
        }
        result = {
            "schema_version": "ZHIXING_WF04_RESULT.v1", "workflow_mode": "wf04_training_evaluation",
            "status": "ok", "action": "generate_question", "student_id": self.student_id,
            "project_id": "PROJ-QUALITY", "task_instance_id": "ASSESSMENT-QUALITY-1",
            "request_id": "REQ-QUALITY", "host_write_allowed": True,
            "question_spec": {
                "question_template_id": "TPL-QUALITY", "knowledge_point_id": "KP-HTML-STRUCTURE",
                "question_type": "choice", "title": "HTML 页面结构", "prompt": "对于 HTML 页面结构，下面哪项最能作为完成本阶段学习的可检查证据？",
                "expected_answer": "c",
            },
            "public_question": {
                "question_type": "choice", "title": "HTML 页面结构", "prompt": "对于 HTML 页面结构，下面哪项最能作为完成本阶段学习的可检查证据？",
                "options": {"a": "看资料", "b": "背术语", "c": "完成任务"},
            },
        }
        with self.assertRaisesRegex(Exception, "通用学习行为题"):
            LearningApplication._wf04_question_candidate(request, result)

    def test_wf04_gate_allows_candidate_point_question_without_point_name(self):
        # 候选知识点名称是"学习XX"式过程性表述（如 KN-CUSTOM-* 路径生成），
        # 不是技术术语；WF04 按知识上下文出题时题干无法也不应出现该名称。
        # 门禁应放行此类题目，改由核心概念关联检查兜底。
        request = {
            "action": "generate_question", "student_id": self.student_id,
            "project_id": "PROJ-CANDIDATE", "task_instance_id": "ASSESSMENT-CANDIDATE-1",
            "request_id": "REQ-CANDIDATE", "knowledge_point": {
                "knowledge_point_id": "KN-CUSTOM-ED86A7914206",
                "knowledge_point_name": "学习云计算学习成果与评价规则",
            },
            "requested_question_type": "choice",
            "knowledge_context": {
                "core_concepts": ["Java", "new"],
                "source_status": "candidate",
            },
        }
        result = {
            "schema_version": "ZHIXING_WF04_RESULT.v1", "workflow_mode": "wf04_training_evaluation",
            "status": "ok", "action": "generate_question", "student_id": self.student_id,
            "project_id": "PROJ-CANDIDATE", "task_instance_id": "ASSESSMENT-CANDIDATE-1",
            "request_id": "REQ-CANDIDATE", "host_write_allowed": True,
            "question_spec": {
                "question_template_id": "TPL-CANDIDATE", "knowledge_point_id": "KN-CUSTOM-ED86A7914206",
                "question_type": "choice", "title": "Java 类与对象创建规则",
                "prompt": "在 Java 中，下列关于类与对象创建的说法，哪一项是正确的？",
                "expected_answer": "b",
                "reference_answer": "在 Java 中，new 关键字用于调用构造器创建类的实例。",
            },
            "public_question": {
                "question_type": "choice", "title": "Java 类与对象创建规则",
                "prompt": "在 Java 中，下列关于类与对象创建的说法，哪一项是正确的？",
                "options": {
                    "a": "使用 class 关键字创建对象实例",
                    "b": "使用 new 关键字创建类的实例",
                    "c": "对象是程序的基本组织单位",
                },
            },
        }
        question = LearningApplication._wf04_question_candidate(request, result)
        self.assertEqual(question["knowledge_point_id"], "KN-CUSTOM-ED86A7914206")

    def test_wf04_gate_rejects_candidate_question_from_another_goal_domain(self):
        request = {
            "action": "generate_question", "student_id": self.student_id,
            "project_id": "PROJ-CLOUD", "task_instance_id": "ASSESSMENT-CLOUD-1",
            "request_id": "REQ-CLOUD", "knowledge_point": {
                "knowledge_point_id": "KN-CUSTOM-CLOUD",
                "knowledge_point_name": "学习云计算关键对象与专业词汇",
            },
            "requested_question_type": "choice",
            "knowledge_context": {
                "source_status": "candidate",
                "goal_name": "学习云计算",
                "goal_anchor_terms": ["云计算"],
                "core_concepts": ["云计算"],
            },
        }
        result = {
            "schema_version": "ZHIXING_WF04_RESULT.v1", "workflow_mode": "wf04_training_evaluation",
            "status": "ok", "action": "generate_question", "student_id": self.student_id,
            "project_id": "PROJ-CLOUD", "task_instance_id": "ASSESSMENT-CLOUD-1",
            "request_id": "REQ-CLOUD", "host_write_allowed": True,
            "question_spec": {
                "question_template_id": "TPL-CLOUD", "knowledge_point_id": "KN-CUSTOM-CLOUD",
                "question_type": "choice", "title": "Java 类与对象创建规则",
                "prompt": "在 Java 中，下列关于类与对象创建的说法，哪一项是正确的？",
                "expected_answer": "b", "reference_answer": "Java 中使用 new 创建类的实例。",
            },
            "public_question": {
                "question_type": "choice", "title": "Java 类与对象创建规则",
                "prompt": "在 Java 中，下列关于类与对象创建的说法，哪一项是正确的？",
                "options": {"a": "class", "b": "new", "c": "构造器"},
            },
        }
        with self.assertRaisesRegex(Exception, "未声明的技术语境"):
            LearningApplication._wf04_question_candidate(request, result)

    def test_wf04_gate_still_rejects_validated_point_question_without_point_name(self):
        # 正式（validated）知识点仍必须保证题干出现可验证的知识点语境，
        # 候选知识点放宽不影响正式知识点的门禁强度。
        request = {
            "action": "generate_question", "student_id": self.student_id,
            "project_id": "PROJ-VALIDATED", "task_instance_id": "ASSESSMENT-VALIDATED-1",
            "request_id": "REQ-VALIDATED", "knowledge_point": {
                "knowledge_point_id": "KP-HTML-STRUCTURE", "knowledge_point_name": "HTML 页面结构",
            },
            "requested_question_type": "choice",
            "knowledge_context": {
                "core_concepts": ["header"],
                "source_status": "validated",
            },
        }
        result = {
            "schema_version": "ZHIXING_WF04_RESULT.v1", "workflow_mode": "wf04_training_evaluation",
            "status": "ok", "action": "generate_question", "student_id": self.student_id,
            "project_id": "PROJ-VALIDATED", "task_instance_id": "ASSESSMENT-VALIDATED-1",
            "request_id": "REQ-VALIDATED", "host_write_allowed": True,
            "question_spec": {
                "question_template_id": "TPL-VALIDATED", "knowledge_point_id": "KP-HTML-STRUCTURE",
                "question_type": "choice", "title": "学习重点",
                "prompt": "下列哪种做法更符合本阶段要求？",
                "expected_answer": "a",
                "reference_answer": "应按要求完成练习。",
            },
            "public_question": {
                "question_type": "choice", "title": "学习重点",
                "prompt": "下列哪种做法更符合本阶段要求？",
                "options": {"a": "完成练习", "b": "浏览资料", "c": "记录笔记"},
            },
        }
        with self.assertRaisesRegex(Exception, "题干未出现可验证的目标知识点语境"):
            LearningApplication._wf04_question_candidate(request, result)

    def test_wf04_quality_gate_requires_core_concept_in_question_and_answer(self):
        request = {
            "action": "generate_question", "student_id": self.student_id,
            "project_id": "PROJ-LINK", "task_instance_id": "ASSESSMENT-LINK-1",
            "request_id": "REQ-LINK", "knowledge_point": {
                "knowledge_point_id": "KP-HTML-STRUCTURE", "knowledge_point_name": "HTML 页面结构",
            },
            "requested_question_type": "choice",
            "knowledge_context": {"core_concepts": ["header", "main", "footer"]},
        }
        result = {
            "schema_version": "ZHIXING_WF04_RESULT.v1", "workflow_mode": "wf04_training_evaluation",
            "status": "ok", "action": "generate_question", "student_id": self.student_id,
            "project_id": "PROJ-LINK", "task_instance_id": "ASSESSMENT-LINK-1",
            "request_id": "REQ-LINK", "host_write_allowed": True,
            "question_spec": {
                "question_template_id": "TPL-LINK", "knowledge_point_id": "KP-HTML-STRUCTURE",
                "question_type": "choice", "title": "HTML 页面结构", "prompt": "学习 HTML 页面结构时，哪种做法更重要？",
                "expected_answer": "a", "reference_answer": "应按页面结构要求组织内容。",
            },
            "public_question": {
                "question_type": "choice", "title": "HTML 页面结构", "prompt": "学习 HTML 页面结构时，哪种做法更重要？",
                "options": {"a": "完成练习", "b": "记住术语", "c": "浏览资料"},
            },
        }
        with self.assertRaisesRegex(Exception, "核心概念"):
            LearningApplication._wf04_question_candidate(request, result)

    def test_wf04_generation_revises_question_after_linkage_rejection(self):
        application = self.server.RequestHandlerClass.application
        request = {
            "schema_version": "ZHIXING_WF04_REQUEST.v1", "request_id": "REQ-REVISE",
            "action": "generate_question", "student_id": self.student_id,
            "project_id": "PROJ-REVISE", "task_instance_id": "ASSESSMENT-REVISE-1",
            "knowledge_point": {"knowledge_point_id": "KP-HTML", "knowledge_point_name": "HTML 页面结构"},
            "requested_question_type": "choice", "task_contract": {},
            "knowledge_context": {"core_concepts": ["header"]},
        }
        original = application.gateway.invoke_wf04_workflow
        calls = []

        def generate_with_bad_first(payload):
            calls.append(payload)
            result = original(payload)
            if len(calls) == 1:
                result["question_spec"]["prompt"] = "HTML 页面结构的学习重点是什么？"
                result["question_spec"]["reference_answer"] = "应理解页面结构的作用。"
                result["question_spec"]["options"] = {"a": "完成练习", "b": "记住术语", "c": "浏览资料"}
                result["public_question"]["prompt"] = result["question_spec"]["prompt"]
                result["public_question"]["options"] = result["question_spec"]["options"]
            return result

        application.gateway.invoke_wf04_workflow = generate_with_bad_first
        try:
            question, attempts = application._generate_wf04_question_with_revisions(request)
        finally:
            application.gateway.invoke_wf04_workflow = original
        self.assertEqual(attempts, 2)
        self.assertEqual(len(calls), 2)
        self.assertIn("header", question["prompt"])
        self.assertTrue(calls[1]["task_contract"]["revision_feedback"])

    def test_wf04_generation_gives_explicit_type_instruction_after_remote_type_error(self):
        # 远程工作流报告 E_MODEL_QUESTION_TYPE_INVALID 后，重试请求必须携带
        # 明确题型指令，否则模型会反复输出协议未定义题型导致 3 次必败。
        application = self.server.RequestHandlerClass.application
        request = {
            "schema_version": "ZHIXING_WF04_REQUEST.v1", "request_id": "REQ-TYPE-RETRY",
            "action": "generate_question", "student_id": self.student_id,
            "project_id": "PROJ-TYPE-RETRY", "task_instance_id": "ASSESSMENT-TYPE-RETRY-1",
            "knowledge_point": {"knowledge_point_id": "KP-HTML", "knowledge_point_name": "HTML 页面结构"},
            "requested_question_type": "choice", "task_contract": {},
            "knowledge_context": {"core_concepts": ["header"]},
        }
        original = application.gateway.invoke_wf04_workflow
        calls = []

        def generate_with_type_errors(payload):
            calls.append(payload)
            if len(calls) <= 2:
                return {
                    "schema_version": "ZHIXING_WF04_RESULT.v1",
                    "workflow_mode": "wf04_training_evaluation",
                    "status": "error", "action": "generate_question",
                    "request_id": "REQ-TYPE-RETRY", "student_id": self.student_id,
                    "project_id": "PROJ-TYPE-RETRY", "task_instance_id": "ASSESSMENT-TYPE-RETRY-1",
                    "error": {
                        "code": "E_MODEL_QUESTION_TYPE_INVALID",
                        "message": "出题模型返回了协议未定义的 question_type",
                        "retryable": True,
                    },
                    "host_write_allowed": False,
                }
            return original(payload)

        application.gateway.invoke_wf04_workflow = generate_with_type_errors
        try:
            question, attempts = application._generate_wf04_question_with_revisions(request)
        finally:
            application.gateway.invoke_wf04_workflow = original
        self.assertEqual(attempts, 3)
        self.assertEqual(len(calls), 3)
        for call in calls[1:]:
            instruction = call["task_contract"].get("revision_instruction", "")
            self.assertIn("question_spec.question_type", instruction)
            self.assertIn("必须使用 choice", instruction)
            self.assertIn("不得使用 code", instruction)

    def test_wf04_gateway_extracts_business_json_from_choice_delta_content(self):
        business = {
            "schema_version": "ZHIXING_WF04_RESULT.v1", "status": "ok",
            "action": "generate_question", "question_spec": {"question_template_id": "TPL-1"},
            "public_question": {"title": "题目", "prompt": "题干", "question_type": "short_answer"},
        }
        outer_response = {"code": 0, "choices": [{"delta": {"content": json.dumps(business)}}]}
        result = self.server.RequestHandlerClass.application.gateway._extract_result(outer_response)
        self.assertEqual(result, business)

    def test_wf04_rejects_short_answer_when_requested_type_was_choice(self):
        request = {
            "schema_version": "ZHIXING_WF04_REQUEST.v1",
            "request_id": "REQ-SHORT-ANSWER",
            "action": "generate_question",
            "student_id": self.student_id,
            "project_id": "PROJ-SHORT-ANSWER",
            "task_instance_id": "TASK-SHORT-ANSWER",
            "requested_question_type": "choice",
            "knowledge_point": {
                "knowledge_point_id": "KP-HTML-STRUCTURE",
                "knowledge_point_name": "HTML 页面结构",
            },
            "knowledge_context": {"core_concepts": ["header"]},
        }
        result = {
            "schema_version": "ZHIXING_WF04_RESULT.v1",
            "workflow_mode": "wf04_training_evaluation",
            "status": "ok",
            "action": "generate_question",
            "request_id": "REQ-SHORT-ANSWER",
            "student_id": self.student_id,
            "project_id": "PROJ-SHORT-ANSWER",
            "task_instance_id": "TASK-SHORT-ANSWER",
            "host_write_allowed": True,
            "question_spec": {
                "question_template_id": "TPL-SHORT-ANSWER",
                "knowledge_point_id": "KP-HTML-STRUCTURE",
                "question_type": "short_answer",
                "title": "HTML 页面结构",
                "prompt": "说明 header 元素在 HTML 页面结构中的作用。",
                "reference_answer": "header 用于表达页面或区块的头部结构。",
                "rubric": [
                    {"description": "说明 header 的语义"},
                    {"description": "说明 header 的结构用途"},
                ],
            },
            "public_question": {
                "question_type": "short_answer",
                "title": "HTML 页面结构",
                "prompt": "说明 header 元素在 HTML 页面结构中的作用。",
                "answer_schema": {"type": "text"},
            },
        }
        with self.assertRaisesRegex(ApiError, "返回题型 short_answer 与请求题型 choice 不一致"):
            LearningApplication._wf04_question_candidate(request, result)

    def test_wf04_status_error_is_not_retried_as_question_quality(self):
        application = self.server.RequestHandlerClass.application
        request = {
            "schema_version": "ZHIXING_WF04_REQUEST.v1",
            "request_id": "REQ-WF04-ERROR",
            "action": "generate_question",
            "student_id": self.student_id,
            "project_id": "PROJ-WF04-ERROR",
            "task_instance_id": "TASK-WF04-ERROR",
            "knowledge_point": {
                "knowledge_point_id": "KP-HTML-STRUCTURE",
                "knowledge_point_name": "HTML 页面结构",
            },
        }
        calls = []
        original = application.gateway.invoke_wf04_workflow

        def return_error(payload):
            calls.append(payload)
            return {
                "schema_version": "ZHIXING_WF04_RESULT.v1",
                "workflow_mode": "wf04_training_evaluation",
                "status": "error",
                "action": "generate_question",
                "request_id": "REQ-WF04-ERROR",
                "student_id": self.student_id,
                "host_write_allowed": False,
                "error": {"code": "E_REQUEST_VALIDATION", "message": "请求参数不符合协议"},
            }

        application.gateway.invoke_wf04_workflow = return_error
        try:
            with self.assertRaisesRegex(GatewayError, "E_REQUEST_VALIDATION"):
                application._generate_wf04_question_with_revisions(request)
        finally:
            application.gateway.invoke_wf04_workflow = original
        self.assertEqual(len(calls), 1)

    def test_wf04_accepts_question_with_partial_knowledge_point_name(self):
        """知识点名含连接词时,题干含其一部分术语即可通过语境门禁。

        回归:KN_JAVA_CLASS(类的定义与对象创建)生成的题目标题为
        "Java类与对象创建选择题",被旧逻辑(整串中文作为单一术语)误杀。
        """
        request = {
            "schema_version": "ZHIXING_WF04_REQUEST.v1",
            "request_id": "REQ-WF04-PARTIAL-KP",
            "action": "generate_question",
            "student_id": self.student_id,
            "project_id": "PROJ-WF04-PARTIAL-KP",
            "task_instance_id": "TASK-WF04-PARTIAL-KP",
            "knowledge_point": {
                "knowledge_point_id": "KP-JAVA-CLASS",
                "knowledge_point_name": "类的定义与对象创建",
            },
            "requested_question_type": "choice",
            "task_contract": {},
            "knowledge_context": {"core_concepts": []},
        }
        result = {
            "schema_version": "ZHIXING_WF04_RESULT.v1",
            "workflow_mode": "wf04_training_evaluation",
            "status": "ok",
            "action": "generate_question",
            "request_id": request["request_id"],
            "student_id": self.student_id,
            "project_id": request["project_id"],
            "task_instance_id": request["task_instance_id"],
            "host_write_allowed": True,
            "question_spec": {
                "knowledge_point_id": "KP-JAVA-CLASS",
                "question_template_id": "TPL-WF04-PARTIAL-KP",
                "question_type": "choice",
                "title": "Java类与对象创建选择题",
                "prompt": "某学生编写了如下代码，使用 new 关键字创建 Student 对象，请选择正确的说法。",
                "options": {"a": "new 关键字返回新对象的引用", "b": "直接赋值即可创建对象", "c": "无需构造器即可使用"},
                "expected_answer": "a",
                "answer_schema": {"type": "single_choice"},
            },
            "public_question": {
                "question_type": "choice",
                "title": "Java类与对象创建选择题",
                "prompt": "某学生编写了如下代码，使用 new 关键字创建 Student 对象，请选择正确的说法。",
                "options": {"a": "new 关键字返回新对象的引用", "b": "直接赋值即可创建对象", "c": "无需构造器即可使用"},
                "answer_schema": {"type": "single_choice"},
            },
        }
        question = LearningApplication._wf04_question_candidate(request, result)
        self.assertEqual(question["question_type"], "choice")

    def test_wf04_retries_transient_invalid_model_output(self):
        application = self.server.RequestHandlerClass.application
        request = {
            "schema_version": "ZHIXING_WF04_REQUEST.v1",
            "request_id": "REQ-WF04-MODEL-OUTPUT",
            "action": "generate_question",
            "student_id": self.student_id,
            "project_id": "PROJ-WF04-MODEL-OUTPUT",
            "task_instance_id": "TASK-WF04-MODEL-OUTPUT",
            "knowledge_point": {
                "knowledge_point_id": "KP-HTML-STRUCTURE",
                "knowledge_point_name": "HTML 页面结构",
            },
            "requested_question_type": "short_answer",
            "task_contract": {},
            "knowledge_context": {"core_concepts": ["header"]},
        }
        calls = []
        original = application.gateway.invoke_wf04_workflow

        def return_transient_error_then_question(payload):
            calls.append(payload)
            if len(calls) == 1:
                return {
                    "schema_version": "ZHIXING_WF04_RESULT.v1",
                    "workflow_mode": "wf04_training_evaluation",
                    "status": "error",
                    "action": "generate_question",
                    "request_id": request["request_id"],
                    "student_id": self.student_id,
                    "host_write_allowed": False,
                    "error": {
                        "code": "E_MODEL_OUTPUT_INVALID",
                        "message": "出题模型未返回合法 JSON 对象",
                    },
                }
            return original(payload)

        application.gateway.invoke_wf04_workflow = return_transient_error_then_question
        try:
            question, attempts = application._generate_wf04_question_with_revisions(request)
        finally:
            application.gateway.invoke_wf04_workflow = original

        self.assertEqual(question["question_type"], "short_answer")
        self.assertEqual(attempts, 2)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]["requested_question_type"], "short_answer")
        self.assertEqual(calls[1]["requested_question_type"], "short_answer")

    def test_wf04_retries_explicitly_retryable_and_missing_rubric_errors(self):
        application = self.server.RequestHandlerClass.application
        request = {
            "schema_version": "ZHIXING_WF04_REQUEST.v1",
            "request_id": "REQ-WF04-RETRYABLE-ERROR",
            "action": "generate_question",
            "student_id": self.student_id,
            "project_id": "PROJ-WF04-RETRYABLE-ERROR",
            "task_instance_id": "TASK-WF04-RETRYABLE-ERROR",
            "knowledge_point": {
                "knowledge_point_id": "KP-HTML-STRUCTURE",
                "knowledge_point_name": "HTML 页面结构",
            },
            "requested_question_type": "short_answer",
            "task_contract": {},
            "knowledge_context": {"core_concepts": ["header"]},
        }
        original = application.gateway.invoke_wf04_workflow
        error_cases = (
            {
                "code": "E_FUTURE_RECOVERABLE",
                "message": "工作流声明该错误可重试",
                "retryable": True,
            },
            {
                "code": "E_RUBRIC_MISSING",
                "message": "评价缺少可计算的 rubric",
            },
        )

        for workflow_error in error_cases:
            with self.subTest(error_code=workflow_error["code"]):
                calls = []

                def return_error_then_question(payload):
                    calls.append(payload)
                    if len(calls) == 1:
                        return {
                            "schema_version": "ZHIXING_WF04_RESULT.v1",
                            "workflow_mode": "wf04_training_evaluation",
                            "status": "error",
                            "action": "generate_question",
                            "request_id": request["request_id"],
                            "student_id": self.student_id,
                            "host_write_allowed": False,
                            "error": workflow_error,
                        }
                    return original(payload)

                application.gateway.invoke_wf04_workflow = return_error_then_question
                try:
                    question, attempts = application._generate_wf04_question_with_revisions(request)
                finally:
                    application.gateway.invoke_wf04_workflow = original

                self.assertEqual(question["question_type"], "short_answer")
                self.assertEqual(attempts, 2)
                self.assertEqual(len(calls), 2)
                self.assertEqual(calls[1]["requested_question_type"], "short_answer")

    def test_wf04_retries_invalid_multiple_choice_schema(self):
        application = self.server.RequestHandlerClass.application
        request = {
            "schema_version": "ZHIXING_WF04_REQUEST.v1",
            "request_id": "REQ-WF04-MULTIPLE-CHOICE",
            "action": "generate_question",
            "student_id": self.student_id,
            "project_id": "PROJ-WF04-MULTIPLE-CHOICE",
            "task_instance_id": "TASK-WF04-MULTIPLE-CHOICE",
            "knowledge_point": {
                "knowledge_point_id": "KP-HTML-STRUCTURE",
                "knowledge_point_name": "HTML 页面结构",
            },
            "requested_question_type": "multiple_choice",
            "task_contract": {},
            "knowledge_context": {"core_concepts": ["header"]},
        }
        calls = []
        original = application.gateway.invoke_wf04_workflow

        def return_invalid_schema_then_question(payload):
            calls.append(payload)
            if len(calls) == 1:
                return {
                    "schema_version": "ZHIXING_WF04_RESULT.v1",
                    "workflow_mode": "wf04_training_evaluation",
                    "status": "error",
                    "action": "generate_question",
                    "request_id": request["request_id"],
                    "student_id": self.student_id,
                    "host_write_allowed": False,
                    "error": {
                        "code": "E_MULTIPLE_CHOICE_SCHEMA",
                        "message": "多选题必须至少有三个选项、两个正确选项，且答案键必须属于 options",
                    },
                }
            return original(payload)

        application.gateway.invoke_wf04_workflow = return_invalid_schema_then_question
        try:
            question, attempts = application._generate_wf04_question_with_revisions(request)
        finally:
            application.gateway.invoke_wf04_workflow = original

        self.assertEqual(question["question_type"], "multiple_choice")
        self.assertEqual(attempts, 2)
        self.assertEqual(len(calls), 2)
        self.assertTrue(
            any(
                "E_MULTIPLE_CHOICE_SCHEMA" in reason
                for reason in calls[1]["task_contract"]["revision_feedback"]
            )
        )

    def test_wf04_regenerates_unknown_question_type_with_protocol_feedback(self):
        application = self.server.RequestHandlerClass.application
        request = {
            "schema_version": "ZHIXING_WF04_REQUEST.v1",
            "request_id": "REQ-WF04-UNKNOWN-TYPE",
            "action": "generate_question",
            "student_id": self.student_id,
            "project_id": "PROJ-WF04-UNKNOWN-TYPE",
            "task_instance_id": "TASK-WF04-UNKNOWN-TYPE",
            "knowledge_point": {
                "knowledge_point_id": "KP-HTML-STRUCTURE",
                "knowledge_point_name": "HTML 页面结构",
            },
            "requested_question_type": "choice",
            "task_contract": {},
            "knowledge_context": {"core_concepts": ["header"]},
        }
        calls = []
        original = application.gateway.invoke_wf04_workflow

        def generate_with_unknown_type_first(payload):
            calls.append(payload)
            result = original(payload)
            if len(calls) == 1:
                result["question_spec"]["question_type"] = "code"
                result["public_question"]["question_type"] = "code"
            return result

        application.gateway.invoke_wf04_workflow = generate_with_unknown_type_first
        try:
            question, attempts = application._generate_wf04_question_with_revisions(request)
        finally:
            application.gateway.invoke_wf04_workflow = original
        self.assertEqual(attempts, 2)
        self.assertEqual(question["question_type"], "choice")
        self.assertEqual(len(calls), 2)
        self.assertIn(
            "choice",
            calls[1]["task_contract"]["revision_instruction"],
        )

    def test_provisional_wf04_request_includes_requested_question_types(self):
        project = self.create_project("六周内掌握 Python 数据分析并完成销售数据看板")["project"]
        application = self.server.RequestHandlerClass.application
        calls = []
        original = application.gateway.invoke_wf04_workflow

        def capture_request(payload):
            calls.append(payload)
            return original(payload)

        application.gateway.invoke_wf04_workflow = capture_request
        try:
            self.request_json(
                "POST",
                f"/api/projects/{project['project_id']}/assessments/start",
                {
                    "student_id": self.student_id,
                    "assessment_type": "provisional_self_check",
                },
            )
        finally:
            application.gateway.invoke_wf04_workflow = original
        self.assertTrue(calls)
        self.assertEqual(
            [payload["requested_question_type"] for payload in calls],
            [
                "choice", "choice", "choice",
                "multiple_choice", "multiple_choice",
                "judgment", "judgment",
                "fill_blank", "fill_blank",
                "short_answer", "short_answer",
                "practical",
            ],
        )
        for payload in calls:
            self.assertEqual(
                set(payload["knowledge_point"]),
                {"knowledge_point_id", "knowledge_point_name"},
            )
            self.assertNotIn("knowledge_type", payload["knowledge_context"])

    def test_formal_wf04_practice_always_passes_requested_question_type(self):
        from unittest.mock import patch

        application = self.server.RequestHandlerClass.application
        captured_requests = []
        context = {
            "training_cycle_id": "CYCLE-1",
            "learning_task_id": "TASK-1",
            "knowledge_point_id": "KN-1",
            "title": "HTML 语义结构",
        }
        spec = {
            "knowledge_point_id": "KN-1",
            "title": "HTML 语义结构",
            "prompt": "说明 header 元素在页面语义结构中的作用。",
            "question_type": "short_answer",
            "answer_schema": {"type": "text"},
            "rubric": [{"criterion": "说明 header 的语义作用", "points": 1}],
            "validation_rules": {"minimum_points": 1},
            "source_refs": [{"url": "https://developer.mozilla.org/zh-CN/docs/Web/HTML/Element/header"}],
        }
        candidate = {
            **spec,
            "question_instance_id": "WF04-TEST",
            "_wf04_question_spec": spec,
        }

        def generate(request):
            captured_requests.append(request)
            return candidate, 1

        incoming = {
            "project_id": "PROJ-1",
            "task_instance_id": "TASK-INSTANCE-1",
            "knowledge_point_id": "KN-1",
            "question_type": "short_answer",
            "task_contract": {
                "assessment_mode": "formal",
                "rubric": spec["rubric"],
                "validation_rules": spec["validation_rules"],
            },
        }
        with (
            patch.object(application, "_wf04_task_context", return_value=context),
            patch.object(application, "_require_project", return_value={"state": {}}),
            patch.object(application, "_project_goal_knowledge_points", return_value=[]),
            patch.object(
                application,
                "_wf04_knowledge_context",
                return_value={"source_refs": spec["source_refs"]},
            ),
            patch.object(application, "_generate_wf04_question_with_revisions", side_effect=generate),
            patch.object(application.domain, "create_wf04_question", return_value={"status": "ok"}),
        ):
            application._create_wf04_practice(self.student_id, incoming)

        self.assertEqual(captured_requests[0]["requested_question_type"], "short_answer")

        invalid = {**incoming, "requested_question_type": "code"}
        with self.assertRaisesRegex(ApiError, "请求题型不受支持"):
            application._create_wf04_practice(self.student_id, invalid)

    def test_wf04_wrongbook_quality_gate_requires_target_and_lineage(self):
        request = {
            "schema_version": "ZHIXING_WF04_REQUEST.v1",
            "request_id": "REQ-WRONGBOOK-GATE",
            "action": "generate_question",
            "student_id": self.student_id,
            "project_id": "PROJ-WRONGBOOK-GATE",
            "task_instance_id": "TASK-WRONGBOOK-GATE",
            "requested_question_type": "choice",
            "question_role": "variant",
            "source_question_instance_id": "QUESTION-SOURCE-001",
            "knowledge_point": {
                "knowledge_point_id": "KP-HTML-STRUCTURE",
                "knowledge_point_name": "HTML 页面结构",
            },
            "knowledge_context": {"core_concepts": ["header"]},
            "learner_context": {
                "practice_intent": "wrongbook_remediation",
                "wrongbook_focus": {
                    "knowledge_point_id": "KP-HTML-STRUCTURE",
                    "source_question_instance_id": "QUESTION-SOURCE-001",
                    "original_question_prompt": "原题：header 应该放在哪里？",
                    "target_error_points": [{"error_id": "ERR-HEADER-NESTING"}],
                    "target_concept_ids": ["CONCEPT-HEADER-NESTING"],
                },
            },
        }
        result = {
            "schema_version": "ZHIXING_WF04_RESULT.v1",
            "workflow_mode": "wf04_training_evaluation",
            "status": "ok",
            "action": "generate_question",
            "request_id": request["request_id"],
            "student_id": self.student_id,
            "project_id": request["project_id"],
            "task_instance_id": request["task_instance_id"],
            "host_write_allowed": True,
            "question_spec": {
                "question_template_id": "TPL-WRONGBOOK-GATE",
                "knowledge_point_id": "KP-HTML-STRUCTURE",
                "question_type": "choice",
                "question_role": "variant",
                "source_question_instance_id": "QUESTION-SOURCE-001",
                "title": "HTML 页面结构变式",
                "prompt": "在新的 HTML 页面结构中，哪个 header 嵌套方式正确？",
                "options": {"a": "按语义放入页面或区块", "b": "放入任意标签", "c": "删除 header"},
                "expected_answer": "a",
                "reference_answer": "header 应按页面或区块语义正确嵌套。",
                "target_error_point_ids": ["ERR-HEADER-NESTING"],
                "target_concept_ids": ["CONCEPT-HEADER-NESTING"],
                "assessed_concept_ids": ["CONCEPT-HEADER-NESTING"],
            },
            "public_question": {
                "question_type": "choice",
                "title": "HTML 页面结构变式",
                "prompt": "在新的 HTML 页面结构中，哪个 header 嵌套方式正确？",
                "options": {"a": "按语义放入页面或区块", "b": "放入任意标签", "c": "删除 header"},
                "answer_schema": {"type": "single_choice"},
            },
        }
        question = LearningApplication._wf04_question_candidate(request, result)
        self.assertEqual(question["question_type"], "choice")

        result["question_spec"]["target_error_point_ids"] = ["ERR-UNRELATED"]
        with self.assertRaisesRegex(GatewayError, "未解决错因"):
            LearningApplication._wf04_question_candidate(request, result)

    def test_formal_practice_defaults_to_wrongbook_focus_but_respects_student_choice(self):
        from unittest.mock import patch

        application = self.server.RequestHandlerClass.application
        captured_requests = []
        context = {
            "training_cycle_id": "CYCLE-WRONGBOOK",
            "learning_task_id": "TASK-WRONGBOOK",
            "task_instance_id": "TASKINST-WRONGBOOK",
            "knowledge_point_id": "KP-WRONGBOOK",
            "title": "数组边界",
        }
        focus = {
            "focus_source": "wrongbook",
            "active_wrongbook_count": 1,
            "knowledge_point_id": "KP-WRONGBOOK",
            "source_question_instance_id": "QUESTION-ROOT-001",
            "root_question_instance_id": "QUESTION-ROOT-001",
            "original_question_prompt": "原题文本",
            "target_error_points": [{"error_id": "ERR-BOUNDARY", "expected_behavior": "检查边界"}],
            "target_concept_ids": ["CONCEPT-BOUNDARY"],
        }
        spec = {
            "knowledge_point_id": "KP-WRONGBOOK",
            "title": "数组边界变式",
            "prompt": "请在新数组场景中检查边界。",
            "question_type": "short_answer",
            "answer_schema": {"type": "text"},
            "expected_answer": "检查上下界",
            "reference_answer": "应同时检查数组上下界。",
            "rubric": [{"criterion_id": "C-1"}],
            "validation_rules": {"pass_score": 80},
            "source_refs": ["WF02-GRAPH"],
            "target_error_point_ids": ["ERR-BOUNDARY"],
            "target_concept_ids": ["CONCEPT-BOUNDARY"],
        }
        candidate = {**spec, "question_instance_id": "WF04-WRONGBOOK", "_wf04_question_spec": spec}

        def generate(request):
            captured_requests.append(request)
            return candidate, 1

        incoming = {
            "project_id": "PROJ-WRONGBOOK",
            "task_instance_id": "TASKINST-WRONGBOOK",
            "requested_question_type": "short_answer",
            "task_contract": {
                "assessment_mode": "formal",
                "rubric": [{"criterion_id": "C-1"}],
                "validation_rules": {"pass_score": 80},
            },
        }
        with (
            patch.object(application, "_wf04_task_context", return_value=context),
            patch.object(application, "_require_project", return_value={"goal_id": "", "state": {}}),
            patch.object(application, "_project_goal_knowledge_points", return_value=[]),
            patch.object(application, "_wf04_knowledge_context", return_value={"source_refs": ["WF02-GRAPH"]}),
            patch.object(application.domain, "wrongbook_focus", return_value=focus),
            patch.object(application, "_generate_wf04_question_with_revisions", side_effect=generate),
            patch.object(application.domain, "create_wf04_question", return_value={"status": "ok"}),
        ):
            application._create_wf04_practice(self.student_id, incoming)
            application._create_wf04_practice(
                self.student_id,
                {**incoming, "learner_context": {"practice_intent": "student_selected"}},
            )

        focused = captured_requests[0]
        self.assertEqual(focused["question_role"], "variant")
        self.assertEqual(focused["source_question_instance_id"], "QUESTION-ROOT-001")
        self.assertEqual(focused["learner_context"]["practice_intent"], "wrongbook_remediation")
        self.assertEqual(
            focused["learner_context"]["wrongbook_focus"]["target_error_points"][0]["error_id"],
            "ERR-BOUNDARY",
        )
        student_selected = captured_requests[1]
        self.assertEqual(student_selected["question_role"], "recommended")
        self.assertEqual(student_selected["learner_context"]["practice_intent"], "student_selected")

    def test_recommendation_prioritizes_wrongbook_unless_student_opts_out(self):
        from unittest.mock import patch

        application = self.server.RequestHandlerClass.application
        captured_requests = []
        context = {
            "training_cycle_id": "CYCLE-WRONGBOOK-POLICY",
            "learning_task_id": "TASK-WRONGBOOK-POLICY",
            "task_instance_id": "TASKINST-WRONGBOOK-POLICY",
            "knowledge_point_id": "KP-WRONGBOOK-POLICY",
            "title": "数组边界",
        }
        focus = {
            "focus_source": "wrongbook",
            "active_wrongbook_count": 2,
            "knowledge_point_id": "KP-WRONGBOOK-POLICY",
            "source_question_instance_id": "QUESTION-ROOT-POLICY",
            "target_error_points": [
                {"error_id": "ERR-BOUNDARY-POLICY", "expected_behavior": "检查数组边界"}
            ],
            "target_concept_ids": ["CONCEPT-BOUNDARY"],
        }

        def invoke(request):
            captured_requests.append(request)
            has_focus = bool(request["evidence_summary"].get("wrongbook_focus"))
            return {
                "schema_version": "ZHIXING_WF04_RESULT.v1",
                "workflow_mode": "wf04_training_evaluation",
                "status": "ok",
                "action": request["action"],
                "request_id": request["request_id"],
                "student_id": request["student_id"],
                "project_id": request["project_id"],
                "task_instance_id": request["task_instance_id"],
                "adaptive_policy": {
                    "recommended_action": "generate_variant" if has_focus else "continue_practice",
                    "recommended_difficulty": "same",
                    "intervention_level": "guided" if has_focus else "normal",
                    "reason": "存在未解决错因" if has_focus else "按常规掌握度继续",
                    "advisory_only": True,
                },
                "host_write_allowed": True,
            }

        incoming = {
            "student_id": self.student_id,
            "session_id": "SESSION-WRONGBOOK-POLICY",
            "project_id": "PROJ-WRONGBOOK-POLICY",
            "task_instance_id": "TASKINST-WRONGBOOK-POLICY",
            "knowledge_point_id": "KP-WRONGBOOK-POLICY",
        }
        with (
            patch.object(application, "_wf04_task_context", return_value=context),
            patch.object(application.domain, "wrongbook_focus", return_value=focus),
            patch.object(application.gateway, "invoke_wf04_workflow", side_effect=invoke),
        ):
            focused = application.recommend_wf04_practice(incoming)
            opted_out = application.recommend_wf04_practice(
                {**incoming, "wrongbook_priority": False}
            )

        self.assertEqual(focused["adaptive_policy"]["recommended_action"], "generate_variant")
        self.assertEqual(
            captured_requests[0]["evidence_summary"]["wrongbook_focus"]["focus_source"],
            "wrongbook",
        )
        self.assertEqual(captured_requests[0]["evidence_summary"]["active_wrongbook_count"], 2)
        self.assertEqual(opted_out["adaptive_policy"]["recommended_action"], "continue_practice")
        self.assertNotIn("wrongbook_focus", captured_requests[1]["evidence_summary"])

    def test_wrongbook_delta_resolves_only_targeted_error(self):
        application = self.server.RequestHandlerClass.application
        domain = application.domain
        project_id = "PROJ-WRONGBOOK-DELTA"
        created = domain.create_wf04_question(
            self.student_id,
            project_id,
            "TASKINST-WRONGBOOK-DELTA",
            "REQ-WRONGBOOK-DELTA",
            {
                "question_template_id": "TPL-WRONGBOOK-DELTA",
                "knowledge_point_id": "KP-ARRAY",
                "title": "数组边界",
                "prompt": "说明数组边界检查。",
                "question_type": "short_answer",
                "answer_schema": {"type": "text"},
                "expected_answer": "边界",
            },
            {
                "title": "数组边界",
                "prompt": "说明数组边界检查。",
                "question_type": "short_answer",
                "answer_schema": {"type": "text"},
            },
            "formal",
        )["question"]
        question_id = created["question_instance_id"]

        def result(
            attempt_id, event_id, instruction, errors, resolved=None,
            independent=False, correct=None,
        ):
            correct = independent if correct is None else bool(correct)
            return {
                "attempt_id": attempt_id,
                "validated_evaluation": {
                    "evaluation_status": "correct" if correct else "incorrect",
                    "independent_evidence": independent,
                    "error_points": errors,
                },
                "adaptive_policy": {"advisory_only": True},
                "wrongbook_event": {
                    "event_id": event_id,
                    "projection_instruction": instruction,
                    "project_id": project_id,
                    "knowledge_point_id": "KP-ARRAY",
                    "question_instance_id": question_id,
                    "root_question_instance_id": question_id,
                    "attempt_error_points": errors,
                    "candidate_resolved_error_point_ids": resolved or [],
                },
            }

        initial_errors = [
            {"error_id": "ERR-CAPACITY", "concept_id": "CONCEPT-CAPACITY", "root_cause": "遗漏容量检查"},
            {"error_id": "ERR-POSITION", "concept_id": "CONCEPT-POSITION", "root_cause": "遗漏位置检查"},
        ]
        domain.submit_wf04_attempt(
            self.student_id,
            question_id,
            "错误答案",
            result("ATTEMPT-WB-1", "EVENT-WB-1", "upsert_needs_review", initial_errors),
        )
        focus = domain.wrongbook_focus(self.student_id, project_id, "KP-ARRAY")
        self.assertEqual(focus["source_question_instance_id"], question_id)
        self.assertEqual(
            {item["error_id"] for item in focus["target_error_points"]},
            {"ERR-CAPACITY", "ERR-POSITION"},
        )

        domain.submit_wf04_attempt(
            self.student_id,
            question_id,
            "使用提示后答对",
            result(
                "ATTEMPT-WB-ASSISTED",
                "EVENT-WB-ASSISTED",
                "retain_needs_review_if_prior_wrong",
                [],
                [],
                False,
                True,
            ),
        )
        after_assisted = domain.wrongbook(
            self.student_id, project_id, status="needs_review"
        )["items"][0]
        self.assertEqual(
            {item["error_id"] for item in after_assisted["last_error_points"]},
            {"ERR-CAPACITY", "ERR-POSITION"},
        )

        domain.submit_wf04_attempt(
            self.student_id,
            question_id,
            "独立答对容量检查",
            result(
                "ATTEMPT-WB-2",
                "EVENT-WB-2",
                "mark_improved_not_deleted_if_prior_wrong",
                [],
                ["ERR-CAPACITY"],
                True,
            ),
        )
        after_one = domain.wrongbook(
            self.student_id, project_id, status="needs_review"
        )["items"][0]
        self.assertEqual(after_one["status"], "needs_review")
        self.assertEqual(
            [item["error_id"] for item in after_one["last_error_points"]],
            ["ERR-POSITION"],
        )

        domain.submit_wf04_attempt(
            self.student_id,
            question_id,
            "独立答对位置检查",
            result(
                "ATTEMPT-WB-3",
                "EVENT-WB-3",
                "mark_improved_not_deleted_if_prior_wrong",
                [],
                ["ERR-POSITION"],
                True,
            ),
        )
        improved = domain.wrongbook(
            self.student_id, project_id, status="improved_not_deleted"
        )["items"][0]
        self.assertEqual(improved["last_error_points"], [])

    def test_wrongbook_normalizes_legacy_string_error_for_targeted_practice(self):
        domain = self.server.RequestHandlerClass.application.domain
        normalized = domain._merge_wrongbook_errors([], ["旧版记录：混淆了元素移动方向"])

        self.assertEqual(len(normalized), 1)
        self.assertTrue(normalized[0]["error_id"].startswith("ERR-"))
        self.assertEqual(normalized[0]["error_type"], "legacy")
        self.assertEqual(normalized[0]["root_cause"], "旧版记录：混淆了元素移动方向")

    def test_wrongbook_retry_preserves_lineage_and_marks_original_improved(self):
        domain = self.server.RequestHandlerClass.application.domain
        project_id = "PROJ-WRONGBOOK-RETRY"
        original = domain.record_choice_attempt(
            student_id=self.student_id,
            source_question_id="SOURCE-WRONGBOOK-RETRY",
            mode="stage_check",
            knowledge_point_id="KP-WRONGBOOK-RETRY",
            knowledge_point_name="边界检查",
            title="哪个选项表示正确边界检查？",
            prompt="请选择正确答案。",
            options={"a": "忽略边界", "b": "先检查上下界"},
            expected="b",
            selected="a",
            explanation="应先检查上下界。",
            project_id=project_id,
            correct_override=False,
        )
        original_id = original["question_instance_id"]
        projected_question = {
            "question_id": "SOURCE-WRONGBOOK-RETRY",
            "knowledge_point_id": "KP-WRONGBOOK-RETRY",
            "knowledge_point_name": "边界检查",
            "title": "哪个选项表示正确边界检查？",
        }
        domain.project_wrongbook_result(
            self.student_id,
            project_id,
            "ASSESS-WRONGBOOK-RETRY",
            projected_question,
            False,
        )
        item = domain.wrongbook(
            self.student_id, project_id, status="needs_review"
        )["items"][0]
        self.assertEqual(item["root_question_instance_id"], original_id)
        self.assertTrue(item["can_retry_original"])
        self.assertEqual(item["question_type"], "choice")

        retry = domain.create_practice(
            self.student_id,
            {
                "project_id": project_id,
                "mode": "retry_original",
                "source_question_instance_id": original_id,
                "knowledge_point_id": "KP-WRONGBOOK-RETRY",
            },
        )["question"]
        result = domain.submit_attempt(
            self.student_id, retry["question_instance_id"], "b"
        )
        domain.project_wrongbook_result(
            self.student_id,
            project_id,
            "ASSESS-WRONGBOOK-RETRY",
            projected_question,
            False,
        )

        self.assertTrue(result["correct"])
        improved = domain.wrongbook(
            self.student_id, project_id, status="improved_not_deleted"
        )["items"][0]
        self.assertEqual(improved["root_question_instance_id"], original_id)
        self.assertEqual(improved["last_error_points"], [])

    def test_clear_certification_goal_is_not_forced_to_java(self):
        result = self.create_project("三个月内通过大学英语四级考试")
        project = result["project"]
        self.assertIn("英语四级", project["goal_name"])
        self.assertEqual(project["goal_type"], "certification")
        self.assertEqual(project["planning_state"], "ready")
        self.assertEqual(project["support_level"], "generated_scaffold")

    def test_named_non_java_certification_does_not_use_java_graph(self):
        project = self.create_project("两个月内通过 PMP 项目管理认证")["project"]
        self.assertEqual(project["goal_type"], "certification")
        self.assertEqual(project["support_level"], "generated_scaffold")
        detail = self.request_json(
            "GET", f"/api/projects/{project['project_id']}?student_id={self.student_id}"
        )["project"]
        names = [item["knowledge_point_name"] for item in detail["learning_path"]["items"]]
        self.assertFalse(any("Java" in name or "类与对象" in name for name in names))
        self.assertTrue(any("绩效域" in name for name in names))
        self.assertTrue(any("敏捷" in name for name in names))

    def test_named_non_java_competition_does_not_use_java_graph(self):
        project = self.create_project("备战全国职业院校短视频创作大赛")["project"]
        self.assertEqual(project["goal_type"], "competition")
        self.assertEqual(project["support_level"], "generated_scaffold")
        detail = self.request_json(
            "GET", f"/api/projects/{project['project_id']}?student_id={self.student_id}"
        )["project"]
        names = [item["knowledge_point_name"] for item in detail["learning_path"]["items"]]
        self.assertTrue(any("分镜" in name for name in names))
        self.assertTrue(any("剪辑" in name for name in names))
        self.assertTrue(any("参赛作品" in name for name in names))
        self.assertFalse(any("Java" in name or "类与对象" in name for name in names))
        self.assertNotIn("target_outcome", project["goal_constraints"])

    def test_unknown_learning_domain_keeps_goal_topic_in_path(self):
        project = self.create_project("掌握无人机航拍并完成校园宣传片")["project"]
        detail = self.request_json(
            "GET", f"/api/projects/{project['project_id']}?student_id={self.student_id}"
        )["project"]
        names = [item["knowledge_point_name"] for item in detail["learning_path"]["items"]]
        self.assertTrue(any("无人机航拍" in name for name in names))
        self.assertTrue(any("校园宣传片" in name for name in names))

    def test_create_project_matches_competition_keyword(self):
        result = self.create_project("备战世界职业院校技能大赛")
        self.assertEqual(result["status"], "ok")
        project = result["project"]
        detail = self.request_json(
            "GET",
            f"/api/projects/{project['project_id']}?student_id={self.student_id}",
        )["project"]
        self.assertEqual(detail["goal_type"], "competition")

    def test_create_project_unmatched_returns_clarification(self):
        result = self.create_project("随便学点什么")
        self.assertEqual(result["status"], "needs_clarification")
        self.assertIn("clarification", result)

    def test_non_learning_request_returns_scope_boundary(self):
        result = self.create_project("帮我订机票去北京")
        self.assertEqual(result["status"], "needs_clarification")
        self.assertEqual(result["reason"], "outside_learning_scope")
        self.assertIn("学习", result["clarification"])

    def test_list_projects_and_detail(self):
        self.assertEqual(self.request_json("GET", f"/api/projects?student_id={self.student_id}")["projects"], [])
        created = self.create_project("完成 Java 面向对象成绩管理实训")
        project_id = created["project"]["project_id"]

        listed = self.request_json("GET", f"/api/projects?student_id={self.student_id}")["projects"]
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["project_id"], project_id)

        detail = self.request_json(
            "GET", f"/api/projects/{project_id}?student_id={self.student_id}"
        )["project"]
        path = detail["learning_path"]
        self.assertEqual(len(path["items"]), 7)
        self.assertEqual(path["items"][0]["status"], "current")
        self.assertEqual(detail["diagnosis_state"], "not_started")

    def test_portrait_reserves_graph_contract_only_for_job_goals(self):
        course = self.create_project("我想系统掌握 Java 面向对象编程")["project"]
        portrait = self.request_json(
            "GET", f"/api/students/{self.student_id}/portrait"
        )
        self.assertEqual(portrait["job_competency_graphs"], [])

        job = self.create_project("我想达到 Java 后端开发岗位要求")["project"]
        self.assertEqual(job["goal_type"], "job")
        portrait = self.request_json(
            "GET", f"/api/students/{self.student_id}/portrait"
        )
        graphs = portrait["job_competency_graphs"]
        self.assertEqual(len(graphs), 1)
        self.assertEqual(graphs[0]["project_id"], job["project_id"])
        self.assertEqual(graphs[0]["status"], "not_connected")
        self.assertEqual(graphs[0]["nodes"], [])
        self.assertEqual(graphs[0]["edges"], [])
        self.assertNotEqual(graphs[0]["project_id"], course["project_id"])

    def test_project_diagnosis_full_flow(self):
        created = self.create_project("备战世界职业院校技能大赛")
        project_id = created["project"]["project_id"]
        started = self.request_json(
            "POST",
            f"/api/projects/{project_id}/diagnosis/start",
            {"student_id": self.student_id},
        )
        self.assertEqual(started["status"], "ok")
        self.assertEqual(started["goal"], "competition")
        questions = started["questions"]
        self.assertTrue(len(questions) >= 1)
        for question in questions:
            self.assertNotIn("answer", question)
            self.assertNotIn("explanation", question)

        summary = None
        for index, question in enumerate(questions):
            # 全部答错，确保产生薄弱点归因
            question_type = str(question.get("question_type") or "choice")
            options = question.get("options") or {}
            expected = str(question.get("answer") or "")
            if question_type in {"choice", "judgment"}:
                wrong = next(
                    (key for key in options if key != expected), None
                )
            elif question_type == "multiple_choice":
                expected_keys = {
                    value.strip()
                    for value in expected.replace("，", ",").split(",")
                    if value.strip()
                }
                wrong = next(
                    (key for key in options if key not in expected_keys), None
                )
            else:
                wrong = "错误答案"
            self.assertIsNotNone(wrong, f"题目缺少可选的错误答案：{question.get('question_id')}")
            answer = self.request_json(
                "POST",
                f"/api/projects/{project_id}/diagnosis/answer",
                {"student_id": self.student_id, "selected": wrong},
            )
            if answer["status"] == "completed":
                summary = answer["summary"]
        self.assertIsNotNone(summary)
        self.assertIn("weak_points", summary)
        self.assertTrue(len(summary["weak_points"]) >= 1)

        detail = self.request_json(
            "GET", f"/api/projects/{project_id}?student_id={self.student_id}"
        )["project"]
        self.assertEqual(detail["diagnosis_state"], "done")
        self.assertEqual(detail["weak_points"], summary["weak_points"])

    def test_project_diagnosis_rejects_unknown_project(self):
        with self.assertRaises(Exception):
            self.request_json(
                "POST",
                "/api/projects/PROJ-UNKNOWN/diagnosis/start",
                {"student_id": self.student_id},
            )

    def test_zero_foundation_skips_initial_assessment_and_starts_learning(self):
        created = self.create_project("我想系统掌握 Java 面向对象编程")
        project_id = created["project"]["project_id"]
        intake = self.request_json(
            "POST",
            f"/api/projects/{project_id}/assessments/intake",
            {
                "student_id": self.student_id,
                "self_reported_level": "zero_foundation",
                "claimed_knowledge_point_ids": [],
            },
        )
        self.assertEqual(intake["initial_assessment_state"], "awaiting_practice")
        self.assertFalse(intake["should_start_initial_assessment"])
        self.assertEqual(intake["suggested_assessment_type"], "")
        self.assertEqual(intake["baseline_profile"]["status"], "not_created")
        self.assertTrue(
            all(
                point["mastery"] is None
                for point in intake["baseline_profile"]["knowledge_points"]
            )
        )
        detail = self.request_json(
            "GET", f"/api/projects/{project_id}?student_id={self.student_id}"
        )["project"]
        self.assertEqual(detail["self_reported_level"], "zero_foundation")
        self.assertEqual(detail["initial_assessment_state"], "awaiting_practice")
        self.assertFalse(detail["active_assessment"])
        self.assertTrue(detail["learning_path"]["items"])
        self.assertTrue(
            all(
                item["lesson_generation_status"] in {"ready", "queued"}
                for item in detail["learning_path"]["items"]
            )
        )
        agent_response = self.agent_turn("开始能力测评", project_id)
        self.assertEqual(agent_response["action"], "reply")
        self.assertIn("无需初始测评", agent_response["message"])
        with self.assertRaises(Exception):
            self.request_json(
                "POST",
                f"/api/projects/{project_id}/assessments/start",
                {
                    "student_id": self.student_id,
                    "assessment_type": "initial_diagnostic",
                },
            )

    def test_project_lessons_wait_for_formal_initial_assessment(self):
        created = self.create_project("我想系统掌握 Java 面向对象编程")
        project_id = created["project"]["project_id"]
        detail = self.request_json(
            "GET", f"/api/projects/{project_id}?student_id={self.student_id}"
        )["project"]
        first = detail["learning_path"]["items"][0]
        self.assertEqual(first["lesson_generation_status"], "queued")

        waiting = self.request_json(
            "POST",
            f"/api/projects/{project_id}/explain",
            {
                "student_id": self.student_id,
                "knowledge_point_id": first["knowledge_point_id"],
            },
        )
        self.assertEqual(waiting["status"], "preparing")
        self.assertEqual(
            waiting["generation_status"], "awaiting_initial_assessment"
        )

        self.request_json(
            "POST",
            f"/api/projects/{project_id}/assessments/intake",
            {
                "student_id": self.student_id,
                "self_reported_level": "experienced",
                "claimed_knowledge_point_ids": [first["knowledge_point_id"]],
            },
        )
        started = self.request_json(
            "POST",
            f"/api/projects/{project_id}/assessments/start",
            {
                "student_id": self.student_id,
                "assessment_type": "initial_diagnostic",
            },
        )
        application = self.server.RequestHandlerClass.application
        session = application.store.get_project(project_id)["state"]["assessment_session"]
        for question in session["questions"]:
            completed = self.request_json(
                "POST",
                f"/api/projects/{project_id}/assessments/answer",
                {
                    "student_id": self.student_id,
                    "assessment_id": started["assessment_id"],
                    "answer": question["answer"],
                },
            )
        self.assertEqual(completed["status"], "completed")
        lesson = self.request_json(
            "POST",
            f"/api/projects/{project_id}/explain",
            {
                "student_id": self.student_id,
                "knowledge_point_id": first["knowledge_point_id"],
            },
        )
        self.assertEqual(lesson["status"], "ok")
        assessment_context = lesson["initial_assessment_context"]
        self.assertEqual(
            assessment_context["basis"], "formal_initial_assessment"
        )
        self.assertEqual(assessment_context["assessment_id"], started["assessment_id"])
        self.assertEqual(assessment_context["coverage_status"], "assessed")
        self.assertGreater(assessment_context["performance"]["correct_count"], 0)
        self.assertTrue(assessment_context["evidence"]["source_event_ids"])
        self.assertNotIn("self_reported_level", assessment_context)

    def test_initial_intake_prioritizes_claimed_points_and_creates_locked_baseline(self):
        created = self.create_project("我想系统掌握 Java 面向对象编程")
        project_id = created["project"]["project_id"]
        detail = self.request_json(
            "GET", f"/api/projects/{project_id}?student_id={self.student_id}"
        )["project"]
        target_id = detail["learning_path"]["items"][0]["knowledge_point_id"]
        with self.assertRaises(Exception):
            self.request_json(
                "POST",
                f"/api/projects/{project_id}/assessments/start",
                {
                    "student_id": self.student_id,
                    "assessment_type": "initial_diagnostic",
                },
            )
        intake = self.request_json(
            "POST",
            f"/api/projects/{project_id}/assessments/intake",
            {
                "student_id": self.student_id,
                "self_reported_level": "experienced",
                "claimed_knowledge_point_ids": [target_id],
            },
        )
        self.assertTrue(intake["should_start_initial_assessment"])
        started = self.request_json(
            "POST",
            f"/api/projects/{project_id}/assessments/start",
            {
                "student_id": self.student_id,
                "assessment_type": "initial_diagnostic",
            },
        )
        active = self.request_json(
            "GET", f"/api/projects/{project_id}?student_id={self.student_id}"
        )["project"]["active_assessment"]
        self.assertEqual(active["assessment_id"], started["assessment_id"])
        self.assertEqual(active["index"], 0)
        self.assertTrue(active["questions"])
        self.assertTrue(all("answer" not in item for item in active["questions"]))
        self.assertEqual(started["blueprint"]["focus_knowledge_point_ids"], [target_id])
        self.assertEqual(started["questions"][0]["knowledge_point_id"], target_id)
        self.assertTrue(
            all("question_type" in question for question in started["questions"])
        )
        self.assertGreater(started["blueprint"]["estimated_minutes"], 0)

        application = self.server.RequestHandlerClass.application
        session = application.store.get_project(project_id)["state"]["assessment_session"]
        completed = None
        for question in session["questions"]:
            completed = self.request_json(
                "POST",
                f"/api/projects/{project_id}/assessments/answer",
                {
                    "student_id": self.student_id,
                    "assessment_id": started["assessment_id"],
                    "answer": question["answer"],
                },
            )
        self.assertEqual(completed["status"], "completed")
        self.assertTrue(completed["summary"]["baseline_profile_created"])
        detail = self.request_json(
            "GET", f"/api/projects/{project_id}?student_id={self.student_id}"
        )["project"]
        baseline = detail["baseline_profile"]
        self.assertEqual(detail["initial_assessment_state"], "completed")
        self.assertEqual(baseline["status"], "assessed")
        measured = [
            point
            for point in baseline["knowledge_points"]
            if point["mastery"] is not None
        ]
        self.assertTrue(measured)
        self.assertTrue(all(point["source_event_ids"] for point in measured))
        self.assertEqual(detail["current_profile"], baseline)
        with self.assertRaises(Exception):
            self.request_json(
                "POST",
                f"/api/projects/{project_id}/assessments/start",
                {
                    "student_id": self.student_id,
                    "assessment_type": "initial_diagnostic",
                },
            )

    def test_assessment_center_lists_stage_and_goal_wide_practice_sheets(self):
        created = self.create_project("我想系统掌握 Java 面向对象编程")
        project_id = created["project"]["project_id"]
        center = self.request_json(
            "GET",
            f"/api/projects/{project_id}/assessments?student_id={self.student_id}",
        )
        self.assertEqual(
            {item["assessment_type"] for item in center["catalog"]},
            {"stage_check"},
        )
        self.assertEqual(center["goal_knowledge_point_count"], 7)
        self.assertEqual(len(center["practice_sheets"]), 7)
        self.assertTrue(
            all(item["assessment_type"] == "self_check" for item in center["practice_sheets"])
        )
        self.assertTrue(all(item["available"] for item in center["practice_sheets"]))
        self.assertEqual(center["history"], [])

        detail = self.request_json(
            "GET", f"/api/projects/{project_id}?student_id={self.student_id}"
        )["project"]
        self.assertEqual(len(detail["goal_knowledge_points"]), 7)
        knowledge_point_id = center["practice_sheets"][0]["knowledge_point_id"]
        started = self.request_json(
            "POST",
            f"/api/projects/{project_id}/assessments/start",
            {
                "student_id": self.student_id,
                "assessment_type": "self_check",
                "knowledge_point_id": knowledge_point_id,
            },
        )
        self.assertEqual(started["assessment_type"], "self_check")
        self.assertEqual(started["stakes"], "low")
        self.assertEqual(len(started["questions"]), 5)
        self.assertEqual(
            {question["question_type"] for question in started["questions"]},
            {"choice", "multiple_choice", "judgment", "fill_blank", "practical"},
        )
        self.assertTrue(started["source_policy"])
        for question in started["questions"]:
            self.assertEqual(question["quality_status"], "reviewed")
            self.assertIn("source_type", question)
            self.assertNotIn("answer", question)

        session = self.server.RequestHandlerClass.application.store.get_project(
            project_id
        )["state"]["assessment_session"]
        completed = None
        for question in session["questions"]:
            completed = self.request_json(
                "POST",
                f"/api/projects/{project_id}/assessments/answer",
                {
                    "student_id": self.student_id,
                    "assessment_id": started["assessment_id"],
                    "answer": question["answer"],
                },
            )
        self.assertEqual(completed["status"], "completed")
        self.assertFalse(completed["summary"]["formal_evidence"])
        self.assertEqual(completed["summary"]["evidence_count"], 0)

        center = self.request_json(
            "GET",
            f"/api/projects/{project_id}/assessments?student_id={self.student_id}",
        )
        self.assertEqual(center["history"], [])
        evidence = self.request_json(
            "GET",
            f"/api/projects/{project_id}/assessments/{started['assessment_id']}/evidence"
            f"?student_id={self.student_id}",
        )
        self.assertEqual(evidence["events"], [])
        detail = self.request_json(
            "GET", f"/api/projects/{project_id}?student_id={self.student_id}"
        )["project"]
        self.assertEqual(detail["current_profile"]["status"], "not_created")

    def test_assessment_history_only_keeps_completed_formal_runs(self):
        created = self.create_project("我想系统掌握 Java 面向对象编程")
        project_id = created["project"]["project_id"]
        detail = self.request_json(
            "GET", f"/api/projects/{project_id}?student_id={self.student_id}"
        )["project"]
        target = detail["learning_path"]["items"][0]
        started = self.request_json(
            "POST",
            f"/api/projects/{project_id}/assessments/start",
            {
                "student_id": self.student_id,
                "assessment_type": "stage_check",
                "knowledge_point_id": target["knowledge_point_id"],
            },
        )
        center = self.request_json(
            "GET", f"/api/projects/{project_id}/assessments?student_id={self.student_id}"
        )
        self.assertEqual(center["history"], [])

        application = self.server.RequestHandlerClass.application
        session = application.store.get_project(project_id)["state"]["assessment_session"]
        completed = None
        for question in session["questions"]:
            completed = self.request_json(
                "POST",
                f"/api/projects/{project_id}/assessments/answer",
                {
                    "student_id": self.student_id,
                    "assessment_id": started["assessment_id"],
                    "answer": question["answer"],
                },
            )
        self.assertEqual(completed["status"], "completed")
        self.assertTrue(completed["summary"]["current_profile_updated"])
        portrait = self.request_json(
            "GET", f"/api/students/{self.student_id}/portrait"
        )
        self.assertEqual(
            portrait["assessment_profile"]["current_profile"]["assessment_id"],
            started["assessment_id"],
        )

        center = self.request_json(
            "GET", f"/api/projects/{project_id}/assessments?student_id={self.student_id}"
        )
        self.assertEqual([run["assessment_id"] for run in center["history"]], [started["assessment_id"]])
        self.assertTrue(all(run["stakes"] == "formal" for run in center["history"]))
        self.assertTrue(all(run["status"] == "completed" for run in center["history"]))

        self.request_json(
            "POST",
            f"/api/projects/{project_id}/assessments/start",
            {
                "student_id": self.student_id,
                "assessment_type": "self_check",
                "knowledge_point_id": target["knowledge_point_id"],
            },
        )
        center = self.request_json(
            "GET", f"/api/projects/{project_id}/assessments?student_id={self.student_id}"
        )
        self.assertEqual([run["assessment_id"] for run in center["history"]], [started["assessment_id"]])

    def test_practice_sheets_keep_full_goal_scope_when_path_is_personalized(self):
        created = self.create_project("我想系统掌握 Java 面向对象编程")
        project_id = created["project"]["project_id"]
        application = self.server.RequestHandlerClass.application
        stored = application.store.get_project(project_id)
        state = stored["state"]
        state["learning_path"]["items"] = state["learning_path"]["items"][:2]
        application.store.save_project_state(project_id, state)

        center = self.request_json(
            "GET",
            f"/api/projects/{project_id}/assessments?student_id={self.student_id}",
        )
        detail = self.request_json(
            "GET", f"/api/projects/{project_id}?student_id={self.student_id}"
        )["project"]
        self.assertEqual(len(detail["learning_path"]["items"]), 2)
        self.assertEqual(len(detail["goal_knowledge_points"]), 7)
        self.assertEqual(len(center["practice_sheets"]), 7)

    def test_stage_check_uses_distinct_evidence_to_unlock_path(self):
        created = self.create_project("我想系统掌握 Java 面向对象编程")
        project_id = created["project"]["project_id"]
        detail = self.request_json(
            "GET", f"/api/projects/{project_id}?student_id={self.student_id}"
        )["project"]
        target = detail["learning_path"]["items"][0]
        started = self.request_json(
            "POST",
            f"/api/projects/{project_id}/assessments/start",
            {
                "student_id": self.student_id,
                "assessment_type": "stage_check",
                "knowledge_point_id": target["knowledge_point_id"],
            },
        )
        application = self.server.RequestHandlerClass.application
        session = application.store.get_project(project_id)["state"]["assessment_session"]
        self.assertGreaterEqual(len(session["questions"]), 2)
        completed = None
        for question in session["questions"]:
            completed = self.request_json(
                "POST",
                f"/api/projects/{project_id}/assessments/answer",
                {
                    "student_id": self.student_id,
                    "assessment_id": started["assessment_id"],
                    "selected": question["answer"],
                },
            )
        self.assertEqual(completed["status"], "completed")
        update = next(
            item
            for item in completed["summary"]["knowledge_updates"]
            if item["knowledge_point_id"] == target["knowledge_point_id"]
        )
        self.assertEqual(update["evidence_status"], "verified_once")
        detail = self.request_json(
            "GET", f"/api/projects/{project_id}?student_id={self.student_id}"
        )["project"]
        updated_target = detail["learning_path"]["items"][0]
        self.assertEqual(updated_target["status"], "completed")
        self.assertEqual(updated_target["mastery_model"], "evidence_rule_v1")
        self.assertTrue(updated_target["mastery_is_estimated"])

    def test_project_explain_returns_teaching_package(self):
        created = self.create_project("完成 Java 面向对象成绩管理实训")
        project_id = created["project"]["project_id"]
        self.set_zero_foundation_intake(project_id)
        detail = self.request_json(
            "GET", f"/api/projects/{project_id}?student_id={self.student_id}"
        )["project"]
        first = detail["learning_path"]["items"][0]
        explanation = self.request_json(
            "POST",
            f"/api/projects/{project_id}/explain",
            {
                "student_id": self.student_id,
                "knowledge_point_id": first["knowledge_point_id"],
            },
        )
        self.assertEqual(explanation["status"], "ok")
        self.assertTrue(explanation["lesson_title"])
        self.assertTrue(len(explanation["content_blocks"]) >= 1)
        self.assertEqual(explanation["knowledge_point_id"], first["knowledge_point_id"])
        self.assertTrue(explanation["generated_with_path"])

    def test_candidate_project_does_not_pregenerate_lessons_before_assessment(self):
        project = self.create_project("六周内掌握 Python 数据分析并完成销售数据看板")["project"]
        detail = self.request_json(
            "GET", f"/api/projects/{project['project_id']}?student_id={self.student_id}"
        )["project"]
        items = detail["learning_path"]["items"]
        self.assertGreaterEqual(len(items), 3)
        self.assertTrue(all(item["lesson_generation_status"] == "queued" for item in items))
        application = self.server.RequestHandlerClass.application
        for item in items:
            cached = application.store.get_project_lesson(
                project["project_id"], self.student_id, item["knowledge_point_id"]
            )
            self.assertEqual(cached["status"], "queued")
            self.assertEqual(cached["lesson"], {})

    def test_reading_project_does_not_sync_initialize_lessons(self):
        project = self.create_project(
            "六周内掌握 Python 数据分析并完成销售数据看板"
        )["project"]
        application = self.server.RequestHandlerClass.application
        original = application.store.initialize_project_lessons
        application.store.initialize_project_lessons = lambda *_args, **_kwargs: (
            (_ for _ in ()).throw(AssertionError("项目详情 GET 不应同步初始化章节"))
        )
        try:
            detail = self.request_json(
                "GET",
                f"/api/projects/{project['project_id']}?student_id={self.student_id}",
            )["project"]
        finally:
            application.store.initialize_project_lessons = original
        self.assertTrue(detail["learning_path"]["items"])

    def test_reading_legacy_candidate_project_does_not_replan_path(self):
        project = self.create_project(
            "六周内掌握 Python 数据分析并完成销售数据看板"
        )["project"]
        application = self.server.RequestHandlerClass.application
        stored = application.store.get_project(project["project_id"])
        state = stored["state"]
        state["learning_path"]["candidate_schema_version"] = 1
        application.store.save_project_state(project["project_id"], state)
        original = application._build_custom_learning_path
        application._build_custom_learning_path = lambda *_args, **_kwargs: (
            (_ for _ in ()).throw(
                AssertionError("项目详情 GET 不应同步重新规划已有学习路径")
            )
        )
        try:
            detail = self.request_json(
                "GET",
                f"/api/projects/{project['project_id']}?student_id={self.student_id}",
            )["project"]
        finally:
            application._build_custom_learning_path = original
        self.assertEqual(detail["learning_path"]["candidate_schema_version"], 1)
        self.assertTrue(detail["learning_path"]["items"])

    def test_clicking_unprepared_candidate_lesson_does_not_generate(self):
        project = self.create_project("六周内掌握 Python 数据分析并完成销售数据看板")["project"]
        detail = self.request_json(
            "GET", f"/api/projects/{project['project_id']}?student_id={self.student_id}"
        )["project"]
        target = detail["learning_path"]["items"][0]
        application = self.server.RequestHandlerClass.application
        original = application._generate_project_lesson
        application._generate_project_lesson = lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("点击章节时不应生成讲解")
        )
        try:
            explanation = self.request_json(
                "POST",
                f"/api/projects/{project['project_id']}/explain",
                {
                    "student_id": self.student_id,
                    "knowledge_point_id": target["knowledge_point_id"],
                },
            )
        finally:
            application._generate_project_lesson = original
        self.assertEqual(explanation["status"], "preparing")
        self.assertEqual(
            explanation["generation_status"], "awaiting_initial_assessment"
        )

    def test_video_candidates_filter_relevance_then_sort_by_play_count(self):
        application = self.server.RequestHandlerClass.application
        context = {
            "current_knowledge_point": {
                "knowledge_point_id": "KN_PANDAS_CLEAN",
                "knowledge_point_name": "Pandas 数据清洗",
            },
            "web_search_context": {
                "status": "ok",
                "provider": "bilibili",
                "results": [
                    {
                        "type": "video",
                        "title": "Pandas 数据清洗入门",
                        "url": "https://www.bilibili.com/video/BV1LowPlay",
                        "play_count": 1200,
                        "play_count_text": "1200",
                    },
                    {
                        "type": "video",
                        "title": "Pandas 数据清洗完整教程",
                        "url": "https://www.bilibili.com/video/BV1HighPlay",
                        "play_count": 86000,
                        "play_count_text": "8.6万",
                    },
                    {
                        "type": "video",
                        "title": "热门游戏直播回放",
                        "url": "https://www.bilibili.com/video/BV1Irrelevant",
                        "play_count": 9_000_000,
                        "play_count_text": "900万",
                    },
                ],
            },
        }
        result = {"resources": []}
        application._merge_video_resources(result, context)
        videos = [item for item in result["resources"] if item["type"] == "video"]
        self.assertEqual(
            [item["url"] for item in videos],
            [
                "https://www.bilibili.com/video/BV1HighPlay",
                "https://www.bilibili.com/video/BV1LowPlay",
            ],
        )

    def test_c_language_video_requires_language_context(self):
        application = self.server.RequestHandlerClass.application
        context = {
            "learning_goal": {"goal_name": "学习 C 语言"},
            "current_knowledge_point": {
                "knowledge_point_id": "KN-C-PROGRAM",
                "knowledge_point_name": "C 语言程序结构、编译与运行",
            },
            "web_search_context": {
                "status": "ok",
                "provider": "bilibili",
                "results": [
                    {
                        "type": "video",
                        "title": "编译原理零基础教程",
                        "url": "https://www.bilibili.com/video/BV1Compiler",
                        "play_count": 900_000,
                    },
                    {
                        "type": "video",
                        "title": "C语言程序结构、编译与运行入门",
                        "url": "https://www.bilibili.com/video/BV1CTutorial",
                        "play_count": 10_000,
                    },
                ],
            },
        }
        result = {"resources": []}
        application._merge_video_resources(result, context)
        videos = [item for item in result["resources"] if item["type"] == "video"]
        self.assertEqual(
            [item["url"] for item in videos],
            ["https://www.bilibili.com/video/BV1CTutorial"],
        )

    def test_video_goal_domain_boosts_ranking_without_hiding_knowledge_match(self):
        application = self.server.RequestHandlerClass.application
        context = {
            "learning_goal": {"goal_name": "学习无人机航拍并完成校园宣传片"},
            "current_knowledge_point": {
                "knowledge_point_id": "KN-DRONE-COMPOSE",
                "knowledge_point_name": "航拍运镜与构图",
                "goal_context_keywords": ["无人机", "航拍", "校园宣传片"],
                "video_context_keywords": ["航拍", "运镜", "构图"],
            },
            "web_search_context": {
                "status": "ok",
                "provider": "bilibili",
                "results": [
                    {
                        "type": "video",
                        "title": "电影摄影运镜与构图教程",
                        "url": "https://www.bilibili.com/video/BV1MovieCamera",
                    },
                    {
                        "type": "video",
                        "title": "无人机航拍运镜与构图教程",
                        "url": "https://www.bilibili.com/video/BV1DroneCamera",
                    },
                ],
            },
        }
        result = {"resources": []}
        application._merge_video_resources(result, context)
        videos = [item for item in result["resources"] if item["type"] == "video"]
        self.assertEqual(
            [item["url"] for item in videos],
            [
                "https://www.bilibili.com/video/BV1DroneCamera",
                "https://www.bilibili.com/video/BV1MovieCamera",
            ],
        )

    def test_video_filter_matches_dynamic_technology_context(self):
        application = self.server.RequestHandlerClass.application
        context = {
            "learning_goal": {
                "goal_name": "应聘后端工程师",
                "original_text": "使用 Java 和 Spring Boot 完成后端项目",
                "constraints": {"tech_stack": ["java", "spring_boot"]},
            },
            "current_knowledge_point": {
                "knowledge_point_id": "KN_JAVA_INHERITANCE",
                "knowledge_point_name": "继承与方法重写",
            },
            "web_search_context": {
                "status": "ok",
                "provider": "bilibili",
                "results": [
                    {
                        "type": "video",
                        "title": "Java 继承与方法重写教程",
                        "url": "https://www.bilibili.com/video/BV1Java",
                    },
                    {
                        "type": "video",
                        "title": "C++ 继承机制教程",
                        "url": "https://www.bilibili.com/video/BV1Cpp",
                    },
                ],
            },
        }
        result = {"resources": []}
        application._merge_video_resources(result, context)
        videos = [item for item in result["resources"] if item["type"] == "video"]
        self.assertEqual(
            [item["url"] for item in videos],
            ["https://www.bilibili.com/video/BV1Java"],
        )

    def test_bilibili_popularity_parser_and_cross_domain_filter(self):
        application = self.server.RequestHandlerClass.application
        search = application.video_search
        self.assertEqual(search._parse_count_text("168.6万"), 1_686_000)
        self.assertEqual(search._parse_count_text("6949"), 6949)
        self.assertIsNone(search._parse_count_text("播放量未知"))
        self.assertTrue(search._bilibili_title_relevant(
            "2026 最新 HTML 标签入门教程", "HTML 页面结构 教学 教程"
        ))
        self.assertTrue(search._bilibili_title_relevant(
            "Pandas 数据读取与清洗完整教程", "Pandas 数据读取与清洗 教学 教程"
        ))
        self.assertFalse(search._bilibili_title_relevant(
            "王者荣耀 HTML 活动页", "HTML 页面结构 教学 教程"
        ))

    def test_custom_goal_explain_waits_for_formal_assessment(self):
        project = self.create_project("六周内掌握 Python 数据分析并完成销售数据看板")["project"]
        detail = self.request_json(
            "GET", f"/api/projects/{project['project_id']}?student_id={self.student_id}"
        )["project"]
        first = detail["learning_path"]["items"][0]
        explanation = self.request_json(
            "POST",
            f"/api/projects/{project['project_id']}/explain",
            {
                "student_id": self.student_id,
                "knowledge_point_id": first["knowledge_point_id"],
            },
        )
        self.assertEqual(explanation["status"], "preparing")
        self.assertEqual(
            explanation["generation_status"], "awaiting_initial_assessment"
        )

    def test_custom_goal_remote_explain_waits_for_formal_assessment(self):
        gateway = self.server.RequestHandlerClass.application.gateway
        original_settings = gateway.settings
        gateway.settings = Settings(
            **{**gateway.settings.__dict__, "xingchen_mode": "remote"}
        )
        original_invoke = gateway.invoke_chat_workflow
        gateway.invoke_chat_workflow = lambda payload: {
            "status": "ok",
            "answer": (
                "### 核心概念\n\nPython 数据处理先要区分原始数据、转换过程和输出结果，"
                "并为缺失值和类型转换建立明确规则。\n\n"
                "### 最小示例\n\n```python\nrows = [1, None, 3]\n"
                "clean = [value for value in rows if value is not None]\nprint(clean)\n```\n\n"
                "### 常见误区\n\n不要把缺失值直接当成零；两者表达的业务含义不同。\n\n"
                "### 动手练习\n\n读取一组包含空值的数据，清洗后输出有效记录数量。"
            ),
        }
        try:
            project = self.create_project("六周内掌握 Python 数据分析并完成销售数据看板")["project"]
            detail = self.request_json(
                "GET", f"/api/projects/{project['project_id']}?student_id={self.student_id}"
            )["project"]
            first = detail["learning_path"]["items"][0]
            explanation = self.request_json(
                "POST",
                f"/api/projects/{project['project_id']}/explain",
                {
                    "student_id": self.student_id,
                    "knowledge_point_id": first["knowledge_point_id"],
                },
            )
        finally:
            gateway.invoke_chat_workflow = original_invoke
            gateway.settings = original_settings

        self.assertEqual(explanation["status"], "preparing")
        self.assertEqual(
            explanation["generation_status"], "awaiting_initial_assessment"
        )

    def test_custom_goal_short_remote_explain_waits_for_formal_assessment(self):
        gateway = self.server.RequestHandlerClass.application.gateway
        original_settings = gateway.settings
        gateway.settings = Settings(
            **{**gateway.settings.__dict__, "xingchen_mode": "remote"}
        )
        original_invoke = gateway.invoke_chat_workflow
        gateway.invoke_chat_workflow = lambda payload: {"status": "ok", "answer": "内容生成中"}
        try:
            project = self.create_project("六周内掌握 Python 数据分析并完成销售数据看板")["project"]
            detail = self.request_json(
                "GET", f"/api/projects/{project['project_id']}?student_id={self.student_id}"
            )["project"]
            first = detail["learning_path"]["items"][0]
            explanation = self.request_json(
                "POST",
                f"/api/projects/{project['project_id']}/explain",
                {
                    "student_id": self.student_id,
                    "knowledge_point_id": first["knowledge_point_id"],
                },
            )
        finally:
            gateway.invoke_chat_workflow = original_invoke
            gateway.settings = original_settings

        self.assertEqual(explanation["status"], "preparing")
        self.assertEqual(
            explanation["generation_status"], "awaiting_initial_assessment"
        )

    def test_project_explain_unknown_knowledge_point(self):
        created = self.create_project("完成 Java 面向对象成绩管理实训")
        project_id = created["project"]["project_id"]
        with self.assertRaises(Exception):
            self.request_json(
                "POST",
                f"/api/projects/{project_id}/explain",
                {"student_id": self.student_id, "knowledge_point_id": "KN_UNKNOWN"},
            )

    def test_multiple_projects_are_isolated(self):
        first = self.create_project("备战世界职业院校技能大赛")["project"]
        second = self.create_project("完成 Java 面向对象成绩管理实训")["project"]
        self.request_json(
            "POST",
            f"/api/projects/{first['project_id']}/diagnosis/start",
            {"student_id": self.student_id},
        )
        listed = self.request_json("GET", f"/api/projects?student_id={self.student_id}")["projects"]
        by_id = {item["project_id"]: item for item in listed}
        self.assertEqual(by_id[first["project_id"]]["diagnosis_state"], "in_progress")
        self.assertEqual(by_id[second["project_id"]]["diagnosis_state"], "not_started")

    # ---------- Tutor Agent 统一编排 ----------

    def agent_turn(self, message, project_id="", session_id="agent-test"):
        return self.request_json(
            "POST",
            "/api/agent/turn",
            {
                "student_id": self.student_id,
                "session_id": session_id,
                "project_id": project_id,
                "message": message,
            },
        )

    def test_agent_turn_creates_project_and_recommends_assessment(self):
        result = self.agent_turn("我想系统掌握 Java 面向对象编程")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["intent"], "create_project")
        self.assertEqual(result["action"], "project_created")
        self.assertIn("project_id", result["project"])
        self.assertEqual(result["project"]["planning_state"], "awaiting_learner_profile")
        self.assertEqual(result["next_interaction"]["type"], "learner_profile")

        project_id = result["project"]["project_id"]
        before = self.request_json(
            "GET", f"/api/projects/{project_id}?student_id={self.student_id}"
        )["project"]
        self.assertEqual(before["learning_path"]["items"], [])
        self.assertEqual(before["learning_plan"], {})

        intake = self.set_zero_foundation_intake(project_id)
        self.assertTrue(intake["learning_path_generated"])
        self.assertEqual(intake["planning_state"], "ready")
        after = self.request_json(
            "GET", f"/api/projects/{project_id}?student_id={self.student_id}"
        )["project"]
        self.assertTrue(after["learning_path"]["items"])
        self.assertTrue(after["learning_plan"]["stages"])
        self.assertEqual(
            after["learning_path"]["personalization"]["self_reported_level"],
            "zero_foundation",
        )

    def test_agent_turn_routes_cross_domain_goal_to_knowledge_planning(self):
        result = self.agent_turn("六周内掌握 Python 数据分析并完成销售数据看板")
        self.assertEqual(result["intent"], "create_project")
        self.assertEqual(result["action"], "project_created")
        self.assertEqual(result["project"]["planning_state"], "awaiting_learner_profile")
        self.assertEqual(result["project"]["assessment_state"], "question_sources_pending")
        self.assertEqual(result["next_interaction"]["type"], "learner_profile")
        self.assertIn("信息收集完成后", result["message"])

    def test_agent_intake_materializes_path_and_adjusts_plan_pacing(self):
        zero_project = self.agent_turn(
            "我想系统掌握 Java 面向对象编程", session_id="deferred-zero"
        )["project"]
        experienced_project = self.agent_turn(
            "我想系统掌握 Java 面向对象编程", session_id="deferred-experienced"
        )["project"]

        zero_detail = self.request_json(
            "GET",
            f"/api/projects/{zero_project['project_id']}?student_id={self.student_id}",
        )["project"]
        experienced_detail = self.request_json(
            "GET",
            f"/api/projects/{experienced_project['project_id']}?student_id={self.student_id}",
        )["project"]
        self.assertEqual(zero_detail["learning_path"]["items"], [])
        self.assertEqual(experienced_detail["learning_path"]["items"], [])

        self.set_zero_foundation_intake(zero_project["project_id"])
        familiar_ids = [
            item["knowledge_point_id"]
            for item in experienced_detail["goal_knowledge_points"][:2]
        ]
        self.request_json(
            "POST",
            f"/api/projects/{experienced_project['project_id']}/assessments/intake",
            {
                "student_id": self.student_id,
                "self_reported_level": "experienced",
                "claimed_knowledge_point_ids": familiar_ids,
            },
        )

        zero_after = self.request_json(
            "GET",
            f"/api/projects/{zero_project['project_id']}?student_id={self.student_id}",
        )["project"]
        experienced_after = self.request_json(
            "GET",
            f"/api/projects/{experienced_project['project_id']}?student_id={self.student_id}",
        )["project"]
        zero_minutes = zero_after["learning_plan"]["time_budget"]["total_estimated_minutes"]
        experienced_minutes = experienced_after["learning_plan"]["time_budget"]["total_estimated_minutes"]
        self.assertGreater(zero_minutes, experienced_minutes)
        self.assertTrue(
            experienced_after["learning_path"]["items"][0]["self_reported_familiar"]
        )
        self.assertIsNone(experienced_after["learning_path"]["items"][0]["mastery"])

    def test_agent_turn_builds_goal_from_multiturn_intake(self):
        first = self.agent_turn("我想学 Python，我是零基础，每天只能学半小时")
        self.assertEqual(first["status"], "needs_clarification")
        self.assertEqual(first["intent"], "clarify_goal")
        self.assertIn("可验收", first["message"])

        second = self.agent_turn("想做销售数据看板")
        self.assertEqual(second["status"], "ok")
        self.assertEqual(second["action"], "project_created")
        constraints = second["project"]["goal_constraints"]
        self.assertIn("销售数据看板", constraints["target_outcome"])
        self.assertEqual(constraints["daily_minutes"], 30)
        self.assertEqual(constraints["current_level"], "zero_foundation")
        self.assertTrue(constraints["duration_assumption"])
        self.assertNotIn("零基础", second["project"]["goal_name"])
        self.assertNotIn("半小时", second["project"]["goal_name"])

        detail = self.request_json(
            "GET",
            f"/api/projects/{second['project']['project_id']}?student_id={self.student_id}",
        )["project"]
        self.assertEqual(detail["learner_preferences"]["daily_minutes"], 30)
        self.assertEqual(
            detail["learner_self_reports"][0]["verification_state"], "unverified"
        )
        messages = self.request_json(
            "GET",
            f"/api/projects/{second['project']['project_id']}/messages?student_id={self.student_id}",
        )["messages"]
        self.assertTrue(any("我想学 Python" in item["content"] for item in messages))
        self.assertTrue(any("销售数据看板" in item["content"] for item in messages))

    def test_agent_turn_clarifies_umbrella_domain_before_building_path(self):
        session_id = "embedded-direction-intake"
        first = self.agent_turn("我想学习嵌入式，零基础", session_id=session_id)
        self.assertEqual(first["status"], "needs_clarification")
        self.assertEqual(first["missing_fields"], ["learning_direction"])
        self.assertIn("哪个方向", first["message"])

        second = self.agent_turn("我想从 STM32 单片机开发开始", session_id=session_id)
        self.assertEqual(second["status"], "needs_clarification")
        self.assertEqual(second["missing_fields"], ["target_outcome"])

        completed = self.agent_turn("我想完成温湿度采集和显示项目", session_id=session_id)
        self.assertEqual(completed["status"], "ok")
        self.assertEqual(completed["action"], "project_created")
        self.assertEqual(
            completed["project"]["goal_constraints"]["learning_direction"], "mcu"
        )
        detail = self.request_json(
            "GET",
            f"/api/projects/{completed['project']['project_id']}?student_id={self.student_id}",
        )["project"]
        self.assertTrue(
            any("STM32 开发板" in item["knowledge_point_name"]
                for item in detail["goal_knowledge_points"])
        )

    def test_job_goal_uses_adaptive_multiturn_intake(self):
        session_id = "adaptive-job-goal"
        first = self.agent_turn("我想成为后端开发工程师", session_id=session_id)
        self.assertEqual(first["status"], "needs_clarification")
        self.assertEqual(first["goal_intake"]["goal_type"], "job")
        self.assertEqual(
            first["missing_fields"],
            ["career_stage", "tech_stack", "help_focus"],
        )
        self.assertIn("哪个阶段", first["message"])

        second = self.agent_turn("我是在校学生", session_id=session_id)
        self.assertEqual(second["missing_fields"], ["tech_stack", "help_focus"])
        self.assertIn("技术栈", second["message"])

        third = self.agent_turn("我想使用 Java 和 Spring Boot", session_id=session_id)
        self.assertEqual(third["missing_fields"], ["help_focus"])
        self.assertIn("最需要", third["message"])

        completed = self.agent_turn("我最需要项目实战和项目经验", session_id=session_id)
        self.assertEqual(completed["action"], "project_created")
        self.assertEqual(completed["project"]["goal_type"], "job")
        constraints = completed["project"]["goal_constraints"]
        self.assertEqual(constraints["career_stage"], "student")
        self.assertEqual(constraints["tech_stack"], ["spring_boot", "java"])
        self.assertEqual(constraints["help_focus"], ["project_practice"])

        detail = self.request_json(
            "GET",
            f"/api/projects/{completed['project']['project_id']}?student_id={self.student_id}",
        )["project"]
        self.assertEqual(detail["learner_self_reports"][0]["verification_state"], "unverified")
        self.assertTrue(
            all(item["verification_state"] == "unverified" for item in detail["learner_self_reports"])
        )
        self.assertTrue(
            all(item.get("mastery") is None for item in detail["learning_path"]["items"])
        )

    def test_complete_job_goal_skips_redundant_questions(self):
        result = self.agent_turn(
            "我是在校学生，想学习 Java 后端开发，最需要项目实战",
            session_id="complete-job-goal",
        )
        self.assertEqual(result["action"], "project_created")
        self.assertEqual(result["project"]["goal_type"], "job")
        constraints = result["project"]["goal_constraints"]
        self.assertEqual(constraints["career_stage"], "student")
        self.assertEqual(constraints["tech_stack"], ["java"])
        self.assertEqual(constraints["help_focus"], ["project_practice"])

    def test_knowledge_goal_clarification_mentions_teaching_preferences(self):
        result = self.agent_turn(
            "我想学 Python",
            session_id="knowledge-goal-preferences",
        )
        self.assertEqual(result["intent"], "clarify_goal")
        self.assertEqual(result["goal_intake"]["goal_type"], "knowledge")
        self.assertEqual(result["missing_fields"], ["target_outcome"])
        self.assertIn("视频", result["message"])
        self.assertIn("项目实战", result["message"])

    def test_goal_draft_is_isolated_by_session(self):
        first = self.agent_turn("我想学 Python", session_id="goal-session-a")
        self.assertEqual(first["intent"], "clarify_goal")

        unrelated = self.agent_turn("想做销售数据看板", session_id="goal-session-b")
        self.assertNotEqual(unrelated.get("action"), "project_created")

        completed = self.agent_turn("想做销售数据看板", session_id="goal-session-a")
        self.assertEqual(completed["action"], "project_created")

    def test_goal_question_does_not_consume_pending_draft(self):
        self.agent_turn("我想学 Python", session_id="goal-question")
        question = self.agent_turn("Python 是什么？", session_id="goal-question")
        self.assertEqual(question["intent"], "knowledge_question")
        completed = self.agent_turn("想做办公自动化", session_id="goal-question")
        self.assertEqual(completed["action"], "project_created")

    def test_general_assistant_request_does_not_consume_pending_goal(self):
        self.agent_turn("我想学 Python", session_id="goal-interrupt")
        interruption = self.agent_turn(
            "帮我解释一下 Java 封装", session_id="goal-interrupt"
        )
        self.assertEqual(interruption["intent"], "knowledge_question")
        completed = self.agent_turn("想做数据看板", session_id="goal-interrupt")
        self.assertEqual(completed["action"], "project_created")

    def test_general_assistant_routes_translation_without_creating_project(self):
        application = self.server.RequestHandlerClass.application
        original_settings = application.gateway.settings
        application.gateway.settings = Settings(
            **{
                **application.gateway.settings.__dict__,
                "xingchen_mode": "remote",
                "chat_flow_id": "chat-flow-id",
                "api_key": "test-key",
                "api_secret": "test-secret",
                "api_url": "https://example.invalid/workflow",
            }
        )
        original = application.gateway.invoke_chat_workflow
        captured = {}

        def answer_general(payload):
            captured.update(payload)
            return {"status": "ok", "answer": "Learning can begin today."}

        application.gateway.invoke_chat_workflow = answer_general
        try:
            result = self.agent_turn("请把‘今天可以开始学习’翻译成英文")
        finally:
            application.gateway.invoke_chat_workflow = original
            application.gateway.settings = original_settings
        self.assertEqual(result["intent"], "general_assistant")
        self.assertEqual(result["action"], "reply")
        self.assertEqual(result["answer_mode"], "general_generation")
        self.assertEqual(result["answer"], "Learning can begin today.")
        self.assertEqual(captured["assistant_mode"], "general")
        self.assertEqual(captured["source_kind"], "none")

    def test_unknown_general_question_routes_to_general_assistant(self):
        application = self.server.RequestHandlerClass.application
        original_mode = application.gateway.settings
        application.gateway.settings = Settings(
            **{
                **original_mode.__dict__,
                "xingchen_mode": "remote",
                "chat_flow_id": "chat-flow-id",
                "api_key": "test-key",
                "api_secret": "test-secret",
                "api_url": "https://example.invalid/workflow",
            }
        )
        original = application.gateway.invoke_chat_workflow
        application.gateway.invoke_chat_workflow = lambda _payload: {
            "status": "ok",
            "answer": "番茄工作法用专注时段与短休息交替管理注意力。",
        }
        try:
            result = self.agent_turn("番茄工作法有什么优缺点？")
        finally:
            application.gateway.invoke_chat_workflow = original
            application.gateway.settings = original_mode
        self.assertEqual(result["intent"], "general_assistant")
        self.assertEqual(result["answer_mode"], "general_generation")

    def test_chat_keeps_explicit_education_mode_for_unknown_question(self):
        """教育对话的未命中问题仍应走澄清/检索/教育回答链路。"""
        application = self.server.RequestHandlerClass.application
        original_settings = application.gateway.settings
        application.gateway.settings = Settings(
            **{
                **original_settings.__dict__,
                "xingchen_mode": "remote",
                "chat_flow_id": "chat-flow-id",
                "api_key": "test-key",
                "api_secret": "test-secret",
                "api_url": "https://example.invalid/workflow",
            }
        )
        original = application.gateway.invoke_chat_workflow
        captured = {}

        def answer_general(payload):
            captured.update(payload)
            return {"status": "ok", "answer": "它有助于聚焦，但固定时段可能打断深度工作。"}

        application.gateway.invoke_chat_workflow = answer_general
        try:
            result = self.request_json(
                "POST",
                "/api/chat",
                {
                    "student_id": self.student_id,
                    "session_id": "defensive-general",
                    "message": "番茄工作法有什么优缺点？",
                    "assistant_mode": "education",
                    "allow_web_search": False,
                },
            )
        finally:
            application.gateway.invoke_chat_workflow = original
            application.gateway.settings = original_settings
        self.assertEqual(captured["assistant_mode"], "education")
        self.assertEqual(result["answer_mode"], "education_generation")

    def test_explicit_web_search_is_not_misclassified_as_project(self):
        result = self.request_json(
            "POST",
            "/api/agent/turn",
            {
                "student_id": self.student_id,
                "session_id": "web-search-test",
                "project_id": "",
                "message": "帮我上网搜索 Python 最新官方教程",
                "allow_web_search": True,
                "force_web_search": True,
            },
        )
        self.assertEqual(result["intent"], "general_assistant")
        self.assertEqual(result["action"], "reply")
        self.assertTrue(result["web_searched"])
        self.assertNotEqual(result.get("action"), "project_created")

    def test_agent_turn_answers_knowledge_question_with_sources(self):
        result = self.agent_turn("什么是 Java 封装？")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["intent"], "knowledge_question")
        self.assertEqual(result["action"], "reply")
        self.assertTrue(result["answer"])
        self.assertTrue(result["sources"])

    def test_agent_turn_returns_validated_turn_understanding(self):
        result = self.agent_turn("我零基础，先解释一下 Python 变量，再帮我规划 Python 学习")
        understanding = result["turn_understanding"]
        self.assertEqual(understanding["primary_intent"], "knowledge_question")
        self.assertIn("goal_discovery", understanding["secondary_intents"])
        self.assertEqual(understanding["topic"]["subject"], "python")
        self.assertTrue(understanding["learner_claims"])

    def test_agent_turn_uses_external_learning_material_when_enabled(self):
        application = self.server.RequestHandlerClass.application
        captured = {}
        project = self.create_project("完成 Java 面向对象成绩管理实训")["project"]

        class FakeMaterialKnowledge:
            enabled = True
            status = "ready"

            @staticmethod
            def query(message):
                captured["message"] = message
                return {
                    "status": "ok",
                    "resources": "封装用于隐藏内部实现并约束访问边界。",
                    "return_memory": "这段外部记忆不能写入画像",
                }

        original = application.material_knowledge
        application.material_knowledge = FakeMaterialKnowledge()
        try:
            result = self.request_json(
                "POST",
                "/api/agent/turn",
                {
                    "student_id": self.student_id,
                    "session_id": "material-plugin-test",
                    "project_id": project["project_id"],
                    "message": "请根据学习资料说明 Java 封装的作用",
                    "use_learning_materials": True,
                    "allow_web_search": False,
                },
            )
        finally:
            application.material_knowledge = original

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["action"], "reply")
        self.assertEqual(result["answer_mode"], "external_learning_material")
        self.assertEqual(result["source_status"], "unverified_external_material")
        self.assertEqual(result["sources"][0]["source_type"], "external_material")
        self.assertIn("Java 封装", captured["message"])
        self.assertNotIn("外部记忆", result["answer"])

    def test_remote_chat_workflow_receives_learning_material_flag(self):
        application = self.server.RequestHandlerClass.application
        gateway = application.gateway
        original_settings = gateway.settings
        original_invoke = gateway.invoke_chat_workflow
        captured = {}
        gateway.settings = Settings(
            **{
                **original_settings.__dict__,
                "xingchen_mode": "remote",
                "chat_flow_id": "chat-flow-id",
                "api_key": "test-key",
                "api_secret": "test-secret",
                "api_url": "https://example.invalid/workflow",
            }
        )

        def invoke_chat(payload):
            captured.update(payload)
            return {"status": "ok", "answer": "基于学习资料的回答。"}

        gateway.invoke_chat_workflow = invoke_chat
        try:
            result = self.request_json(
                "POST",
                "/api/chat",
                {
                    "student_id": self.student_id,
                    "session_id": "remote-material-workflow",
                    "message": "请根据学习资料说明 Java 封装的作用",
                    "use_learning_materials": True,
                    "allow_web_search": False,
                },
            )
        finally:
            gateway.invoke_chat_workflow = original_invoke
            gateway.settings = original_settings

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["answer"], "基于学习资料的回答。")
        self.assertTrue(captured["use_learning_materials"])

    def test_agent_turn_clarifies_unknown_intent(self):
        result = self.agent_turn("随便来点")
        self.assertEqual(result["status"], "needs_clarification")
        self.assertEqual(result["action"], "ask_clarification")
        self.assertTrue(result["clarify_options"])

    def test_agent_turn_clarifies_broad_learning_goal(self):
        result = self.agent_turn("随便学点什么")
        self.assertEqual(result["status"], "needs_clarification")
        self.assertEqual(result["action"], "ask_clarification")
        self.assertIn("具体学什么", result["message"])

    def test_agent_turn_discloses_unavailable_external_action(self):
        result = self.agent_turn("帮我订机票去北京")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["intent"], "general_assistant")
        self.assertEqual(result["action"], "reply")
        self.assertEqual(result["answer_mode"], "tool_unavailable")
        self.assertIn("没有接入机票预订工具", result["answer"])

    def test_agent_turn_starts_assessment_in_current_project(self):
        project = self.agent_turn("备战世界职业院校技能大赛")["project"]
        blocked = self.agent_turn("开始能力测评", project["project_id"])
        self.assertEqual(blocked["action"], "collect_learner_profile")
        self.request_json(
            "POST",
            f"/api/projects/{project['project_id']}/assessments/intake",
            {
                "student_id": self.student_id,
                "self_reported_level": "experienced",
                "claimed_knowledge_point_ids": [],
            },
        )
        result = self.agent_turn("开始能力测评", project["project_id"])
        self.assertEqual(result["action"], "show_assessment")
        self.assertEqual(result["artifact"]["type"], "assessment")
        self.assertGreaterEqual(result["artifact"]["data"]["total"], 1)

    def test_agent_turn_opens_named_lesson(self):
        project = self.agent_turn("我想系统掌握 Java 面向对象编程")["project"]
        self.set_zero_foundation_intake(project["project_id"])
        result = self.agent_turn("开始学习类的定义与对象创建", project["project_id"])
        self.assertEqual(result["action"], "open_lesson")
        self.assertEqual(result["artifact"]["type"], "lesson")
        self.assertEqual(result["artifact"]["data"]["status"], "ok")
        self.assertTrue(result["artifact"]["data"]["content_blocks"])

    def test_project_lesson_falls_back_when_workflow_fails(self):
        # 讲解本地化后：模拟配置了星火但生成失败，引擎应回落确定性模板。
        application = self.server.RequestHandlerClass.application
        from types import SimpleNamespace as _SimpleNamespace

        original_spark = application.local_engine.spark
        original_llm_text = application.local_engine._llm_text
        original_retriever = application.knowledge_evidence_retriever
        application.local_engine.spark = _SimpleNamespace(configured=True)
        # 禁用联网检索，避免 patch 星火可用后触发真实 Bing 请求
        application.knowledge_evidence_retriever = None

        def fail_llm(messages, **kwargs):
            from backend.spark_client import SparkError
            raise SparkError("timeout", "测试：星火请求超时")

        application.local_engine._llm_text = fail_llm
        try:
            project = self.agent_turn("我想系统掌握 Java 面向对象编程")["project"]
            self.set_zero_foundation_intake(project["project_id"])
            detail = self.request_json(
                "GET", f"/api/projects/{project['project_id']}?student_id={self.student_id}"
            )["project"]
            target = detail["learning_path"]["items"][0]
            result = self.request_json(
                "POST",
                f"/api/projects/{project['project_id']}/explain",
                {
                    "student_id": self.student_id,
                    "knowledge_point_id": target["knowledge_point_id"],
                },
            )
        finally:
            application.local_engine.spark = original_spark
            application.local_engine._llm_text = original_llm_text
            application.knowledge_evidence_retriever = original_retriever
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["fallback_used"])
        self.assertEqual(result["source_status"], "verified_local_fallback")
        self.assertTrue(result["content_blocks"])
        self.assertTrue(result["content_version"])
        self.assertTrue(
            all(block.get("block_id") for block in result["content_blocks"])
        )
        self.assertTrue(
            all("markdown" in block for block in result["content_blocks"])
        )

    def test_agent_turn_understands_learning_time_and_self_report(self):
        project = self.agent_turn("我想系统掌握 Java 面向对象编程")["project"]
        result = self.agent_turn(
            "我每天只能学半小时，而且类和对象已经会了", project["project_id"]
        )
        self.assertEqual(result["intent"], "update_learning_context")
        self.assertEqual(result["action"], "context_updated")
        self.assertEqual(result["context_update"]["learner_preferences"]["daily_minutes"], 30)
        self.assertEqual(result["context_update"]["verification_state"], "unverified")
        detail = self.request_json(
            "GET", f"/api/projects/{project['project_id']}?student_id={self.student_id}"
        )["project"]
        self.assertEqual(detail["learner_preferences"]["daily_minutes"], 30)
        self.assertEqual(detail["learning_path"]["items"], [])
        self.assertTrue(detail["learner_self_reports"])

    def test_project_messages_are_persisted_and_isolated(self):
        first = self.agent_turn("我想系统掌握 Java 面向对象编程")["project"]
        second = self.agent_turn("六周内掌握 Python 数据分析并完成销售数据看板")["project"]
        self.agent_turn("我每天可以学习 30 分钟", first["project_id"])
        self.agent_turn("我喜欢先看案例，再解释原理", second["project_id"])
        first_messages = self.request_json(
            "GET",
            f"/api/projects/{first['project_id']}/messages?student_id={self.student_id}",
        )["messages"]
        second_messages = self.request_json(
            "GET",
            f"/api/projects/{second['project_id']}/messages?student_id={self.student_id}",
        )["messages"]
        first_text = " ".join(item["content"] for item in first_messages)
        second_text = " ".join(item["content"] for item in second_messages)
        self.assertIn("30 分钟", first_text)
        self.assertNotIn("先看案例", first_text)
        self.assertIn("先看案例", second_text)
        self.assertNotIn("30 分钟", second_text)

    def test_project_notes_are_scoped_editable_and_deletable(self):
        first = self.agent_turn("我想系统掌握 Java 面向对象编程")["project"]
        second = self.agent_turn("六周内掌握 Python 数据分析并完成销售数据看板")["project"]
        self.set_zero_foundation_intake(first["project_id"])
        detail = self.request_json(
            "GET", f"/api/projects/{first['project_id']}?student_id={self.student_id}"
        )["project"]
        target = detail["learning_path"]["items"][0]
        lesson = self.request_json(
            "POST",
            f"/api/projects/{first['project_id']}/explain",
            {
                "student_id": self.student_id,
                "knowledge_point_id": target["knowledge_point_id"],
            },
        )
        block = lesson["content_blocks"][0]
        created = self.request_json(
            "POST",
            f"/api/projects/{first['project_id']}/notes",
            {
                "student_id": self.student_id,
                "knowledge_point_id": target["knowledge_point_id"],
                "knowledge_point_name": target["knowledge_point_name"],
                "content_version": lesson["content_version"],
                "block_id": block["block_id"],
                "block_title": block.get("title") or "讲解内容",
                "quote_text": "稳定锚点",
                "quote_prefix": "前文",
                "quote_suffix": "后文",
                "note_markdown": "**第一条**笔记",
            },
        )["note"]
        listed = self.request_json(
            "GET",
            f"/api/projects/{first['project_id']}/notes?student_id={self.student_id}"
            f"&knowledge_point_id={target['knowledge_point_id']}",
        )["notes"]
        self.assertEqual([item["note_id"] for item in listed], [created["note_id"]])
        self.assertEqual(listed[0]["content_version"], lesson["content_version"])
        self.assertEqual(
            self.request_json(
                "GET",
                f"/api/projects/{second['project_id']}/notes?student_id={self.student_id}",
            )["notes"],
            [],
        )

        updated_payload = {
            **created,
            "student_id": self.student_id,
            "note_markdown": "更新后的笔记",
        }
        updated = self.request_json(
            "POST",
            f"/api/projects/{first['project_id']}/notes",
            updated_payload,
        )["note"]
        self.assertEqual(updated["note_id"], created["note_id"])
        self.assertEqual(updated["note_markdown"], "更新后的笔记")
        document_markdown = "# 章节覆盖稿\n\n" + "正文" * 4_500
        document_override = self.request_json(
            "POST",
            f"/api/projects/{first['project_id']}/notes",
            {
                **created,
                "student_id": self.student_id,
                "note_id": "",
                "block_id": "LESSON-DOCUMENT",
                "block_title": "章节 Markdown 覆盖稿",
                "note_markdown": document_markdown,
                "tags": ["lesson_document_override"],
            },
        )["note"]
        self.assertEqual(document_override["note_markdown"], document_markdown)
        self.assertIn("lesson_document_override", document_override["tags"])
        retried_override = self.request_json(
            "POST",
            f"/api/projects/{first['project_id']}/notes",
            {
                **document_override,
                "student_id": self.student_id,
                "note_id": "",
                "note_markdown": "网络恢复后的章节覆盖稿",
            },
        )["note"]
        self.assertEqual(retried_override["note_id"], document_override["note_id"])
        self.assertEqual(
            retried_override["note_markdown"], "网络恢复后的章节覆盖稿"
        )
        with self.assertRaises(Exception):
            self.request_json(
                "POST",
                f"/api/projects/{second['project_id']}/notes",
                {**updated_payload, "note_markdown": "跨项目篡改"},
            )
        deleted = self.request_json(
            "POST",
            f"/api/projects/{first['project_id']}/notes/delete",
            {"student_id": self.student_id, "note_id": created["note_id"]},
        )
        self.assertEqual(deleted["deleted_note_id"], created["note_id"])
        self.request_json(
            "POST",
            f"/api/projects/{first['project_id']}/notes/delete",
            {"student_id": self.student_id, "note_id": document_override["note_id"]},
        )
        self.assertEqual(
            self.request_json(
                "GET",
                f"/api/projects/{first['project_id']}/notes?student_id={self.student_id}",
            )["notes"],
            [],
        )

    def test_project_delete_checks_owner_and_removes_project_scoped_data(self):
        first = self.agent_turn("我想系统掌握 Java 面向对象编程")["project"]
        second = self.agent_turn("六周内掌握 Python 数据分析并完成销售数据看板")["project"]
        project_id = first["project_id"]
        self.set_zero_foundation_intake(project_id)
        detail = self.request_json(
            "GET", f"/api/projects/{project_id}?student_id={self.student_id}"
        )["project"]
        target = detail["learning_path"]["items"][0]
        lesson = self.request_json(
            "POST",
            f"/api/projects/{project_id}/explain",
            {
                "student_id": self.student_id,
                "knowledge_point_id": target["knowledge_point_id"],
            },
        )
        self.request_json(
            "POST",
            f"/api/projects/{project_id}/notes",
            {
                "student_id": self.student_id,
                "knowledge_point_id": target["knowledge_point_id"],
                "knowledge_point_name": target["knowledge_point_name"],
                "content_version": lesson["content_version"],
                "block_id": lesson["content_blocks"][0]["block_id"],
                "block_title": "讲解内容",
                "note_markdown": "删除项目时应一并删除",
            },
        )
        self.request_json(
            "POST",
            f"/api/projects/{project_id}/assessments/intake",
            {
                "student_id": self.student_id,
                "self_reported_level": "uncertain",
                "claimed_knowledge_point_ids": [],
            },
        )
        assessment = self.request_json(
            "POST",
            f"/api/projects/{project_id}/assessments/start",
            {
                "student_id": self.student_id,
                "assessment_type": "initial_diagnostic",
            },
        )
        self.request_json(
            "POST",
            f"/api/projects/{project_id}/assessments/answer",
            {
                "student_id": self.student_id,
                "assessment_id": assessment["assessment_id"],
                "selected": "a",
            },
        )
        discovery = self.request_json(
            "POST",
            "/api/discovery/sessions",
            {
                "learner_id": self.student_id,
                "project_id": project_id,
                "goal_candidate": first["goal_name"],
            },
        )
        self.assertTrue(discovery["session"]["session_id"])

        with self.assertRaises(Exception):
            self.request_json(
                "POST",
                f"/api/projects/{project_id}/delete",
                {"student_id": "STU-OTHER"},
            )

        deleted = self.request_json(
            "POST",
            f"/api/projects/{project_id}/delete",
            {"student_id": self.student_id},
        )
        self.assertEqual(deleted["deleted_project_id"], project_id)
        self.assertGreaterEqual(deleted["deleted_records"]["project_messages"], 1)
        self.assertEqual(deleted["deleted_records"]["project_notes"], 1)
        self.assertEqual(deleted["deleted_records"]["assessment_runs"], 1)
        self.assertGreaterEqual(deleted["deleted_records"]["assessment_evidence"], 1)
        self.assertEqual(deleted["deleted_records"]["ld_discovery_sessions"], 1)

        listed = self.request_json(
            "GET", f"/api/projects?student_id={self.student_id}"
        )["projects"]
        self.assertEqual([item["project_id"] for item in listed], [second["project_id"]])
        with self.assertRaises(Exception):
            self.request_json(
                "GET", f"/api/projects/{project_id}?student_id={self.student_id}"
            )

    def test_selected_lesson_excerpt_drives_answer_and_message_context(self):
        project = self.agent_turn("我想系统掌握 Java 面向对象编程")["project"]
        self.set_zero_foundation_intake(project["project_id"])
        detail = self.request_json(
            "GET", f"/api/projects/{project['project_id']}?student_id={self.student_id}"
        )["project"]
        target = detail["learning_path"]["items"][1]
        selected_text = "对象的状态应该通过受控方法访问"
        result = self.request_json(
            "POST",
            "/api/agent/turn",
            {
                "student_id": self.student_id,
                "session_id": "selected-lesson-test",
                "project_id": project["project_id"],
                "message": "为什么要这样设计？",
                "workspace_context": {"view": "blank"},
                "selection_context": {
                    "selected_text": selected_text,
                    "block_id": "BLOCK-TEST",
                    "block_title": "核心概念",
                    "knowledge_point_id": target["knowledge_point_id"],
                    "knowledge_point_name": target["knowledge_point_name"],
                },
            },
        )
        self.assertEqual(result["action"], "reply")
        self.assertIn(selected_text, result["answer"])
        messages = self.request_json(
            "GET",
            f"/api/projects/{project['project_id']}/messages?student_id={self.student_id}",
        )["messages"]
        user_message = next(
            item for item in reversed(messages) if item["role"] == "user"
        )
        self.assertEqual(
            user_message["context"]["selection_context"]["selected_text"],
            selected_text,
        )

    def test_agent_turn_records_preferred_topic_without_skipping_prerequisites(self):
        project = self.agent_turn("六周内掌握 Python 数据分析并完成销售数据看板")["project"]
        result = self.agent_turn("我想先学 Pandas", project["project_id"])
        self.assertEqual(result["action"], "context_updated")
        self.assertIn("优先学习", result["message"])
        self.assertIn("前置知识", result["message"])
        self.assertEqual(result["context_update"]["verification_state"], "unverified")

    def test_candidate_project_question_never_uses_java_knowledge(self):
        project = self.agent_turn("六周内掌握 Python 数据分析并完成销售数据看板")["project"]
        result = self.agent_turn("Pandas 怎么清洗缺失值？", project["project_id"])
        self.assertEqual(result["intent"], "knowledge_question")
        self.assertEqual(result["action"], "reply")
        self.assertIn("还没有绑定", result["answer"])
        self.assertNotIn("Java", result["answer"])

    def test_chat_prefers_active_lesson_knowledge_context(self):
        project = self.agent_turn("我想系统掌握 Java 面向对象编程")["project"]
        self.set_zero_foundation_intake(project["project_id"])
        detail = self.request_json(
            "GET", f"/api/projects/{project['project_id']}?student_id={self.student_id}"
        )["project"]
        target = detail["learning_path"]["items"][1]
        result = self.request_json(
            "POST",
            "/api/agent/turn",
            {
                "student_id": self.student_id,
                "session_id": "agent-test",
                "project_id": project["project_id"],
                "message": "为什么要这么设计？",
                "workspace_context": {
                    "view": "lesson",
                    "project_id": project["project_id"],
                    "knowledge_point_id": target["knowledge_point_id"],
                    "knowledge_point_name": target["knowledge_point_name"],
                },
            },
        )
        self.assertEqual(result["action"], "reply")
        self.assertTrue(result["answer"])
        self.assertTrue(result["sources"])

    def test_plan_question_persists_stable_step_context_with_project_message(self):
        project = self.agent_turn("我想系统掌握 Java 面向对象编程")["project"]
        self.set_zero_foundation_intake(project["project_id"])
        plan = self.request_json(
            "GET", f"/api/projects/{project['project_id']}/plan?student_id={self.student_id}"
        )["learning_plan"]
        stage = next(item for item in plan["stages"] if item["steps"])
        step = stage["steps"][0]
        self.request_json(
            "POST",
            "/api/agent/turn",
            {
                "student_id": self.student_id,
                "session_id": "plan-question-test",
                "project_id": project["project_id"],
                "message": f"我想就“{step['knowledge_point_name']}”提问：该从哪里开始？",
                "workspace_context": {
                    "view": "learning_plan",
                    "project_id": project["project_id"],
                    "knowledge_point_id": step["knowledge_point_id"],
                    "knowledge_point_name": step["knowledge_point_name"],
                    "plan_step_id": step["step_id"],
                    "plan_stage_id": stage["stage_id"],
                },
            },
        )
        messages = self.request_json(
            "GET",
            f"/api/projects/{project['project_id']}/messages?student_id={self.student_id}",
        )["messages"]
        user_message = next(
            item for item in reversed(messages) if item["role"] == "user"
        )
        context = user_message["context"]["workspace_context"]
        self.assertEqual(context["plan_step_id"], step["step_id"])
        self.assertEqual(context["plan_stage_id"], stage["stage_id"])
        self.assertEqual(context["knowledge_point_id"], step["knowledge_point_id"])

    # ---------- 生成式题库 ----------

    def test_generated_quiz_goes_through_validation_and_persistence(self):
        """mock 出题走"生成→校验→入库"链路：provider=mock_bank（如实标注），题库可查。"""
        created = self.create_project("备战世界职业院校技能大赛")
        project_id = created["project"]["project_id"]
        started = self.request_json(
            "POST",
            f"/api/projects/{project_id}/diagnosis/start",
            {"student_id": self.student_id},
        )
        self.assertEqual(started["status"], "ok")
        self.assertEqual(started["provider"], "mock_bank")
        self.assertGreaterEqual(len(started["questions"]), 1)
        # 生成的题已入库（幂等写入，可复用）
        application = self.server.RequestHandlerClass.application
        persisted = application.domain.recent_generated_questions(limit=50)
        self.assertGreaterEqual(len(persisted), len(started["questions"]))
        persisted_ids = {q["question_id"] for q in persisted}
        for question in started["questions"]:
            self.assertIn(question["question_id"], persisted_ids)

    def test_quiz_validation_filters_invalid_questions(self):
        """校验器：答案不在选项 / 选项不足 / 缺字段的生成题被丢弃。"""
        application = self.server.RequestHandlerClass.application
        questions = [
            {"question_id": "Q-OK-1", "knowledge_point_id": "KN_JAVA_CLASS",
             "title": "合法题", "options": {"a": "1", "b": "2", "c": "3"},
             "answer": "b", "explanation": "解析", "difficulty": 2},
            {"question_id": "Q-BAD-1", "knowledge_point_id": "KN_JAVA_CLASS",
             "title": "答案不在选项", "options": {"a": "1", "b": "2", "c": "3"},
             "answer": "z", "explanation": "解析", "difficulty": 1},
            {"question_id": "Q-BAD-2", "knowledge_point_id": "KN_JAVA_CLASS",
             "title": "选项不足", "options": {"a": "1", "b": "2"},
             "answer": "a", "explanation": "解析", "difficulty": 1},
            {"question_id": "Q-BAD-3", "knowledge_point_id": "",
             "title": "无知识点绑定", "options": {"a": "1", "b": "2", "c": "3"},
             "answer": "a", "explanation": "解析", "difficulty": 1},
            "not-a-dict",
        ]
        valid, dropped = application._validate_quiz_questions(questions)
        self.assertEqual(len(valid), 1)
        self.assertEqual(dropped, 4)
        self.assertEqual(valid[0]["question_id"], "Q-OK-1")

    def test_quiz_generation_falls_back_to_local_bank(self):
        """工作流出题异常 → 自动回落本地取样，诊断流程不中断。"""
        from unittest.mock import patch

        application = self.server.RequestHandlerClass.application
        created = self.create_project("备战世界职业院校技能大赛")
        project_id = created["project"]["project_id"]
        with patch.object(
            application.gateway, "invoke_quiz_workflow", side_effect=RuntimeError("platform down")
        ):
            started = self.request_json(
                "POST",
                f"/api/projects/{project_id}/diagnosis/start",
                {"student_id": self.student_id},
            )
        self.assertEqual(started["status"], "ok")
        self.assertEqual(started["provider"], "local_fallback")
        self.assertGreaterEqual(len(started["questions"]), 1)


    def test_learning_map_projection_is_deterministic_and_read_only(self):
        """学习地图：只读投影，未评估知识点保持 NULL，推荐排序稳定可复现。"""
        project = self.create_project("我想系统掌握 Java 面向对象编程")["project"]
        project_id = project["project_id"]
        first = self.request_json(
            "GET", f"/api/projects/{project_id}/learning-map?student_id={self.student_id}"
        )
        second = self.request_json(
            "GET", f"/api/projects/{project_id}/learning-map?student_id={self.student_id}"
        )
        self.assertEqual(first["status"], "ok")
        self.assertEqual(first["project_id"], project_id)
        # 同一状态两次投影结果完全一致（确定性，不使用随机/哈希排序）
        self.assertEqual(first, second)
        # 字段齐全
        for key in (
            "nodes",
            "edges",
            "current_recommended_kc",
            "recommended_candidates",
            "locked_nodes",
            "active_path",
        ):
            self.assertIn(key, first)
        self.assertGreaterEqual(len(first["nodes"]), 3)
        # 未评估知识点 mastery 必须是 None，绝不强制为 0
        for node in first["nodes"]:
            if node["status"] == "unknown":
                self.assertIsNone(node["mastery"])
        # 主推荐最多一个；候选 1~3 个，且与主推荐不重复
        recommended_ids = {
            node["id"]
            for node in first["nodes"]
            if node["status"] in {"weak", "learning", "unknown"}
        }
        if first["current_recommended_kc"]:
            self.assertIn(first["current_recommended_kc"], recommended_ids)
            self.assertNotIn(
                first["current_recommended_kc"], first["recommended_candidates"]
            )
        self.assertLessEqual(len(first["recommended_candidates"]), 3)
        # 锁定的节点不会被推荐
        for locked_id in first["locked_nodes"]:
            self.assertNotEqual(first["current_recommended_kc"], locked_id)
            self.assertNotIn(locked_id, first["recommended_candidates"])
        # edges 必须引用已存在节点
        known_ids = {node["id"] for node in first["nodes"]}
        for edge in first["edges"]:
            self.assertIn(edge["source"], known_ids)
            self.assertIn(edge["target"], known_ids)
        # 只读性：学习地图不改变底层项目状态
        detail_before = self.request_json(
            "GET", f"/api/projects/{project_id}?student_id={self.student_id}"
        )["project"]
        state_items = [
            item["knowledge_point_id"]
            for item in detail_before["learning_path"]["items"]
        ]
        self.assertEqual(
            sorted(item["id"] for item in first["nodes"]), sorted(state_items)
        )

    def test_plan_steps_carry_objective_prereq_time_and_reason_fields(self):
        """阶段3：计划步骤增量字段齐全且确定；无学习周期时不伪造时间预算。"""
        project = self.create_project("我想系统掌握 Java 面向对象编程")["project"]
        project_id = project["project_id"]
        plan = self.request_json(
            "GET", f"/api/projects/{project_id}/plan?student_id={self.student_id}"
        )["learning_plan"]
        steps = [
            step for stage in plan["stages"] for step in stage["steps"]
        ]
        self.assertGreaterEqual(len(steps), 3)
        for step in steps:
            for key in (
                "learning_objective",
                "prerequisites",
                "estimated_minutes",
                "difficulty",
                "recommended",
                "recommendation_reason",
                "source_event_ids",
            ):
                self.assertIn(key, step, f"缺少字段 {key}")
            self.assertIsInstance(step["prerequisites"], list)
            self.assertGreaterEqual(step["estimated_minutes"], 1)
            self.assertIn(step["difficulty"], (1, 2, 3))
        # 用户未提供学习周期/每日时长 → 不伪造时间预算
        self.assertIsNone(plan["time_budget"]["budget_minutes"])
        self.assertFalse(plan["time_budget"]["constraint_applied"])
        self.assertTrue(plan["time_budget"]["constraint_met"])
        # 确定性：同一状态两次请求结果一致
        again = self.request_json(
            "GET", f"/api/projects/{project_id}/plan?student_id={self.student_id}"
        )["learning_plan"]
        self.assertEqual(again, plan)

    def test_explain_carries_step_context_and_resolves_objective(self):
        """阶段6：讲解输入契约——/explain 携带 plan_step 与 learning_objective。

        前端从计划步骤发起时显式携带 step_id 与 learning_objective；未携带时
        后端按 knowledge_point_id 从当前学习计划确定性解析。
        """
        project = self.agent_turn("我想系统掌握 Java 面向对象编程")["project"]
        project_id = project["project_id"]
        self.set_zero_foundation_intake(project_id)
        plan = self.request_json(
            "GET", f"/api/projects/{project_id}/plan?student_id={self.student_id}"
        )["learning_plan"]
        steps = [
            step for stage in plan["stages"] for step in stage["steps"]
        ]
        step = steps[0]
        detail = self.request_json(
            "GET", f"/api/projects/{project_id}?student_id={self.student_id}"
        )["project"]
        target = detail["learning_path"]["items"][0]
        # 显式携带计划步骤上下文
        lesson = self.request_json(
            "POST",
            f"/api/projects/{project_id}/explain",
            {
                "student_id": self.student_id,
                "knowledge_point_id": target["knowledge_point_id"],
                "step_id": step["step_id"],
                "learning_objective": step["learning_objective"],
            },
        )
        self.assertIn(lesson["status"], {"ok", "ready"})
        self.assertTrue(lesson["content_blocks"])
        self.assertEqual(lesson["plan_step"]["step_id"], step["step_id"])
        self.assertEqual(lesson["learning_objective"], step["learning_objective"])
        # 仅 knowledge_point_id 时后端确定性解析计划步骤
        auto = self.request_json(
            "POST",
            f"/api/projects/{project_id}/explain",
            {
                "student_id": self.student_id,
                "knowledge_point_id": target["knowledge_point_id"],
            },
        )
        self.assertIn(auto["status"], {"ok", "ready"})
        self.assertEqual(auto["plan_step"]["step_id"], step["step_id"])
        self.assertEqual(auto["learning_objective"], step["learning_objective"])

    def test_lesson_document_excludes_route_explanation_blocks(self):
        """阶段6：讲解正文不再输出学习路线说明，只保留可溯源正文区块。

        路线依据由学习地图与 PlanBrief 承担；正文每个区块保留来源可追溯。
        """
        project = self.agent_turn("我想系统掌握 Java 面向对象编程")["project"]
        project_id = project["project_id"]
        self.set_zero_foundation_intake(project_id)
        detail = self.request_json(
            "GET", f"/api/projects/{project_id}?student_id={self.student_id}"
        )["project"]
        target = detail["learning_path"]["items"][0]
        lesson = self.request_json(
            "POST",
            f"/api/projects/{project_id}/explain",
            {
                "student_id": self.student_id,
                "knowledge_point_id": target["knowledge_point_id"],
            },
        )
        self.assertIn(lesson["status"], {"ok", "ready"})
        blocks = lesson["content_blocks"]
        self.assertGreaterEqual(len(blocks), 1)
        route_types = {
            "connection", "weakness_connection", "route", "roadmap",
            "path_explanation", "learning_route", "sequence",
        }
        titles = []
        for block in blocks:
            block_type = str(block.get("type") or "").strip().lower()
            title = str(block.get("title") or "")
            titles.append(title)
            self.assertNotIn(block_type, route_types)
            self.assertNotIn("为什么先学", title)
            # 正文区块要么有可溯源来源，要么有实质内容，不出现空占位
            self.assertTrue(
                str(block.get("source") or "").strip()
                or str(block.get("content") or block.get("markdown") or "").strip()
            )
        self.assertNotIn("为什么先学这一点", "".join(titles))
        # 确定性：同一讲解两次读取内容一致
        again = self.request_json(
            "POST",
            f"/api/projects/{project_id}/explain",
            {
                "student_id": self.student_id,
                "knowledge_point_id": target["knowledge_point_id"],
            },
        )
        self.assertEqual(again["content_blocks"], blocks)

    def test_plan_brief_is_deterministic_and_evidence_based(self):
        """阶段4：PlanBrief 确定性生成，未评估知识点不进入 skill_gaps。"""
        project = self.create_project("我想系统掌握 Java 面向对象编程")["project"]
        project_id = project["project_id"]
        first = self.request_json(
            "GET", f"/api/projects/{project_id}/plan-brief?student_id={self.student_id}"
        )
        self.assertEqual(first["status"], "ok")
        for key in (
            "goal",
            "target_outcome",
            "known_skills",
            "skill_gaps",
            "unassessed_skills",
            "critical_path",
            "difficulty_hotspots",
            "adaptation_rules",
            "stage_overview",
        ):
            self.assertIn(key, first)
        # 未评估 ≠ 0：新项目所有知识点都在 unassessed，绝不进 skill_gaps
        self.assertEqual(first["known_skills"], [])
        self.assertEqual(first["skill_gaps"], [])
        self.assertGreaterEqual(len(first["unassessed_skills"]), 3)
        # 三阶段概览齐全
        self.assertEqual(len(first["stage_overview"]), 3)
        self.assertEqual(
            [item["stage_id"] for item in first["stage_overview"]],
            ["foundation", "core", "application"],
        )
        # 关键路径来自真实依赖 DAG（类→封装→继承→多态 是最长链）
        self.assertEqual(
            first["critical_path"],
            ["类的定义与对象创建", "封装与访问控制", "继承与方法重写", "多态与接口"],
        )
        # 用户可读列表不得包含内部 ID / 原始掌握度
        for name in first["known_skills"] + first["skill_gaps"] + first["unassessed_skills"]:
            self.assertNotIn("KN_", name)
        # 确定性：同一状态两次请求一致
        second = self.request_json(
            "GET", f"/api/projects/{project_id}/plan-brief?student_id={self.student_id}"
        )
        self.assertEqual(second, first)
        self.assertTrue(first["adaptation_rules"])

    def test_plan_time_budget_scales_when_duration_and_daily_provided(self):
        """时间约束：总预计分钟 <= duration_days × daily_minutes。"""
        application = self.server.RequestHandlerClass.application
        plan = {
            "stages": [
                {
                    "stage_id": "foundation",
                    "steps": [
                        {"step_id": "S1", "estimated_minutes": 60},
                        {"step_id": "S2", "estimated_minutes": 60},
                    ],
                },
                {
                    "stage_id": "core",
                    "steps": [{"step_id": "S3", "estimated_minutes": 60}],
                },
            ]
        }
        # 无预算 → 不缩放、不伪造
        result = application._apply_plan_time_budget(plan, {"duration_days": None, "daily_minutes": None})
        self.assertIsNone(result["budget_minutes"])
        self.assertEqual(result["total_estimated_minutes"], 180)
        # 有预算且总时长超出 → 等比缩放并保证不超过预算
        result = application._apply_plan_time_budget(plan, {"duration_days": 2, "daily_minutes": 30})
        self.assertEqual(result["budget_minutes"], 60)
        self.assertTrue(result["constraint_applied"])
        self.assertTrue(result["constraint_met"])
        self.assertLessEqual(result["total_estimated_minutes"], 60)
        minutes = [
            step["estimated_minutes"] for stage in plan["stages"] for step in stage["steps"]
        ]
        # 等比缩放后总分钟数压到预算内，且每步至少 1 分钟
        self.assertEqual(sum(minutes), 60)
        self.assertTrue(all(minute >= 1 for minute in minutes))

    def test_plan_includes_budget_safe_daily_execution_schedule(self):
        project = self.create_project(
            "我想在7天内系统掌握 Java 面向对象编程，每天学习30分钟"
        )["project"]
        plan = self.request_json(
            "GET",
            f"/api/projects/{project['project_id']}/plan?student_id={self.student_id}",
        )["learning_plan"]

        schedule = plan["daily_schedule"]
        self.assertEqual(plan["schema_version"], 2)
        self.assertEqual(len(schedule), 7)
        self.assertTrue(all(day["planned_minutes"] <= 30 for day in schedule))
        self.assertEqual(
            sum(task["minutes"] for day in schedule for task in day["tasks"]),
            plan["time_budget"]["total_estimated_minutes"],
        )
        self.assertTrue(plan["target_knowledge_point_ids"])

    def test_manual_plan_regeneration_switches_version_and_invalidates_lessons(self):
        """手动重新生成：新版本校验后切换，章节缓存失效但掌握度不变。"""
        project = self.create_project("我想系统掌握 Java 面向对象编程")["project"]
        project_id = project["project_id"]
        initial = self.request_json(
            "GET", f"/api/projects/{project_id}/plan?student_id={self.student_id}"
        )["learning_plan"]
        first_step = initial["stages"][0]["steps"][0]
        application = self.server.RequestHandlerClass.application
        application.store.set_project_lesson_status(
            project_id,
            self.student_id,
            first_step["knowledge_point_id"],
            "ready",
            lesson={"status": "ok", "content_blocks": [{"type": "concept"}]},
        )
        mastery_before = {
            item["knowledge_point_id"]: item["mastery"]
            for item in application.store.get_project(project_id)["state"]["learning_path"]["items"]
        }

        from unittest.mock import patch

        with patch.object(application, "_queue_project_lesson_generation"):
            regenerated = self.request_json(
                "POST",
                f"/api/projects/{project_id}/plan/regenerate",
                {"student_id": self.student_id},
            )["learning_plan"]

        self.assertEqual(
            int(regenerated["plan_version"]), int(initial["plan_version"]) + 1
        )
        stored = application.store.get_project(project_id)["state"]
        self.assertEqual(stored["learning_plan"]["plan_version"], regenerated["plan_version"])
        self.assertEqual(len(stored["learning_plan_history"]), 1)
        self.assertEqual(
            stored["learning_plan_history"][0]["plan_version"],
            initial["plan_version"],
        )
        cached = application.store.get_project_lesson(
            project_id, self.student_id, first_step["knowledge_point_id"]
        )
        self.assertEqual(cached["status"], "queued")
        self.assertEqual(cached["lesson"], {})
        mastery_after = {
            item["knowledge_point_id"]: item["mastery"]
            for item in application.store.get_project(project_id)["state"]["learning_path"]["items"]
        }
        self.assertEqual(mastery_after, mastery_before)

    def test_invalid_plan_candidate_keeps_current_version(self):
        """候选计划校验失败时不能覆盖现有 current plan。"""
        project = self.create_project("我想系统掌握 Java 面向对象编程")["project"]
        project_id = project["project_id"]
        application = self.server.RequestHandlerClass.application
        before = application.store.get_project(project_id)["state"]["learning_plan"]

        from unittest.mock import patch

        with patch.object(application, "_build_project_learning_plan", return_value={"stages": []}):
            with self.assertRaises(ApiError) as raised:
                application.regenerate_project_learning_plan(
                    {"student_id": self.student_id, "project_id": project_id}
                )
        self.assertEqual(raised.exception.code, "PLAN_REGENERATION_REJECTED")
        after = application.store.get_project(project_id)["state"]["learning_plan"]
        self.assertEqual(after, before)

    def test_formal_assessment_switches_plan_version_from_evidence(self):
        """正式证据改变 PlanContext 后自动切换版本，计划完成状态不参与判定。"""
        project = self.create_project("我想系统掌握 Java 面向对象编程")["project"]
        project_id = project["project_id"]
        self.request_json(
            "POST",
            f"/api/projects/{project_id}/assessments/intake",
            {
                "student_id": self.student_id,
                "self_reported_level": "experienced",
                "claimed_knowledge_point_ids": [],
            },
        )
        before = self.request_json(
            "GET", f"/api/projects/{project_id}/plan?student_id={self.student_id}"
        )["learning_plan"]
        started = self.request_json(
            "POST",
            f"/api/projects/{project_id}/assessments/start",
            {
                "student_id": self.student_id,
                "assessment_type": "initial_diagnostic",
            },
        )
        application = self.server.RequestHandlerClass.application
        session = application.store.get_project(project_id)["state"]["assessment_session"]

        from unittest.mock import patch

        with patch.object(application, "_queue_project_lesson_generation"):
            for question in session["questions"]:
                final = self.request_json(
                    "POST",
                    f"/api/projects/{project_id}/assessments/answer",
                    {
                        "student_id": self.student_id,
                        "assessment_id": started["assessment_id"],
                        "answer": question["answer"],
                    },
                )
        self.assertTrue(final["summary"]["plan_regenerated"])
        after = application.store.get_project(project_id)["state"]["learning_plan"]
        self.assertEqual(int(after["plan_version"]), int(before["plan_version"]) + 1)
        self.assertNotEqual(after["context_hash"], before["context_hash"])
        self.assertTrue(after["context"]["known"])

    def test_learning_map_step_completion_keeps_mastery_none(self):
        """计划步骤完成只更新进度，不改变掌握度（地图仍显示未评估）。"""
        project = self.create_project("我想系统掌握 Java 面向对象编程")["project"]
        project_id = project["project_id"]
        plan = self.request_json(
            "GET", f"/api/projects/{project_id}/plan?student_id={self.student_id}"
        )["learning_plan"]
        first_step = plan["stages"][0]["steps"][0]
        self.request_json(
            "POST",
            f"/api/projects/{project_id}/plan/steps/{first_step['step_id']}",
            {"student_id": self.student_id, "status": "completed"},
        )
        map_data = self.request_json(
            "GET", f"/api/projects/{project_id}/learning-map?student_id={self.student_id}"
        )
        target = next(
            node
            for node in map_data["nodes"]
            if node["id"] == first_step["knowledge_point_id"]
        )
        # 没有正式测评证据前，完成讲解/计划步骤不得产生掌握度；
        # 节点状态仍是"进行中"（路径当前节点），mastery 保持 NULL。
        self.assertNotEqual(target["status"], "mastered")
        self.assertIsNone(target["mastery"])
        # 只有正式测评能产生掌握度，计划完成不会制造 source_event_ids
        self.assertEqual(target["source_event_ids"], [])

    def test_candidate_evidence_is_pending_verification_across_plan_views(self):
        """单次正式答对不是未评估，也不能被当成已掌握或薄弱。"""
        state = {
            "goal": {"goal_name": "Java 面向对象基础", "constraints": {}},
            "goal_knowledge_points": [
                {
                    "knowledge_point_id": "KN_JAVA_ENCAPSULATION",
                    "knowledge_point_name": "封装与访问控制",
                },
                {
                    "knowledge_point_id": "KN_JAVA_INHERITANCE",
                    "knowledge_point_name": "继承与方法重写",
                },
            ],
            "learning_path": {
                "items": [
                    {
                        "knowledge_point_id": "KN_JAVA_ENCAPSULATION",
                        "knowledge_point_name": "封装与访问控制",
                        "recommended_order": 1,
                        "mastery": 60,
                        "evidence_status": "candidate",
                        "source_event_ids": ["ASSESS-001"],
                    },
                    {
                        "knowledge_point_id": "KN_JAVA_INHERITANCE",
                        "knowledge_point_name": "继承与方法重写",
                        "recommended_order": 2,
                        "mastery": None,
                        "evidence_status": "unassessed",
                        "source_event_ids": [],
                        "prerequisites": ["KN_JAVA_ENCAPSULATION"],
                    },
                ]
            },
            "learning_plan": {"stages": []},
        }

        classified = classify_knowledge_points(state)
        self.assertEqual(
            [item["knowledge_point_id"] for item in classified["candidate"]],
            ["KN_JAVA_ENCAPSULATION"],
        )
        self.assertEqual(classified["known"], [])
        self.assertEqual(classified["review"], [])
        self.assertEqual(
            [item["knowledge_point_id"] for item in classified["unknown"]],
            ["KN_JAVA_INHERITANCE"],
        )

        learning_map = build_learning_map(state)
        candidate_node = next(
            node
            for node in learning_map["nodes"]
            if node["id"] == "KN_JAVA_ENCAPSULATION"
        )
        self.assertEqual(candidate_node["status"], "candidate")
        self.assertEqual(candidate_node["mastery"], 60)

        context = build_plan_context(state)
        self.assertEqual(context["candidate_points"], classified["candidate"])
        brief = build_plan_brief(state, context)
        self.assertEqual(brief["candidate_skills"], ["封装与访问控制"])
        self.assertEqual(brief["unassessed_skills"], ["继承与方法重写"])


if __name__ == "__main__":
    unittest.main()
