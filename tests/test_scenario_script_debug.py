import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.schemas.scenario import ScenarioScriptExecuteUnsavedRequest
from app.services.scenario_service import ScenarioService


def build_service():
    db = MagicMock()
    db.scalar.return_value = 1
    service = ScenarioService(db)
    service.permission_service = SimpleNamespace(require_project_permission=lambda *args: None)
    return service


class ScenarioScriptDebugTests(unittest.TestCase):
    def test_execute_unsaved_script_returns_outputs_without_persisting_inputs(self):
        service = build_service()

        result = service.execute_unsaved_script_action(
            project_id=1,
            payload=ScenarioScriptExecuteUnsavedRequest(
                environment_id=2,
                language="python",
                code="result = companyId != 1",
                inputs=["companyId"],
                outputs=["result"],
                timeout_ms=10000,
                input_values={"companyId": 9527},
            ),
            current_user=SimpleNamespace(id=7),
        )

        self.assertEqual(result.status, "passed")
        self.assertEqual(result.outputs, {"result": True})
        self.assertEqual(result.error_message, "")
        self.assertGreaterEqual(result.duration_ms, 0)

    def test_missing_debug_input_is_reported_as_script_failure(self):
        service = build_service()

        result = service.execute_unsaved_script_action(
            project_id=1,
            payload=ScenarioScriptExecuteUnsavedRequest(
                environment_id=2,
                language="python",
                code="result = companyId != 1",
                inputs=["companyId"],
                outputs=["result"],
                input_values={},
            ),
            current_user=SimpleNamespace(id=7),
        )

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.outputs, {})
        self.assertIn("NameError", result.error_message)

    def test_unsaved_script_debug_reuses_import_restriction(self):
        service = build_service()

        result = service.execute_unsaved_script_action(
            project_id=1,
            payload=ScenarioScriptExecuteUnsavedRequest(
                environment_id=2,
                language="python",
                code="import os\nresult = True",
                outputs=["result"],
                input_values={},
            ),
            current_user=SimpleNamespace(id=7),
        )

        self.assertEqual(result.status, "failed")
        self.assertIn("Import", result.error_message)


class ScenarioScriptDebugOpenAPITests(unittest.TestCase):
    def test_unsaved_script_debug_routes_are_declared(self):
        from app.main import create_app

        paths = create_app().openapi()["paths"]

        self.assertIn("/api/v1/scenarios/actions/script/execute-unsaved", paths)
        self.assertIn("/api/v1/scenarios/actions/script/execute-unsave", paths)
        self.assertIn("/api/v1/scenario-actions/script/execute-unsaved", paths)


if __name__ == "__main__":
    unittest.main()
