"""Trusted web evidence retrieval for generated lesson content."""

from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
import html
import ipaddress
import re
import urllib.error
import urllib.request
from typing import Any, Callable
from urllib.parse import quote_plus, urlparse
from xml.etree import ElementTree


SearchFunction = Callable[[str], list[dict[str, str]]]
FetchFunction = Callable[[str], dict[str, str]]


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._ignored_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"}:
            self._ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"}:
            self._ignored_depth = max(0, self._ignored_depth - 1)

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            self._parts.append(data)

    def text(self) -> str:
        return re.sub(r"\s+", " ", " ".join(self._parts)).strip()


@dataclass(frozen=True)
class KnowledgeEvidenceRetriever:
    search_url: str
    timeout: float = 12.0
    max_results: int = 8
    max_body_bytes: int = 1_000_000

    SOURCE_DOMAINS = {
        "openstd.samr.gov.cn": ("standard", "国家标准"),
        "gov.cn": ("standard", "政府网站"),
        "moe.gov.cn": ("standard", "教育部"),
        "mohrss.gov.cn": ("standard", "人力资源和社会保障部"),
        "docs.python.org": ("official_document", "Python 官方文档"),
        "python.org": ("official_document", "Python 官方网站"),
        "learn.microsoft.com": ("official_document", "Microsoft Learn"),
        "developer.mozilla.org": ("official_document", "MDN Web Docs"),
        "w3.org": ("standard", "W3C"),
        "ietf.org": ("standard", "IETF"),
        "rfc-editor.org": ("standard", "RFC Editor"),
        "oracle.com": ("official_document", "Oracle 官方网站"),
        "docs.oracle.com": ("official_document", "Oracle 官方文档"),
        "smartedu.cn": ("course", "国家智慧教育公共服务平台"),
        "icourse163.org": ("course", "中国大学 MOOC"),
        "xuetangx.com": ("course", "学堂在线"),
        "doi.org": ("academic_paper", "DOI"),
        "crossref.org": ("academic_paper", "Crossref"),
        "arxiv.org": ("academic_paper", "arXiv"),
        "pubmed.ncbi.nlm.nih.gov": ("academic_paper", "PubMed"),
        "ieeexplore.ieee.org": ("academic_paper", "IEEE Xplore"),
        "dl.acm.org": ("academic_paper", "ACM Digital Library"),
        "link.springer.com": ("academic_paper", "SpringerLink"),
    }

    REQUIRED_SECTIONS = (
        "definition_and_boundary",
        "core_principles",
        "example_or_steps",
        "application_or_verification",
    )

    OFFICIAL_FALLBACKS = {
        "java": [
            {
                "title": "Lesson: Classes and Objects",
                "url": "https://docs.oracle.com/javase/tutorial/java/javaOO/",
            },
            {
                "title": "Object (Java SE 21)",
                "url": "https://docs.oracle.com/en/java/javase/21/docs/api/java.base/java/lang/Object.html",
            },
            {
                "title": "Class (Java SE 21)",
                "url": "https://docs.oracle.com/en/java/javase/21/docs/api/java.base/java/lang/Class.html",
            },
        ],
    }

    def retrieve(
        self,
        knowledge_point_name: str,
        learning_goal: str,
        *,
        queries: list[str] | None = None,
        search: SearchFunction | None = None,
        fetch: FetchFunction | None = None,
        allow_official_fallback: bool | None = None,
    ) -> dict[str, Any]:
        knowledge_point_name = str(knowledge_point_name or "").strip()
        learning_goal = str(learning_goal or "").strip()
        if not knowledge_point_name:
            return self._empty_pack("知识点名称为空")
        if allow_official_fallback is None:
            allow_official_fallback = search is None
        search = search or self._search_bing_rss
        fetch = fetch or self._fetch_html
        planned_queries = list(queries or self._queries(knowledge_point_name, learning_goal))
        planned_query_terms = self._planned_query_terms(planned_queries)
        candidates: list[dict[str, str]] = []
        for query in planned_queries:
            try:
                candidates.extend(search(query))
            except (OSError, ValueError, urllib.error.URLError):
                continue
        if allow_official_fallback:
            candidates.extend(self._official_fallback_candidates(planned_query_terms))
        evidence: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        for candidate in candidates:
            url = str(candidate.get("url") or "").strip()
            source = self._source_for_url(url)
            if not source or url in seen_urls:
                continue
            seen_urls.add(url)
            try:
                page = fetch(url)
            except (OSError, ValueError, urllib.error.URLError):
                continue
            content = self._clean_text(str(page.get("content") or ""))
            title = self._clean_text(
                str(page.get("title") or candidate.get("title") or "")
            )
            relevance = self._relevance_score(
                knowledge_point_name,
                learning_goal,
                f"{title} {content}",
                planned_query_terms,
            )
            if relevance <= 0 or not content:
                continue
            source_type, source_name = source
            evidence.append(
                {
                    "title": title or url,
                    "url": url,
                    "source": source_name,
                    "source_type": source_type,
                    "body_status": "full_text",
                    "quote": content[:1200],
                    "relevance_score": relevance,
                    "verification_state": "authoritative",
                }
            )
            if len(evidence) >= self.max_results:
                break
        evidence.sort(
            key=lambda item: (
                -int(item["relevance_score"]),
                0 if item["source_type"] in {"standard", "official_document"} else 1,
            )
        )
        return self._evidence_pack(knowledge_point_name, learning_goal, evidence)

    def _queries(self, knowledge_point_name: str, learning_goal: str) -> list[str]:
        focus = " ".join(item for item in (knowledge_point_name, learning_goal) if item)
        domains = " OR ".join(f"site:{domain}" for domain in self.SOURCE_DOMAINS)
        return [
            f"{focus} 官方文档 标准 ({domains})",
            f"{focus} 论文 文献 DOI ({domains})",
        ]

    def _search_bing_rss(self, query: str) -> list[dict[str, str]]:
        endpoint = self.search_url.format(query=quote_plus(query))
        request = urllib.request.Request(
            endpoint,
            headers={
                "Accept": "application/rss+xml, application/xml, text/xml",
                "User-Agent": "ZhixingLessonEvidenceBot/1.0",
            },
            method="GET",
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            body = response.read(self.max_body_bytes)
        root = ElementTree.fromstring(body)
        results = []
        for item in root.findall(".//item"):
            title = self._clean_text(item.findtext("title") or "")
            url = str(item.findtext("link") or "").strip()
            if title and url:
                results.append({"title": title, "url": url})
        return results

    def _fetch_html(self, url: str) -> dict[str, str]:
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "User-Agent": "ZhixingLessonEvidenceBot/1.0",
            },
            method="GET",
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            content_type = str(response.headers.get("Content-Type") or "").lower()
            if "html" not in content_type:
                raise ValueError("来源未返回 HTML 正文")
            body = response.read(self.max_body_bytes)
        decoded = body.decode("utf-8", errors="replace")
        parser = _TextExtractor()
        parser.feed(decoded)
        title_match = re.search(r"<title[^>]*>(.*?)</title>", decoded, flags=re.I | re.S)
        return {
            "title": self._clean_text(title_match.group(1)) if title_match else "",
            "content": parser.text(),
        }

    def _source_for_url(self, url: str) -> tuple[str, str] | None:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if parsed.scheme not in {"http", "https"} or not host or parsed.username:
            return None
        try:
            if ipaddress.ip_address(host).is_private:
                return None
        except ValueError:
            pass
        for domain in sorted(self.SOURCE_DOMAINS, key=len, reverse=True):
            if host == domain or host.endswith("." + domain):
                return self.SOURCE_DOMAINS[domain]
        return None

    @staticmethod
    def _clean_text(value: str) -> str:
        without_tags = re.sub(r"<[^>]+>", " ", str(value or ""))
        return re.sub(r"\s+", " ", html.unescape(without_tags)).strip()

    @staticmethod
    def _planned_query_terms(queries: list[str]) -> list[str]:
        ignored_terms = {
            "and",
            "com",
            "documentation",
            "edu",
            "for",
            "from",
            "gov",
            "http",
            "https",
            "official",
            "org",
            "site",
            "the",
            "tutorial",
            "with",
            "www",
        }
        terms: list[str] = []
        for query in queries:
            query_without_site = re.sub(r"\bsite:[a-z0-9.-]+", " ", query, flags=re.I)
            for match in re.findall(r"[A-Za-z][A-Za-z-]{2,}", query_without_site):
                term = match.casefold()
                if term not in ignored_terms and term not in terms:
                    terms.append(term)
        return terms

    def _official_fallback_candidates(
        self, planned_query_terms: list[str]
    ) -> list[dict[str, str]]:
        candidates: list[dict[str, str]] = []
        for capability, fallback_urls in self.OFFICIAL_FALLBACKS.items():
            if capability in planned_query_terms:
                candidates.extend(fallback_urls)
        return candidates

    @staticmethod
    def _relevance_score(
        knowledge_point_name: str,
        learning_goal: str,
        text: str,
        planned_query_terms: list[str] | None = None,
    ) -> int:
        normalized = str(text or "").casefold()
        knowledge_terms = [
            item.strip().casefold()
            for item in re.split(r"与|和|及|、|，|,|\s+", knowledge_point_name)
            if len(item.strip()) >= 2
        ]
        if knowledge_point_name.casefold() in normalized:
            return 4
        matched = sum(term in normalized for term in knowledge_terms)
        goal_match = int(bool(learning_goal and learning_goal.casefold() in normalized))
        planned_matches = sum(
            term in normalized for term in (planned_query_terms or [])
        )
        planned_match = 2 if planned_matches >= 2 else 0
        return max(matched + goal_match, planned_match)

    def _evidence_pack(
        self,
        knowledge_point_name: str,
        learning_goal: str,
        evidence: list[dict[str, Any]],
    ) -> dict[str, Any]:
        source_types = {str(item.get("source_type") or "") for item in evidence}
        authoritative = any(
            source_type in {"standard", "official_document"}
            for source_type in source_types
        )
        complete = bool(evidence) and authoritative
        return {
            "status": "ready" if complete else "knowledge_unavailable",
            "knowledge_point_name": knowledge_point_name,
            "learning_goal": learning_goal,
            "required_sections": list(self.REQUIRED_SECTIONS),
            "evidence": evidence,
            "completeness": {
                "status": "needs_workflow_review" if complete else "insufficient",
                "authoritative_source_present": authoritative,
                "evidence_count": len(evidence),
                "missing_sections": list(self.REQUIRED_SECTIONS),
            },
        }

    def _empty_pack(self, reason: str) -> dict[str, Any]:
        return {
            "status": "knowledge_unavailable",
            "knowledge_point_name": "",
            "learning_goal": "",
            "required_sections": list(self.REQUIRED_SECTIONS),
            "evidence": [],
            "completeness": {
                "status": "insufficient",
                "authoritative_source_present": False,
                "evidence_count": 0,
                "missing_sections": list(self.REQUIRED_SECTIONS),
                "reason": reason,
            },
        }
