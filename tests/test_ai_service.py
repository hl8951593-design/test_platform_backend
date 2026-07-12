import unittest
from unittest.mock import patch

import httpx
from fastapi import HTTPException

from app.core.config import settings
from app.schemas.ai import (
    AIChatFunctionDefinition,
    AIChatMessage,
    AIChatRequest,
    AIChatToolCall,
    AIChatToolCallFunction,
    AIChatToolDefinition,
)
from app.services.ai_service import AIService


class AIServiceStreamRetryTests(unittest.TestCase):
    def test_chat_payload_includes_native_tools_and_disables_parallel_calls(self):
        payload = AIChatRequest(
            messages=[AIChatMessage(role="user", content="create defect")],
            tools=[
                AIChatToolDefinition(
                    function=AIChatFunctionDefinition(
                        name="defect_create_saved_deadbeef",
                        description="Create a saved defect",
                        parameters={
                            "type": "object",
                            "properties": {"input": {"type": "object"}},
                            "required": ["input"],
                        },
                    )
                )
            ],
            tool_choice="auto",
            parallel_tool_calls=False,
        )

        request_body = AIService()._build_chat_payload(payload)

        self.assertEqual(request_body["tool_choice"], "auto")
        self.assertFalse(request_body["parallel_tool_calls"])
        self.assertEqual(request_body["tools"][0].get("type"), "function")
        self.assertEqual(
            request_body["tools"][0]["function"]["name"],
            "defect_create_saved_deadbeef",
        )

    def test_chat_payload_preserves_required_type_on_assistant_tool_calls(self):
        payload = AIChatRequest(
            messages=[
                AIChatMessage(role="user", content="read context"),
                AIChatMessage(
                    role="assistant",
                    tool_calls=[
                        AIChatToolCall(
                            id="call-1",
                            function=AIChatToolCallFunction(
                                name="project_read_context_ee76237f",
                                arguments='{"input":{"project_id":1}}',
                            ),
                        )
                    ],
                ),
                AIChatMessage(role="tool", tool_call_id="call-1", content='{"project_id":1}'),
            ]
        )

        request_body = AIService()._build_chat_payload(payload)

        self.assertEqual(request_body["messages"][1]["tool_calls"][0].get("type"), "function")

    def test_stream_emits_native_tool_call_deltas(self):
        class FakeStreamResponse:
            def raise_for_status(self):
                return None

            def iter_lines(self):
                yield (
                    'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call-1",'
                    '"type":"function","function":{"name":"defect_create",'
                    '"arguments":"{\\\"input\\\":"}}]}}],"model":"deepseek-test"}'
                )
                yield (
                    'data: {"choices":[{"delta":{"tool_calls":[{"index":0,'
                    '"function":{"arguments":"{}}"}}]},"finish_reason":"tool_calls"}],'
                    '"model":"deepseek-test"}'
                )
                yield "data: [DONE]"

        class FakeStreamContext:
            def __enter__(self):
                return FakeStreamResponse()

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
                return FakeStreamContext()

        payload = AIChatRequest(messages=[AIChatMessage(role="user", content="create")])
        with (
            patch("app.services.ai_service.httpx.Client", FakeClient),
            patch.object(settings, "DEEPSEEK_API_KEY", "test-key"),
        ):
            items = list(AIService().chat_stream(payload))

        self.assertEqual([item["type"] for item in items], ["tool_call_delta", "tool_call_delta", "done"])
        self.assertEqual(items[0]["tool_calls"][0]["id"], "call-1")
        self.assertEqual(items[-1]["finish_reason"], "tool_calls")

    def test_stream_http_error_reads_unconsumed_response_body_before_parsing(self):
        request = httpx.Request("POST", "https://api.deepseek.test/chat/completions")
        response = httpx.Response(
            400,
            request=request,
            stream=httpx.ByteStream(
                b'{"error":{"message":"tools[0]: missing field type","type":"invalid_request_error"}}'
            ),
        )

        class FakeStreamContext:
            def __enter__(self):
                return response

            def __exit__(self, exc_type, exc, tb):
                response.close()
                return False

        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def stream(self, method, endpoint, headers, json):
                return FakeStreamContext()

        payload = AIChatRequest(messages=[AIChatMessage(role="user", content="create")])
        captured = None
        with (
            patch("app.services.ai_service.httpx.Client", FakeClient),
            patch.object(settings, "DEEPSEEK_API_KEY", "test-key"),
            patch.object(settings, "DEEPSEEK_STREAM_MAX_RETRIES", 0),
        ):
            try:
                list(AIService().chat_stream(payload))
            except Exception as exc:  # noqa: BLE001 - assert the public exception type below
                captured = exc

        self.assertIsInstance(captured, HTTPException)
        self.assertEqual(captured.status_code, 502)
        self.assertEqual(captured.detail, "tools[0]: missing field type")

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
