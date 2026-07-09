import unittest
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.api.v1.api import api_router
from app.api.v1.routers import dashboard, test_reports
from app.db.base import Base
from app.models.defect import Defect
from app.models.project import Project, ProjectEnvironment
from app.models.scenario import TestScenario, TestScenarioRun
from app.models.test_case import TestCase, TestCaseExecution
from app.models.test_plan import TestPlanRun
from app.models.user import User
from app.services.dashboard_service import DashboardService


class FrontendAnalyticsContractTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()

        self.owner = User(
            username="当前用户",
            account="owner",
            password_hash="hash",
            phone="10000000000",
            email="owner@example.com",
        )
        self.db.add(self.owner)
        self.db.flush()

        self.project = Project(name="质量大盘项目", created_by_id=self.owner.id)
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

        self.case = TestCase(
            project_id=self.project.id,
            environment_id=self.environment.id,
            name="企业查询接口",
            method="GET",
            path="/api/company",
            body_type="json",
            created_by_id=self.owner.id,
        )
        self.db.add(self.case)
        self.db.flush()

        self.scenario = TestScenario(
            project_id=self.project.id,
            environment_id=self.environment.id,
            name="企业信息全链路回归",
            tags=[],
            created_by_id=self.owner.id,
            updated_by_id=self.owner.id,
        )
        self.db.add(self.scenario)
        self.db.flush()

        now = datetime(2026, 7, 8, 15, 30, 0)
        self.db.add_all([
            TestCaseExecution(
                project_id=self.project.id,
                test_case_id=self.case.id,
                environment_id=self.environment.id,
                executed_by_id=self.owner.id,
                status="passed",
                request_snapshot={},
                duration_ms=1200,
                created_at=now - timedelta(days=1),
            ),
            TestCaseExecution(
                project_id=self.project.id,
                test_case_id=self.case.id,
                environment_id=self.environment.id,
                executed_by_id=self.owner.id,
                status="failed",
                request_snapshot={},
                error_message="gateway timeout",
                duration_ms=5200,
                created_at=now,
            ),
            TestScenarioRun(
                scenario_id=self.scenario.id,
                project_id=self.project.id,
                environment_id=self.environment.id,
                status="failed",
                trigger_type="manual",
                scenario_snapshot={"name": self.scenario.name},
                variables_snapshot={},
                step_results=[{"name": "企业查询接口", "status": "failed", "error": "timeout"}],
                triggered_by_id=self.owner.id,
                started_at=now,
                finished_at=now + timedelta(seconds=4),
                duration_ms=4000,
            ),
            TestPlanRun(
                plan_id=None,
                project_id=self.project.id,
                plan_name="企业回归计划",
                plan_version=1,
                environment_id=self.environment.id,
                environment_name="test",
                status="passed",
                trigger="manual",
                plan_snapshot={},
                target_results=[],
                target_count=2,
                passed_count=1,
                failed_count=1,
                operator_id=self.owner.id,
                started_at=now,
                finished_at=now + timedelta(seconds=8),
                duration_ms=8000,
            ),
            Defect(
                project_id=self.project.id,
                title="企业查询超时",
                bug_type="功能缺陷",
                urgency="高",
                status="open",
                content_html="<p>timeout</p>",
                reporter_id=self.owner.id,
                updated_at=now,
            ),
        ])
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_report_intelligence_overview_matches_frontend_shape(self):
        response = test_reports.get_report_intelligence_overview(
            project_id=self.project.id,
            environment_id=self.environment.id,
            range_value="7d",
            db=self.db,
            current_user=self.owner,
        )

        self.assertEqual(response["code"], 0)
        data = response["data"]
        self.assertIn("generated_at", data)
        self.assertIn("summary", data)
        self.assertIn("pass_rate", data["summary"])
        self.assertIn("failure_cluster_count", data["summary"])
        self.assertGreaterEqual(data["summary"]["slow_test_count"], 1)
        self.assertTrue(data["pass_rate_trend"])
        self.assertTrue(data["risk_indicators"])
        self.assertTrue(data["failure_clusters"])
        self.assertEqual(data["failure_clusters"][0]["priority"], "P0")
        self.assertTrue(data["slow_tests"])
        self.assertIn("duration_ms", data["slow_tests"][0])
        self.assertTrue(data["stability_heatmap"])
        self.assertTrue(data["ai_recommendations"])

    def test_dashboard_quality_overview_matches_frontend_shape(self):
        response = dashboard.get_quality_overview(
            project_id=self.project.id,
            environment_id=self.environment.id,
            range_value="today",
            version="V3.2.1",
            db=self.db,
            current_user=self.owner,
        )

        self.assertEqual(response["code"], 0)
        data = response["data"]
        self.assertEqual(data["scope"]["project_id"], self.project.id)
        self.assertEqual(data["scope"]["environment_id"], self.environment.id)
        self.assertEqual(data["scope"]["range"], "today")
        self.assertEqual(data["scope"]["version"], "V3.2.1")
        self.assertIn("health_score", data["hero"])
        self.assertIsInstance(data["kpis"], list)
        self.assertIn("label", data["kpis"][0])
        self.assertTrue(data["risk_matrix"])
        self.assertTrue(data["automation_efficiency"])
        self.assertTrue(data["health_profile"]["dimensions"])
        self.assertTrue(data["defect_predictions"])
        self.assertTrue(data["ai_recommendations"])
        self.assertTrue(data["activity_feed"])

    def test_dashboard_activity_feed_uses_resource_names_instead_of_ids(self):
        response = dashboard.get_quality_overview(
            project_id=self.project.id,
            environment_id=self.environment.id,
            range_value="today",
            version="V3.2.1",
            db=self.db,
            current_user=self.owner,
        )

        titles = [item["title"] for item in response["data"]["activity_feed"]]

        self.assertTrue(any(self.case.name in title for title in titles))
        self.assertTrue(any(self.scenario.name in title for title in titles))
        self.assertFalse(any(f"HTTP 用例 {self.case.id}" in title for title in titles))
        self.assertFalse(any(f"场景 {self.scenario.id}" in title for title in titles))

    def test_quality_overview_uses_aggregate_queries_instead_of_materializing_execution_rows(self):
        service = DashboardService(self.db)

        def fail_if_materialized(*args, **kwargs):
            raise AssertionError("quality_overview must not materialize full execution rows")

        service._execution_rows = fail_if_materialized

        overview = service.quality_overview(
            project_id=self.project.id,
            environment_id=self.environment.id,
            range_value="today",
            version=None,
            current_user=self.owner,
        )

        self.assertGreaterEqual(overview.hero.health_score, 0)

    def test_frontend_analytics_routes_are_registered(self):
        registered = {(route.path, ",".join(sorted(route.methods))) for route in api_router.routes}

        self.assertIn(("/reports/intelligence-overview", "GET"), registered)
        self.assertIn(("/dashboard/quality-overview", "GET"), registered)


if __name__ == "__main__":
    unittest.main()
