import unittest
from datetime import datetime, timedelta

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.db.base import Base
from app.models.project import Project, ProjectEnvironment
from app.models.test_plan import TestPlanRun
from app.models.test_report import TestReportDeletion, TestReportExport
from app.models.user import User
from app.models.visual_flow import VisualFlowExecution, VisualFlowNodeExecution
from app.repositories.project_repository import ProjectRepository
from app.repositories.test_report_repository import TestReportRepository
from app.services.test_report_service import TestReportService


class TestReportDeletionIntegrationTests(unittest.TestCase):
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
        self.db.flush()
        now = datetime(2026, 7, 18, 9, 0, 0)
        self.plan_run = TestPlanRun(
            project_id=self.project.id,
            plan_name="Nightly",
            plan_version=1,
            environment_id=self.environment.id,
            environment_name="test",
            status="failed",
            trigger="manual",
            plan_snapshot={},
            target_results=[],
            target_count=0,
            passed_count=0,
            failed_count=0,
            operator_id=self.user.id,
            started_at=now,
        )
        self.flow_execution = VisualFlowExecution(
            project_id=self.project.id,
            environment_id=self.environment.id,
            status="passed",
            trigger_type="manual",
            trigger_user_id=self.user.id,
            context_snapshot={"sourceName": "Checkout"},
            started_at=now,
            finished_at=now + timedelta(seconds=1),
        )
        self.db.add_all([self.plan_run, self.flow_execution])
        self.db.flush()
        self.flow_node = VisualFlowNodeExecution(
            execution_id=self.flow_execution.id,
            node_id="start",
            status="passed",
        )
        self.report_export = TestReportExport(
            id="export-plan",
            token_hash="hash",
            project_id=self.project.id,
            source_type="plan",
            source_id=self.plan_run.id,
            created_by_id=self.user.id,
            expires_at=now + timedelta(minutes=5),
        )
        self.db.add_all([self.flow_node, self.report_export])
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_deleting_report_preserves_source_execution_and_revokes_exports(self):
        plan_run_id = self.plan_run.id
        TestReportService(self.db).delete_report(
            project_id=self.project.id,
            source_type="plan",
            source_id=plan_run_id,
            current_user=self.user,
        )

        self.assertIsNotNone(self.db.get(TestPlanRun, plan_run_id))
        self.assertIsNone(self.db.get(TestReportExport, "export-plan"))
        deletion = self.db.scalar(select(TestReportDeletion).where(
            TestReportDeletion.project_id == self.project.id,
            TestReportDeletion.source_type == "plan",
            TestReportDeletion.source_id == plan_run_id,
        ))
        self.assertIsNotNone(deletion)
        self.assertIsNone(TestReportRepository(self.db).get_plan_run(
            project_id=self.project.id,
            source_id=plan_run_id,
        ))

    def test_flow_report_deletion_preserves_flow_nodes(self):
        execution_id = self.flow_execution.id
        node_id = self.flow_node.id
        TestReportService(self.db).delete_report(
            project_id=self.project.id,
            source_type="flow",
            source_id=execution_id,
            current_user=self.user,
        )

        self.assertIsNotNone(self.db.get(VisualFlowExecution, execution_id))
        self.assertIsNotNone(self.db.get(VisualFlowNodeExecution, node_id))
        self.assertIsNone(TestReportRepository(self.db).get_flow_execution(
            project_id=self.project.id,
            source_id=execution_id,
        ))

    def test_project_deletion_removes_report_tombstones_and_exports(self):
        self.db.add(TestReportDeletion(
            project_id=self.project.id,
            source_type="flow",
            source_id=self.flow_execution.id,
            deleted_by_id=self.user.id,
        ))
        self.db.commit()
        project_id = self.project.id

        ProjectRepository(self.db).delete_project(self.project)

        self.assertIsNone(self.db.get(Project, project_id))
        self.assertIsNone(self.db.scalar(select(TestReportDeletion).where(
            TestReportDeletion.project_id == project_id
        )))
        self.assertIsNone(self.db.scalar(select(TestReportExport).where(
            TestReportExport.project_id == project_id
        )))


if __name__ == "__main__":
    unittest.main()
