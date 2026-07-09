import unittest
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.api.v1.routers import execution_center
from app.db.base import Base
from app.models.project import Project, ProjectEnvironment
from app.models.scenario import TestScenario, TestScenarioRun, TestScenarioRunEvent
from app.models.user import User


class ExecutionCenterContractTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()

        self.owner = User(
            username="owner",
            account="owner",
            password_hash="hash",
            phone="10000000000",
            email="owner@example.com",
        )
        self.db.add(self.owner)
        self.db.flush()

        self.project = Project(name="执行中心项目", created_by_id=self.owner.id)
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

        now = datetime(2026, 7, 8, 14, 30, 0)
        self.running = self._run(
            status="running",
            trigger_type="plan",
            started_at=now - timedelta(minutes=2),
        )
        self.queued = self._run(
            status="queued",
            trigger_type="manual",
            started_at=now - timedelta(minutes=1),
        )
        self.failed = self._run(
            status="failed",
            trigger_type="manual",
            started_at=now - timedelta(minutes=10),
            finished_at=now - timedelta(minutes=8),
            duration_ms=120000,
        )
        self.retrying = self._run(
            status="retrying",
            trigger_type="manual",
            started_at=now - timedelta(minutes=3),
        )
        self.db.flush()
        self.db.add(
            TestScenarioRunEvent(
                run_id=self.running.id,
                sequence=1,
                event="run.started",
                payload={"message": "worker assigned"},
                occurred_at=now,
            )
        )
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def _run(
        self,
        *,
        status: str,
        trigger_type: str,
        started_at: datetime,
        finished_at: datetime | None = None,
        duration_ms: int | None = None,
    ) -> TestScenarioRun:
        run = TestScenarioRun(
            scenario_id=self.scenario.id,
            project_id=self.project.id,
            environment_id=self.environment.id,
            status=status,
            trigger_type=trigger_type,
            scenario_snapshot={"name": self.scenario.name},
            variables_snapshot={},
            step_results=[],
            triggered_by_id=self.owner.id,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
        )
        self.db.add(run)
        return run

    def test_overview_aggregates_live_execution_statuses(self):
        response = execution_center.get_execution_center_overview(
            project_id=self.project.id,
            environment_id=self.environment.id,
            db=self.db,
            current_user=self.owner,
        )

        self.assertEqual(response["code"], 0)
        data = response["data"]
        self.assertEqual(data["queue_total"], 4)
        self.assertEqual(data["running_count"], 1)
        self.assertEqual(data["queued_count"], 1)
        self.assertEqual(data["failed_blocking_count"], 1)
        self.assertEqual(data["retrying_count"], 1)
        self.assertGreaterEqual(data["worker_total"], data["worker_online"])
        self.assertEqual(data["refresh_interval_seconds"], 15)

    def test_queue_returns_frontend_shape_from_unified_records(self):
        response = execution_center.list_execution_center_queue(
            project_id=self.project.id,
            environment_id=self.environment.id,
            page=1,
            page_size=10,
            db=self.db,
            current_user=self.owner,
        )

        self.assertEqual(response["code"], 0)
        data = response["data"]
        self.assertEqual(data["total"], 4)
        item = next(row for row in data["items"] if row["execution_id"] == self.running.id)
        self.assertEqual(item["id"], f"RUN-{self.running.id}")
        self.assertEqual(item["execution_type"], "scenario")
        self.assertEqual(item["name"], "企业信息全链路回归")
        self.assertEqual(item["trigger_type"], "plan")
        self.assertEqual(item["priority"], "P1")
        self.assertEqual(item["status"], "running")
        self.assertEqual(item["progress"], 50)
        self.assertEqual(item["attempt"], 1)
        self.assertEqual(item["max_attempts"], 3)

    def test_workers_logs_diagnosis_and_retries_are_real_views(self):
        workers = execution_center.list_execution_center_workers(
            project_id=self.project.id,
            db=self.db,
            current_user=self.owner,
        )["data"]["items"]
        self.assertTrue(workers)
        self.assertIn(workers[0]["state"], {"busy", "idle"})
        self.assertIn("scenario", workers[0]["capabilities"])

        logs = execution_center.list_execution_center_logs(
            project_id=self.project.id,
            after_sequence=0,
            limit=100,
            db=self.db,
            current_user=self.owner,
        )["data"]
        self.assertEqual(logs["items"][0]["run_id"], f"RUN-{self.running.id}")
        self.assertEqual(logs["items"][0]["level"], "info")
        self.assertEqual(logs["next_after_sequence"], logs["items"][0]["sequence"])

        diagnosis = execution_center.list_execution_center_failure_diagnosis(
            project_id=self.project.id,
            db=self.db,
            current_user=self.owner,
        )["data"]["items"]
        self.assertEqual(diagnosis[0]["run_id"], f"RUN-{self.failed.id}")
        self.assertTrue(diagnosis[0]["can_create_defect"])

        retries = execution_center.list_execution_center_retries(
            project_id=self.project.id,
            db=self.db,
            current_user=self.owner,
        )["data"]["items"]
        self.assertEqual(retries[0]["run_id"], f"RUN-{self.retrying.id}")
        self.assertEqual(retries[0]["status"], "retrying")


if __name__ == "__main__":
    unittest.main()
