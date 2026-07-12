import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.execution_diagnostic import ExecutionRecordIndex
from app.core.config import settings
from app.models.execution_diagnostic import (
    ExecutionPayloadArtifact,
    ExecutionStepDiagnostic,
)
from app.schemas.execution_record import ExecutionRecordCursorPage
from app.services.execution_diagnostic_persistence import ExecutionDiagnosticPersistence
from app.services.execution_diagnostic_service import ScenarioStepResultAssembler
from app.services.execution_record_service import ExecutionRecordService
from app.services.scenario_service import ScenarioService
from tests.test_execution_diagnostic_projection import run_220_shape


BASE_TIME = datetime(2026, 7, 13, 8, 0, 0)


class ExecutionDiagnosticScalingTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite+pysqlite:///:memory:")
        for table in (
            ExecutionRecordIndex.__table__,
            ExecutionStepDiagnostic.__table__,
            ExecutionPayloadArtifact.__table__,
        ):
            table.create(engine)
        self.db = sessionmaker(bind=engine)()
        self.service = ExecutionRecordService(self.db)
        self.service.permission_service = MagicMock()
        self.user = SimpleNamespace(id=7)
        for index in range(5):
            self._insert(
                execution_id=index + 1,
                started_at=BASE_TIME - timedelta(minutes=index),
            )
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def _insert(self, *, execution_id: int, started_at: datetime):
        self.db.add(
            ExecutionRecordIndex(
                project_id=1,
                execution_type="http",
                execution_id=execution_id,
                object_ref=f"http:{execution_id}",
                resource_id=100 + execution_id,
                resource_name=f"case-{execution_id}",
                environment_id=4,
                status="passed",
                trigger_type="manual",
                trigger_user_id=7,
                duration_ms=10,
                total_steps=1,
                passed_steps=1,
                failed_steps=0,
                timeout_steps=0,
                skipped_steps=0,
                started_at=started_at,
                finished_at=started_at + timedelta(milliseconds=10),
                source_updated_at=started_at,
                projection_version="execution_diagnostic_projection_v1",
            )
        )

    def _page(self, *, cursor=None, include_total=False):
        return self.service.list_records_cursor(
            project_id=1,
            current_user=self.user,
            execution_type=None,
            status_filter=None,
            environment_id=None,
            trigger_user_id=None,
            started_from=None,
            started_to=None,
            keyword=None,
            cursor=cursor,
            limit=2,
            include_total=include_total,
        )

    def test_cursor_page_is_stable_when_newer_record_arrives(self):
        first = self._page()
        self.assertIsInstance(first, ExecutionRecordCursorPage)
        self.assertTrue(first.has_more)

        self._insert(execution_id=99, started_at=BASE_TIME + timedelta(minutes=1))
        self.db.commit()
        second = self._page(cursor=first.next_cursor)

        first_ids = {item.id for item in first.items}
        second_ids = {item.id for item in second.items}
        self.assertTrue(first_ids.isdisjoint(second_ids))
        self.assertNotIn("http:99", second_ids)

    def test_cursor_page_skips_exact_count_by_default(self):
        self.service.diagnostic_repository.count_records = MagicMock(
            wraps=self.service.diagnostic_repository.count_records
        )

        page = self._page(include_total=False)

        self.assertIsNone(page.total)
        self.service.diagnostic_repository.count_records.assert_not_called()

    def test_cursor_page_computes_total_only_when_requested(self):
        page = self._page(include_total=True)

        self.assertEqual(page.total, 5)
        self.assertEqual(page.returned, 2)

    def test_cursor_rejects_malformed_and_oversized_values(self):
        for cursor in ("not-base64", "x" * 513):
            with self.subTest(cursor_length=len(cursor)):
                with self.assertRaises(HTTPException) as raised:
                    self._page(cursor=cursor)
                self.assertEqual(raised.exception.status_code, 422)

    def test_normalized_steps_assemble_legacy_contract(self):
        ExecutionDiagnosticPersistence(self.db).stage_execution(
            project_id=1,
            execution_type="scenario",
            execution_id=220,
            execution=run_220_shape(),
        )
        snapshot = {
            "nodes": [
                {
                    "id": "NODE-1",
                    "before_actions": [],
                    "test_case": {
                        "id": "STEP-1",
                        "kind": "api_case",
                        "name": "获取企业列表",
                    },
                    "after_actions": [
                        {
                            "id": "STEP-1-AFTER-1",
                            "kind": "delay",
                            "name": "获取企业列表-AFTER_ACTIONS-1",
                        }
                    ],
                },
                {
                    "id": "NODE-2",
                    "before_actions": [],
                    "test_case": {
                        "id": "STEP-2",
                        "kind": "api_case",
                        "name": "获取对应企业CT画像数",
                    },
                    "after_actions": [],
                },
            ]
        }

        result = ScenarioStepResultAssembler(self.db).assemble_scenario_step_results(
            project_id=1,
            execution_id=220,
            scenario_snapshot=snapshot,
            include_artifacts=True,
        )

        self.assertEqual(result[0]["name"], "获取企业列表")
        self.assertEqual(result[2]["assertion_results"][1]["actual"], 90001)

    def test_ten_thousand_steps_do_not_rewrite_growing_run_json(self):
        db = MagicMock()
        scenario_service = ScenarioService(db)
        scenario_service.diagnostic_persistence = MagicMock()
        run = SimpleNamespace(
            id=220,
            project_id=1,
            step_results=[],
            variables_snapshot={},
        )

        for index in range(10000):
            scenario_service._persist_step_result_normalized(
                run=run,
                result={
                    "step_id": f"STEP-{index}",
                    "step_index": index,
                    "name": f"step {index}",
                    "kind": "delay",
                    "status": "passed",
                },
                variables={},
                variable_sources={},
                fallback_index=index,
            )

        self.assertEqual(
            scenario_service.diagnostic_persistence.stage_step.call_count,
            10000,
        )
        self.assertEqual(run.step_results, [])
        db.commit.assert_not_called()

    def test_agent_assembly_keeps_artifact_refs_while_full_assembly_hydrates(self):
        persistence = ExecutionDiagnosticPersistence(self.db)
        persistence.stage_step(
            project_id=1,
            execution_type="scenario",
            execution_id=221,
            step={
                "step_id": "STEP-1",
                "step_index": 0,
                "name": "large response",
                "kind": "api_case",
                "status": "failed",
                "response_snapshot": {"body": "x" * 70000},
            },
            fallback_index=0,
        )
        snapshot = {
            "nodes": [
                {
                    "id": "NODE-1",
                    "before_actions": [],
                    "test_case": {
                        "id": "STEP-1",
                        "name": "large response",
                        "kind": "api_case",
                    },
                    "after_actions": [],
                }
            ]
        }
        assembler = ScenarioStepResultAssembler(self.db)

        agent_view = assembler.assemble_scenario_step_results(
            project_id=1,
            execution_id=221,
            scenario_snapshot=snapshot,
            include_artifacts=False,
        )
        full_view = assembler.assemble_scenario_step_results(
            project_id=1,
            execution_id=221,
            scenario_snapshot=snapshot,
            include_artifacts=True,
        )

        self.assertTrue(agent_view[0]["response_snapshot"]["externalized"])
        self.assertEqual(full_view[0]["response_snapshot"]["body"], "x" * 70000)

    def test_rollback_flag_preserves_legacy_step_result_snapshot_writes(self):
        scenario_service = ScenarioService(MagicMock())
        scenario_service.diagnostic_persistence = MagicMock()
        run = SimpleNamespace(
            id=220,
            project_id=1,
            step_results=[],
            variables_snapshot={},
        )
        completed = {
            "step_id": "STEP-1",
            "step_index": 0,
            "name": "done",
            "kind": "delay",
            "status": "passed",
        }
        pending = {"id": "STEP-2", "name": "next", "kind": "delay"}

        with patch.object(
            settings, "EXECUTION_NORMALIZED_SCENARIO_STEPS_ENABLED", False
        ):
            scenario_service._persist_step_result(
                run,
                [completed],
                {},
                {},
                [pending],
                1,
            )

        self.assertEqual([item["status"] for item in run.step_results], ["passed", "pending"])


if __name__ == "__main__":
    unittest.main()
