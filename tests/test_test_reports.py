import unittest
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock

from fastapi import HTTPException

from app.models.scenario import TestScenarioRun
from app.models.test_plan import TestPlanRun
from app.models.user import User
from app.models.visual_flow import VisualFlowExecution, VisualFlowNodeExecution
from app.services.test_report_service import TestReportService


NOW = datetime(2026, 6, 15, 12, 0, 0)


def build_service() -> TestReportService:
    service = TestReportService(MagicMock())
    service.permission_service = MagicMock()
    service.repository = MagicMock()
    return service


class TestReportServiceTests(unittest.TestCase):
    def setUp(self):
        self.user = User(id=8, username="reporter", password_hash="x", is_admin=False)

    def test_list_reports_normalizes_counts_and_flow_duration(self):
        service = build_service()
        service.repository.list_reports.return_value = ([
            {
                "source_type": "flow",
                "source_id": 4,
                "project_id": 1,
                "name": "Checkout",
                "status": "failed",
                "trigger_type": "manual",
                "trigger_user_id": 8,
                "environment_id": 2,
                "environment_name": None,
                "total_count": 4,
                "passed_count": 2,
                "failed_count": 1,
                "duration_ms": None,
                "started_at": NOW,
                "finished_at": NOW + timedelta(milliseconds=400),
                "created_at": NOW,
            },
        ], 1)

        result = service.list_reports(
            project_id=1,
            current_user=self.user,
            source_type=None,
            status_filter=None,
            environment_id=None,
            started_from=None,
            started_to=None,
            page=1,
            page_size=20,
        )

        self.assertEqual(result.total, 1)
        self.assertEqual(result.items[0].id, "flow:4")
        self.assertEqual(result.items[0].skipped_count, 1)
        self.assertEqual(result.items[0].pass_rate, 50.0)
        self.assertEqual(result.items[0].duration_ms, 400)
        service.permission_service.require_project_permission.assert_called_once_with(
            self.user, 1, "report:view"
        )

    def test_list_reports_rejects_reversed_time_range(self):
        service = build_service()

        with self.assertRaises(HTTPException) as context:
            service.list_reports(
                project_id=1,
                current_user=self.user,
                source_type=None,
                status_filter=None,
                environment_id=None,
                started_from=NOW,
                started_to=NOW - timedelta(seconds=1),
                page=1,
                page_size=20,
            )

        self.assertEqual(context.exception.status_code, 400)
        service.repository.list_reports.assert_not_called()

    def test_plan_report_expands_scenario_record_runs(self):
        service = build_service()
        plan_run = TestPlanRun(
            id=10,
            plan_id=2,
            project_id=1,
            plan_name="Nightly",
            plan_version=3,
            environment_id=2,
            environment_name="test",
            status="failed",
            trigger="schedule",
            plan_snapshot={"targets": [{"id": "scenario-5"}]},
            target_results=[{
                "id": "result-10-scenario-5",
                "name": "Orders",
                "status": "failed",
                "scenario_run_ids": [21, 22],
            }],
            target_count=1,
            passed_count=0,
            failed_count=1,
            operator_id=8,
            started_at=NOW,
            finished_at=NOW + timedelta(seconds=2),
            duration_ms=2000,
            created_at=NOW,
            is_deleted=False,
        )
        scenario_runs = [
            TestScenarioRun(
                id=21,
                project_id=1,
                scenario_id=5,
                environment_id=2,
                dataset_id="DATA-1",
                record_id="RECORD-1",
                record_name="VIP",
                status="passed",
                trigger_type="schedule",
                scenario_snapshot={},
                variables_snapshot={},
                step_results=[],
                triggered_by_id=8,
                started_at=NOW,
                finished_at=NOW + timedelta(seconds=1),
                duration_ms=1000,
                created_at=NOW,
            ),
            TestScenarioRun(
                id=22,
                project_id=1,
                scenario_id=5,
                environment_id=2,
                dataset_id="DATA-1",
                record_id="RECORD-2",
                record_name="Blocked",
                status="failed",
                trigger_type="schedule",
                scenario_snapshot={},
                variables_snapshot={},
                step_results=[{"step_id": "create", "status": "failed"}],
                triggered_by_id=8,
                started_at=NOW,
                finished_at=NOW + timedelta(seconds=1),
                duration_ms=1000,
                created_at=NOW,
            ),
        ]
        service.repository.get_plan_run.return_value = plan_run
        service.repository.list_plan_scenario_runs.return_value = scenario_runs

        report = service.get_report(
            project_id=1,
            source_type="plan",
            source_id=10,
            current_user=self.user,
        )

        self.assertEqual(report.metrics["scenario_run_count"], 2)
        self.assertEqual(report.metrics["failed_scenario_run_count"], 1)
        self.assertEqual(len(report.items[0]["scenario_runs"]), 2)
        self.assertEqual(
            report.items[0]["scenario_runs"][1]["record_name"],
            "Blocked",
        )

    def test_flow_report_calculates_node_metrics(self):
        service = build_service()
        execution = VisualFlowExecution(
            id=4,
            flow_id=3,
            project_id=1,
            environment_id=2,
            status="failed",
            trigger_type="manual",
            trigger_user_id=8,
            context_snapshot={"variables": {}},
            started_at=NOW,
            finished_at=NOW + timedelta(milliseconds=500),
            created_at=NOW,
        )
        nodes = [
            VisualFlowNodeExecution(
                id=1,
                execution_id=4,
                node_id="start",
                status="passed",
                attempt=1,
            ),
            VisualFlowNodeExecution(
                id=2,
                execution_id=4,
                node_id="api",
                status="failed",
                attempt=1,
                error={"message": "timeout"},
            ),
        ]
        service.repository.get_flow_execution.return_value = (execution, "Checkout")
        service.repository.list_flow_nodes.return_value = nodes

        report = service.get_report(
            project_id=1,
            source_type="flow",
            source_id=4,
            current_user=self.user,
        )

        self.assertEqual(report.summary.total_count, 2)
        self.assertEqual(report.summary.pass_rate, 50.0)
        self.assertEqual(report.metrics["failed_node_count"], 1)
        self.assertEqual(report.items[1]["error"]["message"], "timeout")

    def test_missing_report_returns_404(self):
        service = build_service()
        service.repository.get_plan_run.return_value = None

        with self.assertRaises(HTTPException) as context:
            service.get_report(
                project_id=1,
                source_type="plan",
                source_id=999,
                current_user=self.user,
            )

        self.assertEqual(context.exception.status_code, 404)

    def test_daily_trends_calculate_pass_rate_and_other_statuses(self):
        service = build_service()
        service.repository.get_daily_trends.return_value = [{
            "date": date(2026, 6, 15),
            "total_count": 4,
            "passed_count": 2,
            "failed_count": 1,
            "avg_duration_ms": 450,
        }]

        trends = service.get_trends(
            project_id=1,
            current_user=self.user,
            source_type=None,
            environment_id=None,
            started_from=date(2026, 6, 1),
            started_to=date(2026, 6, 15),
        )

        self.assertEqual(trends.interval, "day")
        self.assertEqual(trends.points[0].pass_rate, 50.0)
        self.assertEqual(trends.points[0].other_count, 1)
        self.assertEqual(trends.points[0].avg_duration_ms, 450)

    def test_daily_trends_reject_more_than_366_days(self):
        service = build_service()

        with self.assertRaises(HTTPException) as context:
            service.get_trends(
                project_id=1,
                current_user=self.user,
                source_type=None,
                environment_id=None,
                started_from=date(2025, 1, 1),
                started_to=date(2026, 6, 15),
            )

        self.assertEqual(context.exception.status_code, 400)
        service.repository.get_daily_trends.assert_not_called()

    def test_html_export_escapes_report_content(self):
        service = build_service()
        execution = VisualFlowExecution(
            id=4,
            flow_id=3,
            project_id=1,
            environment_id=2,
            status="failed",
            trigger_type="manual",
            trigger_user_id=8,
            context_snapshot={},
            started_at=NOW,
            finished_at=NOW,
            created_at=NOW,
        )
        node = VisualFlowNodeExecution(
            id=1,
            execution_id=4,
            node_id="<script>alert(1)</script>",
            status="failed",
            attempt=1,
            error={"message": "<img src=x onerror=alert(1)>"},
        )
        service.repository.get_flow_execution.return_value = (
            execution,
            "<b>Unsafe flow</b>",
        )
        service.repository.list_flow_nodes.return_value = [node]
        report = service.get_report(
            project_id=1,
            source_type="flow",
            source_id=4,
            current_user=self.user,
        )

        rendered = service.render_html(report)

        self.assertIn("&lt;b&gt;Unsafe flow&lt;/b&gt;", rendered)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", rendered)
        self.assertNotIn("<script>alert(1)</script>", rendered)
        self.assertNotIn("<img src=x", rendered)


class TestReportOpenAPITests(unittest.TestCase):
    def test_report_routes_are_declared(self):
        from app.main import create_app

        paths = create_app().openapi()["paths"]
        self.assertIn("/api/v1/reports", paths)
        self.assertIn("/api/v1/reports/trends", paths)
        self.assertIn("/api/v1/reports/{source_type}/{source_id}", paths)
        self.assertIn("/api/v1/reports/{source_type}/{source_id}/html", paths)
        html_response = paths[
            "/api/v1/reports/{source_type}/{source_id}/html"
        ]["get"]["responses"]["200"]["content"]
        self.assertIn("text/html", html_response)


if __name__ == "__main__":
    unittest.main()
