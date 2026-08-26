"""SparkClient（历史命名的 OpenAI 兼容直连客户端）单元测试。

通过替换 ``urllib.request.urlopen`` 断言：鉴权头、stream:false、响应解析、
401/429/超时/网络错误分类，以及未配置密钥时的 auth 拒绝。
"""

import json
import socket
import unittest
import urllib.error
from unittest.mock import patch

from backend.spark_client import SparkClient, SparkConfig, SparkError


class _FakeResponse:
    def __init__(self, body: bytes, headers=None):
        self.body = body
        self.headers = headers or {}
        self.status = 200

    def read(self, *args):
        return self.body

    def close(self):
        pass


def _json_body(content: str, choices: int = 1) -> bytes:
    return json.dumps(
        {
            "choices": [
                {"message": {"role": "assistant", "content": content}}
                for _ in range(choices)
            ]
        },
        ensure_ascii=False,
    ).encode("utf-8")


class SparkClientTests(unittest.TestCase):
    def setUp(self):
        self.config = SparkConfig(api_key="test-apipassword")
        self.client = SparkClient(self.config)

    def _capture_request(self, fake_urlopen):
        captured = {}

        def wrapped(request, timeout=None):
            captured["headers"] = dict(request.headers)
            captured["method"] = request.get_method()
            captured["body"] = json.loads(request.data.decode("utf-8"))
            captured["url"] = request.full_url
            return fake_urlopen

        return wrapped, captured

    def test_chat_sends_bearer_stream_false_and_parses_content(self):
        fake = _FakeResponse(_json_body("封装是隐藏对象内部细节。"))
        wrapped, captured = self._capture_request(fake)
        with patch("backend.spark_client.urllib.request.urlopen", wrapped):
            content = self.client.chat([{"role": "user", "content": "讲一下封装"}])
        self.assertEqual(content, "封装是隐藏对象内部细节。")
        self.assertEqual(captured["headers"]["Authorization"], "Bearer test-apipassword")
        self.assertEqual(captured["method"], "POST")
        self.assertFalse(captured["body"]["stream"])
        self.assertEqual(captured["body"]["model"], "deepseek-v4-flash")
        self.assertEqual(
            captured["url"], "https://api.deepseek.com/chat/completions",
        )

    def test_configured_false_raises_auth(self):
        client = SparkClient(SparkConfig(api_key="  "))
        with self.assertRaises(SparkError) as ctx:
            client.chat([])
        self.assertEqual(ctx.exception.kind, "auth")

    def test_http_401_classified_as_auth(self):
        def fake_urlopen(request, timeout=None):
            raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {}, None)

        with patch("backend.spark_client.urllib.request.urlopen", fake_urlopen):
            with self.assertRaises(SparkError) as ctx:
                self.client.chat([])
        self.assertEqual(ctx.exception.kind, "auth")

    def test_http_429_classified_as_refused(self):
        def fake_urlopen(request, timeout=None):
            raise urllib.error.HTTPError(request.full_url, 429, "Too Many", {}, None)

        with patch("backend.spark_client.urllib.request.urlopen", fake_urlopen):
            with self.assertRaises(SparkError) as ctx:
                self.client.chat([])
        self.assertEqual(ctx.exception.kind, "refused")

    def test_http_500_classified_as_http(self):
        def fake_urlopen(request, timeout=None):
            raise urllib.error.HTTPError(request.full_url, 500, "Server Error", {}, None)

        with patch("backend.spark_client.urllib.request.urlopen", fake_urlopen):
            with self.assertRaises(SparkError) as ctx:
                self.client.chat([])
        self.assertEqual(ctx.exception.kind, "http")

    def test_timeout_classified_as_timeout(self):
        def fake_urlopen(request, timeout=None):
            raise socket.timeout("timed out")

        with patch("backend.spark_client.urllib.request.urlopen", fake_urlopen):
            with self.assertRaises(SparkError) as ctx:
                self.client.chat([])
        self.assertEqual(ctx.exception.kind, "timeout")

    def test_urlerror_classified_as_network(self):
        def fake_urlopen(request, timeout=None):
            raise urllib.error.URLError("name resolution failed")

        with patch("backend.spark_client.urllib.request.urlopen", fake_urlopen):
            with self.assertRaises(SparkError) as ctx:
                self.client.chat([])
        self.assertEqual(ctx.exception.kind, "network")

    def test_invalid_json_classified_as_parse(self):
        fake = _FakeResponse(b"not json at all")
        with patch("backend.spark_client.urllib.request.urlopen", lambda request, timeout=None: fake):
            with self.assertRaises(SparkError) as ctx:
                self.client.chat([])
        self.assertEqual(ctx.exception.kind, "parse")

    def test_empty_choices_classified_as_empty(self):
        fake = _FakeResponse(b'{"choices": []}')
        with patch("backend.spark_client.urllib.request.urlopen", lambda request, timeout=None: fake):
            with self.assertRaises(SparkError) as ctx:
                self.client.chat([])
        self.assertEqual(ctx.exception.kind, "empty")

    def test_empty_content_classified_as_empty(self):
        fake = _FakeResponse(b'{"choices": [{"message": {"role": "assistant", "content": "  "}}]}')
        with patch("backend.spark_client.urllib.request.urlopen", lambda request, timeout=None: fake):
            with self.assertRaises(SparkError) as ctx:
                self.client.chat([])
        self.assertEqual(ctx.exception.kind, "empty")


if __name__ == "__main__":
    unittest.main()
