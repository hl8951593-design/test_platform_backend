import unittest
from datetime import datetime
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.api.v1.routers import defects, environment_configs, projects
from app.core.read_response_cache import read_response_cache
from app.db.base import Base
from app.models.defect import Defect
from app.models.project import Project, ProjectEnvironment, ProjectEnvironmentVariable, ProjectMember
from app.models.scenario import TestScenario, TestScenarioRun
from app.models.system_test_case import SystemTestCase
from app.models.test_case import TestCase, TestCaseExecution
from app.models.test_plan import TestPlan, TestPlanRun
from app.models.user import User
from app.models.visual_flow import VisualFlow
from app.models.websocket_test_case import WebSocketTestCase
from app.schemas.project import (
    ProjectCreateRequest,
    ProjectEnvironmentCreateRequest,
    ProjectMemberGrantRequest,
    ProjectMemberUpdateRequest,
)
from app.schemas.defect import DefectCreateRequest
from app.repositories.project_repository import ProjectRepository
from app.services.project_service import ProjectService


class ProjectPageContractTests(unittest.TestCase):
    def setUp(self):
        read_response_cache.clear_all()
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
        self.member = User(
            username="测试成员",
            account="member",
            password_hash="hash",
            phone="10000000001",
            email="member@example.com",
        )
        self.db.add_all([self.owner, self.member])
        self.db.flush()

        self.project = Project(
            name="测试项目",
            description="这个主要进行灵犀相关的测试",
            created_by_id=self.owner.id,
        )
        self.db.add(self.project)
        self.db.flush()

        self.environment = ProjectEnvironment(
            project_id=self.project.id,
            name="test",
            base_url="https://www.lingxidata.cn",
            description="测试环境",
            is_default=True,
            created_by_id=self.owner.id,
        )
        self.db.add(self.environment)
        self.db.flush()

        self.db.add_all([
            ProjectMember(
                project_id=self.project.id,
                user_id=self.member.id,
                added_by_id=self.owner.id,
                is_active=True,
            ),
            ProjectEnvironmentVariable(
                environment_id=self.environment.id,
                name="Lingxi-Auth",
                value="bearer secret-token",
                is_secret=True,
            ),
            TestCase(
                project_id=self.project.id,
                environment_id=self.environment.id,
                name="企业查询接口",
                method="GET",
                path="/api/lingxi-bigdata/company",
                body_type="json",
                created_by_id=self.owner.id,
            ),
            WebSocketTestCase(
                project_id=self.project.id,
                environment_id=self.environment.id,
                name="企业消息订阅",
                path="/ws/company",
                created_by_id=self.owner.id,
            ),
            TestScenario(
                project_id=self.project.id,
                environment_id=self.environment.id,
                name="企业查询场景",
                tags=[],
                created_by_id=self.owner.id,
                updated_by_id=self.owner.id,
            ),
            TestPlan(
                project_id=self.project.id,
                name="企业回归计划",
                environment_ids=[self.environment.id],
                targets=[],
                notification_emails=[],
                tags=[],
                created_by_id=self.owner.id,
                updated_by_id=self.owner.id,
            ),
            Defect(
                project_id=self.project.id,
                title="鉴权失败",
                bug_type="功能缺陷",
                urgency="高",
                status="open",
                content_html="<p>token expired</p>",
                reporter_id=self.owner.id,
            ),
        ])
        self.db.flush()
        http_case_id = self.db.query(TestCase.id).filter_by(project_id=self.project.id).scalar()
        self.db.add(
            TestCaseExecution(
                project_id=self.project.id,
                test_case_id=http_case_id,
                environment_id=self.environment.id,
                executed_by_id=self.owner.id,
                status="passed",
                request_snapshot={},
            )
        )
        self.db.commit()

    def tearDown(self):
        self.db.close()
        read_response_cache.clear_all()

    def test_project_list_returns_members_and_stats_for_frontend_cards(self):
        response = projects.list_projects(db=self.db, current_user=self.owner)

        self.assertEqual(response["code"], 0)
        project = response["data"][0]
        self.assertEqual(project["name"], "测试项目")
        self.assertEqual(project["owner_name"], "当前用户")
        self.assertEqual(project["status"], "active")
        self.assertTrue(project["is_active"])
        self.assertIn(
            {"id": self.owner.id, "name": "当前用户", "role": "负责人"},
            project["members"],
        )
        self.assertIn(
            {"id": self.member.id, "name": "测试成员", "role": "成员"},
            project["members"],
        )

        stats = project["stats"]
        self.assertEqual(stats["api_case_count"], 2)
        self.assertEqual(stats["http_test_case_count"], 1)
        self.assertEqual(stats["test_case_count"], 2)
        self.assertEqual(stats["scenario_count"], 1)
        self.assertEqual(stats["plan_count"], 1)
        self.assertEqual(stats["run_count"], 1)
        self.assertEqual(stats["pass_rate"], 100)
        self.assertEqual(stats["defect_count"], 1)
        self.assertEqual(stats["last_execution_status"], "通过")
        self.assertIsInstance(stats["ai_recommendations"], list)
        self.assertIsInstance(stats["team_activity"], list)

    def test_project_list_uses_batch_stats_instead_of_per_project_stats_builder(self):
        def fail_if_per_project_stats(*args, **kwargs):
            raise AssertionError("project list must not build stats one project at a time")

        with patch.object(ProjectService, "_build_project_stats", fail_if_per_project_stats):
            response = projects.list_projects(db=self.db, current_user=self.owner)

        self.assertEqual(response["code"], 0)
        self.assertEqual(response["data"][0]["stats"]["api_case_count"], 2)

    def test_project_list_refresh_bypasses_the_cached_stats_snapshot(self):
        initial = projects.list_projects(db=self.db, current_user=self.owner)
        self.assertEqual(initial["data"][0]["stats"]["api_case_count"], 2)

        self.db.add(TestCase(
            project_id=self.project.id,
            environment_id=self.environment.id,
            name="新接口",
            method="GET",
            path="/api/new",
            body_type="json",
            created_by_id=self.owner.id,
        ))
        self.db.commit()

        cached = projects.list_projects(db=self.db, current_user=self.owner)
        refreshed = projects.list_projects(refresh=True, db=self.db, current_user=self.owner)

        self.assertEqual(cached["data"][0]["stats"]["api_case_count"], 2)
        self.assertEqual(refreshed["data"][0]["stats"]["api_case_count"], 3)

    def test_defect_mutation_invalidates_cached_project_aggregate(self):
        initial = projects.list_projects(db=self.db, current_user=self.owner)
        self.assertEqual(initial["data"][0]["stats"]["open_defect_count"], 1)

        defects.create_defect(
            project_id=self.project.id,
            payload=DefectCreateRequest(
                title="新增待处理缺陷",
                bug_type="functional",
                urgency="high",
                status="new",
                content_html="<p>new defect</p>",
            ),
            db=self.db,
            current_user=self.owner,
        )

        updated = projects.list_projects(db=self.db, current_user=self.owner)
        self.assertEqual(updated["data"][0]["stats"]["open_defect_count"], 2)

    def test_project_stats_count_root_runs_instead_of_nested_execution_rows(self):
        plan = self.db.query(TestPlan).filter_by(project_id=self.project.id).one()
        scenario = self.db.query(TestScenario).filter_by(project_id=self.project.id).one()
        test_case = self.db.query(TestCase).filter_by(project_id=self.project.id).one()
        plan_run = TestPlanRun(
            plan_id=plan.id,
            project_id=self.project.id,
            plan_name=plan.name,
            plan_version=1,
            environment_id=self.environment.id,
            status="passed",
            trigger="manual",
            plan_snapshot={},
            target_results=[],
            operator_id=self.owner.id,
            started_at=datetime.utcnow(),
        )
        self.db.add(plan_run)
        self.db.flush()
        scenario_run = TestScenarioRun(
            plan_run_id=plan_run.id,
            scenario_id=scenario.id,
            project_id=self.project.id,
            environment_id=self.environment.id,
            status="passed",
            scenario_snapshot={},
            variables_snapshot={},
            step_results=[],
            triggered_by_id=self.owner.id,
            started_at=datetime.utcnow(),
        )
        self.db.add(scenario_run)
        self.db.flush()
        self.db.add(TestCaseExecution(
            project_id=self.project.id,
            test_case_id=test_case.id,
            environment_id=self.environment.id,
            scenario_run_id=scenario_run.id,
            executed_by_id=self.owner.id,
            status="passed",
            request_snapshot={},
        ))
        self.db.commit()

        stats = projects.list_projects(db=self.db, current_user=self.owner)["data"][0]["stats"]

        self.assertEqual(stats["run_count"], 2)
        self.assertEqual(stats["pass_rate"], 100)
        self.assertEqual(stats["coverage_rate"], 50)
        self.assertEqual(stats["automation_rate"], 50)

    def test_testing_overview_uses_explicit_quality_semantics_and_real_resources(self):
        http_case = self.db.query(TestCase).filter_by(project_id=self.project.id).one()
        self.db.add_all([
            SystemTestCase(
                project_id=self.project.id,
                case_code="SYS-001",
                title="企业查询系统链路",
                business_module="企业查询",
                test_objective="验证企业查询主链路",
                priority="P1",
                status="ready",
                tags=[],
                created_by_id=self.owner.id,
            ),
            VisualFlow(
                project_id=self.project.id,
                name="企业查询流程",
                status="draft",
                created_by_id=self.owner.id,
                updated_by_id=self.owner.id,
            ),
            Defect(
                project_id=self.project.id,
                title="已关闭历史缺陷",
                bug_type="functional",
                urgency="low",
                status="closed",
                content_html="<p>closed</p>",
                reporter_id=self.owner.id,
            ),
            TestCaseExecution(
                project_id=self.project.id,
                test_case_id=http_case.id,
                environment_id=self.environment.id,
                executed_by_id=self.owner.id,
                status="failed",
                request_snapshot={},
                created_at=datetime(2030, 1, 1, 12, 0, 0),
            ),
        ])
        self.db.commit()

        response = projects.get_project_testing_overview(
            project_id=self.project.id,
            db=self.db,
            current_user=self.owner,
        )

        overview = response["data"]
        self.assertEqual(overview["counts"]["http_test_cases"], 1)
        self.assertEqual(overview["counts"]["websocket_test_cases"], 1)
        self.assertEqual(overview["counts"]["system_test_cases"], 1)
        self.assertEqual(overview["counts"]["flows"], 1)
        self.assertEqual(overview["counts"]["total_executions"], 2)
        self.assertEqual(overview["counts"]["passed_executions"], 1)
        self.assertEqual(overview["counts"]["failed_executions"], 1)
        self.assertEqual(overview["counts"]["open_defects"], 1)
        self.assertEqual(overview["counts"]["total_defects"], 2)
        self.assertEqual(overview["quality"]["api_execution_coverage_rate"], 50)
        self.assertEqual(overview["quality"]["api_success_coverage_rate"], 50)
        self.assertEqual(overview["latest_execution"]["resource_type"], "http_case")
        self.assertEqual(overview["latest_execution"]["resource_name"], http_case.name)
        self.assertTrue(all(isinstance(item, dict) for item in overview["recommendations"]))
        self.assertTrue(all(item["occurred_at"] for item in overview["activities"]))

    def test_member_management_preserves_implicit_owner_and_reactivates_removed_member(self):
        listed = projects.list_project_members(
            project_id=self.project.id,
            db=self.db,
            current_user=self.owner,
        )["data"]
        self.assertEqual([item["role"] for item in listed], ["owner", "viewer"])
        membership_id = listed[1]["membership_id"]

        updated = projects.update_project_member(
            project_id=self.project.id,
            user_id=self.member.id,
            payload=ProjectMemberUpdateRequest(permission_codes={"test:execute", "report:view"}),
            db=self.db,
            current_user=self.owner,
        )["data"]
        self.assertEqual(updated["id"], self.member.id)
        self.assertEqual(updated["role"], "tester")

        projects.remove_project_member(
            project_id=self.project.id,
            user_id=self.member.id,
            db=self.db,
            current_user=self.owner,
        )
        self.assertEqual(
            len(projects.list_project_members(
                project_id=self.project.id,
                db=self.db,
                current_user=self.owner,
            )["data"]),
            1,
        )

        reactivated = projects.grant_normal_tester_permissions(
            project_id=self.project.id,
            payload=ProjectMemberGrantRequest(
                user_id=self.member.id,
                permission_codes={"project:view"},
            ),
            db=self.db,
            current_user=self.owner,
        )["data"]
        self.assertEqual(reactivated["id"], membership_id)
        self.assertTrue(reactivated["is_active"])

    def test_create_project_returns_frontend_shape_with_default_stats(self):
        response = projects.create_project(
            ProjectCreateRequest(name="新项目", description="新的测试项目"),
            db=self.db,
            current_user=self.owner,
        )

        self.assertEqual(response["code"], 0)
        project = response["data"]
        self.assertEqual(project["name"], "新项目")
        self.assertEqual(project["owner_name"], "当前用户")
        self.assertEqual(project["members"], [
            {"id": self.owner.id, "name": "当前用户", "role": "负责人"},
        ])
        self.assertEqual(project["stats"]["api_case_count"], 0)
        self.assertEqual(project["stats"]["scenario_count"], 0)
        self.assertEqual(project["stats"]["run_count"], 0)
        self.assertEqual(project["stats"]["pass_rate"], 0)
        self.assertEqual(project["stats"]["ai_recommendations"], [])
        self.assertEqual(project["stats"]["team_activity"], [])

    def test_environment_configs_return_frontend_shape_and_mask_secret_variables(self):
        response = environment_configs.list_environment_configs(
            project_id=self.project.id,
            db=self.db,
            current_user=self.owner,
        )

        self.assertEqual(response["code"], 0)
        environment = response["data"][0]
        self.assertEqual(environment["name"], "test")
        self.assertEqual(environment["base_url"], "https://www.lingxidata.cn")
        self.assertTrue(environment["is_default"])
        self.assertTrue(environment["is_active"])
        self.assertEqual(environment["variables"][0]["name"], "Lingxi-Auth")
        self.assertEqual(environment["variables"][0]["value"], "***")
        self.assertTrue(environment["variables"][0]["is_secret"])

        create_response = environment_configs.create_environment_config(
            ProjectEnvironmentCreateRequest(
                name="uat",
                base_url="https://uat.lingxidata.cn",
                description="预发环境",
                is_default=False,
            ),
            project_id=self.project.id,
            db=self.db,
            current_user=self.owner,
        )
        self.assertEqual(create_response["code"], 0)
        self.assertTrue(create_response["data"]["is_active"])

    def test_environment_config_list_uses_batch_case_counts(self):
        self.db.add(
            ProjectEnvironment(
                project_id=self.project.id,
                name="uat",
                base_url="https://uat.lingxidata.cn",
                description="预发环境",
                is_default=False,
                created_by_id=self.owner.id,
            )
        )
        self.db.commit()

        def fail_if_per_environment_count(*args, **kwargs):
            raise AssertionError("environment config list must batch test-case counts")

        with patch.object(
            ProjectRepository,
            "count_test_cases_by_environment",
            fail_if_per_environment_count,
        ):
            response = environment_configs.list_environment_configs(
                project_id=self.project.id,
                db=self.db,
                current_user=self.owner,
            )

        self.assertEqual(response["code"], 0)
        self.assertEqual(len(response["data"]), 2)
        self.assertIn("test_case_count", response["data"][0])


if __name__ == "__main__":
    unittest.main()
