import unittest
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from unittest.mock import MagicMock

from fastapi import HTTPException

from app.models.scenario import TestScenarioRun
from app.models.test_plan import TestPlanRun
from app.models.user import User
from app.models.visual_flow import VisualFlowExecution, VisualFlowNodeExecution
from app.services.test_report_service import TestReportService
from app.schemas.test_report import SupplementCaseDraftRequest


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

    def test_intelligence_overview_uses_count_free_repository_queries(self):
        service = build_service()
        service.repository.list_report_comparison_periods.return_value = [
            {
                "comparison_period": "current",
                "source_type": "plan",
                "source_id": 1,
                "project_id": 1,
                "name": "Current",
                "status": "passed",
                "trigger_type": "manual",
                "trigger_user_id": 8,
                "environment_id": None,
                "environment_name": None,
                "total_count": 10,
                "passed_count": 8,
                "failed_count": 2,
                "duration_ms": 100,
                "started_at": NOW,
                "finished_at": NOW,
                "created_at": NOW,
            },
            {
                "comparison_period": "previous",
                "source_type": "plan",
                "source_id": 2,
                "project_id": 1,
                "name": "Previous",
                "status": "passed",
                "trigger_type": "manual",
                "trigger_user_id": 8,
                "environment_id": None,
                "environment_name": None,
                "total_count": 10,
                "passed_count": 5,
                "failed_count": 5,
                "duration_ms": 100,
                "started_at": NOW - timedelta(days=7),
                "finished_at": NOW - timedelta(days=7),
                "created_at": NOW - timedelta(days=7),
            },
        ]
        service.repository.list_reports.return_value = ([], 0)
        service.db.query.return_value.filter.return_value.order_by.return_value.first.return_value = SimpleNamespace(
            created_at=NOW,
        )
        service._slow_tests = MagicMock(return_value=[])
        service._open_defect_count = MagicMock(return_value=0)

        result = service.get_intelligence_overview(
            project_id=1,
            current_user=self.user,
            environment_id=None,
            range_value="7d",
        )

        self.assertEqual(result.summary.pass_rate, 80.0)
        self.assertEqual(result.summary.pass_rate_delta, 30.0)
        self.assertEqual(result.generated_by, "rules")
        self.assertEqual(result.summary.failure_cluster_count, 1)
        self.assertEqual(len(result.pass_rate_trend), 7)
        service.repository.list_reports.assert_not_called()
        service.repository.list_report_comparison_periods.assert_called_once()

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
        self.assertEqual(report.items[0].name, "Orders")
        self.assertEqual(report.items[0].total_count, 2)
        self.assertEqual(report.items[0].passed_count, 1)
        self.assertEqual(report.items[0].failed_count, 1)

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
        self.assertEqual(report.items[1].name, "api")
        self.assertEqual(report.items[1].error_message, "timeout")
        self.assertEqual(report.items[1].total_count, 1)

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

    def test_delete_report_hides_projection_with_dedicated_permission(self):
        service = build_service()
        service.repository.get_report_status.return_value = "failed"

        service.delete_report(
            project_id=1,
            source_type="flow",
            source_id=4,
            current_user=self.user,
        )

        service.permission_service.require_project_permission.assert_called_once_with(
            self.user, 1, "report:delete"
        )
        service.repository.hide_report.assert_called_once_with(
            project_id=1,
            source_type="flow",
            source_id=4,
            deleted_by_id=8,
        )

    def test_delete_report_rejects_active_execution(self):
        service = build_service()
        service.repository.get_report_status.return_value = "running"

        with self.assertRaises(HTTPException) as context:
            service.delete_report(
                project_id=1,
                source_type="plan",
                source_id=10,
                current_user=self.user,
            )

        self.assertEqual(context.exception.status_code, 409)
        service.repository.hide_report.assert_not_called()

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

    def test_flow_report_standardizes_items_and_redacts_lazy_detail(self):
        service = build_service()
        execution = VisualFlowExecution(
            id=4,
            flow_id=3,
            project_id=1,
            environment_id=2,
            status="passed",
            trigger_type="manual",
            trigger_user_id=8,
            context_snapshot={
                "sourceName": "Checkout flow",
                "sourceVersion": 3,
                "definition": {
                    "nodes": [{
                        "id": "api",
                        "name": "Create order",
                        "kind": "api_case",
                        "referenceId": 7,
                        "method": "POST",
                        "path": "/orders",
                    }],
                },
            },
            started_at=NOW,
            finished_at=NOW + timedelta(milliseconds=500),
            created_at=NOW,
        )
        node = VisualFlowNodeExecution(
            id=2,
            execution_id=4,
            node_id="api",
            status="passed",
            attempt=1,
            request_snapshot={
                "method": "POST",
                "url": "https://example.com/orders?token=real-token",
                "headers": {
                    "Authorization": "Bearer real-token",
                    "Lingxi-Auth": "real-lingxi-token",
                    "X-API-Key": "real-api-key",
                },
                "body": {"password": "real-password", "name": "safe"},
            },
            output_snapshot={
                "durationMs": 480,
                "response": {
                    "status": 514,
                    "headers": {"Set-Cookie": "session=real"},
                    "body": {"access_token": "real-access-token"},
                },
                "assertions": [],
            },
            started_at=NOW,
            finished_at=NOW + timedelta(milliseconds=480),
        )
        service.repository.get_flow_execution.return_value = (
            execution,
            "Current name",
            "reporter",
            "test",
            3,
        )
        service.repository.list_flow_nodes.return_value = [node]

        report = service.get_report(
            project_id=1,
            source_type="flow",
            source_id=4,
            current_user=self.user,
        )
        item = report.items[0]

        self.assertEqual(report.summary.name, "Checkout flow")
        self.assertEqual(report.summary.trigger_user_name, "reporter")
        self.assertEqual(report.summary.environment_name, "test")
        self.assertEqual(item.name, "Create order")
        self.assertEqual(item.path, "/orders")
        self.assertEqual(item.response_status_code, 514)
        self.assertEqual(item.warning_flags, ["no_assertion", "non_2xx_response"])
        self.assertFalse(hasattr(item, "request_snapshot"))

        detail = service.get_report_item(
            project_id=1,
            source_type="flow",
            source_id=4,
            item_id=item.id,
            current_user=self.user,
        )

        self.assertEqual(detail.request["headers"]["Authorization"], "***")
        self.assertEqual(detail.request["headers"]["Lingxi-Auth"], "***")
        self.assertEqual(detail.request["headers"]["X-API-Key"], "***")
        self.assertEqual(detail.request["body"]["password"], "***")
        self.assertEqual(detail.response["headers"]["Set-Cookie"], "***")
        self.assertEqual(detail.response["body"]["access_token"], "***")
        self.assertNotIn("real-token", str(detail.model_dump()))

    def test_intelligence_overview_has_empty_failure_clusters_and_separate_risks(self):
        service = build_service()
        service.repository.list_report_comparison_periods.return_value = []
        service._slow_tests = MagicMock(return_value=[])
        service._open_defect_count = MagicMock(return_value=3)

        result = service.get_intelligence_overview(
            project_id=1,
            current_user=self.user,
            environment_id=4,
            range_value="7d",
        )

        self.assertEqual(result.failure_clusters, [])
        self.assertEqual(result.summary.failure_cluster_count, 0)
        self.assertEqual(
            [item.id for item in result.risk_indicators],
            ["execution_failure_risk", "slow_execution_risk", "open_defect_risk"],
        )
        self.assertEqual(result.risk_indicators[0].score, 0)
        self.assertEqual(result.risk_indicators[2].count, 3)
        self.assertEqual(len(result.stability_heatmap.labels), 7)
        self.assertEqual(result.recommendations[0].action.type, "open_trends")

    def test_one_time_export_is_scoped_and_consumed_once(self):
        service = build_service()
        report = MagicMock()
        report.summary.id = "flow:4"
        service.get_report = MagicMock(return_value=report)
        service.render_html = MagicMock(return_value="<html>safe</html>")

        created = service.create_export(
            project_id=1,
            source_type="flow",
            source_id=4,
            current_user=self.user,
        )

        report_export = service.repository.add_export.call_args.args[0]
        token = parse_qs(urlsplit(created.download_url).query)["token"][0]
        service.repository.get_export_for_update.return_value = report_export
        service._get_report_projection = MagicMock(return_value=report)
        content, filename = service.consume_export(
            export_id=created.export_id,
            token=token,
        )

        self.assertEqual(content, "<html>safe</html>")
        self.assertEqual(filename, "test-report-flow-4.html")
        self.assertIsNotNone(report_export.consumed_at)
        with self.assertRaises(HTTPException) as context:
            service.consume_export(export_id=created.export_id, token=token)
        self.assertEqual(context.exception.status_code, 410)

    def test_supplement_case_drafts_are_rule_generated_from_risk_items(self):
        service = build_service()
        report = MagicMock()
        report.summary.id = "flow:4"
        report.summary.source_type = "flow"
        report.summary.source_id = 4
        report.items = [
            SimpleNamespace(
                id="node-execution:2",
                sequence=1,
                name="Create order",
                failed_count=0,
                warning_flags=["non_2xx_response"],
            )
        ]
        service.get_report = MagicMock(return_value=report)

        result = service.generate_supplement_case_drafts(
            source_type="flow",
            source_id=4,
            payload=SupplementCaseDraftRequest(project_id=1, environment_id=2),
            current_user=self.user,
        )

        self.assertEqual(result.generated_by, "rules")
        self.assertEqual(len(result.drafts), 1)
        self.assertEqual(result.drafts[0].source_item_ids, ["node-execution:2"])
        self.assertIn("非 2xx", result.drafts[0].test_objective)


class TestReportOpenAPITests(unittest.TestCase):
    def test_report_routes_are_declared(self):
        from app.main import create_app

        paths = create_app().openapi()["paths"]
        self.assertIn("/api/v1/reports", paths)
        self.assertIn("/api/v1/reports/trends", paths)
        self.assertIn("/api/v1/reports/{source_type}/{source_id}", paths)
        self.assertIn(
            "delete",
            paths["/api/v1/reports/{source_type}/{source_id}"],
        )
        self.assertIn(
            "/api/v1/reports/{source_type}/{source_id}/items/{item_id}",
            paths,
        )
        self.assertIn(
            "/api/v1/reports/{source_type}/{source_id}/exports",
            paths,
        )
        self.assertIn(
            "/api/v1/reports/exports/{export_id}/download",
            paths,
        )
        self.assertIn(
            "/api/v1/reports/{source_type}/{source_id}/supplement-case-drafts",
            paths,
        )
        self.assertIn("/api/v1/reports/{source_type}/{source_id}/html", paths)
        html_response = paths[
            "/api/v1/reports/{source_type}/{source_id}/html"
        ]["get"]["responses"]["200"]["content"]
        self.assertIn("text/html", html_response)


if __name__ == "__main__":
    unittest.main()
