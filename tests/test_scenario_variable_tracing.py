import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.scenario_service import ScenarioService


class ScenarioVariableTracingTests(unittest.TestCase):
    def setUp(self):
        self.db = MagicMock()
        self.db.scalar.return_value = 101
        self.service = ScenarioService(self.db)
        self.user = SimpleNamespace(id=7)
        self.variables = {}
        self.variable_sources = {}

    @staticmethod
    def api_step(step_id, name, config):
        return {
            "id": step_id,
            "kind": "api_case",
            "reference_id": 101,
            "name": name,
            "config": config,
            "case_snapshot": {
                "method": "GET",
                "path": "/companies",
                "headers": {},
                "query_params": {},
                "body_type": "none",
                "body": None,
                "assertions": [],
                "extractors": [],
            },
        }

    def execute_step(self, step, response_snapshot):
        execution = SimpleNamespace(
            id=301,
            status="passed",
            request_snapshot={
                "method": "GET",
                "url": "https://api.example.com/companies",
                "headers": {"Authorization": "***"},
            },
            response_snapshot=response_snapshot,
            assertion_results=[{
                "name": "HTTP status",
                "status": "passed",
                "expected": 200,
                "actual": 200,
            }],
            error_message=None,
        )
        with patch(
            "app.services.scenario_service.TestCaseService._execute",
            return_value=execution,
        ):
            return self.service._execute_step(
                project_id=1,
                environment_id=2,
                step=step,
                step_index=1,
                variables=self.variables,
                previous_results=[],
                current_user=self.user,
                scenario_run_id=9,
                deadline=None,
                variable_sources=self.variable_sources,
            )

    def test_extracted_values_preserve_json_types(self):
        step = self.api_step(
            "STEP-1",
            "Get company",
            {
                "_scenario_context": {
                    "extractions": [
                        {"id": "VAR-1", "name": "companyId", "path": "data.id"},
                        {"id": "VAR-2", "name": "active", "path": "data.active"},
                        {"id": "VAR-3", "name": "metadata", "path": "data.metadata"},
                        {"id": "VAR-4", "name": "optional", "path": "data.optional"},
                    ]
                }
            },
        )

        result = self.execute_step(
            step,
            {
                "json": {
                    "data": {
                        "id": 9527,
                        "active": True,
                        "metadata": {"tier": "enterprise"},
                        "optional": None,
                    }
                }
            },
        )

        values = {
            item["name"]: item["value"] for item in result["extracted_variables"]
        }
        self.assertEqual(values["companyId"], 9527)
        self.assertIs(values["active"], True)
        self.assertEqual(values["metadata"], {"tier": "enterprise"})
        self.assertIsNone(values["optional"])
        self.assertIsNone(self.variables["optional"])
        self.assertEqual(result["message"], "Execution passed")
        self.assertEqual(
            result["request_snapshot"]["url"],
            "https://api.example.com/companies",
        )
        self.assertEqual(result["response_snapshot"]["json"]["data"]["id"], 9527)
        self.assertEqual(result["assertion_results"][0]["actual"], 200)

    def test_historical_run_detail_hydrates_execution_snapshots(self):
        run = SimpleNamespace(
            id=9,
            project_id=1,
            step_results=[{
                "step_id": "STEP-1",
                "kind": "api_case",
                "execution_id": 301,
                "status": "failed",
                "assertion_results": [{"name": "业务断言", "status": "failed"}],
            }],
        )
        execution = SimpleNamespace(
            id=301,
            project_id=1,
            scenario_run_id=9,
            request_snapshot={
                "method": "POST",
                "url": "https://api.example.com/companies",
                "body": {"name": "OpenAI"},
            },
            response_snapshot={
                "status_code": 400,
                "json": {"code": 40001, "message": "invalid"},
            },
            assertion_results=[],
            error_message="Execution failed",
        )
        self.db.get.return_value = execution

        results = self.service._hydrate_step_result_snapshots(
            run, run.step_results
        )

        self.assertEqual(
            results[0]["request_snapshot"]["body"], {"name": "OpenAI"}
        )
        self.assertEqual(results[0]["response_snapshot"]["status_code"], 400)
        self.assertEqual(results[0]["error_message"], "Execution failed")
        self.assertEqual(
            results[0]["assertion_results"],
            [{"name": "业务断言", "status": "failed"}],
        )

    def test_resolved_binding_is_the_final_request_value(self):
        self.variables["companyId"] = 9527
        self.variable_sources["companyId"] = {
            "source_step_id": "STEP-1",
            "source_extraction_id": "VAR-1",
            "masked": False,
        }
        step = self.api_step(
            "STEP-2",
            "Get company detail",
            {
                "query_params": {"companyId": "{{companyId}}"},
                "_scenario_context": {
                    "bindings": [
                        {
                            "id": "BIND-1",
                            "name": "companyId",
                            "source_step_id": "STEP-1",
                            "source_extraction_id": "VAR-1",
                            "target": "query_params",
                            "target_path": "companyId",
                        }
                    ]
                },
            },
        )
        captured = {}

        def execute(**kwargs):
            captured["query_params"] = kwargs["payload"].query_params
            return SimpleNamespace(
                id=302,
                status="passed",
                response_snapshot={"json": {"ok": True}},
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
                step_index=2,
                variables=self.variables,
                previous_results=[],
                current_user=self.user,
                scenario_run_id=9,
                deadline=None,
                variable_sources=self.variable_sources,
            )

        self.assertEqual(captured["query_params"]["companyId"], 9527)
        self.assertEqual(
            result["resolved_bindings"],
            [{
                "binding_id": "BIND-1",
                "source_step_id": "STEP-1",
                "source_extraction_id": "VAR-1",
                "target": "query_params",
                "target_path": "companyId",
                "value": 9527,
                "masked": False,
            }],
        )

    def test_masked_values_are_used_but_not_returned(self):
        source = self.api_step(
            "STEP-1",
            "Get token",
            {
                "_scenario_context": {
                    "extractions": [{
                        "id": "VAR-SECRET",
                        "name": "sessionValue",
                        "path": "data.token",
                        "masked": True,
                    }]
                }
            },
        )
        source_result = self.execute_step(
            source, {"json": {"data": {"token": "real-secret"}}}
        )
        self.assertEqual(source_result["extracted_variables"][0]["value"], "***")
        self.assertEqual(self.variables["sessionValue"], "real-secret")

        target = self.api_step(
            "STEP-2",
            "Use token",
            {
                "headers": {"Authorization": "Bearer {{sessionValue}}"},
                "_scenario_context": {
                    "bindings": [{
                        "id": "BIND-SECRET",
                        "name": "sessionValue",
                        "source_step_id": "STEP-1",
                        "source_extraction_id": "VAR-SECRET",
                        "target": "headers",
                        "target_path": "Authorization",
                    }]
                },
            },
        )
        captured = {}

        def execute(**kwargs):
            captured["authorization"] = kwargs["payload"].headers["Authorization"]
            return SimpleNamespace(
                id=303,
                status="passed",
                response_snapshot={"json": {}},
                error_message=None,
            )

        with patch(
            "app.services.scenario_service.TestCaseService._execute",
            side_effect=execute,
        ):
            target_result = self.service._execute_step(
                project_id=1,
                environment_id=2,
                step=target,
                step_index=2,
                variables=self.variables,
                previous_results=[],
                current_user=self.user,
                scenario_run_id=9,
                deadline=None,
                variable_sources=self.variable_sources,
            )

        self.assertEqual(captured["authorization"], "Bearer real-secret")
        self.assertEqual(target_result["resolved_bindings"][0]["value"], "***")
        self.assertTrue(target_result["resolved_bindings"][0]["masked"])
        snapshot = self.service._masked_variables_snapshot(
            self.variables, self.variable_sources
        )
        self.assertEqual(snapshot["sessionValue"], "***")

    def test_failed_extraction_is_returned_with_error(self):
        step = self.api_step(
            "STEP-1",
            "Missing value",
            {
                "_scenario_context": {
                    "extractions": [{
                        "id": "VAR-MISSING",
                        "name": "missing",
                        "path": "data.missing",
                    }]
                }
            },
        )

        result = self.execute_step(step, {"json": {"data": {}}})

        self.assertEqual(result["extracted_variables"][0]["value"], None)
        self.assertEqual(
            result["extracted_variables"][0]["error"],
            "Extraction path not found",
        )
        self.assertNotIn("missing", self.variables)

    def test_trace_metadata_is_stable_and_matches_snapshot(self):
        steps = [
            self.api_step(
                "STEP-1",
                "Get company",
                {
                    "_scenario_context": {
                        "extractions": [{
                            "id": "VAR-1",
                            "name": "companyId",
                            "path": "data.id",
                        }]
                    }
                },
            ),
            self.api_step(
                "STEP-2",
                "Get detail",
                {"query_params": {"companyId": "{{companyId}}"}},
            ),
        ]

        self.service._ensure_trace_metadata(steps)
        first_binding = steps[1]["config"]["_scenario_context"]["bindings"][0]
        first_id = first_binding["id"]
        self.service._ensure_trace_metadata(steps)
        bindings = steps[1]["config"]["_scenario_context"]["bindings"]

        self.assertEqual(len(bindings), 1)
        self.assertEqual(bindings[0]["id"], first_id)
        self.assertTrue(first_id.startswith("BIND-AUTO-"))
        self.assertEqual(bindings[0]["source_step_id"], "STEP-1")
        self.assertEqual(bindings[0]["source_extraction_id"], "VAR-1")


if __name__ == "__main__":
    unittest.main()
