import copy
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from app.schemas.scenario import ScenarioDatasetRequest
from app.services.scenario_service import ScenarioService


class ScenarioRequestOverrideTests(unittest.TestCase):
    def setUp(self):
        self.db = MagicMock()
        self.db.scalar.return_value = 101
        self.service = ScenarioService(self.db)
        self.user = SimpleNamespace(id=7)

    @staticmethod
    def api_step():
        return {
            "id": "STEP-CREATE-ORDER",
            "kind": "api_case",
            "reference_id": 101,
            "name": "Create order",
            "config": {},
            "case_snapshot": {
                "method": "POST",
                "path": "/orders",
                "headers": {"X-Source": "scenario"},
                "query_params": {"dry_run": True},
                "body_type": "json",
                "body": {
                    "order": {
                        "customer": {"profile": {"level": "STANDARD"}},
                        "items": [{"sku": "OLD-1"}, {"sku": "OLD-2"}],
                    }
                },
                "assertions": [],
                "extractors": [],
            },
        }

    def definition(self, overrides, step=None):
        return {
            "nodes": [{
                "id": "NODE-1",
                "name": "Create order",
                "before_actions": [],
                "test_case": step or self.api_step(),
                "after_actions": [],
            }],
            "datasets": [{
                "id": "DATA-1",
                "name": "VIP customer",
                "enabled": True,
                "variables": {"tenant_id": 1001},
                "request_overrides": overrides,
            }],
        }

    @staticmethod
    def override(target, path, value, step_id="STEP-CREATE-ORDER"):
        return {
            "step_id": step_id,
            "target": target,
            "path": path,
            "value": value,
        }

    def assert_override_error(self, overrides, message):
        with self.assertRaises(HTTPException) as context:
            self.service._validate_request_overrides(self.definition(overrides))
        self.assertEqual(context.exception.status_code, 400)
        self.assertEqual(context.exception.detail["message"], message)
        self.assertEqual(context.exception.detail["dataset_id"], "DATA-1")
        self.assertEqual(
            context.exception.detail["step_id"], overrides[-1]["step_id"]
        )
        self.assertEqual(context.exception.detail["target"], overrides[-1]["target"])
        self.assertEqual(context.exception.detail["path"], overrides[-1]["path"])

    def test_schema_accepts_typed_values_and_camel_case(self):
        dataset = ScenarioDatasetRequest.model_validate({
            "id": "DATA-1",
            "name": "Typed",
            "variables": {},
            "requestOverrides": [
                {
                    "stepId": "STEP-CREATE-ORDER",
                    "target": "query_params",
                    "path": "dry_run",
                    "value": False,
                },
                {
                    "step_id": "STEP-CREATE-ORDER",
                    "target": "body",
                    "path": "order.metadata",
                    "value": {
                        "priority": 3,
                        "nullable": None,
                        "labels": ["vip", True],
                    },
                },
            ],
        })

        self.assertEqual(len(dataset.records), 1)
        self.assertIs(dataset.records[0].request_overrides[0].value, False)
        self.assertEqual(
            dataset.records[0].request_overrides[1].value,
            {"priority": 3, "nullable": None, "labels": ["vip", True]},
        )

    def test_legacy_values_expand_into_records_but_array_value_stays_typed(self):
        dataset = ScenarioDatasetRequest.model_validate({
            "id": "DATA-1",
            "name": "Customers",
            "request_overrides": [
                {
                    "step_id": "STEP-CREATE-ORDER",
                    "target": "body",
                    "path": "order.customer.profile.level",
                    "values": ["VIP", "BLOCKED"],
                },
                {
                    "step_id": "STEP-CREATE-ORDER",
                    "target": "body",
                    "path": "order.tags",
                    "value": [1, 2],
                },
            ],
        })

        self.assertEqual(
            [record.id for record in dataset.records],
            ["DATA-1-RECORD-1", "DATA-1-RECORD-2"],
        )
        self.assertEqual(
            dataset.records[0].request_overrides[0].value, "VIP"
        )
        self.assertEqual(
            dataset.records[1].request_overrides[0].value, "BLOCKED"
        )
        self.assertEqual(
            dataset.records[0].request_overrides[1].value, [1, 2]
        )
        self.assertEqual(
            dataset.records[1].request_overrides[1].value, [1, 2]
        )

    def test_explicit_records_are_preserved_in_new_response_shape(self):
        dataset = ScenarioDatasetRequest.model_validate({
            "id": "DATA-1",
            "name": "Customers",
            "variables": {"tenant_id": 1001},
            "records": [{
                "id": "RECORD-1",
                "name": "VIP",
                "enabled": True,
                "request_overrides": [{
                    "step_id": "STEP-CREATE-ORDER",
                    "target": "query_params",
                    "path": "dry_run",
                    "value": False,
                }],
            }],
        })

        dumped = dataset.model_dump()
        self.assertNotIn("request_overrides", dumped)
        self.assertEqual(dumped["records"][0]["id"], "RECORD-1")
        self.assertIs(
            dumped["records"][0]["request_overrides"][0]["value"], False
        )

    def test_nested_body_and_request_fields_are_applied_to_a_copy(self):
        step = self.api_step()
        original_snapshot = copy.deepcopy(step["case_snapshot"])
        request = copy.deepcopy(step["case_snapshot"])
        overrides = [
            self.override("path", "", "/tenants/{{tenant_id}}/orders"),
            self.override("headers", "X-Tenant", "{{tenant_id}}"),
            self.override("query_params", "dry_run", False),
            self.override("body", "order.customer.profile.level", "VIP"),
            self.override("body", "order.items[1].sku", "SKU-{{tenant_id}}"),
        ]

        self.service._apply_request_overrides(request, overrides)
        rendered = self.service._render(request, {"tenant_id": 1001})

        self.assertEqual(rendered["path"], "/tenants/1001/orders")
        self.assertEqual(rendered["headers"]["X-Tenant"], 1001)
        self.assertIs(rendered["query_params"]["dry_run"], False)
        self.assertEqual(
            rendered["body"]["order"]["customer"]["profile"]["level"], "VIP"
        )
        self.assertEqual(
            rendered["body"]["order"]["items"][1]["sku"], "SKU-1001"
        )
        self.assertEqual(step["case_snapshot"], original_snapshot)

    def test_override_runs_before_template_resolution_and_reaches_executor(self):
        step = self.api_step()
        captured = {}

        def execute(**kwargs):
            captured["payload"] = kwargs["payload"]
            return SimpleNamespace(
                id=301,
                status="passed",
                request_snapshot={
                    "url": "https://example.test/orders",
                    "body": kwargs["payload"].body,
                },
                response_snapshot={"json": {"ok": True}},
                assertion_results=[],
                error_message=None,
            )

        with patch(
            "app.services.scenario_service.TestCaseService._execute",
            side_effect=execute,
        ):
            result = self.service._execute_step(
                project_id=1,
                environment_id=2,
                step=step,
                request_overrides=[
                    self.override(
                        "body",
                        "order.customer.profile.level",
                        "{{customer_level}}",
                    ),
                    self.override("query_params", "dry_run", False),
                ],
                step_index=1,
                variables={"customer_level": "VIP"},
                previous_results=[],
                current_user=self.user,
                scenario_run_id=9,
                deadline=None,
                variable_sources={},
            )

        self.assertEqual(
            captured["payload"].body["order"]["customer"]["profile"]["level"],
            "VIP",
        )
        self.assertIs(captured["payload"].query_params["dry_run"], False)
        self.assertEqual(
            result["request_snapshot"]["body"]["order"]["customer"]["profile"]["level"],
            "VIP",
        )
        self.assertEqual(
            step["case_snapshot"]["body"]["order"]["customer"]["profile"]["level"],
            "STANDARD",
        )

    def test_no_overrides_preserves_existing_request_merge(self):
        step = self.api_step()
        step["config"] = {
            "path": "/configured-orders",
            "query_params": {"source": "config"},
        }
        captured = {}

        def execute(**kwargs):
            captured["payload"] = kwargs["payload"]
            return SimpleNamespace(
                id=302,
                status="passed",
                request_snapshot={},
                response_snapshot={"json": {}},
                assertion_results=[],
                error_message=None,
            )

        with patch(
            "app.services.scenario_service.TestCaseService._execute",
            side_effect=execute,
        ):
            self.service._execute_step(
                project_id=1,
                environment_id=2,
                step=step,
                step_index=1,
                variables={},
                previous_results=[],
                current_user=self.user,
                scenario_run_id=9,
                deadline=None,
                variable_sources={},
            )

        self.assertEqual(captured["payload"].path, "/configured-orders")
        self.assertEqual(captured["payload"].query_params, {"source": "config"})

    def test_unknown_step_is_rejected_with_field_location(self):
        overrides = [self.override("body", "order.id", 1, step_id="MISSING")]
        self.assert_override_error(
            overrides, "Request override step does not exist"
        )

    def test_unsupported_target_for_step_kind_is_rejected(self):
        websocket_step = {
            "id": "STEP-CREATE-ORDER",
            "kind": "websocket_case",
            "case_snapshot": {"path": "/events", "headers": {}},
            "config": {},
        }
        overrides = [self.override("query_params", "dry_run", False)]
        with self.assertRaises(HTTPException) as context:
            self.service._validate_request_overrides(
                self.definition(overrides, step=websocket_step)
            )
        self.assertEqual(context.exception.status_code, 400)
        self.assertEqual(
            context.exception.detail["message"],
            "Request override target is not supported by the step kind",
        )

    def test_path_target_requires_empty_field_path(self):
        overrides = [self.override("path", "nested", "/orders")]
        self.assert_override_error(
            overrides, "Request path override must use an empty field path"
        )

    def test_duplicate_override_address_is_rejected(self):
        overrides = [
            self.override("headers", "X-Tenant", "one"),
            self.override("headers", "X-Tenant", "two"),
        ]
        self.assert_override_error(overrides, "Duplicate request override")

    def test_body_path_cannot_traverse_scalar(self):
        overrides = [
            self.override("body", "order.customer.profile.level.name", "VIP")
        ]
        self.assert_override_error(
            overrides, "Body override path traverses a scalar value"
        )

    def test_body_array_index_must_exist(self):
        overrides = [self.override("body", "order.items[2].sku", "SKU-3")]
        self.assert_override_error(
            overrides, "Body override array index is invalid"
        )

    def test_record_without_id_is_rejected_with_dataset_location(self):
        definition = self.definition([])
        definition["datasets"][0] = {
            "id": "DATA-1",
            "name": "Customers",
            "records": [{
                "name": "Missing id",
                "request_overrides": [],
            }],
        }

        with self.assertRaises(HTTPException) as context:
            self.service._validate_request_overrides(definition)

        self.assertEqual(context.exception.status_code, 400)
        self.assertEqual(
            context.exception.detail["message"],
            "Dataset record must have an id and name",
        )
        self.assertEqual(context.exception.detail["dataset_id"], "DATA-1")
        self.assertIsNone(context.exception.detail["record_id"])


if __name__ == "__main__":
    unittest.main()
