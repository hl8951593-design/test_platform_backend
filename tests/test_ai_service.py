import unittest
from unittest.mock import patch

import httpx
from fastapi import HTTPException

from app.core.config import settings
from app.schemas.ai import AIChatMessage, AIChatRequest
from app.services.ai_service import AIService


class AIServiceStreamRetryTests(unittest.TestCase):
    def test_chat_stream_retries_before_first_delta_and_reports_retry_item(self):
        attempts = []

        class FakeStreamResponse:
            def raise_for_status(self):
                return None

            def iter_lines(self):
                yield 'data: {"choices":[{"delta":{"content":"ok"}}],"model":"deepseek-test"}'
                yield (
                    'data: {"choices":[{"finish_reason":"stop"}],'
                    '"model":"deepseek-test","usage":{"total_tokens":3}}'
                )
                yield "data: [DONE]"

        class FakeStreamContext:
            def __init__(self, response=None, error=None):
                self.response = response
                self.error = error

            def __enter__(self):
                if self.error is not None:
                    raise self.error
                return self.response

            def __exit__(self, exc_type, exc, tb):
                return False

        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def stream(self, method, endpoint, headers, json):
                attempts.append((method, endpoint, json))
                if len(attempts) == 1:
                    request = httpx.Request(method, endpoint)
                    return FakeStreamContext(
                        error=httpx.ConnectError("temporary EOF", request=request)
                    )
                return FakeStreamContext(response=FakeStreamResponse())

        payload = AIChatRequest(
            messages=[AIChatMessage(role="user", content="ping")],
            temperature=0.2,
        )

        with (
            patch("app.services.ai_service.httpx.Client", FakeClient),
            patch("time.sleep") as sleep,
            patch.object(settings, "DEEPSEEK_API_KEY", "test-key"),
        ):
            try:
                items = list(AIService().chat_stream(payload))
            except HTTPException as exc:
                self.fail(f"chat_stream did not retry before first delta: {exc.detail}")

        self.assertEqual(len(attempts), 2)
        self.assertEqual([item["type"] for item in items], ["retry", "delta", "done"])
        self.assertEqual(items[0]["attempt"], 1)
        self.assertGreaterEqual(items[0]["max_retries"], 1)
        self.assertIn("temporary EOF", items[0]["error_message"])
        self.assertEqual(items[1]["content"], "ok")
        self.assertEqual(items[2]["model"], "deepseek-test")
        sleep.assert_called_once()


if __name__ == "__main__":
    unittest.main()
