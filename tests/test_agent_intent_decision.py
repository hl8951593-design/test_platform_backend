import unittest
from types import SimpleNamespace

from app.services.agent_intent_action import parse_agent_intent_action


class AgentIntentDecisionTests(unittest.TestCase):
    def test_cross_domain_paraphrase_matrix_uses_structured_llm_roles(self):
        from app.services.agent_intent_decision_service import AgentIntentDecisionService

        cases = (
            ("给错误的测试用例创建缺陷", "defect", ("test_case",)),
            ("根据失败用例创建对应的缺陷", "defect", ("test_case",)),
            ("创建缺陷，证据采用失败测试用例", "defect", ("test_case",)),
            ("把失败执行转成缺陷", "defect", ("execution",)),
            ("根据报告生成测试计划", "test_plan", ("report",)),
            ("生成测试计划，数据来源是当前报告", "test_plan", ("report",)),
            ("使用这个缺陷生成回归测试用例", "test_case", ("defect",)),
            ("给这个测试计划创建执行场景", "scenario", ("test_plan",)),
        )

        for text, target, sources in cases:
            with self.subTest(text=text):
                class FakeAIService:
                    def chat(self, _request):
                        return SimpleNamespace(
                            content=(
                                '{"action":"create","target_domain":"'
                                + target
                                + '","source_domains":'
                                + str(list(sources)).replace("'", '"')
                                + ',"confidence":0.96}'
                            )
                        )

                decision = AgentIntentDecisionService(ai_service=FakeAIService()).decide(
                    intent=text,
                    working_context=None,
                    domains=("defect", "execution", "report", "scenario", "test_case", "test_plan"),
                )
                self.assertEqual(
                    (decision.action, decision.target_domain, decision.source_domains),
                    ("create", target, sources),
                )

    def test_deterministic_fallback_does_not_guess_cross_domain_target_from_word_order(self):
        cases = (
            "根据失败用例创建对应的缺陷",
            "创建缺陷，证据采用失败测试用例",
        )

        for text in cases:
            with self.subTest(text=text):
                action = parse_agent_intent_action(text)
                self.assertEqual(action.action, "create")
                self.assertIsNone(action.target_domain)
                self.assertEqual(action.source_domains, ())
                self.assertIn("intent:fallback_cross_domain_ambiguous", action.reason_codes)

    def test_llm_structured_decision_is_validated_and_exposes_confidence(self):
        from app.services.agent_intent_decision_service import AgentIntentDecisionService

        class FakeAIService:
            def chat(self, _request):
                return SimpleNamespace(
                    content=(
                        '{"action":"create","target_domain":"defect",'
                        '"source_domains":["test_case"],"confidence":0.96}'
                    )
                )

        decision = AgentIntentDecisionService(ai_service=FakeAIService()).decide(
            intent="给错误的测试用例创建缺陷",
            working_context=None,
            domains=("defect", "test_case"),
        )

        self.assertEqual(decision.action, "create")
        self.assertEqual(decision.target_domain, "defect")
        self.assertEqual(decision.source_domains, ("test_case",))
        self.assertEqual(decision.confidence, 0.96)
        self.assertEqual(decision.source, "llm_intent")

    def test_write_action_without_target_domain_is_rejected(self):
        from app.services.agent_intent_decision_service import (
            AgentIntentDecisionError,
            AgentIntentDecisionService,
        )

        class FakeAIService:
            def chat(self, _request):
                return SimpleNamespace(
                    content=(
                        '{"action":"create","target_domain":null,'
                        '"source_domains":["test_case","defect"],"confidence":0.99}'
                    )
                )

        with self.assertRaises(AgentIntentDecisionError):
            AgentIntentDecisionService(ai_service=FakeAIService()).decide(
                intent="根据失败用例创建缺陷",
                working_context=None,
                domains=("defect", "test_case"),
            )

    def test_context_manager_uses_validated_llm_target_instead_of_text_fallback(self):
        from app.services.agent_context_manager import AgentContextManager
        from app.services.agent_intent_decision_service import ValidatedAgentIntentDecision

        decision = ValidatedAgentIntentDecision(
            action="create",
            target_domain="defect",
            source_domains=("test_case",),
            confidence=0.96,
            source="llm_intent",
            reason_codes=("intent_decision:validated",),
        )

        plan = AgentContextManager().route(
            "生成测试用例",
            intent_action=decision.as_intent_action(),
        )

        self.assertEqual(plan.primary_skill, "defect-triage")
        self.assertIn("http-test-case-design", plan.supporting_skills)
        self.assertIn("defect.create_saved", plan.allowed_tools)
        self.assertNotIn("testcase.create_saved", plan.allowed_tools)

    def test_untrusted_fallback_decision_cannot_authorize_write_tools(self):
        from app.services.agent_context_manager import AgentContextManager
        from app.services.agent_intent_decision_service import ValidatedAgentIntentDecision

        decision = ValidatedAgentIntentDecision(
            action="create",
            target_domain="defect",
            source_domains=("test_case",),
            confidence=0.2,
            source="deterministic_fallback",
            reason_codes=("intent_decision:repair_failed",),
            write_authorized=False,
        )

        plan = AgentContextManager().route(
            "给错误的测试用例创建缺陷",
            intent_action=decision.as_intent_action(),
        )

        self.assertIn("defect.query_project_defects", plan.allowed_tools)
        self.assertIn("testcase.query_project_cases", plan.allowed_tools)
        self.assertNotIn("defect.create_saved", plan.allowed_tools)

    def test_analyze_action_exposes_only_read_or_deterministic_tools(self):
        from app.services.agent_context_manager import AgentContextManager
        from app.services.agent_intent_decision_service import ValidatedAgentIntentDecision
        from app.services.agent_tool_service import ToolRegistry

        decision = ValidatedAgentIntentDecision(
            action="analyze",
            target_domain="test_case",
            source_domains=(),
            confidence=0.95,
            source="llm_intent",
            reason_codes=("intent_decision:validated",),
        )

        plan = AgentContextManager().route(
            "分析测试用例",
            intent_action=decision.as_intent_action(),
        )

        registry = ToolRegistry()
        self.assertIn("project.read_context", plan.allowed_tools)
        self.assertIn("testcase.query_project_cases", plan.allowed_tools)
        self.assertTrue(
            all(
                registry.get(tool_name).side_effect_class in {"read_only", "deterministic_compute"}
                for tool_name in plan.allowed_tools
            )
        )
        self.assertNotIn("testcase.batch_execute", plan.allowed_tools)
        self.assertNotIn("testcase.create_saved", plan.allowed_tools)
        self.assertNotIn("testcase.update_saved", plan.allowed_tools)


if __name__ == "__main__":
    unittest.main()
