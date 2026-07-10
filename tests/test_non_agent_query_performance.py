import importlib
import importlib.util
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

from app.models.browser_capture import BrowserCaptureEntry
from app.models.scenario import TestScenarioRun
from app.services.scenario_service import ScenarioService


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


if __name__ == "__main__":
    unittest.main()
