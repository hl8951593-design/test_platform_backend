import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.schemas.test_plan import TestPlanUpdateRequest
from app.services.test_plan_service import TestPlanService


class TestPlanVersionBindingTests(unittest.TestCase):
    def test_update_preserves_bound_version_when_not_explicitly_changed(self):
        service = TestPlanService(MagicMock())
        service._get_environment = MagicMock()
        service._calculate_next_run = MagicMock(return_value=None)
        service._target_snapshot = MagicMock(return_value={
            "id": "scenario-9",
            "reference_id": 9,
            "kind": "scenario",
            "name": "Scenario",
            "method": "SCENARIO",
            "path": None,
            "sort_order": 1,
            "scenario_version": 3,
        })
        plan = SimpleNamespace(targets=[{
            "reference_id": 9,
            "kind": "scenario",
            "scenario_version": 3,
        }])
        payload = TestPlanUpdateRequest.model_validate({
            "version": 1,
            "name": "Plan",
            "environment_ids": [2],
            "targets": [{"reference_id": 9, "kind": "scenario", "sort_order": 1}],
        })

        service._apply_payload(plan, payload, 7, preserve_bound_versions=True)

        self.assertEqual(service._target_snapshot.call_args.kwargs["fallback_version"], 3)
        self.assertIsNone(service._target_snapshot.call_args.kwargs["requested_version"])

    def test_explicit_version_replaces_bound_version(self):
        service = TestPlanService(MagicMock())
        service._get_environment = MagicMock()
        service._calculate_next_run = MagicMock(return_value=None)
        service._target_snapshot = MagicMock(return_value={
            "id": "scenario-9",
            "reference_id": 9,
            "kind": "scenario",
            "name": "Scenario",
            "method": "SCENARIO",
            "path": None,
            "sort_order": 1,
            "scenario_version": 4,
        })
        plan = SimpleNamespace(targets=[{
            "reference_id": 9,
            "kind": "scenario",
            "scenario_version": 3,
        }])
        payload = TestPlanUpdateRequest.model_validate({
            "version": 1,
            "name": "Plan",
            "environment_ids": [2],
            "targets": [{
                "reference_id": 9,
                "kind": "scenario",
                "sort_order": 1,
                "scenario_version": 4,
            }],
        })

        service._apply_payload(plan, payload, 7, preserve_bound_versions=True)

        self.assertEqual(service._target_snapshot.call_args.kwargs["requested_version"], 4)


if __name__ == "__main__":
    unittest.main()
