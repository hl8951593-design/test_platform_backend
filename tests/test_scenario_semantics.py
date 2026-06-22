import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi import HTTPException

from app.services.scenario_service import ScenarioService


class ScenarioDatasetSemanticsTests(unittest.TestCase):
    def setUp(self):
        self.db = MagicMock()
        self.service = ScenarioService(self.db)
        self.service.permission_service.require_project_permission = MagicMock()
        self.service._get_environment = MagicMock()
        self.service._idempotent = MagicMock(return_value=None)
        self.service._execute_dataset = MagicMock(side_effect=lambda **kwargs: kwargs["dataset"]["id"])
        self.scenario = SimpleNamespace(id=11, project_id=7, environment_id=3, last_run_at=None)
        self.version = SimpleNamespace(
            id=21,
            version=2,
            definition={
                "nodes": [{
                    "id": "node-1",
                    "name": "Node 1",
                    "before_actions": [],
                    "test_case": {"id": "step-1", "kind": "api_case"},
                    "after_actions": [],
                }],
                "datasets": [
                    {
                        "id": "enabled", "name": "Enabled", "enabled": True,
                        "variables": {}, "records": [{"id": "R-1", "name": "Record", "enabled": True, "request_overrides": []}],
                    },
                    {
                        "id": "disabled", "name": "Disabled", "enabled": False,
                        "variables": {}, "records": [{"id": "R-2", "name": "Record", "enabled": True, "request_overrides": []}],
                    },
                ],
            },
        )
        self.service._get_scenario = MagicMock(return_value=self.scenario)
        self.service._get_version = MagicMock(return_value=self.version)
        self.user = SimpleNamespace(id=5)

    def execute(self, dataset_ids):
        return self.service.execute_scenario(
            project_id=7,
            scenario_id=11,
            environment_id=3,
            dataset_ids=dataset_ids,
            idempotency_key=None,
            current_user=self.user,
        )

    def test_omitted_dataset_ids_runs_only_enabled_datasets(self):
        self.assertEqual(self.execute(None), ["enabled"])

    def test_empty_dataset_ids_runs_nothing(self):
        self.assertEqual(self.execute([]), [])

    def test_explicit_dataset_can_select_disabled_dataset(self):
        self.assertEqual(self.execute(["disabled"]), ["disabled"])

    def test_unknown_dataset_is_rejected(self):
        with self.assertRaises(HTTPException) as context:
            self.execute(["missing"])
        self.assertEqual(context.exception.status_code, 400)

    def test_scenario_without_datasets_runs_once_with_empty_variables(self):
        self.version.definition["datasets"] = []
        self.service._execute_dataset.side_effect = lambda **kwargs: kwargs["dataset"]["id"]
        self.assertEqual(self.execute(None), [None])

    def test_each_enabled_record_creates_an_independent_run(self):
        self.version.definition["datasets"] = [{
            "id": "records",
            "name": "Records",
            "enabled": True,
            "variables": {"tenant_id": 1001},
            "records": [
                {
                    "id": "RECORD-1",
                    "name": "VIP",
                    "enabled": True,
                    "request_overrides": [],
                },
                {
                    "id": "RECORD-2",
                    "name": "Blocked",
                    "enabled": True,
                    "request_overrides": [],
                },
                {
                    "id": "RECORD-3",
                    "name": "Disabled",
                    "enabled": False,
                    "request_overrides": [],
                },
            ],
        }]
        self.service._execute_dataset.side_effect = (
            lambda **kwargs: kwargs["dataset"]["record_id"]
        )

        self.assertEqual(self.execute(None), ["RECORD-1", "RECORD-2"])
        calls = self.service._execute_dataset.call_args_list
        self.assertEqual(calls[0].kwargs["dataset"]["variables"], {"tenant_id": 1001})
        self.assertEqual(calls[1].kwargs["dataset"]["record_name"], "Blocked")


class ScenarioNodeActionTests(unittest.TestCase):
    def test_before_failure_skips_case_but_always_runs_every_after_action(self):
        db = MagicMock()
        service = ScenarioService(db)
        executed: list[str] = []

        def execute_step(**kwargs):
            step_id = kwargs["step"]["id"]
            executed.append(step_id)
            return {
                "step_id": step_id,
                "status": "passed" if step_id == "teardown-2" else "failed",
            }

        service._execute_step = MagicMock(side_effect=execute_step)
        run = SimpleNamespace(
            id=101,
            project_id=7,
            environment_id=3,
            status="queued",
            started_at=None,
            finished_at=None,
            step_results=[],
            variables_snapshot={},
            current_step_id=None,
            current_step_index=None,
            duration_ms=None,
        )
        definition = {
            "nodes": [{
                "id": "node-1",
                "name": "Node 1",
                "before_actions": [
                    {"id": "setup", "name": "Setup", "kind": "condition", "continue_on_failure": False},
                ],
                "test_case": {"id": "main", "name": "Main", "kind": "api_case", "continue_on_failure": False},
                "after_actions": [
                    {"id": "teardown-1", "name": "Cleanup 1", "kind": "delay", "continue_on_failure": False},
                    {"id": "teardown-2", "name": "Cleanup 2", "kind": "delay", "continue_on_failure": False},
                ],
            }]
        }

        service._run_dataset(
            run=run,
            definition=definition,
            variables={},
            current_user=SimpleNamespace(id=5),
            scenario_version=1,
            deadline=None,
            emit_events=False,
        )

        self.assertEqual(executed, ["setup", "teardown-1", "teardown-2"])
        self.assertEqual([item["step_id"] for item in run.step_results], [
            "setup", "main", "teardown-1", "teardown-2",
        ])
        self.assertEqual(run.step_results[1]["status"], "skipped")
        self.assertEqual(run.status, "failed")


if __name__ == "__main__":
    unittest.main()
