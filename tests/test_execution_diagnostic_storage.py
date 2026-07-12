import unittest
import gzip
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi import HTTPException
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
from app.services.execution_payload_store import DatabaseExecutionPayloadStore
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

    def test_large_response_is_externalized_and_round_trips_by_chunk(self):
        store = DatabaseExecutionPayloadStore(self.db)
        value = {"body": "测" * 40000, "authorization": "Bearer secret"}

        ref = store.put(
            project_id=1,
            execution_type="scenario",
            execution_id=220,
            step_id="STEP-1",
            section="response",
            value=value,
        )
        self.db.flush()
        chunks = []
        offset = 0
        while True:
            chunk = store.read_chunk(
                project_id=1,
                artifact_ref=ref,
                offset=offset,
                max_bytes=8192,
            )
            chunks.append(chunk.content)
            if not chunk.has_more:
                break
            offset = chunk.next_offset

        artifact = self.db.scalar(
            select(ExecutionPayloadArtifact).where(
                ExecutionPayloadArtifact.artifact_ref == ref
            )
        )
        self.assertEqual(chunk.sha256, artifact.sha256)
        self.assertLess(artifact.stored_size_bytes, artifact.raw_size_bytes)
        self.assertEqual(store.read_all(project_id=1, artifact_ref=ref), {
            "body": "测" * 40000,
            "authorization": "***",
        })
        self.assertEqual(json.loads("".join(chunks)), {
            "body": "测" * 40000,
            "authorization": "***",
        })

    def test_artifact_is_hidden_from_other_projects(self):
        store = DatabaseExecutionPayloadStore(self.db)
        ref = store.put(
            project_id=1,
            execution_type="scenario",
            execution_id=220,
            step_id="STEP-1",
            section="response",
            value={"body": "x" * 100000},
        )
        self.db.flush()

        with self.assertRaises(HTTPException) as raised:
            store.read_chunk(
                project_id=2,
                artifact_ref=ref,
                offset=0,
                max_bytes=8192,
            )

        self.assertEqual(raised.exception.status_code, 404)

    def test_missing_artifact_returns_not_found_and_chunk_size_is_capped(self):
        store = DatabaseExecutionPayloadStore(self.db)
        with self.assertRaises(HTTPException) as raised:
            store.read_chunk(
                project_id=1,
                artifact_ref="execution-artifact://1/scenario/220/missing",
                offset=0,
                max_bytes=8192,
            )
        self.assertEqual(raised.exception.status_code, 404)

        ref = store.put(
            project_id=1,
            execution_type="scenario",
            execution_id=220,
            step_id="STEP-1",
            section="response",
            value={"body": "x" * 100000},
        )
        chunk = store.read_chunk(
            project_id=1,
            artifact_ref=ref,
            offset=0,
            max_bytes=999999,
        )
        self.assertLessEqual(len(chunk.content.encode("utf-8")), 65536)

    def test_artifact_integrity_failure_is_rejected(self):
        store = DatabaseExecutionPayloadStore(self.db)
        ref = store.put(
            project_id=1,
            execution_type="scenario",
            execution_id=220,
            step_id="STEP-1",
            section="response",
            value={"body": "x" * 100000},
        )
        artifact = self.db.scalar(
            select(ExecutionPayloadArtifact).where(
                ExecutionPayloadArtifact.artifact_ref == ref
            )
        )
        artifact.content = gzip.compress(b'{"body":"tampered"}', mtime=0)
        self.db.flush()

        with self.assertRaises(HTTPException) as raised:
            store.read_chunk(
                project_id=1,
                artifact_ref=ref,
                offset=0,
                max_bytes=8192,
            )

        self.assertEqual(raised.exception.status_code, 409)

    def test_stage_step_externalizes_large_sections_independently(self):
        persistence = ExecutionDiagnosticPersistence(self.db)
        persistence.stage_step(
            project_id=1,
            execution_type="scenario",
            execution_id=220,
            step={
                "step_id": "STEP-LARGE",
                "name": "large request",
                "status": "failed",
                "request": {"body": "r" * 70000},
                "response": {"body": "s" * 70000},
                "logs": ["l" * 70000],
                "attempt_history": [{"error": "e" * 70000}],
            },
            fallback_index=1,
        )
        self.db.flush()

        row = self.db.scalar(select(ExecutionStepDiagnostic))
        artifacts = self.db.scalars(select(ExecutionPayloadArtifact)).all()
        self.assertEqual(len(artifacts), 4)
        self.assertTrue(row.detail_json["request"]["externalized"])
        self.assertTrue(row.detail_json["response"]["externalized"])
        self.assertTrue(row.detail_json["logs"]["externalized"])
        self.assertTrue(row.detail_json["attempt_history"]["externalized"])
        self.assertEqual(row.request_artifact_ref, row.detail_json["request"]["artifact_ref"])
        self.assertEqual(row.response_artifact_ref, row.detail_json["response"]["artifact_ref"])


if __name__ == "__main__":
    unittest.main()
