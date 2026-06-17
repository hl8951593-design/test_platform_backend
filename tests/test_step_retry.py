import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import websocket

from app.schemas.test_case import TestCaseRequestConfig
from app.schemas.websocket_test_case import WebSocketTestCaseConfig
from app.services.scenario_service import ScenarioService
from app.services.test_case_service import TestCaseService
from app.services.websocket_test_case_service import WebSocketTestCaseService


class StepRetryTests(unittest.TestCase):
    def setUp(self):
        self.user = SimpleNamespace(id=7)

    def http_service(self):
        service = TestCaseService(MagicMock())
        service._load_environment_context = MagicMock(return_value=(None, {}))
        service.repository.create_execution = MagicMock(
            side_effect=lambda **values: SimpleNamespace(**values, id=101)
        )
        return service

    @staticmethod
    def http_payload(**overrides):
        data = {
            "method": "GET",
            "path": "https://example.test/status",
            "assertions": [],
            "extractors": [],
            "retry_policy": {
                "enabled": True,
                "max_attempts": 3,
                "base_delay_ms": 0,
                "max_delay_ms": 0,
                "jitter": "none",
            },
        }
        data.update(overrides)
        return TestCaseRequestConfig.model_validate(data)

    def test_http_retries_retryable_status_until_success(self):
        service = self.http_service()
        service._send_request = MagicMock(side_effect=[
            {"status_code": 503, "headers": {}, "body": "busy", "json": None},
            {"status_code": 200, "headers": {}, "body": "ok", "json": {"ok": True}},
        ])

        result = service._execute(
            project_id=1,
            test_case_id=None,
            payload=self.http_payload(),
            current_user=self.user,
        )

        self.assertEqual(result.status, "passed")
        self.assertEqual(service._send_request.call_count, 2)
        self.assertEqual(result.attempt_history[0]["retry_reason"], "http_status_503")
        self.assertEqual(result.attempt_history[1]["status"], "passed")

    def test_http_does_not_retry_regular_4xx(self):
        service = self.http_service()
        service._send_request = MagicMock(return_value={
            "status_code": 400,
            "headers": {},
            "body": "bad request",
            "json": None,
        })

        result = service._execute(
            project_id=1,
            test_case_id=None,
            payload=self.http_payload(
                assertions=[{"type": "status_code", "expected": 200}]
            ),
            current_user=self.user,
        )

        self.assertEqual(result.status, "failed")
        self.assertEqual(service._send_request.call_count, 1)
        self.assertIsNone(result.attempt_history[0]["retry_reason"])

    def test_http_429_uses_retry_path(self):
        service = self.http_service()
        service._send_request = MagicMock(side_effect=[
            {
                "status_code": 429,
                "headers": {"Retry-After": "1"},
                "body": "limited",
                "json": None,
            },
            {"status_code": 200, "headers": {}, "body": "ok", "json": {}},
        ])

        with patch(
            "app.services.test_case_service.retry_delay_seconds",
            return_value=0,
        ) as delay:
            result = service._execute(
                project_id=1,
                test_case_id=None,
                payload=self.http_payload(),
                current_user=self.user,
            )

        self.assertEqual(result.status, "passed")
        self.assertEqual(result.attempt_history[0]["retry_reason"], "http_status_429")
        self.assertEqual(delay.call_args.kwargs["response_headers"]["Retry-After"], "1")

    def test_http_unsafe_method_requires_explicit_opt_in(self):
        service = self.http_service()
        service._send_request = MagicMock(return_value={
            "status_code": 503,
            "headers": {},
            "body": "busy",
            "json": None,
        })

        result = service._execute(
            project_id=1,
            test_case_id=None,
            payload=self.http_payload(method="POST"),
            current_user=self.user,
        )

        self.assertEqual(result.status, "passed")
        self.assertEqual(service._send_request.call_count, 1)

    def test_polling_assertion_retries_and_extracts_only_final_response(self):
        service = self.http_service()
        service._send_request = MagicMock(side_effect=[
            {
                "status_code": 200,
                "headers": {},
                "body": '{"state":"pending","id":"old"}',
                "json": {"state": "pending", "id": "old"},
            },
            {
                "status_code": 200,
                "headers": {},
                "body": '{"state":"done","id":"final"}',
                "json": {"state": "done", "id": "final"},
            },
        ])
        service._run_extractors = MagicMock()

        result = service._execute(
            project_id=1,
            test_case_id=None,
            payload=self.http_payload(
                assertions=[{
                    "type": "json_equals",
                    "path": "state",
                    "expected": "done",
                    "retry_on_failure": True,
                }],
                extractors=[{"name": "task_id", "path": "id"}],
            ),
            current_user=self.user,
        )

        self.assertEqual(result.status, "passed")
        self.assertEqual(service._run_extractors.call_count, 1)
        final_response = service._run_extractors.call_args.args[1]
        self.assertEqual(final_response["json"]["id"], "final")

    def test_http_network_error_retries(self):
        service = self.http_service()
        request = httpx.Request("GET", "https://example.test/status")
        service._send_request = MagicMock(side_effect=[
            httpx.ConnectError("offline", request=request),
            {"status_code": 200, "headers": {}, "body": "ok", "json": {}},
        ])

        result = service._execute(
            project_id=1,
            test_case_id=None,
            payload=self.http_payload(),
            current_user=self.user,
        )

        self.assertEqual(result.status, "passed")
        self.assertEqual(result.attempt_history[0]["retry_reason"], "network_error")

    def test_websocket_reconnects_inside_step(self):
        service = WebSocketTestCaseService(MagicMock())
        service._load_environment_context = MagicMock(return_value=(None, {}))
        service.repository.create_execution = MagicMock(
            side_effect=lambda **values: SimpleNamespace(**values, id=201)
        )
        service._run_session = MagicMock(side_effect=[
            websocket.WebSocketTimeoutException("timed out"),
            {
                "sent_messages": [],
                "received_messages": [{"type": "text", "data": "ready", "json": None}],
                "negotiated_subprotocol": None,
            },
        ])
        payload = WebSocketTestCaseConfig.model_validate({
            "path": "wss://example.test/events",
            "assertions": [{"type": "message_contains", "expected": "ready"}],
            "retry_policy": {
                "enabled": True,
                "max_attempts": 2,
                "base_delay_ms": 0,
                "max_delay_ms": 0,
                "jitter": "none",
            },
        })

        result = service._execute(1, None, payload, self.user)

        self.assertEqual(result.status, "passed")
        self.assertEqual(service._run_session.call_count, 2)
        self.assertEqual(result.attempt_history[0]["retry_reason"], "timeout")

    def test_failed_scenario_step_does_not_publish_extracted_variables(self):
        service = ScenarioService(MagicMock())
        service.db.scalar.return_value = 101
        variables = {}
        step = {
            "id": "STEP-1",
            "kind": "api_case",
            "reference_id": 101,
            "name": "Failed request",
            "config": {
                "_scenario_context": {
                    "extractions": [{
                        "id": "EXTRACT-1",
                        "name": "task_id",
                        "path": "id",
                    }]
                }
            },
            "case_snapshot": {
                "method": "GET",
                "path": "/status",
                "headers": {},
                "query_params": {},
                "body_type": "none",
                "body": None,
                "assertions": [],
                "extractors": [],
            },
        }
        execution = SimpleNamespace(
            id=301,
            status="failed",
            request_snapshot={},
            response_snapshot={"json": {"id": "must-not-leak"}},
            assertion_results=[{"passed": False}],
            error_message="Assertion failed",
        )

        with patch(
            "app.services.scenario_service.TestCaseService._execute",
            return_value=execution,
        ):
            result = service._execute_step(
                project_id=1,
                environment_id=2,
                step=step,
                step_index=1,
                variables=variables,
                previous_results=[],
                current_user=self.user,
                scenario_run_id=9,
                deadline=None,
                variable_sources={},
            )

        self.assertEqual(result["status"], "failed")
        self.assertNotIn("task_id", variables)
        self.assertEqual(result["extracted_variables"], [])


if __name__ == "__main__":
    unittest.main()
