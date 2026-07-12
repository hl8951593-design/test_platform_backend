import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.scenario_service import ScenarioService


def _run(**overrides):
    values = {
        "id": 220,
        "project_id": 1,
        "scenario_id": 45,
        "scenario_version_id": 3,
        "environment_id": 4,
        "dataset_id": None,
        "record_id": None,
        "status": "running",
        "trigger_type": "agent_dry_run",
        "triggered_by_id": 7,
        "started_at": datetime(2026, 7, 12, 10, 0, 0),
        "finished_at": None,
        "duration_ms": None,
        "step_results": [],
        "variables_snapshot": {},
        "last_event_sequence": 0,
        "current_step_id": None,
        "current_step_index": None,
        "execution_id": 99,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _failed_step():
    return {
        "step_id": "STEP-2",
        "step_index": 1,
        "name": "CT image count",
        "kind": "api_case",
        "status": "failed",
        "error_code": "ASSERTION_FAILED",
    }


class ExecutionDiagnosticWritePathTests(unittest.TestCase):
    def setUp(self):
        self.db = MagicMock()
        self.db.scalar.return_value = None
        self.service = ScenarioService(self.db)
        self.service.diagnostic_persistence = MagicMock()

    def test_scenario_step_projection_reuses_event_commit(self):
        run = _run()
        result = _failed_step()

        self.service._persist_step_result(run, [result], {}, {}, [], 1)

        self.service.diagnostic_persistence.stage_step.assert_called_once_with(
            project_id=1,
            execution_type="scenario",
            execution_id=220,
            step=result,
            fallback_index=0,
        )
        self.db.commit.assert_not_called()

        self.service._append_event(
            run,
            3,
            "step_failed",
            {"step_id": "STEP-2", "status": "failed"},
        )
        self.assertEqual(self.db.commit.call_count, 1)

    def test_diagnostic_execution_view_requires_no_database_query(self):
        run = _run(status="failed", duration_ms=4282)

        result = self.service._diagnostic_execution_view(run, [_failed_step()])

        self.assertEqual(result["summary"]["id"], "scenario:220")
        self.assertEqual(result["summary"]["status"], "failed")
        self.assertEqual(result["detail"]["step_results"][0]["step_id"], "STEP-2")
        self.db.scalar.assert_not_called()

    def test_queued_context_failure_stages_index_before_existing_commit(self):
        execution = SimpleNamespace(
            id=99,
            status="running",
            finished_at=None,
        )
        run = _run()
        self.db.scalars.return_value = SimpleNamespace(all=lambda: [run])
        self.db.get.return_value = SimpleNamespace(version=3)
        timeline = []
        self.service.diagnostic_persistence.stage_execution.side_effect = (
            lambda **_: timeline.append("diagnostic")
        )
        self.service._append_event = MagicMock(
            side_effect=lambda *_, **__: timeline.append("event")
        )
        self.db.commit.side_effect = lambda: timeline.append("commit")

        self.service._fail_queued_execution(execution, "missing environment")

        self.assertEqual(timeline, ["diagnostic", "event", "commit"])
        self.service.diagnostic_persistence.stage_execution.assert_called_once()


if __name__ == "__main__":
    unittest.main()
