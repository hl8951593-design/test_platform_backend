import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.scenario_service import ScenarioService


class ScenarioRealtimeEventTests(unittest.TestCase):
    def setUp(self):
        self.db = MagicMock()
        self.service = ScenarioService(self.db)
        self.user = SimpleNamespace(id=7)

    @staticmethod
    def delay_step(step_id):
        return {
            "id": step_id,
            "kind": "delay",
            "name": step_id,
            "config": {"duration_ms": 0},
            "continue_on_failure": False,
        }

    def run_with_events(self, steps):
        run = SimpleNamespace(
            id=11,
            scenario_id=5,
            project_id=3,
            environment_id=2,
            dataset_id="DATA-1",
            status="queued",
            started_at=None,
            finished_at=None,
            duration_ms=None,
            current_step_id=None,
            current_step_index=None,
            step_results=[],
            variables_snapshot={},
        )
        events = []

        def append_event(_, __, event, data, commit=True):
            events.append((event, data))

        self.service._append_event = MagicMock(side_effect=append_event)
        self.service._run_dataset(
            run=run,
            definition={
                "nodes": [
                    {
                        "id": f"NODE-{index}",
                        "name": step["name"],
                        "before_actions": [],
                        "test_case": step,
                        "after_actions": [],
                    }
                    for index, step in enumerate(steps, start=1)
                ]
            },
            variables={},
            current_user=self.user,
            scenario_version=4,
            deadline=None,
            emit_events=True,
        )
        return run, events

    def test_successful_run_emits_contract_order(self):
        run, events = self.run_with_events([
            self.delay_step("STEP-1"),
            self.delay_step("STEP-2"),
        ])

        self.assertEqual(
            [event for event, _ in events],
            [
                "run_started",
                "step_started",
                "step_completed",
                "transition_started",
                "step_started",
                "step_completed",
                "run_completed",
            ],
        )
        self.assertEqual(events[1][1]["step_index"], 0)
        self.assertEqual(events[4][1]["step_index"], 1)
        self.assertEqual(run.status, "passed")
        self.assertEqual([item["step_index"] for item in run.step_results], [0, 1])

    def test_failure_skips_remaining_steps(self):
        condition = {
            "id": "STEP-1",
            "kind": "condition",
            "name": "Stop",
            "config": {"expression": "False"},
            "continue_on_failure": False,
        }
        run, events = self.run_with_events([
            condition,
            self.delay_step("STEP-2"),
        ])

        self.assertEqual(
            [event for event, _ in events],
            [
                "run_started",
                "step_started",
                "step_failed",
                "step_skipped",
                "run_failed",
            ],
        )
        self.assertEqual(run.status, "failed")
        self.assertEqual(run.step_results[1]["status"], "skipped")

    def test_realtime_index_does_not_change_step_variable_names(self):
        variables = {}
        result = self.service._execute_step(
            project_id=3,
            environment_id=2,
            step=self.delay_step("STEP-1"),
            step_index=0,
            variable_step_index=1,
            variables=variables,
            previous_results=[],
            current_user=self.user,
            scenario_run_id=11,
            deadline=None,
            variable_sources={},
        )

        self.assertEqual(result["step_index"], 0)
        self.assertIn("step_1", variables)
        self.assertNotIn("step_0", variables)


if __name__ == "__main__":
    unittest.main()
