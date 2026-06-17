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
                "steps": [{"id": "step-1"}],
                "datasets": [
                    {"id": "enabled", "name": "Enabled", "enabled": True, "variables": {}},
                    {"id": "disabled", "name": "Disabled", "enabled": False, "variables": {}},
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


if __name__ == "__main__":
    unittest.main()
