from __future__ import annotations

import unittest
from unittest.mock import patch

import keiba_public_watch as mod


class KeibaPublicWatchTest(unittest.TestCase):
    def test_event_level_mapping(self) -> None:
        self.assertEqual(mod._event_level("recovered"), mod.LEVEL_INFO)
        self.assertEqual(mod._event_level("url_changed"), mod.LEVEL_WARN)
        self.assertEqual(mod._event_level("unhealthy"), mod.LEVEL_CRITICAL)

    def test_notify_remote_uses_post_ntfy_for_ntfy_only(self) -> None:
        seen = {}

        def fake_post_ntfy(url, title, body, **kwargs):
            seen["url"] = url
            seen["title"] = title
            seen["body"] = body
            seen["kwargs"] = kwargs
            return True, "HTTP 200"

        with patch.object(mod, "post_ntfy", side_effect=fake_post_ntfy):
            ok, msg = mod._notify_remote(
                {
                    "ntfy_topic_url": "https://ntfy.example/topic",
                    "ntfy_bearer_token": "token-1",
                },
                "KEIBA public unhealthy",
                "http: 500 / message: bad",
                {"event": "unhealthy"},
                "unhealthy",
            )

        self.assertTrue(ok)
        self.assertIn("ntfy:HTTP 200", msg)
        self.assertEqual(seen["url"], "https://ntfy.example/topic")
        self.assertEqual(seen["kwargs"]["level"], mod.LEVEL_CRITICAL)
        self.assertEqual(seen["kwargs"]["tags"], "horse,public_watch")

    def test_notify_remote_includes_event_level_in_webhook_payload(self) -> None:
        seen = {}

        def fake_http_post(url, body, headers):
            seen["url"] = url
            seen["body"] = body
            seen["headers"] = headers
            return True, "HTTP 200"

        with patch.object(mod, "_http_post", side_effect=fake_http_post):
            ok, msg = mod._notify_remote(
                {
                    "webhook_url": "https://example.test/hook",
                    "webhook_bearer_token": "token-2",
                },
                "KEIBA public unhealthy",
                "http: 500 / message: bad",
                {"event": "unhealthy", "foo": "bar"},
                "unhealthy",
            )

        self.assertTrue(ok)
        self.assertIn("webhook:HTTP 200", msg)
        self.assertEqual(seen["url"], "https://example.test/hook")
        self.assertEqual(seen["headers"]["Authorization"], "Bearer token-2")
        payload = mod.json.loads(seen["body"].decode("utf-8"))
        self.assertEqual(payload["event_code"], "unhealthy")
        self.assertEqual(payload["event_level"], mod.LEVEL_CRITICAL)
        self.assertEqual(payload["foo"], "bar")
