import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.models.execution_diagnostic import (
    ExecutionPayloadArtifact,
    ExecutionRecordIndex,
    ExecutionStepDiagnostic,
)
from app.repositories.execution_diagnostic_repository import (
    ExecutionDiagnosticRepository,
)
from app.services.execution_diagnostic_persistence import (
    ExecutionDiagnosticPersistence,
)
from scripts.backfill_execution_diagnostics import ExecutionDiagnosticBackfillRunner
from tests.test_execution_diagnostic_projection import run_220_shape


class _FakeSourceReader:
    def __init__(self, rows):
        self.rows = rows
        self.after_ids = []

    def read_batch(
        self,
        *,
        project_id,
        execution_type,
        after_id,
        limit,
        restore_legacy_snapshots,
    ):
        self.after_ids.append(after_id)
        return [row for row in self.rows if row[0] > after_id][:limit]


class ExecutionDiagnosticStorageTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite+pysqlite:///:memory:")
        for table in (
            ExecutionRecordIndex.__table__,
            ExecutionStepDiagnostic.__table__,
            ExecutionPayloadArtifact.__table__,
        ):
            table.create(engine)
        self.db = sessionmaker(bind=engine)()

    def tearDown(self):
        self.db.close()

    def test_stage_execution_is_idempotent_and_does_not_commit(self):
        persistence = ExecutionDiagnosticPersistence(self.db)
        self.db.commit = MagicMock()

        persistence.stage_execution(
            project_id=1,
            execution_type="scenario",
            execution_id=220,
            execution=run_220_shape(),
        )
        persistence.stage_execution(
            project_id=1,
            execution_type="scenario",
            execution_id=220,
            execution=run_220_shape(),
        )
        self.db.flush()

        index_count = self.db.scalar(
            select(func.count()).select_from(ExecutionRecordIndex)
        )
        step_count = self.db.scalar(
            select(func.count()).select_from(ExecutionStepDiagnostic)
        )
        self.assertEqual(index_count, 1)
        self.assertEqual(step_count, 3)
        self.db.commit.assert_not_called()

    def test_step_identity_is_project_scoped(self):
        repository = ExecutionDiagnosticRepository(self.db)
        base = {
            "execution_type": "scenario",
            "execution_id": 220,
            "step_id": "STEP-2",
            "step_index": 2,
            "name": "failed step",
            "kind": "scenario",
            "status": "failed",
            "assertion_summary_json": [],
            "response_summary_json": {},
            "binding_summary_json": [],
            "extraction_summary_json": [],
            "retry_summary_json": {},
            "detail_json": {},
            "projection_version": "execution_diagnostic_projection_v1",
        }
        repository.upsert_step({"project_id": 1, **base})
        self.db.flush()

        self.assertIsNotNone(
            repository.get_step(
                project_id=1,
                execution_type="scenario",
                execution_id=220,
                step_id="STEP-2",
            )
        )
        self.assertIsNone(
            repository.get_step(
                project_id=2,
                execution_type="scenario",
                execution_id=220,
                step_id="STEP-2",
            )
        )

    def test_stage_step_replay_updates_without_duplicate(self):
        persistence = ExecutionDiagnosticPersistence(self.db)
        running = {"step_id": "STEP-9", "name": "request", "status": "running"}
        failed = {
            "step_id": "STEP-9",
            "name": "request",
            "status": "failed",
            "error_code": "timeout",
        }

        persistence.stage_step(
            project_id=1,
            execution_type="scenario",
            execution_id=220,
            step=running,
            fallback_index=9,
        )
        persistence.stage_step(
            project_id=1,
            execution_type="scenario",
            execution_id=220,
            step=failed,
            fallback_index=9,
        )
        self.db.flush()

        rows = self.db.scalars(select(ExecutionStepDiagnostic)).all()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].status, "failed")
        self.assertEqual(rows[0].error_code, "timeout")

    def test_backfill_resumes_strictly_after_checkpoint_and_commits_per_batch(self):
        rows = [(6, {"summary": {}, "detail": {}}), (7, {"summary": {}, "detail": {}}), (9, {"summary": {}, "detail": {}})]
        reader = _FakeSourceReader(rows)
        persistence = MagicMock()
        db = MagicMock()
        runner = ExecutionDiagnosticBackfillRunner(
            db=db,
            source_reader=reader,
            persistence=persistence,
        )

        last_id = runner.run(
            project_id=1,
            execution_type="scenario",
            after_id=5,
            batch_size=2,
            dry_run=False,
            restore_legacy_snapshots=False,
        )

        self.assertEqual(last_id, 9)
        self.assertEqual(reader.after_ids, [5, 7, 9])
        self.assertEqual(db.commit.call_count, 2)
        self.assertEqual(persistence.stage_execution.call_count, 3)

    def test_backfill_dry_run_rolls_back_every_batch(self):
        reader = _FakeSourceReader([(3, {"summary": {}, "detail": {}})])
        db = MagicMock()
        runner = ExecutionDiagnosticBackfillRunner(
            db=db,
            source_reader=reader,
            persistence=MagicMock(),
        )

        runner.run(
            project_id=1,
            execution_type="http",
            after_id=0,
            batch_size=500,
            dry_run=True,
            restore_legacy_snapshots=True,
        )

        db.commit.assert_not_called()
        db.rollback.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
