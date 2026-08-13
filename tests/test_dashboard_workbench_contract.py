import unittest
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.api.v1.api import api_router
from app.db.base import Base
from app.models.dashboard import DashboardAssetDailySnapshot
from app.models.defect import Defect
from app.models.project import Project, ProjectEnvironment
from app.models.scenario import TestScenario
from app.models.system_test_case import SystemTestCase
from app.models.test_case import TestCase, TestCaseExecution
from app.models.user import User
from app.models.websocket_test_case import WebSocketTestCase
from app.schemas.dashboard import CreateDashboardAIJobRequest, CreateDashboardRegressionRunRequest
from app.services.dashboard_ai_analysis_service import DashboardAIAnalysisService
from app.services.dashboard_asset_snapshot_service import DashboardAssetSnapshotService
from app.services.dashboard_regression_service import DashboardRegressionService
from app.services.dashboard_service import DashboardService


class DashboardWorkbenchContractTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.owner = User(
            username="工作台用户",
            account="dashboard-owner",
            password_hash="hash",
            phone="18800000000",
            email="dashboard@example.com",
        )
        self.db.add(self.owner)
        self.db.flush()
        self.project = Project(name="工作台项目", created_by_id=self.owner.id)
        self.db.add(self.project)
        self.db.flush()
        self.environment = ProjectEnvironment(
            project_id=self.project.id,
            name="test",
            base_url="https://example.test",
            is_default=True,
            created_by_id=self.owner.id,
        )
        self.db.add(self.environment)
        self.db.flush()
        self.http_case = TestCase(
            project_id=self.project.id,
            environment_id=self.environment.id,
            name="查询企业",
            method="GET",
            path="/companies",
            body_type="none",
            created_by_id=self.owner.id,
        )
        self.websocket_case = WebSocketTestCase(
            project_id=self.project.id,
            environment_id=self.environment.id,
            name="企业消息",
            path="/ws/companies",
            created_by_id=self.owner.id,
        )
        self.system_case = SystemTestCase(
            project_id=self.project.id,
            case_code="SYS-001",
            title="企业查询链路",
            business_module="企业",
            test_objective="验证企业查询链路",
            status="active",
            tags=[],
            created_by_id=self.owner.id,
        )
        self.scenario = TestScenario(
            project_id=self.project.id,
            environment_id=self.environment.id,
            name="企业回归场景",
            tags=[],
            created_by_id=self.owner.id,
            updated_by_id=self.owner.id,
        )
        self.defect = Defect(
            project_id=self.project.id,
            title="企业查询失败",
            bug_type="功能缺陷",
            urgency="高",
            status="open",
            content_html="<p>assertion failed</p>",
            reporter_id=self.owner.id,
        )
        self.db.add_all([
            self.http_case,
            self.websocket_case,
            self.system_case,
            self.scenario,
            self.defect,
        ])
        self.db.flush()
        self.execution = TestCaseExecution(
            project_id=self.project.id,
            test_case_id=self.http_case.id,
            environment_id=self.environment.id,
            executed_by_id=self.owner.id,
            trigger_source="manual",
            status="failed",
            request_snapshot={},
            error_message="断言校验失败",
            created_at=datetime.now(),
        )
        self.db.add(self.execution)
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_trends_use_persisted_previous_snapshot_and_real_breakdown(self):
        previous_date = datetime.now().date() - timedelta(days=7)
        self.db.add(
            DashboardAssetDailySnapshot(
                project_id=self.project.id,
                environment_id=self.environment.id,
                scope_key=f"environment:{self.environment.id}",
                snapshot_date=previous_date,
                http_test_case_count=0,
                websocket_test_case_count=0,
                system_test_case_count=0,
                scenario_count=0,
                scenario_enabled_count=0,
                defect_open_count=0,
                defect_total_count=0,
                captured_at=datetime.combine(previous_date, datetime.min.time()),
            )
        )
        self.db.commit()

        result = DashboardAssetSnapshotService(self.db).project_asset_trends(
            project_id=self.project.id,
            environment_id=self.environment.id,
            range_value="7d",
            current_user=self.owner,
        )

        self.assertEqual(result.test_cases.current, 3)
        self.assertEqual(result.test_cases.breakdown.model_dump(), {"http": 1, "websocket": 1, "system": 1})
        self.assertEqual(result.test_cases.previous, 0)
        self.assertEqual(result.test_cases.delta_rate, 0)
        self.assertEqual(result.automation_flows.current, 1)
        self.assertEqual(result.defects.current_open, 1)
        self.assertFalse(result.historical_data_complete)
        self.assertEqual(
            [point.date for point in result.test_cases.points],
            sorted(point.date for point in result.test_cases.points),
        )
        today_snapshot = self.db.scalar(
            select(DashboardAssetDailySnapshot).where(
                DashboardAssetDailySnapshot.project_id == self.project.id,
                DashboardAssetDailySnapshot.scope_key
                == f"environment:{self.environment.id}",
                DashboardAssetDailySnapshot.snapshot_date == datetime.now().date(),
            )
        )
        self.assertIsNone(today_snapshot)

    def test_activity_feed_exposes_navigation_identity_and_normalized_status(self):
        result = DashboardService(self.db).activity_feed(
            project_id=self.project.id,
            current_user=self.owner,
            environment_id=self.environment.id,
            resource_type="http_test_case",
            status_value="failed",
        )

        self.assertEqual(result.total, 1)
        item = result.items[0]
        self.assertEqual(item.resource_id, self.http_case.id)
        self.assertEqual(item.run_id, self.execution.id)
        self.assertEqual(item.resource_name, self.http_case.name)
        self.assertEqual(item.status, "failed")
        self.assertEqual(item.action.code, "view_failure_analysis")
        self.assertEqual(item.action.resource_id, self.execution.id)

    def test_quality_overview_has_structured_actions(self):
        overview = DashboardService(self.db).quality_overview(
            project_id=self.project.id,
            current_user=self.owner,
            environment_id=self.environment.id,
            range_value="today",
            version=None,
        )

        self.assertIsNotNone(overview.activity_feed[0].resource_id)
        self.assertIsNotNone(overview.activity_feed[0].action)
        self.assertIsNotNone(overview.ai_recommendations[0].id)
        self.assertIsNotNone(overview.ai_recommendations[0].action)

    def test_defect_prediction_job_is_honest_and_does_not_require_provider(self):
        service = DashboardAIAnalysisService(self.db)
        accepted = service.create_job(
            payload=CreateDashboardAIJobRequest(
                project_id=self.project.id,
                environment_id=self.environment.id,
                range="7d",
                analysis_type="defect_prediction",
            ),
            current_user=self.owner,
        )
        service._execute(accepted.job_id)
        result = service.get_job(job_id=accepted.job_id, current_user=self.owner)

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.recommendations, [])
        self.assertIn("尚未部署", result.summary)

    def test_regression_selection_is_persisted_and_duplicate_active_run_conflicts(self):
        payload = CreateDashboardRegressionRunRequest(
            project_id=self.project.id,
            environment_id=self.environment.id,
            scope_type="smart",
            strategy="failed_first",
            include_http=True,
            include_websocket=False,
            include_system_cases=False,
        )
        service = DashboardRegressionService(self.db)
        created = service.create_run(payload=payload, current_user=self.owner)

        self.assertEqual(created.status, "queued")
        self.assertEqual(created.run_type, "batch_test_case")
        self.assertEqual(created.target_count, 1)
        with self.assertRaises(HTTPException) as context:
            service.create_run(payload=payload, current_user=self.owner)
        self.assertEqual(context.exception.status_code, 409)

    def test_defect_prediction_insight_reports_unavailable(self):
        result = DashboardService(self.db).insight_detail(
            insight_type="defect-prediction",
            project_id=self.project.id,
            current_user=self.owner,
            environment_id=self.environment.id,
            range_value="7d",
        )

        self.assertFalse(result.available)
        self.assertEqual(result.metrics, [])
        self.assertEqual(result.items, [])

    def test_risk_insight_paginates_real_failed_executions_and_defects(self):
        result = DashboardService(self.db).insight_detail(
            insight_type="risk-analysis",
            project_id=self.project.id,
            current_user=self.owner,
            environment_id=self.environment.id,
            range_value="7d",
            page=1,
            page_size=1,
        )

        self.assertTrue(result.available)
        self.assertEqual(result.total, 2)
        self.assertEqual(result.page, 1)
        self.assertEqual(result.page_size, 1)
        self.assertEqual(len(result.items), 1)
        self.assertIsNotNone(result.items[0].resource_id)

    def test_workbench_routes_are_registered(self):
        status_by_route = {
            (route.path, method): route.status_code
            for route in api_router.routes
            for method in getattr(route, "methods", set())
        }
        self.assertIn(("/dashboard/project-asset-trends", "GET"), status_by_route)
        self.assertIn(("/dashboard/activity-feed", "GET"), status_by_route)
        self.assertEqual(status_by_route[("/dashboard/ai-analysis-jobs", "POST")], 202)
        self.assertEqual(status_by_route[("/dashboard/regression-runs", "POST")], 202)
        self.assertIn(("/dashboard/insights/{insight_type}", "GET"), status_by_route)


if __name__ == "__main__":
    unittest.main()
