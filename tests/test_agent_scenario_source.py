import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401 - register all tables
from app.core.sensitive_data import request_fingerprint
from app.db.base import Base
from app.models.project import Project, ProjectEnvironment
from app.models.test_case import TestCase
from app.models.user import User
from app.schemas.agent import AgentRunCreateRequest, AgentToolCallCreateRequest
from app.services.agent_capability_plan_service import AgentCapabilityPlanService
from app.services.agent_context_manager import AgentContextManager
from app.services.agent_intent_decision_service import ValidatedAgentIntentDecision
from app.services.agent_runtime_service import AgentRuntimeService, AgentToolRuntime, ExecutionLedgerService


class AgentScenarioSourceServiceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        self.user = User(
            id=1,
            username="owner",
            account="owner",
            password_hash="x",
            phone="10000000001",
            email="owner@example.test",
            is_admin=True,
        )
        self.project = Project(id=1, name="Scenario Source", created_by_id=1)
        self.other_project = Project(id=2, name="Other Project", created_by_id=1)
        self.environment = ProjectEnvironment(
            id=4,
            project_id=1,
            name="Test",
            base_url="https://example.test",
            is_default=True,
            is_deleted=False,
            created_by_id=1,
        )
        self.db.add_all([self.user, self.project, self.other_project, self.environment])
        self.db.flush()
        self.cases = [
            TestCase(
                id=index,
                project_id=1,
                environment_id=4,
                name=f"Real Case {index}",
                method="GET" if index % 2 else "POST",
                path=f"/api/real/{index}",
                headers={},
                query_params={},
                body_type="json",
                body={} if index % 2 == 0 else None,
                assertions=[{"type": "status_code", "expected": 200}],
                extractors=[],
                retry_policy={},
                created_by_id=1,
            )
            for index in range(1, 16)
        ]
        self.db.add_all(self.cases)
        self.db.commit()
        self.run = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(project_id=1, intent="Analyze project cases"),
            current_user=self.user,
        )
        decision = ValidatedAgentIntentDecision(
            action="analyze",
            target_domain="test_case",
            source_domains=(),
            confidence=0.99,
            source="llm_intent",
            reason_codes=("intent_decision:validated",),
        )
        context_plan = AgentContextManager().route(
            self.run.intent,
            intent_action=decision.as_intent_action(),
        )
        AgentCapabilityPlanService(self.db).create_active_plan(
            run=self.run,
            iteration=0,
            context_plan=context_plan,
            intent_decision=decision,
            source="llm_intent",
        )
        call = ExecutionLedgerService(self.db).create_tool_call(
            payload=AgentToolCallCreateRequest(
                run_id=self.run.run_id,
                tool_name="testcase.query_project_cases",
                input={
                    "project_id": 1,
                    "environment_id": 4,
                    "detail_level": "summary",
                    "include_websocket": True,
                },
                step_index=0,
            ),
            current_user=self.user,
            enqueue=False,
        )
        output = AgentToolRuntime(self.db).execute(call=call, current_user=self.user)
        call.status = "succeeded"
        call.output_json_redacted = output
        call.output_hash = request_fingerprint(output)
        self.db.commit()
        self.call = call
        self.case_source = {
            "artifact_id": f"agent-tool-artifact://{call.tool_call_id}/test_case_query_snapshot",
            "output_hash": call.output_hash,
        }

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_resolves_complete_case_source_from_same_project_ledger(self):
        from app.services.agent_scenario_source_service import AgentScenarioSourceService

        resolved = AgentScenarioSourceService(self.db).resolve(
            project_id=1,
            user_id=1,
            conversation_id=self.run.conversation_id,
            case_source=self.case_source,
            environment_id=4,
        )

        self.assertEqual(resolved.http_case_ids, tuple(range(1, 16)))
        self.assertEqual(resolved.websocket_case_ids, ())
        self.assertEqual(len(resolved.case_snapshots), 15)
        self.assertEqual(resolved.case_snapshots[0]["name"], "Real Case 1")
        self.assertEqual(resolved.case_snapshots[-1]["path"], "/api/real/15")
        self.assertEqual(resolved.environment_id, 4)
        self.assertEqual(resolved.evidence_sources[0]["output_hash"], self.call.output_hash)

    def test_rejects_cross_project_or_stale_hash_source(self):
        from app.services.agent_scenario_source_service import AgentScenarioSourceService

        service = AgentScenarioSourceService(self.db)
        for project_id, output_hash in ((2, self.call.output_hash), (1, "stale-hash")):
            with self.subTest(project_id=project_id, output_hash=output_hash):
                source = {**self.case_source, "output_hash": output_hash}
                with self.assertRaises(HTTPException) as raised:
                    service.resolve(
                        project_id=project_id,
                        user_id=1,
                        conversation_id=self.run.conversation_id,
                        case_source=source,
                        environment_id=4,
                    )
                self.assertEqual(raised.exception.detail["code"], "agent_scenario_case_source_invalid")

    def test_scenario_compose_uses_complete_authoritative_case_source(self):
        from app.services.agent_tool_service import AgentToolBackend

        captured = {}

        def fake_run_skill(_service, *, skill_id, payload, current_user):
            captured["skill_id"] = skill_id
            captured["request"] = payload
            return {
                "scenario": {
                    "name": "Real Project Scenario",
                    "environment_id": 4,
                    "nodes": [
                        {
                            "id": f"NODE-{case.id}",
                            "name": case.name,
                            "test_case": {
                                "id": f"CASE-{case.id}",
                                "kind": "api_case",
                                "reference_id": case.id,
                                "name": case.name,
                                "method": case.method,
                                "path": case.path,
                                "config": {},
                            },
                        }
                        for case in self.cases
                    ],
                }
            }

        with patch("app.services.agent_tool_service.AISkillService.run_skill", new=fake_run_skill):
            result = AgentToolBackend(self.db)._scenario_compose_draft(
                {
                    "project_id": 1,
                    "environment_reference": "object-ref://environment/project/4",
                    "case_source": self.case_source,
                    "requirement": "Construct a real executable scenario from the analyzed cases.",
                    "execute_candidates": True,
                    "self_validate": True,
                },
                self.user,
            )

        self.assertEqual(captured["skill_id"], "scenario-composer")
        self.assertEqual(captured["request"].environment_id, 4)
        self.assertEqual(captured["request"].input["http_test_case_ids"], list(range(1, 16)))
        self.assertFalse(captured["request"].input["execute_candidates"])
        self.assertFalse(captured["request"].input["self_validate"])
        self.assertEqual(
            result["draft"]["evidence_sources"][0]["artifact_id"],
            self.case_source["artifact_id"],
        )
        self.assertTrue(result["draft"]["scenario_validation"]["valid"])
        self.assertEqual(result["draft"]["scenario_validation"]["referenced_case_count"], 15)

    def test_runner_records_scenario_draft_validation_event(self):
        from sqlalchemy import select

        from app.models.agent import AgentEvent
        from app.services.agent_runtime_service import AgentConversationRunner

        call = SimpleNamespace(
            tool_call_id="compose-validation-1",
            tool_name="scenario.compose_draft",
            output_json_redacted={
                "draft": {
                    "scenario_validation": {
                        "valid": True,
                        "referenced_case_count": 15,
                        "unresolved_reference_count": 0,
                        "dependency_edge_count": 2,
                        "resolved_template_count": 2,
                        "unresolved_template_count": 0,
                    }
                }
            },
        )

        AgentConversationRunner(self.db)._record_scenario_draft_validation_event(
            run=self.run,
            runtime=AgentRuntimeService(self.db),
            call=call,
            iteration=0,
        )

        event = self.db.scalar(
            select(AgentEvent).where(
                AgentEvent.run_id == self.run.run_id,
                AgentEvent.event_type == "scenario.draft_validation_completed",
            )
        )
        self.assertIsNotNone(event)
        self.assertEqual(event.payload_json["tool_call_id"], "compose-validation-1")
        self.assertEqual(event.payload_json["referenced_case_count"], 15)


if __name__ == "__main__":
    unittest.main()
