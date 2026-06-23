import unittest
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import MagicMock

from pydantic import ValidationError
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.core.sensitive_data import encrypt_sensitive
from app.schemas.scenario import ScenarioCreateRequest
from app.services.scenario_script_sandbox import run_scenario_script
from app.services.scenario_service import ScenarioService

_convert_definition = import_module(
    "migrations.versions.0020_migrate_scenarios_to_nodes"
)._convert_definition


def api_case(step_id: str = "STEP-1") -> dict:
    return {
        "id": step_id,
        "kind": "api_case",
        "referenceId": 11,
        "name": "Login",
        "method": "POST",
        "path": "/login",
        "config": {},
        "continueOnFailure": False,
    }


class ScenarioNodeSchemaTests(unittest.TestCase):
    def payload(self) -> dict:
        return {
            "name": "Login flow",
            "environmentId": 1,
            "nodes": [{
                "id": "NODE-1",
                "name": "Login",
                "beforeActions": [{
                    "id": "ACTION-1",
                    "kind": "fixed_value",
                    "name": "Set tenant",
                    "config": {"output": "tenant_id", "value": 1001},
                }],
                "testCase": api_case(),
                "afterActions": [{
                    "id": "ACTION-2",
                    "kind": "delay",
                    "name": "Settle",
                    "config": {"duration_ms": 0},
                }],
            }],
        }

    def test_camel_case_aliases_are_accepted_and_dumped_as_snake_case(self):
        payload = ScenarioCreateRequest.model_validate(self.payload())
        dumped = payload.model_dump()

        self.assertEqual(dumped["environment_id"], 1)
        self.assertEqual(dumped["nodes"][0]["test_case"]["reference_id"], 11)
        self.assertIn("before_actions", dumped["nodes"][0])

    def test_legacy_steps_and_execution_phase_are_rejected(self):
        payload = self.payload()
        payload["steps"] = [api_case()]
        payload["nodes"][0]["testCase"]["execution_phase"] = "main"

        with self.assertRaises(ValidationError):
            ScenarioCreateRequest.model_validate(payload)

    def test_invalid_action_configs_are_rejected(self):
        payload = self.payload()
        payload["nodes"][0]["beforeActions"][0] = {
            "id": "ACTION-1",
            "kind": "random",
            "name": "Bad range",
            "config": {"type": "integer", "min": 2, "max": 1, "output": "value"},
        }

        with self.assertRaises(ValidationError):
            ScenarioCreateRequest.model_validate(payload)


