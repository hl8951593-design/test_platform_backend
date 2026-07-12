import json
import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.schemas.defect import DefectRead
from app.schemas.execution_record import ExecutionRecordPage, ExecutionRecordSummary
from app.schemas.test_plan import TestPlanRead
from app.services.agent_context_manager import AgentContextManager
from app.services.agent_runtime_service import _tool_input_summary
from app.services.agent_runtime_service import (
    ENVIRONMENT_REFERENCE_RULE,
    FLOW_HTTP_TEST_CASE_REFERENCE_RULE,
    FLOW_WEBSOCKET_TEST_CASE_REFERENCE_RULE,
    OBJECT_REFERENCE_GUARD_RULES,
    PLAN_SCENARIO_TARGET_REFERENCE_RULE,
    ToolExecutor,
)
from app.services.agent_tool_result_projection import ToolResultProjectionService
from app.services.agent_tool_service import AgentToolBackend, ToolRegistry


OLD_TOOL_NAMES = {
    "ai_skill.run_draft",
    "environment.create_config",
    "environment.delete_config",
    "environment.delete_variable",
    "environment.query_project_configs",
    "environment.update_config",
    "environment.upsert_variable",
    "project.read_context",
    "report.read_summary",
    "scenario.compose_draft",
    "scenario.create_saved",
    "scenario.execute_dry_run",
    "scenario.query_project_scenarios",
    "scenario.update_saved",
    "testcase.batch_execute",
    "testcase.batch_update_assertions",
    "testcase.create_saved",
    "testcase.execute_saved",
    "testcase.query_project_cases",
    "testcase.update_assertions",
    "testcase.update_saved",
    "testcase.validate_schema",
    "tool_result.read_full",
    "websocket_testcase.batch_execute",
    "websocket_testcase.batch_update_assertions",
    "websocket_testcase.create_saved",
    "websocket_testcase.execute_saved",
    "websocket_testcase.update_assertions",
    "websocket_testcase.update_saved",
}

NEW_TOOL_NAMES = {
    "execution.query_records",
    "execution.read_detail",
    "execution.diagnose",
    "plan.query_project_plans",
    "plan.create_saved",
    "plan.update_saved",
    "plan.set_enabled",
    "plan.execute_saved",
    "plan.query_runs",
    "plan.read_run",
    "flow.query_project_flows",
    "flow.validate_graph",
    "flow.create_saved",
    "flow.update_saved",
    "flow.execute_saved",
    "defect.query_project_defects",
    "defect.create_saved",
    "defect.update_saved",
    "defect.transition_status",
}


