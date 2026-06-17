import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.core.permissions import ProjectPermission
from app.db.base import Base
from app.models.defect import Defect
from app.models.project import Project, ProjectEnvironment, ProjectEnvironmentVariable
from app.models.scenario import (
    TestScenario,
    TestScenarioExecution,
    TestScenarioRun,
    TestScenarioRunEvent,
    TestScenarioVersion,
)
from app.models.test_case import TestCase, TestCaseExecution
from app.models.test_plan import TestPlan, TestPlanEnvironment, TestPlanRun
from app.models.user import User
from app.models.visual_flow import (
    VisualFlow,
    VisualFlowExecution,
    VisualFlowNodeExecution,
    VisualFlowVersion,
)
from app.models.websocket_test_case import WebSocketTestCaseExecution
from app.repositories.project_repository import ProjectRepository
from app.repositories.visual_flow_repository import VisualFlowRepository
from app.services.scenario_service import ScenarioService
from app.services.test_plan_service import TestPlanService


class PhysicalDeletionTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")

        @event.listens_for(engine, "connect")
        def enable_foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.user = User(
            username="owner",
            account="owner",
            password_hash="hash",
            phone="10000000000",
            email="owner@example.com",
        )
        self.db.add(self.user)
        self.db.flush()
        self.project = Project(name="Project", created_by_id=self.user.id)
        self.db.add(self.project)
        self.db.flush()
        self.environment = ProjectEnvironment(
            project_id=self.project.id,
            name="test",
            base_url="https://example.com",
            created_by_id=self.user.id,
        )
        self.db.add(self.environment)
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_visual_flow_delete_removes_flow_and_versions(self):
        flow = VisualFlow(
            project_id=self.project.id,
            name="Flow",
            created_by_id=self.user.id,
            updated_by_id=self.user.id,
        )
        self.db.add(flow)
        self.db.flush()
        version = VisualFlowVersion(
            flow_id=flow.id,
            version=1,
            definition={"nodes": [], "edges": []},
            definition_hash="hash",
            created_by_id=self.user.id,
        )
        self.db.add(version)
        self.db.flush()
        execution = VisualFlowExecution(
            flow_id=flow.id,
            flow_version_id=version.id,
            project_id=self.project.id,
            environment_id=self.environment.id,
            status="passed",
            trigger_user_id=self.user.id,
            context_snapshot={},
        )
        self.db.add(execution)
        self.db.flush()
        node_execution = VisualFlowNodeExecution(
            execution_id=execution.id,
            node_id="start",
            status="passed",
        )
        self.db.add(node_execution)
        self.db.commit()
        flow_id, version_id, execution_id = flow.id, version.id, execution.id

        VisualFlowRepository(self.db).delete_flow(flow=flow)

        self.assertIsNone(self.db.get(VisualFlow, flow_id))
        self.assertIsNone(self.db.get(VisualFlowVersion, version_id))
        retained_execution = self.db.get(VisualFlowExecution, execution_id)
        self.assertIsNotNone(retained_execution)
        self.assertIsNone(retained_execution.flow_id)
        self.assertIsNone(retained_execution.flow_version_id)

    def test_scenario_delete_removes_scenario_and_versions(self):
        scenario = TestScenario(
            project_id=self.project.id,
            environment_id=self.environment.id,
            name="Scenario",
            tags=[],
            created_by_id=self.user.id,
            updated_by_id=self.user.id,
        )
        self.db.add(scenario)
        self.db.flush()
        version = TestScenarioVersion(
            scenario_id=scenario.id,
            version=1,
            definition={"steps": [], "datasets": []},
            created_by_id=self.user.id,
        )
        self.db.add(version)
        self.db.flush()
        run = TestScenarioRun(
            scenario_id=scenario.id,
            scenario_version_id=version.id,
            project_id=self.project.id,
            environment_id=self.environment.id,
            status="passed",
            scenario_snapshot={},
            variables_snapshot={},
            step_results=[],
            triggered_by_id=self.user.id,
            started_at=datetime.utcnow(),
        )
        self.db.add(run)
        self.db.commit()
        scenario_id, version_id, run_id = scenario.id, version.id, run.id
        service = ScenarioService(self.db)
        service.permission_service.require_project_permission = MagicMock()

        service.delete_scenario(
            project_id=self.project.id,
            scenario_id=scenario.id,
            current_user=self.user,
        )

        self.assertIsNone(self.db.get(TestScenario, scenario_id))
        self.assertIsNone(self.db.get(TestScenarioVersion, version_id))
        retained_run = self.db.get(TestScenarioRun, run_id)
        self.assertIsNotNone(retained_run)
        self.assertIsNone(retained_run.scenario_id)
        self.assertIsNone(retained_run.scenario_version_id)

    def test_plan_delete_removes_plan_and_bindings(self):
        plan = TestPlan(
            project_id=self.project.id,
            name="Plan",
            environment_ids=[self.environment.id],
            targets=[],
            notification_emails=[],
            tags=[],
            created_by_id=self.user.id,
            updated_by_id=self.user.id,
        )
        self.db.add(plan)
        self.db.flush()
        self.db.add(TestPlanEnvironment(
            plan_id=plan.id,
            project_id=self.project.id,
            environment_id=self.environment.id,
        ))
        run = TestPlanRun(
            plan_id=plan.id,
            project_id=self.project.id,
            plan_name=plan.name,
            plan_version=1,
            environment_id=self.environment.id,
            status="passed",
            trigger="manual",
            plan_snapshot={},
            target_results=[],
            operator_id=self.user.id,
            started_at=datetime.utcnow(),
        )
        self.db.add(run)
        self.db.commit()
        plan_id, run_id = plan.id, run.id
        service = TestPlanService(self.db)
        service.permission_service.require_project_permission = MagicMock()

        service.delete_plan(
            project_id=self.project.id,
            plan_id=plan.id,
            current_user=self.user,
        )

        self.assertIsNone(self.db.get(TestPlan, plan_id))
        self.assertEqual(
            self.db.scalar(
                select(func.count())
                .select_from(TestPlanEnvironment)
                .where(TestPlanEnvironment.plan_id == plan_id)
            ),
            0,
        )
        self.assertIsNone(self.db.get(TestPlanRun, run_id).plan_id)

    def test_project_delete_removes_project_owned_data(self):
        environment_id = self.environment.id
        test_case = TestCase(
            project_id=self.project.id,
            environment_id=environment_id,
            name="Case",
            method="GET",
            path="/health",
            body_type="none",
            created_by_id=self.user.id,
        )
        self.db.add(test_case)
        defect = Defect(
            project_id=self.project.id,
            title="Defect",
            bug_type="functional",
            urgency="high",
            status="new",
            content_html="<p>detail</p>",
            reporter_id=self.user.id,
        )
        self.db.add(defect)
        self.db.add(ProjectEnvironmentVariable(
            environment_id=environment_id,
            name="token",
            value="value",
        ))
        self.db.commit()
        project_id, test_case_id, defect_id = self.project.id, test_case.id, defect.id

        ProjectRepository(self.db).delete_project(self.project)

        self.assertIsNone(self.db.get(Project, project_id))
        self.assertIsNone(self.db.get(ProjectEnvironment, environment_id))
        self.assertIsNone(self.db.get(TestCase, test_case_id))
        self.assertIsNone(self.db.get(Defect, defect_id))

    def test_plan_run_delete_physically_removes_history(self):
        run = TestPlanRun(
            project_id=self.project.id,
            plan_name="Deleted plan",
            plan_version=1,
            environment_id=self.environment.id,
            status="passed",
            trigger="manual",
            plan_snapshot={},
            target_results=[],
            operator_id=self.user.id,
            started_at=datetime.utcnow(),
        )
        self.db.add(run)
        self.db.flush()
        scenario_run = TestScenarioRun(
            plan_run_id=run.id,
            project_id=self.project.id,
            environment_id=self.environment.id,
            status="passed",
            scenario_snapshot={},
            variables_snapshot={},
            step_results=[],
            triggered_by_id=self.user.id,
            started_at=datetime.utcnow(),
        )
        self.db.add(scenario_run)
        self.db.commit()
        run_id, scenario_run_id = run.id, scenario_run.id
        service = TestPlanService(self.db)
        service.permission_service.require_project_permission = MagicMock()

        service.delete_run(
            project_id=self.project.id,
            run_id=run_id,
            current_user=self.user,
        )

        self.assertIsNone(self.db.get(TestPlanRun, run_id))
        self.assertIsNone(self.db.get(TestScenarioRun, scenario_run_id).plan_run_id)

    def test_scenario_run_delete_removes_events_and_detaches_case_executions(self):
        execution = TestScenarioExecution(
            id="scenario-execution",
            project_id=self.project.id,
            status="passed",
            request_hash="hash",
            triggered_by_id=self.user.id,
        )
        self.db.add(execution)
        self.db.flush()
        run = TestScenarioRun(
            execution_id=execution.id,
            project_id=self.project.id,
            environment_id=self.environment.id,
            status="passed",
            scenario_snapshot={},
            variables_snapshot={},
            step_results=[],
            triggered_by_id=self.user.id,
            started_at=datetime.utcnow(),
        )
        self.db.add(run)
        self.db.flush()
        event_item = TestScenarioRunEvent(
            run_id=run.id,
            sequence=1,
            event="run_completed",
            payload={"status": "passed"},
            occurred_at=datetime.utcnow(),
        )
        case_execution = TestCaseExecution(
            project_id=self.project.id,
            environment_id=self.environment.id,
            scenario_run_id=run.id,
            executed_by_id=self.user.id,
            status="passed",
            request_snapshot={},
        )
        websocket_execution = WebSocketTestCaseExecution(
            project_id=self.project.id,
            environment_id=self.environment.id,
            scenario_run_id=run.id,
            executed_by_id=self.user.id,
            status="passed",
            session_snapshot={},
        )
        self.db.add_all([event_item, case_execution, websocket_execution])
        self.db.commit()
        execution_id = execution.id
        run_id = run.id
        event_id = event_item.id
        case_execution_id = case_execution.id
        websocket_execution_id = websocket_execution.id
        service = ScenarioService(self.db)
        service.permission_service.require_project_permission = MagicMock()

        service.delete_run(
            project_id=self.project.id,
            run_id=run_id,
            current_user=self.user,
        )

        self.assertIsNone(self.db.get(TestScenarioRun, run_id))
        self.assertIsNone(self.db.get(TestScenarioRunEvent, event_id))
        self.assertIsNone(self.db.get(TestScenarioExecution, execution_id))
        self.assertIsNone(
            self.db.get(TestCaseExecution, case_execution_id).scenario_run_id
        )
        self.assertIsNone(
            self.db.get(
                WebSocketTestCaseExecution, websocket_execution_id
            ).scenario_run_id
        )
        service.permission_service.require_project_permission.assert_called_once_with(
            self.user,
            self.project.id,
            ProjectPermission.MANAGE_SCENARIO.value,
        )


if __name__ == "__main__":
    unittest.main()
