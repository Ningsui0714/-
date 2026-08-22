import unittest

from backend.knowledge_retrieval import KnowledgeEvidenceRetriever
from backend.server import LearningApplication


class KnowledgeEvidenceRetrieverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.retriever = KnowledgeEvidenceRetriever(
            "https://www.bing.com/search?format=rss&q={query}"
        )

    def test_retrieves_only_whitelisted_relevant_full_text_sources(self):
        searches = []

        def search(query):
            searches.append(query)
            return [
                {"title": "Java 教程", "url": "https://docs.oracle.com/java"},
                {"title": "无关页面", "url": "https://example.com/java"},
            ]

        def fetch(url):
            self.assertEqual(url, "https://docs.oracle.com/java")
            return {
                "title": "Java 封装与访问控制",
                "content": "封装通过访问控制限制字段访问，并通过方法定义公开行为。",
            }

        result = self.retriever.retrieve("封装与访问控制", "Java 面向对象编程", search=search, fetch=fetch)

        self.assertEqual(len(searches), 2)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["completeness"]["status"], "needs_workflow_review")
        self.assertEqual(len(result["evidence"]), 1)
        evidence = result["evidence"][0]
        self.assertEqual(evidence["source_type"], "official_document")
        self.assertEqual(evidence["body_status"], "full_text")
        self.assertNotIn("example.com", str(result))

    def test_rejects_private_and_non_whitelisted_sources(self):
        def search(_query):
            return [
                {"title": "内网资料", "url": "http://127.0.0.1/internal"},
                {"title": "博客", "url": "https://example.com/post"},
            ]

        result = self.retriever.retrieve("封装与访问控制", "Java", search=search)

        self.assertEqual(result["status"], "knowledge_unavailable")
        self.assertFalse(result["evidence"])

    def test_uses_workflow_planned_queries_when_provided(self):
        searches = []

        def search(query):
            searches.append(query)
            return []

        self.retriever.retrieve(
            "封装与访问控制",
            "Java",
            queries=["封装与访问控制 官方文档"],
            search=search,
        )

        self.assertEqual(searches, ["封装与访问控制 官方文档"])

    def test_accepts_english_official_page_using_planned_query_terms(self):
        def search(_query):
            return [{"title": "Classes and Objects", "url": "https://docs.oracle.com/java"}]

        def fetch(_url):
            return {
                "title": "Java Classes and Objects",
                "content": "A class defines objects and their behavior in Java.",
            }

        result = self.retriever.retrieve(
            "Java 类与对象",
            "掌握 Java 应用开发中的面向对象编程",
            queries=["Java 类与对象 classes objects site:docs.oracle.com"],
            search=search,
            fetch=fetch,
        )

        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["evidence"][0]["source"], "Oracle 官方文档")

    def test_uses_java_official_fallback_when_search_results_are_unusable(self):
        fallback_url = "https://docs.oracle.com/javase/tutorial/java/javaOO/"

        def search(_query):
            return [{"title": "Oracle Java 下载", "url": "https://www.oracle.com/java/"}]

        def fetch(url):
            if url == "https://www.oracle.com/java/":
                raise OSError("营销页拒绝正文抓取")
            self.assertIn(url, {item["url"] for item in self.retriever.OFFICIAL_FALLBACKS["java"]})
            return {
                "title": "Lesson: Classes and Objects",
                "content": "A Java class defines objects and their behavior.",
            }

        result = self.retriever.retrieve(
            "Java 类与对象",
            "掌握 Java 应用开发中的面向对象编程",
            queries=["Java 类与对象 classes objects site:docs.oracle.com"],
            search=search,
            fetch=fetch,
            allow_official_fallback=True,
        )

        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["evidence"][0]["url"], fallback_url)

    def test_audit_requires_traced_sources_and_required_blocks(self):
        evidence_pack = {
            "required_sections": [
                "definition_and_boundary",
                "core_principles",
                "example_or_steps",
                "application_or_verification",
            ],
            "evidence": [
                {
                    "title": "Java Platform SE Documentation",
                    "source": "Oracle 官方文档",
                    "url": "https://docs.oracle.com/javase/",
                }
            ],
        }
        result = {
            "content_blocks": [
                {
                    "type": "concept",
                    "source": "Java Platform SE Documentation",
                },
                {
                    "type": "steps",
                    "source": "Oracle 官方文档",
                },
                {
                    "type": "workplace",
                    "source": "https://docs.oracle.com/javase/",
                },
            ]
        }

        audit = LearningApplication._audit_lesson_evidence(
            LearningApplication.__new__(LearningApplication), result, evidence_pack
        )

        self.assertEqual(audit["status"], "passed")


if __name__ == "__main__":
    unittest.main()
