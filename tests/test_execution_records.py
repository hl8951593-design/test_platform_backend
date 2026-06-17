import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock

from fastapi import HTTPException

from app.models.scenario import TestScenarioRun, TestScenarioRunEvent
from app.models.test_case import TestCaseExecution
from app.models.user import User
from app.models.visual_flow import VisualFlowExecution, VisualFlowNodeExecution
from app.models.websocket_test_case import WebSocketTestCaseExecution
from app.schemas.execution_record import ExecutionRecordPage
from app.services.execution_record_service import ExecutionRecordService


NOW = datetime(2026, 6, 15, 10, 0, 0)


def build_service() -> ExecutionRecordService:
    service = ExecutionRecordService(MagicMock())
    service.permission_service = MagicMock()
    service.repository = MagicMock()
    return service


class ExecutionRecordServiceTests(unittest.TestCase):
    def setUp(self):
        self.user = User(id=9, username="reporter", password_hash="x", is_admin=False)

    def test_list_records_normalizes_common_fields_and_trigger_type(self):
        service = build_service()
        service.repository.list_records.return_value = ([
            {
                "execution_type": "http",
                "execution_id": 11,
                "project_id": 3,
                "resource_id": 7,
                "resource_name": "Create order",
                "environment_id": 5,
                "scenario_run_id": 21,
                "status": "passed",
                "scenario_trigger": "scenario",
                "trigger_user_id": 9,
                "duration_ms": 120,
                "error_message": None,
                "dataset_id": None,
                "dataset_name": None,
                "record_id": None,
                "record_name": None,
                "started_at": NOW,
                "finished_at": None,
                "created_at": NOW,
            },
            {
                "execution_type": "scenario",
                "execution_id": 21,
                "project_id": 3,
                "resource_id": 4,
                "resource_name": "Order lifecycle",
                "environment_id": 5,
                "scenario_run_id": None,
                "status": "failed",
                "scenario_trigger": "plan",
                "trigger_user_id": 9,
                "duration_ms": 500,
                "error_message": None,
                "dataset_id": "DATA-1",
                "dataset_name": "Customers",
                "record_id": "RECORD-2",
                "record_name": "Blocked",
                "started_at": NOW - timedelta(seconds=1),
                "finished_at": NOW,
                "created_at": NOW - timedelta(seconds=1),
            },
        ], 2)

        result = service.list_records(
            project_id=3,
            current_user=self.user,
            execution_type=None,
            status_filter=None,
            environment_id=None,
            trigger_user_id=None,
            started_from=None,
            started_to=None,
            keyword=None,
            page=1,
            page_size=20,
        )

        self.assertIsInstance(result, ExecutionRecordPage)
        self.assertEqual(result.total, 2)
        self.assertEqual(result.items[0].id, "http:11")
        self.assertEqual(result.items[0].trigger_type, "scenario")
        self.assertEqual(result.items[1].record_id, "RECORD-2")
        service.permission_service.require_project_permission.assert_called_once_with(
            self.user, 3, "report:view"
        )

    def test_list_records_rejects_reversed_time_range(self):
        service = build_service()

        with self.assertRaises(HTTPException) as context:
            service.list_records(
                project_id=3,
                current_user=self.user,
                execution_type=None,
                status_filter=None,
                environment_id=None,
                trigger_user_id=None,
                started_from=NOW,
                started_to=NOW - timedelta(minutes=1),
                keyword=None,
                page=1,
                page_size=20,
            )

        self.assertEqual(context.exception.status_code, 400)
        service.repository.list_records.assert_not_called()

    def test_http_detail_preserves_request_assertions_and_attempt_history(self):
        service = build_service()
        execution = TestCaseExecution(
            id=11,
            project_id=3,
            test_case_id=7,
            environment_id=5,
            scenario_run_id=None,
            executed_by_id=9,
            status="failed",
            request_snapshot={"path": "/orders"},
            response_snapshot={"status_code": 503},
            assertion_results=[],
            attempt_history=[{"attempt": 1}, {"attempt": 2}],
            error_message="service unavailable",
            duration_ms=900,
            created_at=NOW,
        )
        service.repository.get_http.return_value = (execution, "Create order")

        result = service.get_detail(
            project_id=3,
            execution_type="http",
            execution_id=11,
            current_user=self.user,
        )

        self.assertEqual(result.summary.trigger_type, "manual")
        self.assertEqual(result.detail["request_snapshot"]["path"], "/orders")
        self.assertEqual(len(result.detail["attempt_history"]), 2)

    def test_websocket_detail_preserves_session_snapshot(self):
        service = build_service()
        execution = WebSocketTestCaseExecution(
            id=12,
            project_id=3,
            websocket_test_case_id=8,
            environment_id=5,
            scenario_run_id=21,
            executed_by_id=9,
            status="passed",
            session_snapshot={"url": "wss://example.test"},
            response_snapshot={"messages": ["ready"]},
            assertion_results=[{"passed": True}],
            attempt_history=[{"attempt": 1}],
            duration_ms=80,
            created_at=NOW,
        )
        service.repository.get_websocket.return_value = (execution, "Events")

        result = service.get_detail(
            project_id=3,
            execution_type="websocket",
            execution_id=12,
            current_user=self.user,
        )

        self.assertEqual(result.summary.trigger_type, "scenario")
        self.assertEqual(result.detail["session_snapshot"]["url"], "wss://example.test")

    def test_scenario_detail_includes_dataset_record_and_events(self):
        service = build_service()
        execution = TestScenarioRun(
            id=21,
            project_id=3,
            scenario_id=4,
            scenario_version_id=2,
            environment_id=5,
            dataset_id="DATA-1",
            dataset_name="Customers",
            record_id="RECORD-1",
            record_name="VIP",
            status="passed",
            trigger_type="manual",
            scenario_snapshot={"steps": []},
            variables_snapshot={"tenant_id": 1001},
            step_results=[{"step_id": "STEP-1", "status": "passed"}],
            triggered_by_id=9,
            started_at=NOW,
            finished_at=NOW + timedelta(seconds=1),
            duration_ms=1000,
            created_at=NOW,
        )
        event = TestScenarioRunEvent(
            id=1,
            run_id=21,
            sequence=1,
            event="run.started",
            payload={},
            occurred_at=NOW,
        )
        service.repository.get_scenario.return_value = (execution, "Order lifecycle")
        service.repository.list_scenario_events.return_value = [event]

        result = service.get_detail(
            project_id=3,
            execution_type="scenario",
            execution_id=21,
            current_user=self.user,
        )

        self.assertEqual(result.summary.record_name, "VIP")
        self.assertEqual(result.detail["variables_snapshot"]["tenant_id"], 1001)
        self.assertEqual(result.detail["events"][0]["event"], "run.started")

    def test_flow_detail_includes_nodes_and_calculates_duration(self):
        service = build_service()
        execution = VisualFlowExecution(
            id=31,
            project_id=3,
            flow_id=6,
            flow_version_id=4,
            environment_id=5,
            status="failed",
            trigger_type="manual",
            trigger_user_id=9,
            context_snapshot={"variables": {}},
            started_at=NOW,
            finished_at=NOW + timedelta(milliseconds=250),
            created_at=NOW,
        )
        node = VisualFlowNodeExecution(
            id=1,
            execution_id=31,
            node_id="api-1",
            status="failed",
            attempt=1,
            request_snapshot={"path": "/health"},
            error={"message": "timeout"},
            started_at=NOW,
            finished_at=NOW + timedelta(milliseconds=250),
        )
        service.repository.get_flow.return_value = (execution, "Health flow")
        service.repository.list_flow_nodes.return_value = [node]

        result = service.get_detail(
            project_id=3,
            execution_type="flow",
            execution_id=31,
            current_user=self.user,
        )

        self.assertEqual(result.summary.duration_ms, 250)
        self.assertEqual(result.detail["node_executions"][0]["node_id"], "api-1")

    def test_missing_detail_returns_404(self):
        service = build_service()
        service.repository.get_http.return_value = None

        with self.assertRaises(HTTPException) as context:
            service.get_detail(
                project_id=3,
                execution_type="http",
                execution_id=999,
                current_user=self.user,
            )

        self.assertEqual(context.exception.status_code, 404)


class ExecutionRecordOpenAPITests(unittest.TestCase):
    def test_routes_and_filters_are_declared(self):
        from app.main import create_app

        schema = create_app().openapi()
        list_operation = schema["paths"]["/api/v1/execution-records"]["get"]
        detail_operation = schema["paths"][
            "/api/v1/execution-records/{execution_type}/{execution_id}"
        ]["get"]

        parameters = {item["name"] for item in list_operation["parameters"]}
        self.assertTrue({
            "project_id",
            "execution_type",
            "status",
            "environment_id",
            "trigger_user_id",
            "started_from",
            "started_to",
            "keyword",
            "page",
            "page_size",
        }.issubset(parameters))
        self.assertEqual(
            detail_operation["parameters"][0]["name"],
            "execution_type",
        )


if __name__ == "__main__":
    unittest.main()
