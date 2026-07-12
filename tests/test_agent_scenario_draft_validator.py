import unittest
from types import SimpleNamespace

from app.services.agent_scenario_source_service import ResolvedScenarioSource


def source(*, first_extractors=None, environment_variable_names=()):
    return ResolvedScenarioSource(
        project_id=1,
        environment_id=4,
        case_snapshot_id="case-snapshot://real",
        http_case_ids=(1, 2),
        websocket_case_ids=(),
        case_snapshots=(
            {
                "id": 1,
                "reference_id": 1,
                "object_ref": "object-ref://test_case/http/real/1",
                "case_type": "http",
                "name": "List companies",
                "method": "GET",
                "path": "/api/companies",
                "environment_ids": [4],
                "headers": {},
                "query_params": {},
                "body": None,
                "assertions": [{"type": "status_code", "expected": 200}],
                "extractors": first_extractors or [],
            },
            {
                "id": 2,
                "reference_id": 2,
                "object_ref": "object-ref://test_case/http/real/2",
                "case_type": "http",
                "name": "Company detail",
                "method": "GET",
                "path": "/api/companies/detail",
                "environment_ids": [4],
                "headers": {},
                "query_params": {},
                "body": None,
                "assertions": [{"type": "status_code", "expected": 200}],
                "extractors": [],
            },
        ),
        evidence_sources=({
            "artifact_id": "agent-tool-artifact://query/test_case_query_snapshot",
            "output_hash": "real-output-hash",
        },),
        environment_variable_names=tuple(environment_variable_names),
    )


def scenario(*, first_config=None, second_config=None, second_path="/api/companies/detail"):
    return {
        "name": "Company scenario",
        "environment_id": 4,
        "nodes": [
            {
                "id": "NODE-1",
                "name": "List companies",
                "test_case": {
                    "id": "CASE-1",
                    "kind": "api_case",
                    "reference_id": 1,
                    "name": "List companies",
                    "method": "GET",
                    "path": "/api/companies",
                    "config": first_config or {},
                },
            },
            {
                "id": "NODE-2",
                "name": "Company detail",
                "test_case": {
                    "id": "CASE-2",
                    "kind": "api_case",
                    "reference_id": 2,
                    "name": "Company detail",
                    "method": "GET",
                    "path": second_path,
                    "config": second_config or {},
                },
            },
        ],
        "datasets": [],
    }


def issue_codes(result):
    return {item["code"] for item in result.validation["quality_issues"]}


