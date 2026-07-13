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

DEFECT_SKILL_INDEX = [
    {
        "name": "defect-triage",
        "description": "Inspect execution evidence and create persisted defects.",
        "owns": ["defect"],
        "consumes": ["test_case", "execution"],
        "produces": ["defect"],
        "tool_names": ["execution.read_detail", "defect.create_saved"],
    }
]

DEFECT_TOOL_INDEX = [
    {
        "name": "execution.read_detail",
        "summary": "Read execution evidence.",
        "side_effect_class": "read_only",
        "replay_policy": "reuse_allowed",
        "required_permissions": ["test:execute"],
        "schema_hash": "execution-detail-schema",
    },
    {
        "name": "defect.create_saved",
        "summary": "Create a persisted defect after approval.",
        "side_effect_class": "business_update",
        "replay_policy": "require_revalidation",
        "required_permissions": ["defect:create"],
        "schema_hash": "defect-create-schema",
    },
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
        request_payload = json.loads(request.messages[-1].content)
        contract = request_payload["output_contract"]
        self.assertEqual(contract["type"], "object")
        self.assertIn("goal", contract["required"])
        self.assertIn("selected_skills", contract["required"])
        self.assertEqual(
            contract["properties"]["requested_effect_scope"]["enum"],
            ["observe", "derive", "draft", "execute", "persist"],
        )
        self.assertIn("top-level JSON object", request.messages[0].content)
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

    def test_bounded_repair_emits_invalid_and_retrying_observability_events(self):
        from app.services.agent_planning_service import AgentPlanningDecisionService

        ai_service = FakeAIService(
            response("", finish_reason="length"),
            response(planning_json()),
        )
        events = []

        AgentPlanningDecisionService(ai_service=ai_service).decide(
            intent="build scenario",
            conversation_context={"active_artifact_handles": ARTIFACT_INDEX},
            skill_index=SKILL_INDEX,
            tool_index=TOOL_INDEX,
            artifact_index=ARTIFACT_INDEX,
            project_id=1,
            permissions=("view_project", "view_test_case", "view_scenario", "execute_test"),
            on_event=lambda event_type, payload: events.append((event_type, payload)),
        )

        self.assertEqual([item[0] for item in events], ["invalid", "retrying"])
        self.assertEqual(events[0][1]["code"], "planner_response_incomplete")
        self.assertEqual(events[1][1]["next_attempt"], 2)

    def test_invalid_decision_event_and_repair_include_bounded_selection_summary(self):
        from app.services.agent_planning_service import AgentPlanningDecisionService

        invalid = planning_json(
            target_domain="defect",
            selected_tools=["scenario.compose_draft"],
        )
        ai_service = FakeAIService(response(invalid), response(planning_json()))
        events = []

        AgentPlanningDecisionService(ai_service=ai_service).decide(
            intent="build scenario",
            conversation_context={"active_artifact_handles": ARTIFACT_INDEX},
            skill_index=SKILL_INDEX,
            tool_index=TOOL_INDEX,
            artifact_index=ARTIFACT_INDEX,
            project_id=1,
            permissions=("view_project", "view_test_case", "view_scenario", "execute_test"),
            on_event=lambda event_type, payload: events.append((event_type, payload)),
        )

        invalid_payload = events[0][1]
        self.assertEqual(
            invalid_payload["code"],
            "planner_target_domain_incompatible",
        )
        self.assertEqual(
            invalid_payload["selected_skills"],
            ["scenario-composition"],
        )
        self.assertEqual(
            invalid_payload["selected_tools"],
            ["scenario.compose_draft"],
        )
        self.assertEqual(invalid_payload["selected_artifact_id_count"], 1)
        self.assertEqual(invalid_payload["target_domain"], "defect")
        self.assertEqual(
            invalid_payload["source_domains"],
            ["test_case", "environment"],
        )

        repair_payload = json.loads(ai_service.requests[1].messages[-1].content)
        repair_error = repair_payload["validation_error"]
        self.assertEqual(
            repair_error["selected_skills"],
            ["scenario-composition"],
        )
        self.assertEqual(
            repair_error["selected_tools"],
            ["scenario.compose_draft"],
        )
        self.assertEqual(repair_error["selected_artifact_id_count"], 1)
        self.assertNotIn(
            "selected_artifact_ids",
            json.dumps(repair_error, ensure_ascii=False),
        )

    def test_unknown_tool_is_never_silently_rewritten(self):
        from app.services.agent_planning_service import AgentPlanningFailed

        invalid = planning_json(selected_tools=["scenario.compose_draft", "invented.tool"])
        ai_service = FakeAIService(response(invalid), response(invalid))

        with self.assertRaises(AgentPlanningFailed) as raised:
            self.decide(ai_service)

        self.assertEqual(raised.exception.code, "agent_planning_failed")
        self.assertEqual(len(ai_service.requests), 2)
        self.assertIn("invented.tool", raised.exception.details["last_error"]["unknown_tools"])

    def test_registered_tools_do_not_fail_when_selected_skill_does_not_declare_them(self):
        from app.services.agent_planning_service import AgentPlanningDecisionService

        skill_index = [
            {
                "name": "assertion-extractor-binding",
                "owns": ["assertion"],
                "consumes": ["test_case", "execution"],
                "produces": ["assertion"],
                "tool_names": [],
            },
            {
                "name": "http-test-case-design",
                "owns": ["test_case"],
                "consumes": ["execution"],
                "produces": ["test_case"],
                "tool_names": [
                    "testcase.update_assertions",
                    "testcase.batch_update_assertions",
                ],
            },
        ]
        tool_index = [
            {
                "name": name,
                "summary": "Update saved assertions after approval.",
                "side_effect_class": "business_update",
                "replay_policy": "require_revalidation",
                "required_permissions": ["case:manage"],
                "schema_hash": f"{name}-schema",
            }
            for name in (
                "testcase.update_assertions",
                "testcase.batch_update_assertions",
            )
        ]
        decision_json = planning_json(
            goal="Repair saved assertions.",
            action="repair",
            target_domain="assertion",
            source_domains=["test_case", "execution"],
            selected_skills=["assertion-extractor-binding"],
            selected_tools=[item["name"] for item in tool_index],
            selected_artifact_ids=[],
            required_facts=["saved_case_assertions"],
            requested_effect_scope="persist",
        )

        decision = AgentPlanningDecisionService(
            ai_service=FakeAIService(response(decision_json), response(decision_json))
        ).decide(
            intent="修复断言",
            conversation_context=None,
            skill_index=skill_index,
            tool_index=tool_index,
            artifact_index=[],
            project_id=1,
            permissions=("case:manage",),
        )

        self.assertEqual(
            decision.selected_tools,
            (
                "testcase.update_assertions",
                "testcase.batch_update_assertions",
            ),
        )
        self.assertEqual(decision.alignment.aligned_tools, ())
        self.assertEqual(
            decision.alignment.supporting_skill_candidates_by_tool,
            {
                "testcase.batch_update_assertions": ("http-test-case-design",),
                "testcase.update_assertions": ("http-test-case-design",),
            },
        )
        self.assertEqual(decision.alignment.unbound_tools, ())

    def test_alignment_is_deterministic_and_reports_globally_unbound_registered_tools(self):
        from app.services.agent_planning_service import derive_tool_skill_alignment

        skill_index = [
            {
                "name": "http-test-case-design",
                "tool_names": ["testcase.update_assertions"],
            },
            {
                "name": "assertion-extractor-binding",
                "tool_names": [],
            },
        ]

        alignment = derive_tool_skill_alignment(
            selected_skills=("assertion-extractor-binding",),
            selected_tools=("future.repair", "testcase.update_assertions"),
            skill_index=skill_index,
        )

        self.assertEqual(
            alignment.model_view(),
            {
                "selected_skill_declared_tools": [],
                "aligned_tools": [],
                "supporting_skill_candidates_by_tool": {
                    "testcase.update_assertions": ["http-test-case-design"],
                },
                "unbound_tools": ["future.repair"],
            },
        )

    def test_planner_safe_context_keeps_terminal_run_state_without_assistant_prose(self):
        ai_service = FakeAIService(response(planning_json()))
        context = {
            "schema_version": "conversation_working_context_v2",
            "recent_run_states": [
                {
                    "run_id": "agent-run-failed-1",
                    "status": "failed",
                    "user_intent": "create defects from failed cases",
                    "error_code": "agent_planning_failed",
                    "error_message": "bounded planning failure",
                    "last_event_sequence": 8,
                }
            ],
            "recent_turns": [
                {
                    "run_id": "agent-run-completed-1",
                    "user_intent": "analyze cases",
                    "assistant_message": "private assistant prose must not enter planning",
                }
            ],
            "active_artifact_handles": ARTIFACT_INDEX,
        }

        from app.services.agent_planning_service import AgentPlanningDecisionService

        AgentPlanningDecisionService(ai_service=ai_service).decide(
            intent="为什么上一轮失败",
            conversation_context=context,
            skill_index=SKILL_INDEX,
            tool_index=TOOL_INDEX,
            artifact_index=ARTIFACT_INDEX,
            project_id=1,
            permissions=("view_project", "view_test_case", "view_scenario", "execute_test"),
        )

        request_payload = json.loads(ai_service.requests[0].messages[-1].content)
        safe_context = request_payload["conversation_context"]
        self.assertIn("recent_run_states", safe_context)
        self.assertEqual(safe_context["recent_run_states"], context["recent_run_states"])
        self.assertNotIn("recent_turns", safe_context)
        self.assertNotIn("private assistant prose", json.dumps(safe_context))

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

    def test_business_update_scope_is_normalized_to_persist(self):
        from app.services.agent_planning_service import AgentPlanningDecisionService

        decision_payload = planning_json(
            goal="Inspect failed execution evidence and create a persisted defect.",
            action="create",
            target_domain="defect",
            source_domains=["test_case", "execution"],
            selected_skills=["defect-triage"],
            selected_tools=["execution.read_detail", "defect.create_saved"],
            selected_artifact_ids=[],
            required_facts=["failure cause"],
            requested_effect_scope="execute",
            reason_summary="Use confirmed execution evidence before defect persistence.",
        )
        ai_service = FakeAIService(response(decision_payload), response(decision_payload))

        try:
            decision = AgentPlanningDecisionService(ai_service=ai_service).decide(
                intent="查看失败用例并创建对应缺陷",
                conversation_context=None,
                skill_index=DEFECT_SKILL_INDEX,
                tool_index=DEFECT_TOOL_INDEX,
                artifact_index=[],
                project_id=1,
                permissions=("test:execute", "defect:create"),
            )
        except Exception as exc:
            self.fail(f"registered Tool effect scope should be normalized, got {exc!r}")

        self.assertEqual(decision.model_requested_effect_scope, "execute")
        self.assertEqual(decision.required_effect_scope, "persist")
        self.assertEqual(decision.requested_effect_scope, "persist")
        self.assertTrue(decision.effect_scope_normalized)
        request_payload = json.loads(ai_service.requests[0].messages[-1].content)
        create_tool = next(
            item for item in request_payload["tool_index"] if item["name"] == "defect.create_saved"
        )
        self.assertEqual(create_tool["required_effect_scope"], "persist")

    def test_unknown_side_effect_class_still_fails_closed(self):
        from app.services.agent_planning_service import AgentPlanningDecisionService, AgentPlanningFailed

        invalid_tools = [
            {
                **DEFECT_TOOL_INDEX[1],
                "side_effect_class": "unregistered_effect",
            }
        ]
        decision_payload = planning_json(
            goal="Create a persisted defect.",
            action="create",
            target_domain="defect",
            source_domains=[],
            selected_skills=["defect-triage"],
            selected_tools=["defect.create_saved"],
            selected_artifact_ids=[],
            required_facts=[],
            requested_effect_scope="persist",
        )
        ai_service = FakeAIService(response(decision_payload), response(decision_payload))

        with self.assertRaises(AgentPlanningFailed) as raised:
            AgentPlanningDecisionService(ai_service=ai_service).decide(
                intent="create defect",
                conversation_context=None,
                skill_index=DEFECT_SKILL_INDEX,
                tool_index=invalid_tools,
                artifact_index=[],
                project_id=1,
                permissions=("defect:create",),
            )

        self.assertEqual(
            raised.exception.details["last_error"]["code"],
            "planner_tool_effect_unknown",
        )


if __name__ == "__main__":
    unittest.main()
