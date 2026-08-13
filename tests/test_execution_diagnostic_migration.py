import importlib
import inspect
import unittest
from pathlib import Path

from sqlalchemy import BigInteger

from app.core.config import Settings


TABLE_NAMES = (
    "execution_record_index",
    "execution_step_diagnostics",
    "execution_payload_artifacts",
    "execution_metrics_hourly",
    "execution_metrics_daily",
)


class ExecutionDiagnosticMigrationTests(unittest.TestCase):
    def test_execution_history_migration_does_not_recreate_0006_owned_indexes(self):
        source = Path(
            "migrations/versions/0032_execution_history_query_indexes.py"
        ).read_text(encoding="utf-8")

        self.assertNotIn(
            'op.create_index(\n        "ix_test_case_executions_project_created_at"',
            source,
        )
        self.assertNotIn(
            'op.create_index(\n        "ix_test_case_executions_case_created_at"',
            source,
        )
        self.assertNotIn(
            'op.drop_index("ix_test_case_executions_project_created_at"',
            source,
        )
        self.assertNotIn(
            'op.drop_index("ix_test_case_executions_case_created_at"',
            source,
        )
    def test_migration_is_additive_and_points_to_current_head(self):
        module = importlib.import_module(
            "migrations.versions.0041_execution_diagnostic_read_models"
        )

        self.assertEqual(module.down_revision, "0040_agent_capability_plans")
        source = inspect.getsource(module.upgrade)
        for table in TABLE_NAMES:
            self.assertIn(table, source)
        self.assertNotIn("drop_table", source)
        self.assertNotIn("drop_column", source)

    def test_migration_downgrade_only_removes_new_read_models(self):
        module = importlib.import_module(
            "migrations.versions.0041_execution_diagnostic_read_models"
        )
        source = inspect.getsource(module.downgrade)

        for table in TABLE_NAMES:
            self.assertIn(f'op.drop_table("{table}")', source)
        for legacy_table in (
            "test_case_executions",
            "websocket_test_case_executions",
            "test_scenario_runs",
            "visual_flow_executions",
        ):
            self.assertNotIn(legacy_table, source)

    def test_models_expose_required_identity_constraints_and_big_integer_ids(self):
        models = importlib.import_module("app.models.execution_diagnostic")

        record_table = models.ExecutionRecordIndex.__table__
        step_table = models.ExecutionStepDiagnostic.__table__
        artifact_table = models.ExecutionPayloadArtifact.__table__
        self.assertIsInstance(record_table.c.id.type, BigInteger)
        self.assertIsInstance(record_table.c.execution_id.type, BigInteger)
        self.assertIsInstance(step_table.c.execution_id.type, BigInteger)
        self.assertIsInstance(artifact_table.c.execution_id.type, BigInteger)
        self.assertIn(
            "uq_execution_record_index_identity",
            {constraint.name for constraint in record_table.constraints},
        )
        self.assertIn(
            "uq_execution_step_diagnostic_identity",
            {constraint.name for constraint in step_table.constraints},
        )

    def test_runtime_limits_match_approved_spec(self):
        settings = Settings()

        self.assertEqual(settings.EXECUTION_DIAGNOSTIC_MODEL_MAX_CHARS, 12000)
        self.assertEqual(settings.EXECUTION_DIAGNOSTIC_MODEL_HARD_MAX_CHARS, 24000)
        self.assertEqual(settings.EXECUTION_ARTIFACT_INLINE_THRESHOLD_BYTES, 65536)
        self.assertEqual(settings.EXECUTION_ARTIFACT_CHUNK_BYTES, 8192)
        self.assertTrue(settings.EXECUTION_NORMALIZED_SCENARIO_STEPS_ENABLED)
        self.assertTrue(settings.EXECUTION_METRICS_SCHEDULER_ENABLED)
        self.assertEqual(settings.EXECUTION_METRICS_SCHEDULER_INTERVAL_SECONDS, 60)

    def test_ui_artifact_delivery_migration_extends_current_desktop_head(self):
        module = importlib.import_module(
            "migrations.versions.0049_ui_execution_artifact_delivery"
        )

        self.assertEqual(module.down_revision, "0048_ui_execution_runtime")
        upgrade_source = inspect.getsource(module.upgrade)
        self.assertIn("execution_artifact_upload_sessions", upgrade_source)
        self.assertIn("metadata_json", upgrade_source)
        self.assertNotIn("drop_table", upgrade_source)
        self.assertNotIn("drop_column", upgrade_source)

    def test_ui_patch_request_migration_links_applied_patch_to_command(self):
        module = importlib.import_module(
            "migrations.versions.0050_ui_execution_patch_requests"
        )

        self.assertEqual(module.down_revision, "0049_ui_execution_artifact_delivery")
        upgrade_source = inspect.getsource(module.upgrade)
        self.assertIn("request_command_id", upgrade_source)
        self.assertIn("fk_ui_runtime_patches_request_command", upgrade_source)
        self.assertIn("uq_ui_runtime_patches_request_command", upgrade_source)
        self.assertNotIn("drop_table", upgrade_source)


if __name__ == "__main__":
    unittest.main()
