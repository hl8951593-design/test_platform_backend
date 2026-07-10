import importlib
import importlib.util
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.db.base import Base
from app.models.browser_capture import BrowserCapture, BrowserCaptureEntry
from app.models.project import Project, ProjectEnvironment
from app.models.scenario import TestScenarioRun
from app.models.test_plan import TestPlan, TestPlanRun
from app.models.user import User
from app.schemas.browser_capture import BrowserCaptureEntryBatchRequest
from app.services.browser_capture_service import BrowserCaptureService
from app.services.scenario_service import ScenarioService
from app.services.test_plan_service import TestPlanService


class ScenarioRunQueryPerformanceTests(unittest.TestCase):
    def test_list_query_defers_snapshot_but_detail_query_keeps_full_entity(self):
        db = MagicMock()
        db.scalar.return_value = 0
        db.scalars.return_value.all.return_value = []
        service = ScenarioService(db)
        service.permission_service.require_project_permission = MagicMock()

        service.list_runs(
            project_id=7,
            scenario_id=None,
            current_user=SimpleNamespace(id=9),
            page=1,
            page_size=20,
        )

        list_statement = db.scalars.call_args.args[0]
        list_sql = str(
            list_statement.compile(compile_kwargs={"literal_binds": True})
        ).lower()
        self.assertNotIn("scenario_snapshot", list_sql)

        db.reset_mock()
        db.scalar.return_value = SimpleNamespace(status="passed")
        service.get_run(
            project_id=7,
            run_id=3,
            current_user=SimpleNamespace(id=9),
        )

        detail_statement = db.scalar.call_args.args[0]
        detail_sql = str(
            detail_statement.compile(compile_kwargs={"literal_binds": True})
        ).lower()
        self.assertIn("scenario_snapshot", detail_sql)


class NonAgentQueryIndexTests(unittest.TestCase):
    def test_model_metadata_contains_ordered_query_indexes(self):
        scenario_indexes = {
            index.name: index for index in TestScenarioRun.__table__.indexes
        }
        capture_indexes = {
            index.name: index for index in BrowserCaptureEntry.__table__.indexes
        }

        self.assertIn(
            "ix_test_scenario_runs_project_started_id",
            scenario_indexes,
        )
        self.assertEqual(
            [
                column.name
                for column in scenario_indexes[
                    "ix_test_scenario_runs_project_started_id"
                ].columns
            ],
            ["project_id", "started_at", "id"],
        )
        self.assertIn(
            "ix_browser_capture_entries_capture_id_order",
            capture_indexes,
        )
        self.assertEqual(
            [
                column.name
                for column in capture_indexes[
                    "ix_browser_capture_entries_capture_id_order"
                ].columns
            ],
            ["capture_id", "id"],
        )

    def test_migration_creates_and_drops_only_the_query_indexes(self):
        module_name = (
            "migrations.versions.0038_non_agent_query_performance_indexes"
        )
        if importlib.util.find_spec(module_name) is None:
            self.fail("0038 non-Agent query performance migration is missing")
        migration = importlib.import_module(module_name)

        self.assertEqual(
            migration.down_revision,
            "0037_browser_capture_analysis_audit_fields",
        )
        with patch.object(migration.op, "create_index") as create_index:
            migration.upgrade()
        self.assertEqual(
            create_index.call_args_list,
            [
                call(
                    "ix_test_scenario_runs_project_started_id",
                    "test_scenario_runs",
                    ["project_id", "started_at", "id"],
                    unique=False,
                ),
                call(
                    "ix_browser_capture_entries_capture_id_order",
                    "browser_capture_entries",
                    ["capture_id", "id"],
                    unique=False,
                ),
            ],
        )

        with patch.object(migration.op, "drop_index") as drop_index:
            migration.downgrade()
        self.assertEqual(
            drop_index.call_args_list,
            [
                call(
                    "ix_browser_capture_entries_capture_id_order",
                    table_name="browser_capture_entries",
                ),
                call(
                    "ix_test_scenario_runs_project_started_id",
                    table_name="test_scenario_runs",
                ),
            ],
        )


class TestPlanQueryPerformanceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine, expire_on_commit=False)()
        self.user = User(
            username="planner",
            account="planner",
            password_hash="hash",
            phone="13000000001",
            email="planner@example.com",
        )
        self.db.add(self.user)
        self.db.flush()
        self.project = Project(name="Plan performance", created_by_id=self.user.id)
        self.db.add(self.project)
        self.db.flush()

        plans = [
            TestPlan(
                project_id=self.project.id,
                name="Manual enabled",
                enabled=True,
                trigger_type="manual",
                environment_ids=[],
                targets=[],
                notification_emails=[],
                tags=[],
                created_by_id=self.user.id,
                updated_by_id=self.user.id,
            ),
            TestPlan(
                project_id=self.project.id,
                name="Cron enabled",
                enabled=True,
                trigger_type="cron",
                environment_ids=[],
                targets=[],
                notification_emails=[],
                tags=[],
                created_by_id=self.user.id,
                updated_by_id=self.user.id,
            ),
            TestPlan(
                project_id=self.project.id,
                name="Manual disabled",
                enabled=False,
                trigger_type="manual",
                environment_ids=[],
                targets=[],
                notification_emails=[],
                tags=[],
                created_by_id=self.user.id,
                updated_by_id=self.user.id,
            ),
        ]
        self.db.add_all(plans)
        self.db.flush()
        for status in ("failed", "passed"):
            self.db.add(TestPlanRun(
                plan_id=plans[0].id,
                project_id=self.project.id,
                plan_name=plans[0].name,
                plan_version=1,
                status=status,
                trigger="manual",
                plan_snapshot={},
                target_results=[],
                operator_id=self.user.id,
                started_at=datetime(2026, 7, 11, 10, 0, 0),
            ))
        self.db.commit()
        self.service = TestPlanService(self.db)
        self.service.permission_service.require_project_permission = MagicMock()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _list_with_statement_count(self, **filters):
        statements = []

        def record_statement(_conn, _cursor, statement, _params, _context, _many):
            statements.append(statement)

        event.listen(self.engine, "before_cursor_execute", record_statement)
        try:
            result = self.service.list_plans(
                project_id=self.project.id,
                current_user=self.user,
                keyword=filters.get("keyword"),
                enabled=filters.get("enabled"),
                trigger_type=filters.get("trigger_type"),
                page=1,
                page_size=20,
            )
        finally:
            event.remove(self.engine, "before_cursor_execute", record_statement)
        return result, statements

    def test_unfiltered_list_reuses_project_total_and_bounds_sql(self):
        result, statements = self._list_with_statement_count()

        self.assertEqual(result["total"], 3)
        self.assertEqual(result["statistics"], {
            "total": 3,
            "enabled": 2,
            "scheduled": 1,
            "recent_failed": 1,
        })
        self.assertLessEqual(len(statements), 2)

    def test_filtered_list_keeps_project_statistics_and_bounds_sql(self):
        result, statements = self._list_with_statement_count(enabled=False)

        self.assertEqual(result["total"], 1)
        self.assertEqual([plan.name for plan in result["items"]], ["Manual disabled"])
        self.assertEqual(result["statistics"], {
            "total": 3,
            "enabled": 2,
            "scheduled": 1,
            "recent_failed": 1,
        })
        self.assertLessEqual(len(statements), 3)


class BrowserCaptureUpsertPerformanceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine, expire_on_commit=False)()
        self.user = User(
            username="capture-owner",
            account="capture-owner",
            password_hash="hash",
            phone="13000000002",
            email="capture-owner@example.com",
        )
        self.db.add(self.user)
        self.db.flush()
        self.project = Project(
            name="Capture performance",
            created_by_id=self.user.id,
        )
        self.db.add(self.project)
        self.db.flush()
        environment = ProjectEnvironment(
            project_id=self.project.id,
            name="test",
            base_url="https://example.test",
            is_default=True,
            created_by_id=self.user.id,
        )
        self.db.add(environment)
        self.db.flush()
        self.capture = BrowserCapture(
            project_id=self.project.id,
            environment_id=environment.id,
            name="Capture",
            created_by_id=self.user.id,
        )
        self.db.add(self.capture)
        self.db.commit()
        self.service = BrowserCaptureService(self.db)
        self.service.permission_service.require_project_permission = MagicMock()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    @staticmethod
    def _entry(client_id: str, *, name: str | None = None):
        return {
            "client_entry_id": client_id,
            "protocol": "http",
            "fingerprint": f"fingerprint-{client_id}",
            "name": name or f"GET /items/{client_id}",
            "method": "GET",
            "path": f"/items/{client_id}",
            "source_url": f"https://example.test/items/{client_id}",
            "request_data": {},
            "response_data": {"status_code": 200},
            "draft_data": {},
            "captured_at": "2026-07-11T10:00:00+08:00",
        }

    def _upsert(self, entries):
        return self.service.upsert_entries(
            project_id=self.project.id,
            capture_id=self.capture.id,
            payload=BrowserCaptureEntryBatchRequest(entries=entries),
            current_user=self.user,
        )

    def test_new_and_mixed_batches_preserve_order_and_update_identity(self):
        initial = self._upsert([
            self._entry("entry-2"),
            self._entry("entry-1"),
        ])
        original_id = initial[0].id
        self.assertEqual(
            [entry.client_entry_id for entry in initial],
            ["entry-2", "entry-1"],
        )

        mixed = self._upsert([
            self._entry("entry-2", name="Updated entry"),
            self._entry("entry-3"),
        ])

        self.assertEqual(
            [entry.client_entry_id for entry in mixed],
            ["entry-2", "entry-3"],
        )
        self.assertEqual(mixed[0].id, original_id)
        self.assertEqual(mixed[0].name, "Updated entry")
        self.assertTrue(all(isinstance(entry.id, int) for entry in mixed))
        stored_count = self.db.query(BrowserCaptureEntry).filter(
            BrowserCaptureEntry.capture_id == self.capture.id,
        ).count()
        self.assertEqual(stored_count, 3)

    def test_one_hundred_new_entries_use_constant_query_count(self):
        statements = []

        def record_statement(_conn, _cursor, statement, _params, _context, _many):
            statements.append(statement)

        event.listen(self.engine, "before_cursor_execute", record_statement)
        try:
            result = self._upsert([
                self._entry(f"entry-{index}")
                for index in range(100)
            ])
        finally:
            event.remove(self.engine, "before_cursor_execute", record_statement)

        select_count = sum(
            statement.lstrip().upper().startswith("SELECT")
            for statement in statements
        )
        self.assertEqual(len(result), 100)
        self.assertEqual(
            [entry.client_entry_id for entry in result],
            [f"entry-{index}" for index in range(100)],
        )
        self.assertLessEqual(len(statements), 10)
        self.assertLessEqual(select_count, 4)


if __name__ == "__main__":
    unittest.main()
