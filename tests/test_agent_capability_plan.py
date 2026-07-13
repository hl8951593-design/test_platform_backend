import json
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401 - register all tables on Base.metadata
import app.services.agent_runtime_service as agent_runtime_service
from app.db.base import Base
from app.models.agent import AgentCapabilityPlanRecord, AgentEvent, AgentToolCall
from app.models.project import Project
from app.models.user import User
from app.schemas.agent import AgentRunCreateRequest, AgentToolCallCreateRequest
from app.schemas.ai import AIChatMessage
from app.services.agent_context_manager import AgentContextManager
from app.services.agent_intent_decision_service import ValidatedAgentIntentDecision
from app.services.agent_runtime_service import (
    AgentConversationRunner,
    AgentRuntimeService,
    ExecutionLedgerService,
)


class AgentCapabilityPlanTests(unittest.TestCase):
    def setUp(self):
        self.llm_planning_patch = patch.object(
            agent_runtime_service.settings,
            "AGENT_LLM_INTENT_DECISION_ENABLED",
            False,
        )
        self.llm_planning_patch.start()
        self.addCleanup(self.llm_planning_patch.stop)
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        self.owner = User(
            id=1,
            username="owner",
            account="owner",
            password_hash="x",
            phone="10000000001",
            email="owner@example.test",
            is_admin=True,
        )
        self.project = Project(id=10, name="Capability Plan Project", created_by_id=1)
        self.db.add_all([self.owner, self.project])
        self.db.commit()
        self.run = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(
                project_id=10,
                intent="给错误的测试用例创建缺陷",
            ),
            current_user=self.owner,
        )
        self.decision = ValidatedAgentIntentDecision(
            action="create",
            target_domain="defect",
            source_domains=("test_case",),
            confidence=0.96,
            source="llm_intent",
            reason_codes=("intent_decision:validated",),
        )
        self.context_plan = AgentContextManager().route(
            self.run.intent,
            intent_action=self.decision.as_intent_action(),
        )

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_capability_plan_persists_and_supersedes_revisions(self):
        from app.services.agent_capability_plan_service import AgentCapabilityPlanService

        service = AgentCapabilityPlanService(self.db)
        first = service.create_active_plan(
            run=self.run,
            iteration=0,
            context_plan=self.context_plan,
            intent_decision=self.decision,
            source="llm_intent",
        )
        second = service.supersede_with_plan(
            current=first,
            context_plan=self.context_plan,
            intent_decision=self.decision,
            source="route_rebuild",
        )

        self.db.refresh(first)
        self.db.refresh(self.run)
        self.assertEqual(first.status, "superseded")
        self.assertEqual(second.parent_capability_plan_id, first.capability_plan_id)
        self.assertEqual(second.revision, 1)
        self.assertEqual(self.run.active_capability_plan_id, second.capability_plan_id)
        self.assertIn("defect.create_saved", second.allowed_tools_json)

    def test_tool_membership_rejects_plan_external_tool(self):
        from app.services.agent_capability_plan_service import (
            AgentCapabilityPlanService,
            CapabilityPlanToolNotAllowed,
        )

        service = AgentCapabilityPlanService(self.db)
        plan = service.create_active_plan(
            run=self.run,
            iteration=0,
            context_plan=self.context_plan,
            intent_decision=self.decision,
            source="llm_intent",
        )

        accepted = service.require_tool_membership(
            run=self.run,
            capability_plan_id=plan.capability_plan_id,
            tool_name="defect.create_saved",
        )
        self.assertEqual(accepted.capability_plan_id, plan.capability_plan_id)

        with self.assertRaises(CapabilityPlanToolNotAllowed):
            service.require_tool_membership(
                run=self.run,
                capability_plan_id=plan.capability_plan_id,
                tool_name="scenario.create_saved",
            )

    def test_runner_binds_model_events_and_tool_call_to_active_plan(self):
        def fake_chat(_service, _payload):
            return SimpleNamespace(
                content=(
                    '{"action":"create","target_domain":"defect",'
                    '"source_domains":["test_case"],"confidence":0.96}'
                )
            )

        def fake_stream(_service, payload):
            self.assertTrue(any("defect.create_saved" in (message.content or "") for message in payload.messages))
            yield {
                "type": "delta",
                "content": (
                    "```agent_tool_request\n"
                    '{"tool_name":"defect.create_saved","input":{"project_id":10,'
                    '"defect":{"title":"failed case defect","bug_type":"functional",'
                    '"urgency":"medium","content_html":"<p>failure evidence</p>"}},'
                    '"reason":"create defect from failed case","evidence_refs":[]}\n'
                    "```"
                ),
            }
            yield {"type": "done", "finish_reason": "stop", "model": "deepseek-test"}

        with (
            patch("app.services.agent_intent_decision_service.AIService.chat", new=fake_chat),
            patch("app.services.agent_runtime_service.AIService.chat_stream", new=fake_stream),
        ):
            completed = AgentConversationRunner(self.db).run(
                run_id=self.run.run_id,
                user_id=self.owner.id,
            )

        self.db.refresh(completed)
        tool_call = self.db.scalar(
            select(AgentToolCall).where(AgentToolCall.run_id == self.run.run_id)
        )
        model_events = list(
            self.db.scalars(
                select(AgentEvent).where(
                    AgentEvent.run_id == self.run.run_id,
                    AgentEvent.event_type.in_(["model.started", "model.completed"]),
                )
            ).all()
        )
        self.assertIsNotNone(completed.active_capability_plan_id)
        self.assertIsNotNone(tool_call)
        self.assertEqual(tool_call.capability_plan_id, completed.active_capability_plan_id)
        self.assertTrue(model_events)
        self.assertTrue(
            all(
                event.payload_json.get("capability_plan_id") == completed.active_capability_plan_id
                for event in model_events
            )
        )

    def test_execution_ledger_rejects_plan_external_tool_before_creating_call(self):
        from app.services.agent_capability_plan_service import (
            AgentCapabilityPlanService,
            CapabilityPlanToolNotAllowed,
        )

        plan = AgentCapabilityPlanService(self.db).create_active_plan(
            run=self.run,
            iteration=0,
            context_plan=self.context_plan,
            intent_decision=self.decision,
            source="llm_intent",
        )

        with self.assertRaises(CapabilityPlanToolNotAllowed):
            ExecutionLedgerService(self.db).create_tool_call(
                payload=AgentToolCallCreateRequest(
                    run_id=self.run.run_id,
                    capability_plan_id=plan.capability_plan_id,
                    tool_name="scenario.create_saved",
                    input={},
                    step_index=0,
                ),
                current_user=self.owner,
                enqueue=False,
            )

        self.assertIsNone(
            self.db.scalar(
                select(AgentToolCall).where(AgentToolCall.run_id == self.run.run_id)
            )
        )

    def test_execution_ledger_cannot_bypass_active_plan_by_omitting_plan_id(self):
        from app.services.agent_capability_plan_service import (
            AgentCapabilityPlanService,
            CapabilityPlanToolNotAllowed,
        )

        AgentCapabilityPlanService(self.db).create_active_plan(
            run=self.run,
            iteration=0,
            context_plan=self.context_plan,
            intent_decision=self.decision,
            source="llm_intent",
        )

        with self.assertRaises(CapabilityPlanToolNotAllowed):
            ExecutionLedgerService(self.db).create_tool_call(
                payload=AgentToolCallCreateRequest(
                    run_id=self.run.run_id,
                    tool_name="scenario.create_saved",
                    input={},
                    step_index=0,
                ),
                current_user=self.owner,
                enqueue=False,
            )

    def test_execution_ledger_inherits_active_plan_id_for_allowed_tool(self):
        from app.services.agent_capability_plan_service import AgentCapabilityPlanService

        plan = AgentCapabilityPlanService(self.db).create_active_plan(
            run=self.run,
            iteration=0,
            context_plan=self.context_plan,
            intent_decision=self.decision,
            source="llm_intent",
        )

        call = ExecutionLedgerService(self.db).create_tool_call(
            payload=AgentToolCallCreateRequest(
                run_id=self.run.run_id,
                tool_name="project.read_context",
                input={"project_id": self.run.project_id},
                step_index=0,
            ),
            current_user=self.owner,
            enqueue=False,
        )

        self.assertEqual(call.capability_plan_id, plan.capability_plan_id)

    def test_capability_plan_carries_forward_to_next_iteration_with_lineage(self):
        from app.services.agent_capability_plan_service import AgentCapabilityPlanService

        service = AgentCapabilityPlanService(self.db)
        first = service.create_active_plan(
            run=self.run,
            iteration=0,
            context_plan=self.context_plan,
            intent_decision=self.decision,
            source="llm_intent",
        )

        second = service.carry_forward_plan(
            run=self.run,
            current=first,
            iteration=1,
        )

        self.db.refresh(first)
        self.db.refresh(self.run)
        self.assertEqual(first.status, "superseded")
        self.assertEqual(second.iteration, 1)
        self.assertEqual(second.revision, 0)
        self.assertEqual(second.source, "carry_forward")
        self.assertEqual(second.parent_capability_plan_id, first.capability_plan_id)
        self.assertEqual(second.allowed_tools_json, first.allowed_tools_json)
        self.assertEqual(self.run.active_capability_plan_id, second.capability_plan_id)

    def test_capability_denial_text_is_observability_only_and_does_not_rebuild_plan(self):
        from app.services.agent_capability_plan_service import AgentCapabilityPlanService

        stale_tools = tuple(
            name for name in self.context_plan.allowed_tools if name != "defect.create_saved"
        )
        stale_context_plan = replace(
            self.context_plan,
            allowed_tools=stale_tools,
            capability_plan=replace(
                self.context_plan.capability_plan,
                allowed_tools=stale_tools,
            ),
        )
        service = AgentCapabilityPlanService(self.db)
        stale = service.create_active_plan(
            run=self.run,
            iteration=0,
            context_plan=stale_context_plan,
            intent_decision=self.decision,
            source="llm_intent",
        )
        manager = AgentContextManager()
        messages = [
            AIChatMessage(role="system", content="agent runtime"),
            manager.skill_plan_message(stale_context_plan),
            manager.tool_catalog_message(stale_context_plan),
            manager.capability_plan_message(stale_context_plan),
        ]
        contract = manager.tool_contract_message(
            stale_context_plan,
            input_summary_builder=lambda schema: {
                "required": list((schema or {}).get("required") or []),
                "properties": sorted(((schema or {}).get("properties") or {}).keys()),
            },
        )
        if contract is not None:
            messages.append(contract)

        captured_messages = []

        def fake_stream(_service, payload):
            captured_messages.extend(payload.messages)
            yield {
                "type": "delta",
                "content": (
                    "```agent_tool_request\n"
                    '{"tool_name":"defect.create_saved","input":{"project_id":10,'
                    '"defect":{"title":"failed case defect","bug_type":"functional",'
                    '"urgency":"medium","content_html":"<p>failure evidence</p>"}},'
                    '"reason":"retry with rebuilt plan","evidence_refs":[]}\n'
                    "```"
                ),
            }
            yield {"type": "done", "finish_reason": "stop", "model": "deepseek-test"}

        runtime = AgentRuntimeService(self.db)
        with (
            patch("app.services.agent_runtime_service.AIService.chat_stream", new=fake_stream),
            patch(
                "app.services.agent_runtime_service.AgentContextManager.route",
                return_value=stale_context_plan,
            ),
        ):
            repaired = AgentConversationRunner(self.db)._guard_available_capability_denial(
                run=self.run,
                runtime=runtime,
                content="当前工具不包含 defect.create_saved，无法创建缺陷",
                iteration=0,
                final_summary=False,
                model_payload={"model_call_id": "model-call-stale-plan"},
            )

        self.db.refresh(self.run)
        self.db.refresh(stale)
        active = service.get_active_plan(run=self.run)
        events = list(self.db.scalars(
            select(AgentEvent).where(AgentEvent.run_id == self.run.run_id)
        ))
        self.assertIsNone(repaired)
        self.assertEqual(captured_messages, [])
        self.assertEqual(stale.status, "active")
        self.assertEqual(active.capability_plan_id, stale.capability_plan_id)
        self.assertNotIn("defect.create_saved", active.allowed_tools_json)
        self.assertIn("model.capability_denial_observed", [event.event_type for event in events])

    def test_runner_normalizes_native_tool_call_into_existing_tool_ledger(self):
        from app.services.agent_capability_plan_service import AgentCapabilityPlanService

        expected_html = '<pre>{"code":90001}\n"quoted"</pre>'
        observed_native_catalog = []

        def fake_chat(_service, _payload):
            return SimpleNamespace(
                content=(
                    '{"action":"create","target_domain":"defect",'
                    '"source_domains":["test_case"],"confidence":0.97}'
                )
            )

        def fake_stream(_service, payload):
            plan = AgentCapabilityPlanService(self.db).get_active_plan(run=self.run)
            alias = next(
                provider_alias
                for provider_alias, canonical in plan.tool_aliases_json.items()
                if canonical == "defect.create_saved"
            )
            observed_native_catalog.append([tool.function.name for tool in payload.tools])
            arguments = json.dumps(
                {
                    "input": {
                        "project_id": 10,
                        "defect": {
                            "title": "native failed case defect",
                            "bug_type": "functional",
                            "urgency": "medium",
                            "content_html": expected_html,
                        },
                    },
                    "reason": "native tool request",
                    "evidence_refs": [],
                },
                ensure_ascii=False,
            )
            middle = len(arguments) // 2
            yield {
                "type": "tool_call_delta",
                "tool_calls": [{
                    "index": 0,
                    "id": "native-call-1",
                    "type": "function",
                    "function": {"name": alias, "arguments": arguments[:middle]},
                }],
            }
            yield {
                "type": "tool_call_delta",
                "tool_calls": [{
                    "index": 0,
                    "function": {"arguments": arguments[middle:]},
                }],
            }
            yield {"type": "done", "finish_reason": "tool_calls", "model": "deepseek-test"}

        with (
            patch("app.services.agent_intent_decision_service.AIService.chat", new=fake_chat),
            patch("app.services.agent_runtime_service.AIService.chat_stream", new=fake_stream),
        ):
            completed = AgentConversationRunner(self.db).run(
                run_id=self.run.run_id,
                user_id=self.owner.id,
            )

        tool_call = self.db.scalar(
            select(AgentToolCall).where(AgentToolCall.run_id == self.run.run_id)
        )
        self.assertTrue(observed_native_catalog)
        self.assertTrue(any(observed_native_catalog))
        self.assertIsNotNone(tool_call)
        self.assertEqual(tool_call.capability_plan_id, completed.active_capability_plan_id)
        self.assertEqual(
            tool_call.input_json_redacted["defect"]["content_html"],
            expected_html,
        )

    def test_runner_repairs_invalid_native_tool_call_instead_of_completing_claim_text(self):
        from app.services.agent_capability_plan_service import AgentCapabilityPlanService

        model_turn = 0

        def fake_chat(_service, _payload):
            return SimpleNamespace(
                content=(
                    '{"action":"create","target_domain":"defect",'
                    '"source_domains":["test_case"],"confidence":0.97}'
                )
            )

        def fake_stream(_service, _payload):
            nonlocal model_turn
            model_turn += 1
            plan = AgentCapabilityPlanService(self.db).get_active_plan(run=self.run)
            alias = next(
                provider_alias
                for provider_alias, canonical in plan.tool_aliases_json.items()
                if canonical == "defect.create_saved"
            )
            if model_turn == 1:
                yield {
                    "type": "delta",
                    "content": "我现在创建缺陷记录，并停在人工审批。",
                }
                yield {
                    "type": "tool_call_delta",
                    "tool_calls": [{
                        "index": 0,
                        "id": "native-invalid-1",
                        "type": "function",
                        "function": {
                            "name": alias,
                            "arguments": '{"input":{"project_id":10,"defect":{"title":"unterminated',
                        },
                    }],
                }
                yield {"type": "done", "finish_reason": "tool_calls", "model": "deepseek-test"}
                return
            arguments = json.dumps({
                "input": {
                    "project_id": 10,
                    "defect": {
                        "title": "商标信息接口断言期望值配置错误",
                        "bug_type": "functional",
                        "urgency": "medium",
                        "content_html": "<p>expected=666666, actual=200</p>",
                    },
                },
                "reason": "repair malformed native arguments",
                "evidence_refs": [],
            }, ensure_ascii=False)
            yield {
                "type": "tool_call_delta",
                "tool_calls": [{
                    "index": 0,
                    "id": "native-repaired-1",
                    "type": "function",
                    "function": {"name": alias, "arguments": arguments},
                }],
            }
            yield {"type": "done", "finish_reason": "tool_calls", "model": "deepseek-test"}

        with (
            patch("app.services.agent_intent_decision_service.AIService.chat", new=fake_chat),
            patch("app.services.agent_runtime_service.AIService.chat_stream", new=fake_stream),
        ):
            completed = AgentConversationRunner(self.db).run(
                run_id=self.run.run_id,
                user_id=self.owner.id,
            )

        tool_calls = list(self.db.scalars(
            select(AgentToolCall).where(AgentToolCall.run_id == self.run.run_id)
        ).all())
        event_types = list(self.db.scalars(
            select(AgentEvent.event_type).where(AgentEvent.run_id == self.run.run_id)
        ).all())
        self.assertEqual(model_turn, 2)
        self.assertEqual(completed.status, "needs_human")
        self.assertEqual(len(tool_calls), 1)
        self.assertEqual(tool_calls[0].tool_name, "defect.create_saved")
        self.assertTrue(tool_calls[0].approval_required)
        self.assertIn("model.native_tool_call_invalid", event_types)
        self.assertIn("model.tool_request_repaired", event_types)
        self.assertNotIn("run.completed", event_types)

    def test_runner_carries_plan_identity_forward_for_each_model_iteration(self):
        model_turn = 0

        def fake_chat(_service, _payload):
            return SimpleNamespace(
                content=(
                    '{"action":"create","target_domain":"defect",'
                    '"source_domains":["test_case"],"confidence":0.97}'
                )
            )

        def fake_stream(_service, _payload):
            nonlocal model_turn
            model_turn += 1
            if model_turn == 1:
                yield {
                    "type": "delta",
                    "content": (
                        "```agent_tool_request\n"
                        '{"tool_name":"project.read_context","input":{"project_id":10},'
                        '"reason":"read project context","evidence_refs":[]}\n'
                        "```"
                    ),
                }
                yield {"type": "done", "finish_reason": "stop", "model": "deepseek-test"}
                return
            yield {"type": "delta", "content": "已完成项目上下文读取。"}
            yield {"type": "done", "finish_reason": "stop", "model": "deepseek-test"}

        with (
            patch("app.services.agent_intent_decision_service.AIService.chat", new=fake_chat),
            patch("app.services.agent_runtime_service.AIService.chat_stream", new=fake_stream),
        ):
            completed = AgentConversationRunner(self.db).run(
                run_id=self.run.run_id,
                user_id=self.owner.id,
            )

        plans = list(
            self.db.scalars(
                select(AgentCapabilityPlanRecord)
                .where(AgentCapabilityPlanRecord.run_id == self.run.run_id)
                .order_by(AgentCapabilityPlanRecord.iteration, AgentCapabilityPlanRecord.revision)
            ).all()
        )
        started_events = list(
            self.db.scalars(
                select(AgentEvent)
                .where(
                    AgentEvent.run_id == self.run.run_id,
                    AgentEvent.event_type == "model.started",
                )
                .order_by(AgentEvent.event_seq)
            ).all()
        )
        tool_call = self.db.scalar(
            select(AgentToolCall).where(AgentToolCall.run_id == self.run.run_id)
        )
        self.assertEqual(completed.status, "completed")
        self.assertEqual([plan.iteration for plan in plans], [0, 1])
        self.assertEqual(plans[0].status, "superseded")
        self.assertEqual(plans[1].status, "active")
        self.assertEqual(tool_call.capability_plan_id, plans[0].capability_plan_id)
        self.assertEqual(
            [event.payload_json.get("capability_plan_id") for event in started_events],
            [plans[0].capability_plan_id, plans[1].capability_plan_id],
        )

    def test_native_tool_result_round_trip_uses_assistant_and_tool_roles(self):
        from app.services.agent_capability_plan_service import AgentCapabilityPlanService

        model_turn = 0
        observed_round_trip = []

        def fake_chat(_service, _payload):
            return SimpleNamespace(
                content=(
                    '{"action":"query","target_domain":"test_case",'
                    '"source_domains":[],"confidence":0.98}'
                )
            )

        def fake_stream(_service, payload):
            nonlocal model_turn
            model_turn += 1
            if model_turn == 1:
                plan = AgentCapabilityPlanService(self.db).get_active_plan(run=self.run)
                alias = next(
                    provider_alias
                    for provider_alias, canonical in plan.tool_aliases_json.items()
                    if canonical == "project.read_context"
                )
                arguments = json.dumps({"input": {"project_id": 10}}, ensure_ascii=False)
                yield {"type": "reasoning_delta", "content": "Need current project context first."}
                yield {
                    "type": "tool_call_delta",
                    "tool_calls": [{
                        "index": 0,
                        "id": "native-read-1",
                        "type": "function",
                        "function": {"name": alias, "arguments": arguments},
                    }],
                }
                yield {"type": "done", "finish_reason": "tool_calls", "model": "deepseek-test"}
                return
            assistant_calls = [
                message
                for message in payload.messages
                if message.role == "assistant" and message.tool_calls
            ]
            tool_results = [message for message in payload.messages if message.role == "tool"]
            observed_round_trip.append((assistant_calls, tool_results))
            yield {"type": "delta", "content": "原生工具结果已处理。"}
            yield {"type": "done", "finish_reason": "stop", "model": "deepseek-test"}

        with (
            patch("app.services.agent_intent_decision_service.AIService.chat", new=fake_chat),
            patch("app.services.agent_runtime_service.AIService.chat_stream", new=fake_stream),
        ):
            completed = AgentConversationRunner(self.db).run(
                run_id=self.run.run_id,
                user_id=self.owner.id,
            )

        self.assertEqual(completed.status, "completed")
        self.assertTrue(observed_round_trip)
        assistant_calls, tool_results = observed_round_trip[0]
        self.assertEqual(len(assistant_calls), 1)
        self.assertEqual(len(tool_results), 1)
        self.assertEqual(assistant_calls[0].tool_calls[0].id, "native-read-1")
        self.assertEqual(
            assistant_calls[0].reasoning_content,
            "Need current project context first.",
        )
        self.assertEqual(tool_results[0].tool_call_id, "native-read-1")

    def test_llm_planning_decision_allows_draft_only_tool_in_draft_scope(self):
        from app.services.agent_capability_resolver import AgentCapabilityResolver
        from app.services.agent_planning_service import ValidatedAgentPlanningDecision

        decision = ValidatedAgentPlanningDecision(
            goal="Build a real scenario draft.",
            action="create_draft",
            target_domain="scenario",
            source_domains=("test_case", "environment"),
            selected_skills=("scenario-composition",),
            selected_tools=(
                "project.read_context",
                "testcase.query_project_cases",
                "scenario.compose_draft",
            ),
            selected_artifact_ids=("agent-tool-artifact://source/cases",),
            required_facts=("project_environment_snapshot", "test_case_query_snapshot"),
            requested_effect_scope="draft",
            confidence=0.92,
            reason_summary="The user requested a scenario draft from saved cases.",
        )

        plan = AgentCapabilityResolver().resolve_planning_decision(
            intent="现在构建一个自动化测试流程",
            decision=decision,
        )

        self.assertIn("scenario.compose_draft", plan.allowed_tools)
        self.assertEqual(plan.allowed_skills, ("scenario-composition",))
        self.assertEqual(plan.requested_effect_scope, "draft")
        self.assertEqual(plan.selected_artifact_ids, ("agent-tool-artifact://source/cases",))

    def test_llm_selection_is_not_rewritten_by_misleading_intent_keywords(self):
        from app.services.agent_capability_resolver import AgentCapabilityResolver
        from app.services.agent_planning_service import ValidatedAgentPlanningDecision

        decision = ValidatedAgentPlanningDecision(
            goal="Build a scenario.",
            action="create_draft",
            target_domain="scenario",
            source_domains=("test_case",),
            selected_skills=("scenario-composition",),
            selected_tools=("scenario.compose_draft",),
            selected_artifact_ids=(),
            required_facts=("test_case_query_snapshot",),
            requested_effect_scope="draft",
            confidence=0.9,
            reason_summary="The semantic target is a scenario.",
        )

        plan = AgentCapabilityResolver().resolve_planning_decision(
            intent="这里包含流程、图形、报告等容易误导关键词，但规划目标保持不变",
            decision=decision,
        )

        self.assertEqual(plan.allowed_skills, ("scenario-composition",))
        self.assertEqual(plan.allowed_tools, ("scenario.compose_draft",))
        self.assertEqual(plan.domain, "scenario")
        self.assertEqual(plan.intent_action, "create_draft")

    def test_capability_activation_rejects_mixed_request_atomically(self):
        from app.services.agent_capability_plan_service import AgentCapabilityPlanService

        service = AgentCapabilityPlanService(self.db)
        current = service.create_active_plan(
            run=self.run,
            iteration=0,
            context_plan=self.context_plan,
            intent_decision=self.decision,
            source="llm_intent",
        )
        before_id = self.run.active_capability_plan_id

        result = service.request_capabilities(
            run=self.run,
            current=current,
            tool_names=("scenario.compose_draft", "invented.tool"),
            reason="Scenario composition is now required.",
        )

        self.db.refresh(self.run)
        self.assertFalse(result.accepted)
        self.assertEqual(result.plan_id, before_id)
        self.assertIn("invented.tool", result.rejected_tools)
        self.assertEqual(self.run.active_capability_plan_id, before_id)
        revisions = list(self.db.scalars(
            select(AgentCapabilityPlanRecord).where(
                AgentCapabilityPlanRecord.parent_capability_plan_id == before_id,
            )
        ))
        self.assertEqual(revisions, [])

    def test_capability_activation_supersedes_plan_without_keyword_intent_match(self):
        from app.services.agent_capability_plan_service import AgentCapabilityPlanService

        service = AgentCapabilityPlanService(self.db)
        current = service.create_active_plan(
            run=self.run,
            iteration=0,
            context_plan=self.context_plan,
            intent_decision=self.decision,
            source="llm_intent",
        )

        result = service.request_capabilities(
            run=self.run,
            current=current,
            tool_names=("scenario.compose_draft",),
            reason="The model needs the registered scenario composer.",
        )

        self.db.refresh(current)
        self.db.refresh(self.run)
        self.assertTrue(result.accepted)
        self.assertEqual(result.activated_tools, ("scenario.compose_draft",))
        self.assertEqual(current.status, "superseded")
        self.assertNotEqual(result.plan_id, current.capability_plan_id)
        replacement = service.get_active_plan(run=self.run)
        self.assertIn("scenario.compose_draft", replacement.allowed_tools_json)
        self.assertEqual(replacement.source, "llm_capability_request")

    def test_capability_activation_uses_frozen_snapshot_skill_declarations(self):
        from app.models.agent import AgentRuntimeSnapshot
        from app.services.agent_capability_plan_service import AgentCapabilityPlanService

        snapshot = self.db.scalar(
            select(AgentRuntimeSnapshot).where(
                AgentRuntimeSnapshot.snapshot_id == self.run.runtime_snapshot_id,
            )
        )
        self.assertIsNotNone(snapshot)
        self.assertIn("skills", snapshot.manifests_json)
        self.assertIn("scenario-composition", snapshot.manifests_json["skills"])

        service = AgentCapabilityPlanService(self.db)
        current = service.create_active_plan(
            run=self.run,
            iteration=0,
            context_plan=self.context_plan,
            intent_decision=self.decision,
            source="llm_intent",
        )

        def empty_live_registry(registry, *args, **kwargs):
            registry.root = None
            registry._skills = {}

        with patch(
            "app.services.agent_capability_plan_service.AgentSkillRegistry.__init__",
            new=empty_live_registry,
        ):
            result = service.request_capabilities(
                run=self.run,
                current=current,
                tool_names=("scenario.compose_draft",),
                reason="The frozen runtime snapshot declares this capability.",
            )

        self.assertTrue(result.accepted)
        replacement = service.get_active_plan(run=self.run)
        self.assertIn("scenario-composition", replacement.skill_plan_json["selected_skill_names"])

    def test_llm_planner_receives_frozen_snapshot_skill_index(self):
        from app.services.agent_planning_service import ValidatedAgentPlanningDecision

        captured = {}

        class CapturingPlanningService:
            def decide(self, **kwargs):
                captured.update(kwargs)
                return ValidatedAgentPlanningDecision(
                    goal="Inspect saved cases.",
                    action="query",
                    target_domain="test_case",
                    source_domains=(),
                    selected_skills=("http-test-case-design",),
                    selected_tools=("testcase.query_project_cases",),
                    selected_artifact_ids=(),
                    required_facts=(),
                    requested_effect_scope="read",
                    confidence=0.99,
                    reason_summary="Use the frozen registered capability.",
                )

        def empty_live_registry(registry, *args, **kwargs):
            registry.root = None
            registry._skills = {}

        runner = AgentConversationRunner(
            self.db,
            planning_decision_service=CapturingPlanningService(),
        )
        runtime = AgentRuntimeService(self.db)
        with patch(
            "app.services.agent_runtime_service.AgentSkillRegistry.__init__",
            new=empty_live_registry,
        ):
            decision = runner._resolve_planning_decision(
                run=self.run,
                current_user=self.owner,
                runtime=runtime,
                working_context=None,
                tool_artifact_manifests=[],
            )

        self.assertEqual(decision.target_domain, "test_case")
        frozen_names = {item["name"] for item in captured["skill_index"]}
        self.assertIn("http-test-case-design", frozen_names)
        self.assertIn("scenario-composition", frozen_names)

    def test_legacy_intent_router_cannot_run_when_llm_planning_is_enabled(self):
        from app.services.agent_planning_service import AgentPlanningFailed

        runner = AgentConversationRunner(self.db)
        with (
            patch.object(
                agent_runtime_service.settings,
                "AGENT_LLM_INTENT_DECISION_ENABLED",
                True,
            ),
            self.assertRaises(AgentPlanningFailed) as ctx,
        ):
            runner._resolve_intent_decision(
                run=self.run,
                runtime=AgentRuntimeService(self.db),
                working_context=None,
            )

        self.assertEqual(ctx.exception.code, "agent_planning_failed")
        self.assertEqual(
            ctx.exception.details["last_error"]["code"],
            "planner_legacy_router_disabled",
        )

    def test_runner_processes_native_capability_request_before_next_model_turn(self):
        from app.services.agent_capability_plan_service import AgentCapabilityPlanService
        from app.services.agent_native_tool_call import RUNTIME_REQUEST_CAPABILITY_ALIAS

        model_turn = 0
        observed_native_catalogs = []

        def fake_chat(_service, _payload):
            return SimpleNamespace(
                content=(
                    '{"action":"create","target_domain":"defect",'
                    '"source_domains":["test_case"],"confidence":0.97}'
                )
            )

        def fake_stream(_service, payload):
            nonlocal model_turn
            model_turn += 1
            observed_native_catalogs.append([item.function.name for item in payload.tools])
            if model_turn == 1:
                arguments = json.dumps({
                    "tool_names": ["scenario.compose_draft"],
                    "reason": "The current goal now requires registered scenario composition.",
                })
                yield {
                    "type": "tool_call_delta",
                    "tool_calls": [{
                        "index": 0,
                        "id": "capability-native-1",
                        "type": "function",
                        "function": {
                            "name": RUNTIME_REQUEST_CAPABILITY_ALIAS,
                            "arguments": arguments,
                        },
                    }],
                }
                yield {"type": "done", "finish_reason": "tool_calls", "model": "deepseek-test"}
                return
            yield {"type": "delta", "content": "Capability plan has been revised."}
            yield {"type": "done", "finish_reason": "stop", "model": "deepseek-test"}

        with (
            patch("app.services.agent_intent_decision_service.AIService.chat", new=fake_chat),
            patch("app.services.agent_runtime_service.AIService.chat_stream", new=fake_stream),
        ):
            completed = AgentConversationRunner(self.db).run(
                run_id=self.run.run_id,
                user_id=self.owner.id,
            )

        self.assertEqual(completed.status, "completed")
        self.assertGreaterEqual(len(observed_native_catalogs), 2)
        self.assertIn(RUNTIME_REQUEST_CAPABILITY_ALIAS, observed_native_catalogs[0])
        active = AgentCapabilityPlanService(self.db).get_active_plan(run=self.run)
        self.assertIn("scenario.compose_draft", active.allowed_tools_json)
        events = list(self.db.scalars(
            select(AgentEvent).where(AgentEvent.run_id == self.run.run_id)
        ))
        event_types = [event.event_type for event in events]
        self.assertIn("planner.capability_activation_requested", event_types)
        self.assertIn("planner.capability_activation_accepted", event_types)
        self.assertNotIn("agent_conversation_unhandled_error", event_types)

    def test_inactive_fenced_tool_call_returns_structured_model_error(self):
        model_turn = 0
        second_turn_messages = []

        def fake_chat(_service, _payload):
            return SimpleNamespace(
                content=(
                    '{"action":"create","target_domain":"defect",'
                    '"source_domains":["test_case"],"confidence":0.97}'
                )
            )

        def fake_stream(_service, payload):
            nonlocal model_turn
            model_turn += 1
            if model_turn == 1:
                yield {
                    "type": "delta",
                    "content": (
                        "```agent_tool_request\n"
                        '{"tool_name":"scenario.compose_draft","input":{"project_id":10,'
                        '"environment_id":1,"requirement":"compose"},'
                        '"reason":"inactive direct call","evidence_refs":[]}\n'
                        "```"
                    ),
                }
                yield {"type": "done", "finish_reason": "stop", "model": "deepseek-test"}
                return
            second_turn_messages.extend(payload.messages)
            yield {"type": "delta", "content": "The inactive capability was handled safely."}
            yield {"type": "done", "finish_reason": "stop", "model": "deepseek-test"}

        with (
            patch("app.services.agent_intent_decision_service.AIService.chat", new=fake_chat),
            patch("app.services.agent_runtime_service.AIService.chat_stream", new=fake_stream),
        ):
            completed = AgentConversationRunner(self.db).run(
                run_id=self.run.run_id,
                user_id=self.owner.id,
            )

        self.assertEqual(completed.status, "completed")
        self.assertNotEqual(completed.error_code, "agent_conversation_unhandled_error")
        self.assertIn(
            "agent_capability_not_active",
            "\n".join(message.content or "" for message in second_turn_messages),
        )
        rejected_calls = list(self.db.scalars(
            select(AgentToolCall).where(
                AgentToolCall.run_id == self.run.run_id,
                AgentToolCall.tool_name == "scenario.compose_draft",
            )
        ))
        self.assertEqual(rejected_calls, [])
        event_types = [
            event.event_type
            for event in self.db.scalars(select(AgentEvent).where(AgentEvent.run_id == self.run.run_id))
        ]
        self.assertIn("planner.capability_call_rejected", event_types)

    def test_runner_persists_unified_llm_planning_decision_without_keyword_reroute(self):
        from app.services.agent_capability_plan_service import AgentCapabilityPlanService
        from app.services.agent_planning_service import (
            AgentSkillDomainAlignment,
            AgentToolSkillAlignment,
            ValidatedAgentPlanningDecision,
        )

        planning_inputs = []
        native_catalogs = []

        class FakePlanningService:
            def decide(self, **kwargs):
                planning_inputs.append(kwargs)
                return ValidatedAgentPlanningDecision(
                    goal="Inspect project defects from current project facts.",
                    action="query",
                    target_domain="defect",
                    source_domains=(),
                    selected_skills=("defect-triage",),
                    selected_tools=("project.read_context", "defect.query_project_defects"),
                    selected_artifact_ids=(),
                    required_facts=("project_context",),
                    requested_effect_scope="observe",
                    confidence=0.98,
                    reason_summary="The requested task is a defect query.",
                    model_selected_skills=("defect-triage",),
                    alignment=AgentToolSkillAlignment(
                        selected_skill_declared_tools=(
                            "defect.query_project_defects",
                            "project.read_context",
                        ),
                        aligned_tools=(
                            "defect.query_project_defects",
                            "project.read_context",
                        ),
                    ),
                    domain_alignment=AgentSkillDomainAlignment(
                        model_selected_skills=("defect-triage",),
                        effective_selected_skills=("defect-triage",),
                        target_domain="defect",
                        target_aligned=True,
                        target_skill_candidates=("defect-triage",),
                    ),
                )

        def fake_stream(_service, payload):
            native_catalogs.append([tool.function.name for tool in payload.tools])
            yield {"type": "delta", "content": "Defect planning context is ready."}
            yield {"type": "done", "finish_reason": "stop", "model": "deepseek-test"}

        run = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(
                project_id=10,
                intent="This text deliberately contains scenario flow report words but asks the injected planner.",
            ),
            current_user=self.owner,
        )
        with (
            patch.object(
                agent_runtime_service.settings,
                "AGENT_LLM_INTENT_DECISION_ENABLED",
                True,
            ),
            patch("app.services.agent_runtime_service.AIService.chat_stream", new=fake_stream),
        ):
            completed = AgentConversationRunner(
                self.db,
                planning_decision_service=FakePlanningService(),
            ).run(run_id=run.run_id, user_id=self.owner.id)

        self.assertEqual(completed.status, "completed")
        self.assertEqual(len(planning_inputs), 1)
        plan = AgentCapabilityPlanService(self.db).get_active_plan(run=run)
        self.assertEqual(
            plan.intent_decision_json["model_selected_skills"],
            ["defect-triage"],
        )
        self.assertEqual(plan.intent_decision_json["selected_skills"], ["defect-triage"])
        self.assertEqual(
            plan.intent_decision_json["skill_domain_alignment"],
            {
                "model_selected_skills": ["defect-triage"],
                "effective_selected_skills": ["defect-triage"],
                "auto_added_supporting_skills": [],
                "target_domain": "defect",
                "target_aligned": True,
                "target_skill_candidates": ["defect-triage"],
                "aligned_source_domains": [],
                "source_skill_candidates_by_domain": {},
                "unbound_source_domains": [],
            },
        )
        self.assertEqual(
            plan.allowed_tools_json,
            ["project.read_context", "defect.query_project_defects"],
        )
        self.assertEqual(plan.required_facts_json, ["project_context"])
        self.assertEqual(
            plan.intent_decision_json["tool_skill_alignment"],
            {
                "selected_skill_declared_tools": [
                    "defect.query_project_defects",
                    "project.read_context",
                ],
                "aligned_tools": [
                    "defect.query_project_defects",
                    "project.read_context",
                ],
                "supporting_skill_candidates_by_tool": {},
                "unbound_tools": [],
            },
        )
        self.assertTrue(native_catalogs)
        event_types = [
            event.event_type
            for event in self.db.scalars(select(AgentEvent).where(AgentEvent.run_id == run.run_id))
        ]
        self.assertIn("planner.llm_decision_started", event_types)
        self.assertIn("planner.llm_decision_completed", event_types)
        self.assertNotIn("planner.intent_decision_fallback", event_types)

    def test_persisted_planning_decision_round_trips_domain_and_tool_alignment(self):
        from app.services.agent_planning_service import (
            AgentSkillDomainAlignment,
            AgentToolSkillAlignment,
            ValidatedAgentPlanningDecision,
        )
        from app.services.agent_runtime_service import (
            _validated_planning_decision_from_plan,
        )

        original = ValidatedAgentPlanningDecision(
            goal="Repair assertions and rerun failed cases.",
            action="repair_and_rerun",
            target_domain="test_case",
            source_domains=("test_case", "execution"),
            selected_skills=(
                "assertion-extractor-binding",
                "execution-diagnosis",
                "http-test-case-design",
            ),
            selected_tools=(
                "testcase.update_assertions",
                "testcase.execute_saved",
            ),
            selected_artifact_ids=(),
            required_facts=("execution_details",),
            requested_effect_scope="persist",
            confidence=0.98,
            reason_summary="Use execution evidence and approval-gated updates.",
            model_selected_skills=(
                "assertion-extractor-binding",
                "execution-diagnosis",
            ),
            model_requested_effect_scope="execute",
            required_effect_scope="persist",
            effect_scope_normalized=True,
            alignment=AgentToolSkillAlignment(
                selected_skill_declared_tools=(
                    "testcase.execute_saved",
                    "testcase.update_assertions",
                ),
                aligned_tools=(
                    "testcase.execute_saved",
                    "testcase.update_assertions",
                ),
            ),
            domain_alignment=AgentSkillDomainAlignment(
                model_selected_skills=(
                    "assertion-extractor-binding",
                    "execution-diagnosis",
                ),
                effective_selected_skills=(
                    "assertion-extractor-binding",
                    "execution-diagnosis",
                    "http-test-case-design",
                ),
                auto_added_supporting_skills=("http-test-case-design",),
                target_domain="test_case",
                target_aligned=True,
                target_skill_candidates=("http-test-case-design",),
                aligned_source_domains=("test_case", "execution"),
                source_skill_candidates_by_domain={
                    "test_case": (
                        "assertion-extractor-binding",
                        "execution-diagnosis",
                        "http-test-case-design",
                    ),
                    "execution": (
                        "assertion-extractor-binding",
                        "http-test-case-design",
                    ),
                },
            ),
        )

        restored = _validated_planning_decision_from_plan(original.model_view())

        self.assertEqual(restored.model_view(), original.model_view())

    def test_planning_failure_has_controlled_run_error_without_keyword_fallback(self):
        from app.services.agent_planning_service import AgentPlanningError, AgentPlanningFailed

        class FailingPlanningService:
            def decide(self, **_kwargs):
                raise AgentPlanningFailed(
                    last_error=AgentPlanningError(
                        "empty provider response",
                        code="planner_response_incomplete",
                    )
                )

        run = AgentRuntimeService(self.db).create_run(
            payload=AgentRunCreateRequest(project_id=10, intent="Plan this request"),
            current_user=self.owner,
        )
        with patch.object(
            agent_runtime_service.settings,
            "AGENT_LLM_INTENT_DECISION_ENABLED",
            True,
        ):
            failed = AgentConversationRunner(
                self.db,
                planning_decision_service=FailingPlanningService(),
            ).run(run_id=run.run_id, user_id=self.owner.id)

        self.assertEqual(failed.status, "failed")
        self.assertEqual(failed.error_code, "agent_planning_failed")
        event_types = [
            event.event_type
            for event in self.db.scalars(select(AgentEvent).where(AgentEvent.run_id == run.run_id))
        ]
        self.assertIn("planner.llm_decision_failed", event_types)
        self.assertNotIn("planner.intent_decision_fallback", event_types)

    def test_multiturn_planner_selects_case_artifact_then_switches_to_report_skill(self):
        from app.core.sensitive_data import request_fingerprint
        from app.models.project import ProjectEnvironment
        from app.models.test_case import TestCase
        from app.services.agent_capability_plan_service import AgentCapabilityPlanService
        from app.services.agent_planning_service import ValidatedAgentPlanningDecision
        from app.services.agent_runtime_service import AgentToolRuntime

        conversation_id = "agent-conv-planning-switch"
        environment = ProjectEnvironment(
            id=40,
            project_id=10,
            name="Planning Env",
            base_url="https://example.test",
            is_default=True,
            is_deleted=False,
            created_by_id=self.owner.id,
        )
        case = TestCase(
            id=401,
            project_id=10,
            environment_id=40,
            name="Real query case",
            method="GET",
            path="/api/real-query",
            headers={},
            query_params={},
            body_type="none",
            body=None,
            assertions=[{"type": "status_code", "expected": 200}],
            extractors=[],
            retry_policy={},
            created_by_id=self.owner.id,
        )
        self.db.add_all([environment, case])
        self.db.commit()
        runtime = AgentRuntimeService(self.db)
        source_run = runtime.create_run(
            payload=AgentRunCreateRequest(
                project_id=10,
                conversation_id=conversation_id,
                intent="Analyze project cases",
            ),
            current_user=self.owner,
        )
        source_decision = ValidatedAgentIntentDecision(
            action="analyze",
            target_domain="test_case",
            source_domains=(),
            confidence=0.99,
            source="offline_test_setup",
        )
        source_context = AgentContextManager().route(
            source_run.intent,
            intent_action=source_decision.as_intent_action(),
        )
        AgentCapabilityPlanService(self.db).create_active_plan(
            run=source_run,
            iteration=0,
            context_plan=source_context,
            intent_decision=source_decision,
            source=source_decision.source,
        )
        query_call = ExecutionLedgerService(self.db).create_tool_call(
            payload=AgentToolCallCreateRequest(
                run_id=source_run.run_id,
                tool_name="testcase.query_project_cases",
                input={
                    "project_id": 10,
                    "environment_id": 40,
                    "detail_level": "summary",
                },
                step_index=0,
            ),
            current_user=self.owner,
            enqueue=False,
        )
        query_output = AgentToolRuntime(self.db).execute(call=query_call, current_user=self.owner)
        query_call.status = "succeeded"
        query_call.output_json_redacted = query_output
        query_call.output_hash = request_fingerprint(query_output)
        self.db.commit()
        runtime.complete_run(source_run, {"message": "Case analysis complete."}, commit=True)
        case_artifact_id = f"agent-tool-artifact://{query_call.tool_call_id}/test_case_query_snapshot"

        planner_inputs = []

        class SwitchingPlanningService:
            def decide(self, **kwargs):
                planner_inputs.append(kwargs)
                if "scenario" in kwargs["intent"]:
                    artifact_ids = {item["artifact_id"] for item in kwargs["artifact_index"]}
                    if case_artifact_id not in artifact_ids:
                        raise AssertionError("test-case SOURCE artifact was not exposed to the planner")
                    return ValidatedAgentPlanningDecision(
                        goal="Compose a scenario from the analyzed cases.",
                        action="create_draft",
                        target_domain="scenario",
                        source_domains=("test_case",),
                        selected_skills=("scenario-composition",),
                        selected_tools=("scenario.compose_draft",),
                        selected_artifact_ids=(case_artifact_id,),
                        required_facts=("test_case_query_snapshot",),
                        requested_effect_scope="draft",
                        confidence=0.98,
                        reason_summary="Use the authoritative case query artifact.",
                    )
                return ValidatedAgentPlanningDecision(
                    goal="Read the project report.",
                    action="query",
                    target_domain="report",
                    source_domains=(),
                    selected_skills=("report-summary",),
                    selected_tools=("report.read_summary",),
                    selected_artifact_ids=(),
                    required_facts=(),
                    requested_effect_scope="observe",
                    confidence=0.97,
                    reason_summary="The later turn requests a report, not scenario composition.",
                )

        def fake_stream(_service, payload):
            yield {"type": "delta", "content": "Turn completed."}
            yield {"type": "done", "finish_reason": "stop", "model": "deepseek-test"}

        scenario_run = runtime.create_run(
            payload=AgentRunCreateRequest(
                project_id=10,
                conversation_id=conversation_id,
                intent="build a scenario from those cases",
            ),
            current_user=self.owner,
        )
        report_run = None
        with (
            patch.object(agent_runtime_service.settings, "AGENT_LLM_INTENT_DECISION_ENABLED", True),
            patch("app.services.agent_runtime_service.AIService.chat_stream", new=fake_stream),
        ):
            scenario_run = AgentConversationRunner(
                self.db,
                planning_decision_service=SwitchingPlanningService(),
            ).run(run_id=scenario_run.run_id, user_id=self.owner.id)
            report_run = runtime.create_run(
                payload=AgentRunCreateRequest(
                    project_id=10,
                    conversation_id=conversation_id,
                    intent="now read the project report",
                ),
                current_user=self.owner,
            )
            report_run = AgentConversationRunner(
                self.db,
                planning_decision_service=SwitchingPlanningService(),
            ).run(run_id=report_run.run_id, user_id=self.owner.id)

        scenario_plan = self.db.scalar(
            select(AgentCapabilityPlanRecord).where(
                AgentCapabilityPlanRecord.run_id == scenario_run.run_id,
                AgentCapabilityPlanRecord.status == "active",
            )
        )
        report_plan = self.db.scalar(
            select(AgentCapabilityPlanRecord).where(
                AgentCapabilityPlanRecord.run_id == report_run.run_id,
                AgentCapabilityPlanRecord.status == "active",
            )
        )
        self.assertEqual(scenario_run.status, "completed")
        self.assertEqual(report_run.status, "completed")
        self.assertEqual(scenario_plan.intent_decision_json["selected_skills"], ["scenario-composition"])
        self.assertEqual(scenario_plan.intent_decision_json["selected_artifact_ids"], [case_artifact_id])
        self.assertEqual(report_plan.intent_decision_json["selected_skills"], ["report-summary"])
        self.assertNotIn("scenario-composition", report_plan.intent_decision_json["selected_skills"])
        self.assertEqual(len(planner_inputs), 2)


if __name__ == "__main__":
    unittest.main()
