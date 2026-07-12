import unittest

from pydantic import ValidationError

from app.schemas.execution_diagnostic import (
    ExecutionDiagnosticQuery,
    ExecutionDiagnosticSelector,
)
from app.services.execution_diagnostic_projection import (
    ExecutionDiagnosticProjectionService,
)


def run_220_shape() -> dict:
    return {
        "summary": {
            "id": "scenario:220",
            "execution_id": 220,
            "execution_type": "scenario",
            "status": "failed",
            "duration_ms": 4282,
        },
        "detail": {
            "step_results": [
                {
                    "step_id": "STEP-1",
                    "name": "获取企业列表",
                    "status": "passed",
                    "response_snapshot": {"body": "x" * 167000},
                },
                {
                    "step_id": "STEP-1-AFTER-1",
                    "name": "获取企业列表-AFTER_ACTIONS-1",
                    "status": "passed",
                },
                {
                    "step_id": "STEP-2",
                    "name": "获取对应企业CT画像数",
                    "status": "failed",
                    "error_message": "Assertion failed",
                    "response_snapshot": {
                        "status_code": 200,
                        "body": '{"msg":"请求未授权","code":90001,"data":null}',
                    },
                    "assertion_results": [
                        {
                            "assertion": {"type": "status_code", "expected": 200},
                            "actual": 200,
                            "passed": True,
                        },
                        {
                            "assertion": {
                                "type": "json_equals",
                                "path": "code",
                                "expected": 200,
                            },
                            "actual": 90001,
                            "passed": False,
                        },
                        {
                            "assertion": {
                                "type": "json_equals",
                                "path": "success",
                                "expected": True,
                            },
                            "actual": None,
                            "passed": False,
                        },
                    ],
                    "resolved_bindings": [],
                    "extracted_variables": [],
                },
            ]
        },
    }


def protocol_fixtures() -> dict[str, dict]:
    common_summary = {"status": "failed", "duration_ms": 50}
    return {
        "http": {
            "summary": {
                **common_summary,
                "id": "http:11",
                "execution_id": 11,
                "execution_type": "http",
            },
            "detail": {
                "status": "failed",
                "response_snapshot": {"status_code": 500, "body": '{"code":500}'},
                "assertion_results": [],
            },
        },
        "websocket": {
            "summary": {
                **common_summary,
                "id": "websocket:12",
                "execution_id": 12,
                "execution_type": "websocket",
            },
            "detail": {
                "status": "failed",
                "response_snapshot": {"messages": ["secret payload"]},
                "assertion_results": [],
            },
        },
        "scenario": {
            "summary": {
                **common_summary,
                "id": "scenario:13",
                "execution_id": 13,
                "execution_type": "scenario",
            },
            "detail": {
                "step_results": [
                    {"step_id": "S1", "name": "request", "status": "failed"}
                ]
            },
        },
        "flow": {
            "summary": {
                **common_summary,
                "id": "flow:14",
                "execution_id": 14,
                "execution_type": "flow",
            },
            "detail": {
                "node_executions": [
                    {"node_id": "N1", "name": "branch", "status": "failed"}
                ]
            },
        },
    }