class AgentPlatformToolTests(unittest.TestCase):
    def setUp(self):
        self.db = MagicMock()
        self.user = SimpleNamespace(id=1, username="owner", is_active=True)
        self.backend = AgentToolBackend(self.db)

    def test_registry_adds_platform_tools_without_replacing_existing_tools(self):
        specs = {item.name: item for item in ToolRegistry().list_specs()}

        self.assertEqual(set(specs), OLD_TOOL_NAMES | NEW_TOOL_NAMES)
        self.assertEqual(len(specs), 48)
        self.assertEqual(specs["testcase.query_project_cases"].backend_handler, "_testcase_query_project_cases")
        self.assertEqual(specs["scenario.execute_dry_run"].side_effect_class, "execution_record")
        self.assertEqual(specs["plan.execute_saved"].side_effect_class, "execution_record")
        self.assertEqual(specs["flow.validate_graph"].side_effect_class, "deterministic_compute")
        self.assertEqual(specs["defect.create_saved"].side_effect_class, "business_update")
        self.assertEqual(specs["execution.diagnose"].side_effect_class, "draft_only")
        for spec in specs.values():
            self.assertTrue(callable(getattr(self.backend, spec.backend_handler or "", None)), spec.name)

    def test_context_routes_each_platform_domain_and_exposes_model_contracts(self):
        cases = [
            (
                "查询当前项目最近失败执行并诊断原因",
                "execution-diagnosis",
                {"execution.query_records", "execution.read_detail", "execution.diagnose"},
            ),
            (
                "查询并执行当前项目测试计划",
                "test-plan-management",
                {"plan.query_project_plans", "plan.execute_saved", "plan.query_runs", "plan.read_run"},
            ),
            (
                "设计、校验并保存一个可视化流程 DAG",
                "visual-flow-design",
                {"flow.query_project_flows", "flow.validate_graph", "flow.create_saved"},
            ),
            (
                "查询当前缺陷并关闭已经修复的缺陷",
                "defect-triage",
                {"defect.query_project_defects", "defect.transition_status"},
            ),
        ]
        registry = ToolRegistry()
        for intent, expected_skill, expected_tools in cases:
            with self.subTest(intent=intent):
                plan = AgentContextManager().route(intent)
                self.assertEqual([item.name for item in plan.selected_skills], [expected_skill])
                self.assertTrue(expected_tools.issubset(set(plan.allowed_tools)))
                contracts = {
                    name: _tool_input_summary(registry.get(name).input_schema)
                    for name in expected_tools
                }
                self.assertTrue(all(item["required"] for item in contracts.values()))
                self.assertTrue(all("project_id" in item["properties"] for item in contracts.values()))

    @patch("app.services.agent_platform_tool_service.ExecutionRecordService.list_records")
    def test_execution_query_returns_snapshot_and_object_reference(self, list_records):
        list_records.return_value = ExecutionRecordPage(
            items=[
                ExecutionRecordSummary(
                    id="http:41",
                    execution_type="http",
                    execution_id=41,
                    project_id=10,
                    resource_id=7,
                    resource_name="login",
                    status="failed",
                    trigger_type="agent",
                    trigger_user_id=1,
                    created_at=datetime.now(UTC),
                )
            ],
            total=1,
            page=1,
            page_size=20,
        )

        result = self.backend.execute(
            tool_name="execution.query_records",
            payload={"project_id": 10, "status": "failed"},
            current_user=self.user,
        )

        self.assertEqual(result["executions"][0]["execution_id"], 41)
        self.assertTrue(result["executions"][0]["object_ref"].endswith("/41"))
        self.assertEqual(result["object_reference_manifest"]["query_tool"], "execution.query_records")

    @patch("app.services.agent_platform_tool_service.TestPlanService.list_plans")
    def test_plan_query_returns_fact_snapshot(self, list_plans):
        now = datetime.now(UTC)
        plan = TestPlanRead(
            id=5,
            project_id=10,
            version=2,
            name="smoke",
            description="smoke plan",
            enabled=True,
            trigger_type="manual",
            cron_expression=None,
            schedule_timezone="Asia/Shanghai",
            webhook_event=None,
            environment_ids=[3],
            targets=[],
            execution_mode="serial",
            failure_policy="stop",
            retry_count=0,
            timeout_minutes=30,
            notification_emails=[],
            tags=["smoke"],
            created_by_id=1,
            created_at=now,
            updated_at=now,
            last_run_at=None,
            next_run_at=None,
        )
        list_plans.return_value = {
            "items": [plan],
            "total": 1,
            "page": 1,
            "page_size": 20,
            "statistics": {"total": 1, "enabled": 1},
        }

        result = self.backend.execute(
            tool_name="plan.query_project_plans",
            payload={"project_id": 10},
            current_user=self.user,
        )

        self.assertEqual(result["plan_ids"], [5])
        self.assertTrue(result["plans"][0]["object_ref"].endswith("/5"))
        self.assertEqual(result["object_reference_manifest"]["query_tool"], "plan.query_project_plans")

    @patch("app.services.agent_platform_tool_service.execution_worker.submit", return_value=True)
    @patch("app.services.agent_platform_tool_service.TestPlanService.create_plan_run")
    def test_plan_execute_queues_background_work_without_running_inline(self, create_plan_run, submit):
        create_plan_run.return_value = SimpleNamespace(
            id=55,
            plan_id=5,
            plan_name="smoke",
            plan_version=2,
            project_id=10,
            environment_id=3,
            environment_name="test",
            status="pending",
            trigger="agent",
            scheduled_at=None,
            started_at=datetime.now(UTC),
            finished_at=None,
            duration_ms=None,
            target_count=1,
            passed_count=0,
            failed_count=0,
            error_message=None,
            operator_id=1,
            operator=self.user,
            target_results=[],
        )

        result = self.backend.execute(
            tool_name="plan.execute_saved",
            payload={"project_id": 10, "plan_id": 5, "environment_id": 3},
            current_user=self.user,
        )

        self.assertTrue(result["accepted"])
        self.assertEqual(result["run_id"], 55)
        submit.assert_called_once()
        self.assertEqual(submit.call_args.args[1], 55)

    @patch("app.services.agent_platform_tool_service.VisualFlowService.validate_definition")
    def test_flow_validate_uses_existing_service_without_persisting(self, validate_definition):
        validate_definition.return_value = {"valid": True, "issues": [], "executable": True}
        definition = {
            "schemaVersion": "1.0",
            "nodes": [
                {"id": "start", "kind": "start", "name": "Start", "position": {"x": 0, "y": 0}},
                {"id": "end", "kind": "end", "name": "End", "position": {"x": 200, "y": 0}},
            ],
            "edges": [{"id": "edge-1", "source": "start", "target": "end", "route": "success"}],
        }

        result = self.backend.execute(
            tool_name="flow.validate_graph",
            payload={"project_id": 10, "definition": definition},
            current_user=self.user,
        )

        self.assertTrue(result["valid"])
        validate_definition.assert_called_once()

    @patch("app.services.agent_platform_tool_service.DefectService.list_defects")
    def test_defect_query_returns_fact_snapshot(self, list_defects):
        now = datetime.now(UTC)
        defect = DefectRead(
            id=9,
            project_id=10,
            title="Login returns 500",
            assignee_name=None,
            bug_type="functional",
            urgency="high",
            status="new",
            content_html="<p>500</p>",
            reporter_name="owner",
            attachments=[],
            created_at=now,
            updated_at=now,
        )
        list_defects.return_value = {"items": [defect], "total": 1, "page": 1, "page_size": 20}

        result = self.backend.execute(
            tool_name="defect.query_project_defects",
            payload={"project_id": 10},
            current_user=self.user,
        )

        self.assertEqual(result["defect_ids"], [9])
        self.assertTrue(result["defects"][0]["object_ref"].endswith("/9"))
        self.assertEqual(result["object_reference_manifest"]["query_tool"], "defect.query_project_defects")

    def test_platform_query_projection_keeps_refs_and_snapshot_for_model(self):
        output = {
            "project_id": 10,
            "total": 1,
            "page": 1,
            "page_size": 20,
            "object_reference_manifest": {
                "snapshot_id": "plan-snapshot://abc",
                "validity_scope": "current_agent_conversation_latest_query",
            },
            "plans": [{"id": 5, "object_ref": "object-ref://test_plan/test_plan/token/5", "name": "smoke"}],
        }

        projection = ToolResultProjectionService().project("plan.query_project_plans", output)

        self.assertIsNotNone(projection)
        self.assertEqual(projection.model_output["snapshot"]["snapshot_id"], "plan-snapshot://abc")
        self.assertEqual(projection.model_output["plans"][0]["object_ref"], output["plans"][0]["object_ref"])
        json.dumps(projection.model_output, ensure_ascii=False)

    def test_plan_nested_targets_and_environments_are_visible_to_reference_preflight(self):
        call = SimpleNamespace(
            input_json_redacted={
                "project_id": 10,
                "plan": {
                    "environment_ids": [3, 4],
                    "targets": [
                        {"kind": "scenario", "reference_id": 21, "sort_order": 1},
                        {"kind": "scenario", "reference_id": 22, "sort_order": 2},
                    ],
                },
            }
        )

        self.assertEqual(
            ToolExecutor._object_reference_requested_ids(call, PLAN_SCENARIO_TARGET_REFERENCE_RULE),
            [21, 22],
        )
        self.assertEqual(
            ToolExecutor._object_reference_requested_refs(
                SimpleNamespace(input_json_redacted={"object_reference": "object-ref://test_plan/test_plan/x/5"}),
                PLAN_SCENARIO_TARGET_REFERENCE_RULE,
            ),
            [],
        )
        self.assertEqual(
            ToolExecutor._object_reference_requested_ids(call, ENVIRONMENT_REFERENCE_RULE),
            [3, 4],
        )
        self.assertEqual(
            OBJECT_REFERENCE_GUARD_RULES["plan.update_saved"][0].query_tool,
            "plan.query_project_plans",
        )
        self.assertEqual(
            OBJECT_REFERENCE_GUARD_RULES["flow.execute_saved"][0].query_tool,
            "flow.query_project_flows",
        )
        self.assertEqual(
            OBJECT_REFERENCE_GUARD_RULES["defect.transition_status"][0].query_tool,
            "defect.query_project_defects",
        )
        flow_call = SimpleNamespace(
            input_json_redacted={
                "project_id": 10,
                "flow": {"definition": {"environment_id": 3}},
            }
        )
        self.assertEqual(
            ToolExecutor._object_reference_requested_ids(flow_call, ENVIRONMENT_REFERENCE_RULE),
            [3],
        )
        flow_case_call = SimpleNamespace(
            input_json_redacted={
                "project_id": 10,
                "case_snapshot_id": "case-snapshot://latest",
                "flow": {
                    "definition": {
                        "nodes": [
                            {"kind": "api_case", "referenceId": 41},
                            {"kind": "websocket_case", "reference_id": 42},
                        ]
                    }
                },
            }
        )
        self.assertEqual(
            ToolExecutor._object_reference_requested_ids(flow_case_call, FLOW_HTTP_TEST_CASE_REFERENCE_RULE),
            [41],
        )
        self.assertEqual(
            ToolExecutor._object_reference_requested_ids(flow_case_call, FLOW_WEBSOCKET_TEST_CASE_REFERENCE_RULE),
            [42],
        )
        self.assertEqual(
            OBJECT_REFERENCE_GUARD_RULES["flow.create_saved"][:2],
            (FLOW_HTTP_TEST_CASE_REFERENCE_RULE, FLOW_WEBSOCKET_TEST_CASE_REFERENCE_RULE),
        )


if __name__ == "__main__":
    unittest.main()
