import json
import unittest
from types import SimpleNamespace


SKILL_INDEX = [
    {
        "name": "scenario-composition",
        "description": "Compose executable test scenarios from saved cases.",
        "owns": ["scenario"],
        "consumes": ["test_case", "environment"],
        "produces": ["scenario_draft"],
        "tool_names": [
            "project.read_context",
            "testcase.query_project_cases",
            "scenario.compose_draft",
        ],
    }
]

TOOL_INDEX = [
    {
        "name": "project.read_context",
        "summary": "Read project context.",
        "side_effect_class": "read_only",
        "replay_policy": "reuse_allowed",
        "required_permissions": ["view_project"],
        "schema_hash": "context-schema",
    },
    {
        "name": "testcase.query_project_cases",
        "summary": "Query saved project cases.",
        "side_effect_class": "read_only",
        "replay_policy": "reuse_allowed",
        "required_permissions": ["view_test_case"],
        "schema_hash": "case-schema",
    },
    {
        "name": "scenario.compose_draft",
        "summary": "Compose a scenario draft.",
        "side_effect_class": "draft_only",
        "replay_policy": "reuse_allowed",
        "required_permissions": ["view_scenario", "execute_test"],
        "schema_hash": "scenario-schema",
    },
]

ARTIFACT_INDEX = [
    {
        "artifact_id": "agent-tool-artifact://run-1/test_case_query_snapshot",
        "artifact_type": "test_case_query_snapshot",
        "artifact_trust": "SOURCE",
        "available_followup_actions": ["compose_scenario"],
        "output_hash": "case-output-hash",
    }
]


def planning_json(**overrides):
    payload = {
        "goal": "Construct an executable scenario from the project's saved cases.",
        "action": "create_draft",
        "target_domain": "scenario",
        "source_domains": ["test_case", "environment"],
        "selected_skills": ["scenario-composition"],
        "selected_tools": [
            "project.read_context",
            "testcase.query_project_cases",
            "scenario.compose_draft",
        ],
        "selected_artifact_ids": ["agent-tool-artifact://run-1/test_case_query_snapshot"],
        "required_facts": ["project_environment_snapshot", "test_case_query_snapshot"],
        "requested_effect_scope": "draft",
        "confidence": 0.92,
        "reason_summary": "The current turn asks to turn the analyzed saved cases into a scenario.",
    }
    payload.update(overrides)
    return json.dumps(payload)


class FakeAIService:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def chat(self, request):
        self.requests.append(request)
        return self.responses.pop(0)


def response(content, *, finish_reason="stop"):
    return SimpleNamespace(content=content, finish_reason=finish_reason)


class AgentPlanningDecisionServiceTests(unittest.TestCase):
    def decide(self, ai_service):
        from app.services.agent_planning_service import AgentPlanningDecisionService

        return AgentPlanningDecisionService(ai_service=ai_service).decide(
            intent="现在我需要构建一个自动化测试流程",
            conversation_context={"active_artifact_handles": ARTIFACT_INDEX},
            skill_index=SKILL_INDEX,
            tool_index=TOOL_INDEX,
            artifact_index=ARTIFACT_INDEX,
            project_id=1,
            permissions=("view_project", "view_test_case", "view_scenario", "execute_test"),
        )

    def test_request_disables_thinking_and_returns_complete_decision(self):
        ai_service = FakeAIService(response(planning_json()))

        decision = self.decide(ai_service)

        request = ai_service.requests[0]
        self.assertEqual(request.thinking, "disabled")
        self.assertEqual(request.temperature, 0)
        self.assertEqual(request.response_format, "json")
        self.assertGreaterEqual(request.max_tokens or 0, 1024)
        self.assertEqual(decision.selected_skills, ("scenario-composition",))
        self.assertEqual(decision.selected_tools[-1], "scenario.compose_draft")
        self.assertEqual(
            decision.required_facts,
            ("project_environment_snapshot", "test_case_query_snapshot"),
        )
        self.assertEqual(decision.requested_effect_scope, "draft")

    def test_empty_length_truncated_response_is_repaired_once(self):
        ai_service = FakeAIService(
            response("", finish_reason="length"),
            response(planning_json()),
        )

        decision = self.decide(ai_service)

        self.assertEqual(decision.target_domain, "scenario")
        self.assertEqual(len(ai_service.requests), 2)
        repair_payload = json.loads(ai_service.requests[1].messages[-1].content)
        self.assertEqual(repair_payload["attempt"], 2)
        self.assertEqual(repair_payload["validation_error"]["code"], "planner_response_incomplete")

    def test_unknown_tool_is_never_silently_rewritten(self):
        from app.services.agent_planning_service import AgentPlanningFailed

        invalid = planning_json(selected_tools=["scenario.compose_draft", "invented.tool"])
        ai_service = FakeAIService(response(invalid), response(invalid))

        with self.assertRaises(AgentPlanningFailed) as raised:
            self.decide(ai_service)

        self.assertEqual(raised.exception.code, "agent_planning_failed")
        self.assertEqual(len(ai_service.requests), 2)
        self.assertIn("invented.tool", raised.exception.details["last_error"]["unknown_tools"])

    def test_registered_future_skill_requires_no_keyword_router_branch(self):
        from app.services.agent_planning_service import AgentPlanningDecisionService

        future_skill_index = [
            {
                "name": "future-contract-audit",
                "description": "Audit contracts.",
                "owns": ["contract"],
                "consumes": [],
                "produces": ["contract_audit"],
                "tool_names": ["contract.audit"],
            }
        ]
        future_tool_index = [
            {
                "name": "contract.audit",
                "summary": "Audit contracts.",
                "side_effect_class": "deterministic_compute",
                "replay_policy": "reuse_allowed",
                "required_permissions": ["view_project"],
                "schema_hash": "future-schema",
            }
        ]
        future_json = planning_json(
            goal="Audit the current contracts.",
            action="analyze",
            target_domain="contract",
            source_domains=[],
            selected_skills=["future-contract-audit"],
            selected_tools=["contract.audit"],
            selected_artifact_ids=[],
            required_facts=[],
            requested_effect_scope="derive",
        )

        decision = AgentPlanningDecisionService(ai_service=FakeAIService(response(future_json))).decide(
            intent="perform the requested audit",
            conversation_context=None,
            skill_index=future_skill_index,
            tool_index=future_tool_index,
            artifact_index=[],
            project_id=1,
            permissions=("view_project",),
        )

        self.assertEqual(decision.selected_skills, ("future-contract-audit",))
        self.assertEqual(decision.selected_tools, ("contract.audit",))


if __name__ == "__main__":
    unittest.main()