class ExecutionDiagnosticProjectionTests(unittest.TestCase):
    def test_externalized_sections_are_returned_as_evidence_refs_and_omissions(self):
        execution = run_220_shape()
        execution["detail"]["step_results"][2]["response"] = {
            "artifact_ref": "execution-artifact://1/scenario/220/abc",
            "raw_size_bytes": 100000,
            "externalized": True,
        }

        result = self.projector.project(
            execution_type="scenario",
            execution=execution,
            query=ExecutionDiagnosticQuery(view="failures"),
        )

        self.assertEqual(
            result.evidence_refs[0]["artifact_ref"],
            "execution-artifact://1/scenario/220/abc",
        )
        self.assertTrue(
            any(item.reason == "artifact_externalized" for item in result.omissions)
        )
        self.assertNotIn("x" * 1000, result.model_dump_json())
    def setUp(self):
        self.projector = ExecutionDiagnosticProjectionService()

    def test_failure_view_keeps_first_failure_after_huge_success_output(self):
        query = ExecutionDiagnosticQuery(view="failures", max_chars=12000)

        result = self.projector.project(
            execution_type="scenario", execution=run_220_shape(), query=query
        )

        first_failure = result.data["first_failure"]
        self.assertEqual(first_failure["step_id"], "STEP-2")
        self.assertEqual(first_failure["response"]["business_code"], 90001)
        self.assertEqual(first_failure["response"]["message"], "请求未授权")
        self.assertEqual(first_failure["assertions"][1]["expected"], 200)
        self.assertEqual(first_failure["assertions"][1]["actual"], 90001)
        encoded = result.model_dump_json()
        self.assertNotIn("x" * 1000, encoded)
        self.assertLessEqual(len(encoded), 12000)

    def test_failure_identity_is_stable_and_auth_based(self):
        result = self.projector.canonicalize(
            execution_type="scenario", execution=run_220_shape()
        )

        self.assertEqual(result.failure_category, "authorization")
        self.assertEqual(
            result.failure_signature,
            "SCENARIO_AUTHORIZATION_HTTP_200_BUSINESS_90001_JSON_EQUALS_CODE",
        )
        self.assertNotIn("请求未授权", result.failure_signature)

    def test_all_protocols_return_common_envelope(self):
        for protocol, execution in protocol_fixtures().items():
            with self.subTest(protocol=protocol):
                result = self.projector.project(
                    execution_type=protocol,
                    execution=execution,
                    query=ExecutionDiagnosticQuery(view="summary"),
                )
                self.assertTrue(result.resource_ref.startswith(f"{protocol}:"))
                self.assertEqual(
                    set(result.data["counts"]),
                    {"total", "passed", "failed", "timeout", "skipped"},
                )

    def test_budget_omits_low_priority_passed_steps_with_reference(self):
        execution = run_220_shape()
        execution["detail"]["step_results"] = [
            {
                "step_id": f"STEP-{index}",
                "name": "passed " + ("z" * 300),
                "status": "passed",
            }
            for index in range(30)
        ]
        execution["detail"]["step_results"].append(
            {
                "step_id": "FAILED-LAST",
                "name": "important failure",
                "status": "failed",
                "error_message": "assertion failed",
            }
        )

        result = self.projector.project(
            execution_type="scenario",
            execution=execution,
            query=ExecutionDiagnosticQuery(view="steps", max_chars=3000),
        )

        self.assertLessEqual(len(result.model_dump_json()), 3000)
        self.assertIn(
            "FAILED-LAST", {item["step_id"] for item in result.data["steps"]}
        )
        self.assertTrue(
            result.page.has_more
            or any(item.reason == "budget_exceeded" for item in result.omissions)
        )

    def test_projection_never_emits_credentials_or_message_payloads(self):
        execution = protocol_fixtures()["http"]
        execution["detail"].update(
            {
                "request_snapshot": {
                    "headers": {"Authorization": "Bearer secret"},
                    "cookies": {"session": "secret"},
                },
                "response_snapshot": {
                    "status_code": 401,
                    "headers": {"Set-Cookie": "token=secret"},
                    "body": '{"code":401,"message":"unauthorized"}',
                    "messages": ["secret websocket payload"],
                },
            }
        )

        encoded = self.projector.project(
            execution_type="http",
            execution=execution,
            query=ExecutionDiagnosticQuery(view="failures"),
        ).model_dump_json()

        self.assertNotIn("Authorization", encoded)
        self.assertNotIn("Bearer secret", encoded)
        self.assertNotIn("Set-Cookie", encoded)
        self.assertNotIn("secret websocket payload", encoded)

    def test_query_validates_step_and_artifact_selectors(self):
        with self.assertRaises(ValidationError):
            ExecutionDiagnosticQuery(view="step")
        with self.assertRaises(ValidationError):
            ExecutionDiagnosticQuery(view="artifact")

        query = ExecutionDiagnosticQuery(
            view="failures", selector=ExecutionDiagnosticSelector()
        )
        self.assertEqual(query.selector.statuses, ["failed", "timeout", "error"])


if __name__ == "__main__":
    unittest.main()