class AgentScenarioDraftValidatorTests(unittest.TestCase):
    def test_scenario_compose_projection_uses_grounded_authoritative_counts(self):
        from app.services.agent_tool_result_projection import ToolResultProjectionService

        output = {
            "draft": {
                "scenario": {
                    "name": "Grounded scenario",
                    "environment_id": 4,
                    "nodes": [
                        {"test_case": {"reference_id": 7}},
                        {"test_case": {"reference_id": 10}},
                    ],
                },
                "scenario_grounding": {
                    "grounded_node_count": 2,
                    "excluded_node_count": 1,
                    "excluded_nodes": [{
                        "reference_id": 56,
                        "reason": "saved_case_external_template_unresolved",
                        "unresolved_variables": ["authorization"],
                    }],
                },
                "case_source_summary": {
                    "http_test_case_ids": [7, 10, 56, 99],
                    "websocket_test_case_ids": [],
                    "case_count": 4,
                },
                "scenario_validation": {
                    "valid": True,
                    "referenced_case_count": 2,
                    "dependency_edge_count": 0,
                    "quality_issues": [],
                    "graph_errors": [],
                },
                "self_validated": False,
                "validation_attempts": [],
                "warnings": ["model candidate said 3 nodes"],
            }
        }

        projection = ToolResultProjectionService().project("scenario.compose_draft", output)

        self.assertIsNotNone(projection)
        view = projection.model_output
        self.assertEqual(view["scenario"]["node_count"], 2)
        self.assertEqual(view["scenario"]["reference_ids"], [7, 10])
        self.assertEqual(view["grounding"]["excluded_nodes"][0]["reference_id"], 56)
        self.assertEqual(view["source"]["reference_ids"], [7, 10, 56, 99])
        self.assertEqual(view["candidate"]["reference_ids"], [7, 10, 56])
        self.assertEqual(view["candidate"]["omitted_by_composer_reference_ids"], [99])
        self.assertIn("reason is not recorded", view["authoritative_summary"])
        self.assertTrue(view["validation"]["valid"])
        self.assertEqual(view["execution"], {"executed": False, "self_validated": False})
        self.assertEqual(view["persistence"], {"saved": False})
        self.assertNotIn("warnings", view)

    def test_grounding_restores_saved_case_config_and_removes_invented_dependencies(self):
        from app.services.agent_scenario_draft_validator import AgentScenarioDraftValidator

        candidate = scenario(
            first_config={
                "assertions": [{"type": "status_code", "expected": 201}],
                "extractors": [{"id": "VAR-invented", "name": "company_id", "path": "invented.path"}],
                "_scenario_context": {
                    "extractions": [{"id": "VAR-invented", "name": "company_id", "path": "invented.path"}],
                },
            },
            second_config={
                "query_params": {"companyId": "{{company_id}}"},
                "_scenario_context": {
                    "bindings": [{
                        "name": "company_id",
                        "source_step_id": "CASE-1",
                        "source_extraction_id": "VAR-invented",
                        "target": "query_params",
                        "target_path": "companyId",
                    }],
                },
            },
        )
        validator = AgentScenarioDraftValidator()

        grounded = validator.ground(draft=candidate, source=source())
        result = validator.validate(draft=grounded.scenario, source=source())

        first_config = grounded.scenario["nodes"][0]["test_case"]["config"]
        second_config = grounded.scenario["nodes"][1]["test_case"]["config"]
        self.assertEqual(first_config["assertions"], [{"type": "status_code", "expected": 200}])
        self.assertEqual(first_config["extractors"], [])
        self.assertEqual(second_config["query_params"], {})
        self.assertNotIn("_scenario_context", first_config)
        self.assertNotIn("_scenario_context", second_config)
        self.assertEqual(grounded.grounding["canonicalized_node_count"], 2)
        self.assertEqual(grounded.grounding["removed_unsupported_extractor_count"], 1)
        self.assertTrue(result.valid, result.validation)

    def test_invalid_compose_result_is_not_projected_as_authoritative_scenario_draft(self):
        from app.services.agent_runtime_service import _tool_call_artifact_manifest

        call = SimpleNamespace(
            tool_call_id="compose-invalid-1",
            tool_name="scenario.compose_draft",
            run_id="run-1",
            output_hash="invalid-hash",
            output_json_redacted={
                "draft": {
                    "scenario": {"name": "Invalid", "environment_id": 4, "nodes": []},
                    "scenario_validation": {
                        "valid": False,
                        "quality_issues": [{"code": "scenario_nodes_missing"}],
                    },
                }
            },
        )
        run = SimpleNamespace(conversation_id="conversation-1")

        manifest = _tool_call_artifact_manifest(call, run)

        self.assertEqual(manifest["artifact_type"], "scenario_draft_invalid")
        self.assertEqual(manifest["artifact_class"], "DERIVED")
        self.assertEqual(manifest["available_followup_actions"], ["repair"])

    def test_zero_node_scenario_is_invalid(self):
        from app.services.agent_scenario_draft_validator import AgentScenarioDraftValidator

        empty = {"name": "Empty", "environment_id": 4, "nodes": [], "datasets": []}

        result = AgentScenarioDraftValidator().validate(draft=empty, source=source())

        self.assertFalse(result.valid)
        self.assertIn("scenario_nodes_missing", issue_codes(result))

    def test_independent_real_cases_are_valid_without_invented_edges(self):
        from app.services.agent_scenario_draft_validator import AgentScenarioDraftValidator

        result = AgentScenarioDraftValidator().validate(
            draft=scenario(),
            source=source(),
        )

        self.assertTrue(result.valid)
        self.assertEqual(result.validation["referenced_case_count"], 2)
        self.assertEqual(result.validation["unresolved_reference_count"], 0)
        self.assertEqual(result.validation["dependency_edge_count"], 0)
        self.assertEqual(result.validation["unresolved_template_count"], 0)

    def test_saved_extractor_can_evidence_downstream_binding(self):
        from app.services.agent_scenario_draft_validator import AgentScenarioDraftValidator

        result = AgentScenarioDraftValidator().validate(
            draft=scenario(
                first_config={
                    "extractors": [{"id": "VAR-company-id", "name": "company_id", "path": "data.0.id"}],
                },
                second_config={
                    "query_params": {"companyId": "{{company_id}}"},
                },
            ),
            source=source(first_extractors=[{"name": "company_id", "path": "data.0.id"}]),
        )

        self.assertTrue(result.valid, result.validation)
        self.assertEqual(result.validation["extractor_count"], 1)
        self.assertEqual(result.validation["binding_count"], 1)
        self.assertEqual(result.validation["dependency_edge_count"], 1)
        self.assertEqual(result.validation["resolved_template_count"], 1)

    def test_environment_variable_template_is_not_treated_as_node_dependency(self):
        from app.services.agent_scenario_draft_validator import AgentScenarioDraftValidator

        result = AgentScenarioDraftValidator().validate(
            draft=scenario(
                second_config={"headers": {"lingxi-auth": "{{Lingxi-Auth}}"}},
            ),
            source=source(environment_variable_names=("Lingxi-Auth",)),
        )

        self.assertTrue(result.valid, result.validation)
        self.assertEqual(result.validation["dependency_edge_count"], 0)
        self.assertEqual(result.validation["resolved_template_count"], 1)
        self.assertEqual(result.validation["unresolved_template_count"], 0)

    def test_grounding_excludes_saved_case_with_unresolvable_external_template(self):
        from app.services.agent_scenario_draft_validator import AgentScenarioDraftValidator

        real_source = source(environment_variable_names=("Lingxi-Auth",))
        real_source.case_snapshots[1]["headers"] = {
            "Authorization": "{{authorization}}",
        }
        validator = AgentScenarioDraftValidator()

        grounded = validator.ground(draft=scenario(), source=real_source)
        result = validator.validate(draft=grounded.scenario, source=real_source)

        self.assertEqual(len(grounded.scenario["nodes"]), 1)
        self.assertEqual(grounded.grounding["excluded_node_count"], 1)
        self.assertEqual(
            grounded.grounding["excluded_nodes"][0]["unresolved_variables"],
            ["authorization"],
        )
        self.assertTrue(result.valid, result.validation)

    def test_invented_endpoint_and_extractor_are_not_authoritative(self):
        from app.services.agent_scenario_draft_validator import AgentScenarioDraftValidator

        result = AgentScenarioDraftValidator().validate(
            draft=scenario(
                first_config={
                    "extractors": [{"id": "VAR-invented", "name": "company_id", "path": "invented.path"}],
                },
                second_config={
                    "query_params": {"companyId": "{{company_id}}"},
                },
                second_path="/api/invented/detail",
            ),
            source=source(),
        )

        self.assertFalse(result.valid)
        self.assertIn("node_request_reference_mismatch", issue_codes(result))
        self.assertIn("extractor_not_evidenced", issue_codes(result))
        self.assertIn("binding_source_not_evidenced", issue_codes(result))
        self.assertGreater(result.validation["unresolved_template_count"], 0)


if __name__ == "__main__":
    unittest.main()
