"""计算机信息技术专业群能力目录的回归测试。"""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path

from backend.data.capability_catalog import (
    FORMAL_SUPPORT_LEVEL,
    REFERENCE_SUPPORT_LEVEL,
    match_capability_pack,
    public_capability_catalog,
    reference_path_nodes,
)
from backend.server import LearningApplication, Settings, create_server


class CapabilityCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        settings = Settings(
            host="127.0.0.1",
            port=0,
            database_path=Path(self.temporary_directory.name) / "catalog-test.db",
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

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temporary_directory.cleanup()

    def request_json(
        self, method: str, path: str, payload: dict | None = None
    ) -> dict:
        import urllib.request

        body = None
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + path,
            data=body,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))

    def test_catalog_covers_all_declared_professionals(self) -> None:
        catalog = public_capability_catalog()
        programs = {
            item["professional_code"]: item
            for item in catalog["programs"]
        }
        self.assertEqual(
            set(programs), {"510201", "510202", "510203", "510206", "510209"}
        )
        software_packs = programs["510203"]["capability_packs"]
        self.assertTrue(
            any(pack["support_level"] == FORMAL_SUPPORT_LEVEL for pack in software_packs)
        )
        self.assertTrue(
            any(pack["support_level"] == REFERENCE_SUPPORT_LEVEL for pack in software_packs)
        )

    def test_reference_pack_nodes_have_valid_dependencies(self) -> None:
        pack = match_capability_pack("学习计算机网络技术，掌握交换路由和网络运维")
        self.assertIsNotNone(pack)
        self.assertEqual(pack["pack_id"], "PACK-COMPUTER-NETWORK")
        nodes = reference_path_nodes(
            pack,
            "学习计算机网络技术，掌握交换路由和网络运维",
        )
        validated = LearningApplication._validate_candidate_nodes(
            nodes,
            "学习计算机网络技术，掌握交换路由和网络运维",
            ["计算机网络技术"],
            pack["matched_keywords"],
        )
        self.assertEqual(validated[0]["node_key"], "network-foundation")
        self.assertEqual(validated[-1]["node_key"], "network-project")
        self.assertIn("network-automation", validated[-1]["prerequisites"])

    def test_each_reference_professional_has_a_curated_path(self) -> None:
        cases = (
            ("我想学习软件技术的前端开发和软件测试", "PACK-SOFTWARE-ENGINEERING"),
            ("我想学习计算机应用技术和系统维护", "PACK-COMPUTER-APPLICATION"),
            ("我想学习计算机网络技术和网络运维", "PACK-COMPUTER-NETWORK"),
            ("我想学习大数据技术，掌握 Spark 数据工程", "PACK-BIG-DATA"),
            ("我想学习人工智能技术应用，先学习机器学习", "PACK-AI-APPLICATION"),
        )
        for goal_name, expected_pack_id in cases:
            with self.subTest(goal_name=goal_name):
                pack = match_capability_pack(goal_name)
                self.assertIsNotNone(pack)
                self.assertEqual(pack["pack_id"], expected_pack_id)
                nodes = reference_path_nodes(pack, goal_name)
                validated = LearningApplication._validate_candidate_nodes(
                    nodes,
                    goal_name,
                    [goal_name],
                    pack["matched_keywords"],
                )
                self.assertGreaterEqual(len(validated), 7)
                self.assertTrue(any(item["prerequisites"] for item in validated[1:]))

    def test_catalog_api_agent_and_reference_project_are_consistent(self) -> None:
        catalog = self.request_json("GET", "/api/capability-catalog")
        self.assertEqual(catalog["status"], "ok")
        self.assertEqual(len(catalog["programs"]), 5)

        agent = self.request_json(
            "POST",
            "/api/agent/turn",
            {
                "student_id": "STU-CATALOG-001",
                "session_id": "catalog-test",
                "message": "查看专业群方向目录",
            },
        )
        self.assertEqual(agent["action"], "show_capability_catalog")
        self.assertEqual(len(agent["artifact"]["data"]["programs"]), 5)

        created = self.request_json(
            "POST",
            "/api/projects",
            {
                "student_id": "STU-CATALOG-001",
                "text": "我想学习计算机网络技术，掌握交换路由和网络运维",
            },
        )["project"]
        self.assertEqual(created["support_level"], REFERENCE_SUPPORT_LEVEL)
        self.assertEqual(created["assessment_state"], "question_sources_pending")
        self.assertEqual(created["capability_pack"]["pack_id"], "PACK-COMPUTER-NETWORK")


if __name__ == "__main__":
    unittest.main()