class ScenarioNodeExecutionTests(unittest.TestCase):
    def setUp(self):
        self.service = ScenarioService(MagicMock())
        self.user = SimpleNamespace(id=7)

    def test_execution_order_is_bound_to_node_containers(self):
        steps = self.service._execution_steps({
            "nodes": [{
                "id": "NODE-1",
                "name": "Login",
                "before_actions": [{"id": "BEFORE", "kind": "delay", "name": "Before"}],
                "test_case": {"id": "CASE", "kind": "api_case", "name": "Case"},
                "after_actions": [{"id": "AFTER", "kind": "delay", "name": "After"}],
            }]
        })

        self.assertEqual([step["id"] for step in steps], ["BEFORE", "CASE", "AFTER"])
        self.assertEqual(
            [step["_node_phase"] for step in steps],
            ["before", "test_case", "after"],
        )

    def test_fixed_value_keeps_json_type_and_script_uses_declared_io(self):
        variables = {}
        sources = {}
        fixed = {
            "id": "FIXED",
            "kind": "fixed_value",
            "name": "Set flags",
            "config": {"output": "flags", "value": {"enabled": True}},
        }
        result = self.service._execute_step(
            project_id=1, environment_id=1, step=fixed, step_index=1,
            variables=variables, previous_results=[], current_user=self.user,
            scenario_run_id=1, deadline=None, variable_sources=sources,
        )

        self.assertEqual(result["status"], "passed")
        self.assertEqual(variables["flags"], {"enabled": True})
        outputs = run_scenario_script(
            language="python",
            code="result = {'count': value + 1}",
            inputs={"value": 2},
            outputs=["result"],
            timeout_ms=1000,
        )
        self.assertEqual(outputs, {"result": {"count": 3}})

    def test_condition_supports_typed_placeholders_and_json_literals(self):
        self.assertTrue(self.service._evaluate_condition(
            "{{status}} == 'ready' and {{count}} >= -1 and true != null",
            {"status": "ready", "count": 0},
            [],
        ))

    def test_script_sandbox_rejects_imports(self):
        with self.assertRaises(RuntimeError):
            run_scenario_script(
                language="python",
                code="import os\nresult = os.getcwd()",
                inputs={},
                outputs=["result"],
                timeout_ms=1000,
            )

    def test_duplicate_name_during_create_returns_conflict(self):
        db = MagicMock()
        db.flush.side_effect = IntegrityError(
            "INSERT INTO test_scenarios", {}, Exception("duplicate")
        )
        service = ScenarioService(db)
        service._require_manage = MagicMock()
        service._validated_definition = MagicMock(return_value={"nodes": [], "datasets": []})
        payload = SimpleNamespace(
            environment_id=1,
            name="测试场景",
            description=None,
            tags=[],
        )

        with self.assertRaises(HTTPException) as context:
            service.create_scenario(
                project_id=1,
                payload=payload,
                current_user=SimpleNamespace(id=1),
            )

        self.assertEqual(context.exception.status_code, 409)
        self.assertEqual(context.exception.detail, "同一项目下场景名称不能重复")
        db.rollback.assert_called_once_with()

    def test_detail_includes_environment_name(self):
        db = MagicMock()
        db.scalar.return_value = "UAT"
        service = ScenarioService(db)
        service._get_version = MagicMock(return_value=SimpleNamespace(
            definition=encrypt_sensitive({
                "nodes": [{
                    "id": "NODE-1",
                    "name": "Login",
                    "before_actions": [],
                    "test_case": {
                        "id": "CASE-1",
                        "kind": "api_case",
                        "name": "Login",
                        "case_snapshot": {"headers": {}},
                    },
                    "after_actions": [],
                }],
                "datasets": [],
            })
        ))
        scenario = SimpleNamespace(
            id=14,
            project_id=1,
            environment_id=2,
            current_version=1,
            name="登录场景",
            description=None,
            tags=[],
            created_at=None,
            updated_at=None,
            last_run_at=None,
        )

        detail = service._detail(scenario)

        self.assertEqual(detail["environment_name"], "UAT")
        self.assertEqual(detail["environment_id"], 2)
        self.assertNotIn("case_snapshot", detail["nodes"][0]["test_case"])


class ScenarioNodeMigrationTests(unittest.TestCase):
    def test_unambiguous_phases_are_converted_once(self):
        converted = _convert_definition(1, {
            "steps": [
                {"id": "SETUP", "kind": "fixed_value", "execution_phase": "setup", "continue_on_failure": True},
                {"id": "CASE-1", "kind": "api_case", "name": "One", "continue_on_failure": True},
                {"id": "CASE-2", "kind": "websocket_case", "name": "Two", "continue_on_failure": True},
                {"id": "CLEAN", "kind": "script", "execution_phase": "teardown"},
            ],
            "datasets": [],
        })

        self.assertNotIn("steps", converted)
        self.assertEqual(len(converted["nodes"]), 2)
        self.assertEqual(converted["nodes"][0]["before_actions"][0]["id"], "SETUP")
        self.assertEqual(converted["nodes"][1]["after_actions"][0]["id"], "CLEAN")

    def test_ambiguous_main_action_blocks_migration(self):
        with self.assertRaises(ValueError):
            _convert_definition(2, {
                "steps": [
                    {"id": "CASE", "kind": "api_case"},
                    {"id": "WAIT-1", "kind": "delay", "continue_on_failure": False},
                    {"id": "WAIT-2", "kind": "delay"},
                ]
            })

    def test_action_between_cases_binds_before_the_next_case(self):
        converted = _convert_definition(3, {
            "steps": [
                {"id": "CASE-1", "kind": "api_case", "name": "One"},
                {"id": "GATE", "kind": "condition", "name": "Gate"},
                {"id": "CASE-2", "kind": "api_case", "name": "Two"},
            ]
        })

        self.assertEqual(converted["nodes"][0]["after_actions"], [])
        self.assertEqual(
            converted["nodes"][1]["before_actions"][0]["id"], "GATE"
        )


if __name__ == "__main__":
    unittest.main()
