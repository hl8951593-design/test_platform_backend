import json
import unittest
from types import SimpleNamespace

from fastapi import HTTPException

from app.ai_skills import get_ai_skill
from app.ai_skills.base import AISkillRunner
from app.schemas.ai import (
    AIGeneratedScenarioResponse,
    AIScenarioComposeRequest,
    AISkillRunRequest,
    AITestCaseGenerateRequest,
    AIWebSocketTestCaseGenerateRequest,
)
from app.services.ai_run_event_service import AIRunEventStore, AIRunTrace
from app.services.ai_scenario_composer_service import AIScenarioComposerService
from app.services.ai_skill_run_service import AISkillRunService
from app.services.ai_skill_service import AISkillService
from app.services.ai_test_case_service import AITestCaseService
from app.services.ai_websocket_test_case_service import AIWebSocketTestCaseService


class FakeAIService:
    def __init__(self, content: dict):
        self.content = content
        self.requests = []

    def chat(self, payload):
        self.requests.append(payload)
        return SimpleNamespace(content=json.dumps(self.content, ensure_ascii=False))


class AISkillTests(unittest.TestCase):
    def test_formal_skill_metadata_is_loaded(self):
        skill = get_ai_skill("http-test-case")

        self.assertEqual(skill.name, "http-test-case")
        self.assertIn("HTTP API test case", skill.description)
        self.assertEqual(skill.package.info().protocol, "http")

    def test_skill_service_lists_manifest_and_json_schema(self):
        skills = AISkillService(SimpleNamespace()).list_skills()
        http_skill = next(item for item in skills if item.id == "http-test-case")
        generate = next(item for item in http_skill.operations if item.name == "generate")

        self.assertEqual(http_skill.version, "1.0.0")
        self.assertEqual(generate.input_schema, "AITestCaseGenerateRequest")
        self.assertIn("interface_text", generate.input_json_schema["properties"])
        self.assertTrue(generate.requires_environment)

        scenario_skill = next(item for item in skills if item.id == "scenario-composer")
        compose = next(item for item in scenario_skill.operations if item.name == "compose")
        self.assertEqual(compose.input_schema, "AIScenarioComposeRequest")
        self.assertIn("requirement", compose.input_json_schema["properties"])

    def test_http_case_generation_uses_formal_skill_package(self):
        service = object.__new__(AITestCaseService)
        service.permission_service = SimpleNamespace(require_project_permission=lambda *args: None)
        service.project_repository = SimpleNamespace(
            get_environment=lambda **kwargs: SimpleNamespace(
                id=2,
                name="dev",
                base_url="https://api.example.test",
                description=None,
            ),
            list_environment_variables=lambda **kwargs: [SimpleNamespace(name="token", is_secret=True)],
        )
        service.ai_service = FakeAIService({
            "source_summary": "login api",
            "cases": [{
                "name": "登录成功",
                "method": "post",
                "path": "https://api.example.test/login?client=web",
                "headers": {"Authorization": "Bearer {{token}}"},
                "query_params": {},
                "body_type": "json",
                "body": {"username": "demo"},
                "assertions": [{"type": "status_code", "expected": 200}],
                "extractors": [{"name": "access_token", "path": "data.token"}],
            }],
            "warnings": [],
        })

        result = service.generate_test_cases(
            project_id=1,
            environment_id=2,
            payload=AITestCaseGenerateRequest(interface_text="POST /login"),
            current_user=SimpleNamespace(id=1),
        )

        self.assertEqual(result.cases[0].method, "POST")
        self.assertEqual(result.cases[0].path, "/login")
        self.assertEqual(result.cases[0].query_params, {"client": "web"})
        self.assertIn("接口测试用例生成助手", service.ai_service.requests[0].messages[0].content)

    def test_generic_skill_run_delegates_to_http_generation(self):
        db = SimpleNamespace()
        user = SimpleNamespace(id=1)
        generated = SimpleNamespace(project_id=1, marker="generated")
        captured = {}

        class FakeTestCaseService:
            def __init__(self, service_db):
                captured["db"] = service_db

            def generate_test_cases(self, **kwargs):
                captured.update(kwargs)
                return generated

        original = __import__("app.services.ai_skill_service", fromlist=["AITestCaseService"]).AITestCaseService
        module = __import__("app.services.ai_skill_service", fromlist=["AITestCaseService"])
        module.AITestCaseService = FakeTestCaseService
        try:
            result = AISkillService(db).run_skill(
                skill_id="http-test-case",
                payload=AISkillRunRequest(
                    operation="generate",
                    project_id=1,
                    environment_id=2,
                    input={"interface_text": "GET /health"},
                ),
                current_user=user,
            )
        finally:
            module.AITestCaseService = original

        self.assertIs(result, generated)
        self.assertIs(captured["db"], db)
        self.assertEqual(captured["project_id"], 1)
        self.assertEqual(captured["environment_id"], 2)
        self.assertIs(captured["current_user"], user)
        self.assertIsInstance(captured["payload"], AITestCaseGenerateRequest)

    def test_scenario_composer_skill_normalizes_candidate_references(self):
        skill = get_ai_skill("scenario-composer")
        payload = AIScenarioComposeRequest(
            requirement="登录后查询用户详情",
            scenario_name="用户详情链路",
            http_test_case_ids=[10, 11],
        )
        result = skill.parse_response(
            json.dumps({
                "source_summary": "组合登录和详情查询",
                "scenario": {
                    "name": "用户详情链路",
                    "description": "登录后查询用户详情",
                    "environment_id": 999,
                    "nodes": [
                        {
                            "id": "LOGIN",
                            "name": "登录",
                            "before_actions": [{
                                "id": "SET-TENANT",
                                "kind": "fixed_value",
                                "name": "设置租户",
                                "config": {"output": "tenantId", "value": 1001},
                            }],
                            "test_case": {
                                "id": "LOGIN-CASE",
                                "kind": "api_case",
                                "reference_id": 10,
                                "assertions": [
                                    {"type": "status_code", "expected": 200},
                                    {"type": "json_equals", "path": "code", "expected": 0},
                                ],
                                "extractors": [{"id": "VAR-token", "name": "token", "path": "data.token"}],
                                "config": {
                                    "_scenario_context": {
                                        "extractions": [{"id": "VAR-token", "name": "token", "path": "data.token"}]
                                    }
                                },
                            },
                        },
                        {
                            "id": "DETAIL",
                            "name": "查询详情",
                            "test_case": {
                                "id": "DETAIL-CASE",
                                "kind": "api_case",
                                "reference_id": 11,
                                "bindings": [{
                                    "id": "BIND-token",
                                    "name": "token",
                                    "source_step_id": "LOGIN-CASE",
                                    "source_extraction_id": "VAR-token",
                                    "target": "headers",
                                    "target_path": "Authorization",
                                }],
                                "config": {
                                    "headers": {"Authorization": "Bearer {{token}}"},
                                    "_scenario_context": {
                                        "bindings": [{
                                            "id": "BIND-token",
                                            "name": "token",
                                            "source_step_id": "LOGIN-CASE",
                                            "source_extraction_id": "VAR-token",
                                            "target": "headers",
                                            "target_path": "Authorization",
                                        }]
                                    }
                                },
                            },
                            "after_actions": [{
                                "id": "WAIT-AFTER",
                                "kind": "delay",
                                "name": "等待数据同步",
                                "config": {"duration_ms": 1},
                            }],
                        },
                    ],
                    "datasets": [{"id": "SHOULD-DROP", "name": "drop", "variables": {}}],
                },
                "warnings": [],
            }, ensure_ascii=False),
            {
                "project_id": 1,
                "environment_id": 2,
                "payload": payload,
                "candidate_cases": [],
                "environment": {"id": 2, "name": "UAT"},
                "candidate_index": {
                    ("api_case", 10): {"name": "登录", "method": "POST", "path": "/login"},
                    ("api_case", 11): {"name": "查询详情", "method": "GET", "path": "/users/me"},
                },
            },
        )

        self.assertEqual(result.environment_id, 2)
        self.assertEqual(result.environment_name, "UAT")
        self.assertEqual(result.scenario.environment_id, 2)
        self.assertEqual(len(result.scenario.nodes), 2)
        self.assertEqual(result.scenario.nodes[0].test_case.reference_id, 10)
        self.assertEqual(result.scenario.nodes[0].before_actions[0].kind, "fixed_value")
        self.assertEqual(result.scenario.nodes[0].test_case.config["assertions"][1]["path"], "code")
        self.assertEqual(result.scenario.nodes[0].test_case.config["extractors"][0]["name"], "token")
        self.assertEqual(result.scenario.nodes[1].test_case.config["_scenario_context"]["bindings"][0]["name"], "token")
        self.assertEqual(result.scenario.nodes[1].test_case.config["headers"]["Authorization"], "Bearer {{token}}")
        self.assertEqual(result.scenario.nodes[1].after_actions[0].kind, "delay")
        self.assertEqual(result.scenario.datasets, [])

    def test_scenario_composer_repairs_blank_assertion_expected_values(self):
        skill = get_ai_skill("scenario-composer")
        payload = AIScenarioComposeRequest(
            requirement="取消关注后校验响应",
            scenario_name="取消关注",
            http_test_case_ids=[10],
        )

        result = skill.parse_response(
            json.dumps({
                "source_summary": "组合取消关注接口",
                "scenario": {
                    "name": "取消关注",
                    "description": "取消关注后校验业务码",
                    "nodes": [{
                        "id": "UNFOLLOW",
                        "name": "取消关注",
                        "test_case": {
                            "id": "UNFOLLOW-CASE",
                            "kind": "api_case",
                            "reference_id": 10,
                            "assertions": [
                                {"type": "status_code", "expected": ""},
                                {"type": "json_equals", "path": "code", "expected": ""},
                            ],
                        },
                    }],
                },
                "warnings": [],
            }, ensure_ascii=False),
            {
                "project_id": 1,
                "environment_id": 2,
                "payload": payload,
                "candidate_cases": [],
                "candidate_index": {
                    ("api_case", 10): {
                        "kind": "api_case",
                        "name": "取消关注",
                        "method": "POST",
                        "path": "/follow/cancel",
                        "assertions": [],
                        "execution_sample": {
                            "response_snapshot": {
                                "status_code": 201,
                                "json": {"code": 0, "message": "ok"},
                            }
                        },
                    },
                },
            },
        )

        assertions = result.scenario.nodes[0].test_case.config["assertions"]
        self.assertEqual(assertions[0]["expected"], 201)
        self.assertEqual(assertions[1]["path"], "code")
        self.assertEqual(assertions[1]["expected"], 0)

    def test_scenario_composer_drops_unrepairable_assertions(self):
        skill = get_ai_skill("scenario-composer")
        payload = AIScenarioComposeRequest(
            requirement="查询用户详情",
            scenario_name="用户详情",
            http_test_case_ids=[11],
        )

        result = skill.parse_response(
            json.dumps({
                "source_summary": "组合详情接口",
                "scenario": {
                    "name": "用户详情",
                    "description": "查询用户详情",
                    "nodes": [{
                        "id": "DETAIL",
                        "name": "查询详情",
                        "test_case": {
                            "id": "DETAIL-CASE",
                            "kind": "api_case",
                            "reference_id": 11,
                            "assertions": [
                                {"type": "json_equals", "path": "data.missing", "expected": ""},
                                {"type": "body_contains", "expected": ""},
                            ],
                        },
                    }],
                },
                "warnings": [],
            }, ensure_ascii=False),
            {
                "project_id": 1,
                "environment_id": 2,
                "payload": payload,
                "candidate_cases": [],
                "candidate_index": {
                    ("api_case", 11): {
                        "kind": "api_case",
                        "name": "查询详情",
                        "method": "GET",
                        "path": "/users/me",
                        "assertions": [],
                        "execution_sample": {
                            "response_snapshot": {
                                "status_code": 200,
                                "json": {"code": 0},
                            }
                        },
                    },
                },
            },
        )

        self.assertNotIn("assertions", result.scenario.nodes[0].test_case.config)
        self.assertTrue(any("已忽略" in warning for warning in result.warnings))

    def test_scenario_composer_replaces_unbound_templates_with_candidate_values(self):
        skill = get_ai_skill("scenario-composer")
        payload = AIScenarioComposeRequest(
            requirement="新增关注公司",
            scenario_name="新增关注",
            http_test_case_ids=[12],
        )

        result = skill.parse_response(
            json.dumps({
                "source_summary": "组合新增关注接口",
                "scenario": {
                    "name": "新增关注",
                    "description": "新增关注公司",
                    "nodes": [{
                        "id": "SAVE",
                        "name": "新增关注",
                        "test_case": {
                            "id": "SAVE-CASE",
                            "kind": "api_case",
                            "reference_id": 12,
                            "config": {
                                "body": {
                                    "companyId": "{{companyId}}",
                                    "companyName": "{{companyName}}",
                                }
                            },
                        },
                    }],
                },
                "warnings": [],
            }, ensure_ascii=False),
            {
                "project_id": 1,
                "environment_id": 2,
                "payload": payload,
                "candidate_cases": [],
                "candidate_index": {
                    ("api_case", 12): {
                        "kind": "api_case",
                        "name": "新增关注",
                        "method": "POST",
                        "path": "/myAttentionCompany/save",
                        "body": {
                            "companyId": 9527,
                            "companyName": "测试公司",
                        },
                        "assertions": [],
                    },
                },
            },
        )

        body = result.scenario.nodes[0].test_case.config["body"]
        self.assertEqual(body["companyId"], 9527)
        self.assertEqual(body["companyName"], "测试公司")
        self.assertTrue(any("已回填候选用例真实值" in warning for warning in result.warnings))

    def test_scenario_composer_repairs_extractor_paths_from_response_sample(self):
        skill = get_ai_skill("scenario-composer")
        payload = AIScenarioComposeRequest(
            requirement="获取企业后关注",
            scenario_name="企业关注链路",
            http_test_case_ids=[20, 21],
        )

        result = skill.parse_response(
            json.dumps({
                "source_summary": "组合获取企业和关注接口",
                "scenario": {
                    "name": "企业关注链路",
                    "description": "从分页接口提取企业信息后关注",
                    "nodes": [
                        {
                            "id": "PAGE",
                            "name": "获取企业列表",
                            "test_case": {
                                "id": "PAGE-CASE",
                                "kind": "api_case",
                                "reference_id": 20,
                                "extractors": [
                                    {"id": "VAR-companyId", "name": "companyId", "path": "companyId"},
                                    {"id": "VAR-companyName", "name": "companyName", "path": "companyName"},
                                ],
                            },
                        },
                        {
                            "id": "SAVE",
                            "name": "关注企业",
                            "test_case": {
                                "id": "SAVE-CASE",
                                "kind": "api_case",
                                "reference_id": 21,
                                "config": {
                                    "body": {
                                        "companyId": "{{companyId}}",
                                        "companyName": "{{companyName}}",
                                    }
                                },
                            },
                        },
                    ],
                },
                "warnings": [],
            }, ensure_ascii=False),
            {
                "project_id": 1,
                "environment_id": 2,
                "payload": payload,
                "candidate_cases": [],
                "candidate_index": {
                    ("api_case", 20): {
                        "kind": "api_case",
                        "name": "获取企业列表",
                        "method": "POST",
                        "path": "/getEntPageList",
                        "assertions": [],
                        "execution_sample": {
                            "response_snapshot": {
                                "status_code": 200,
                                "json": {
                                    "code": 0,
                                    "data": {
                                        "records": [{
                                            "companyId": 9527,
                                            "companyName": "测试公司",
                                        }]
                                    },
                                },
                            }
                        },
                    },
                    ("api_case", 21): {
                        "kind": "api_case",
                        "name": "关注企业",
                        "method": "POST",
                        "path": "/myAttentionCompany/save",
                        "body": {
                            "companyId": 1,
                            "companyName": "原始公司",
                        },
                        "assertions": [],
                    },
                },
            },
        )

        page_config = result.scenario.nodes[0].test_case.config
        self.assertEqual(page_config["extractors"][0]["path"], "data.records.0.companyId")
        self.assertEqual(page_config["extractors"][1]["path"], "data.records.0.companyName")
        self.assertEqual(
            page_config["_scenario_context"]["extractions"][0]["path"],
            "data.records.0.companyId",
        )
        save_body = result.scenario.nodes[1].test_case.config["body"]
        self.assertEqual(save_body["companyId"], "{{companyId}}")
        self.assertEqual(save_body["companyName"], "{{companyName}}")
        self.assertTrue(any("已修正" in warning for warning in result.warnings))

    def test_scenario_composer_keeps_templates_with_available_sources(self):
        skill = get_ai_skill("scenario-composer")
        payload = AIScenarioComposeRequest(
            requirement="登录后查询用户详情",
            scenario_name="用户详情链路",
            http_test_case_ids=[10, 11],
        )

        result = skill.parse_response(
            json.dumps({
                "source_summary": "组合登录和详情",
                "scenario": {
                    "name": "用户详情链路",
                    "description": "登录后查询用户详情",
                    "nodes": [
                        {
                            "id": "LOGIN",
                            "name": "登录",
                            "test_case": {
                                "id": "LOGIN-CASE",
                                "kind": "api_case",
                                "reference_id": 10,
                                "extractors": [{"id": "VAR-token", "name": "token", "path": "data.token"}],
                            },
                        },
                        {
                            "id": "DETAIL",
                            "name": "详情",
                            "test_case": {
                                "id": "DETAIL-CASE",
                                "kind": "api_case",
                                "reference_id": 11,
                                "config": {"headers": {"Authorization": "Bearer {{token}}"}},
                            },
                        },
                    ],
                },
                "warnings": [],
            }, ensure_ascii=False),
            {
                "project_id": 1,
                "environment_id": 2,
                "payload": payload,
                "candidate_cases": [],
                "candidate_index": {
                    ("api_case", 10): {
                        "kind": "api_case",
                        "name": "登录",
                        "method": "POST",
                        "path": "/login",
                        "assertions": [],
                    },
                    ("api_case", 11): {
                        "kind": "api_case",
                        "name": "详情",
                        "method": "GET",
                        "path": "/users/me",
                        "headers": {"Authorization": "Bearer saved-token"},
                        "assertions": [],
                    },
                },
            },
        )

        headers = result.scenario.nodes[1].test_case.config["headers"]
        self.assertEqual(headers["Authorization"], "Bearer {{token}}")

    def test_scenario_composer_service_repairs_after_failed_self_validation(self):
        scenario = {
            "name": "自验证场景",
            "description": "验证失败后修复",
            "environment_id": 2,
            "tags": ["ai-composed"],
            "nodes": [{
                "id": "NODE-1",
                "name": "查询",
                "test_case": {
                    "id": "CASE-1",
                    "kind": "api_case",
                    "reference_id": 10,
                    "name": "查询",
                    "method": "GET",
                    "path": "/items",
                    "config": {},
                },
            }],
            "datasets": [],
        }
        generated = [
            AIGeneratedScenarioResponse(
                project_id=1,
                environment_id=2,
                source_summary="first",
                scenario=scenario,
                warnings=[],
            ),
            AIGeneratedScenarioResponse(
                project_id=1,
                environment_id=2,
                source_summary="repaired",
                scenario=scenario,
                warnings=[],
            ),
        ]
        captured_contexts = []

        class FakeRunner:
            def __init__(self, ai_service):
                pass

            def run(self, skill, context):
                captured_contexts.append(context)
                return generated.pop(0)

        class FakeScenarioService:
            calls = 0

            def __init__(self, db):
                pass

            def validate_unsaved_scenario(self, **kwargs):
                FakeScenarioService.calls += 1
                status_value = "failed" if FakeScenarioService.calls == 1 else "passed"
                return SimpleNamespace(
                    id=FakeScenarioService.calls,
                    status=status_value,
                    duration_ms=10,
                    step_results=[{
                        "step_id": "CASE-1",
                        "step_index": 1,
                        "kind": "api_case",
                        "name": "查询",
                        "status": status_value,
                        "message": "Assertion failed" if status_value == "failed" else "Execution passed",
                        "error_message": "Assertion failed" if status_value == "failed" else None,
                        "assertion_results": (
                            [{"assertion": {"type": "json_equals", "path": "code", "expected": 0}, "actual": 1, "passed": False}]
                            if status_value == "failed"
                            else []
                        ),
                        "extracted_variables": [],
                        "request_snapshot": {"method": "GET", "url": "https://api.test/items"},
                        "response_snapshot": {"status_code": 200, "json": {"code": 1}},
                    }],
                )

        service = object.__new__(AIScenarioComposerService)
        service.db = SimpleNamespace(
            scalar=lambda statement: SimpleNamespace(
                id=2,
                name="dev",
                base_url="https://api.test",
                description=None,
            )
        )
        service.permission_service = SimpleNamespace(require_project_permission=lambda *args: None)
        service.ai_service = FakeAIService({})
        service._candidate_cases = lambda **kwargs: [{
            "kind": "api_case",
            "reference_id": 10,
            "name": "查询",
            "method": "GET",
            "path": "/items",
        }]

        module = __import__("app.services.ai_scenario_composer_service", fromlist=["AISkillRunner", "ScenarioService"])
        original_runner = module.AISkillRunner
        original_scenario_service = module.ScenarioService
        module.AISkillRunner = FakeRunner
        module.ScenarioService = FakeScenarioService
        try:
            result = service.compose(
                project_id=1,
                environment_id=2,
                payload=AIScenarioComposeRequest(
                    requirement="查询列表",
                    http_test_case_ids=[10],
                    self_validate=True,
                    max_validation_attempts=3,
                ),
                current_user=SimpleNamespace(id=1),
            )
        finally:
            module.AISkillRunner = original_runner
            module.ScenarioService = original_scenario_service

        self.assertTrue(result.self_validated)
        self.assertEqual(len(result.validation_attempts), 2)
        self.assertEqual(result.validation_attempts[0].status, "failed")
        self.assertEqual(result.validation_attempts[1].status, "passed")
        self.assertEqual(result.environment_name, "dev")
        self.assertIn("validation_feedback", captured_contexts[1])
        self.assertEqual(FakeScenarioService.calls, 2)

    def test_generic_skill_run_delegates_to_scenario_composer(self):
        db = SimpleNamespace()
        user = SimpleNamespace(id=1)
        generated = SimpleNamespace(project_id=1, marker="scenario")
        captured = {}

        class FakeScenarioComposerService:
            def __init__(self, service_db):
                captured["db"] = service_db

            def compose(self, **kwargs):
                captured.update(kwargs)
                return generated

        module = __import__("app.services.ai_skill_service", fromlist=["AIScenarioComposerService"])
        original = module.AIScenarioComposerService
        module.AIScenarioComposerService = FakeScenarioComposerService
        try:
            result = AISkillService(db).run_skill(
                skill_id="scenario-composer",
                payload=AISkillRunRequest(
                    operation="compose",
                    project_id=1,
                    environment_id=2,
                    input={"requirement": "组合登录链路", "http_test_case_ids": [10]},
                ),
                current_user=user,
            )
        finally:
            module.AIScenarioComposerService = original

        self.assertIs(result, generated)
        self.assertIs(captured["db"], db)
        self.assertEqual(captured["project_id"], 1)
        self.assertEqual(captured["environment_id"], 2)
        self.assertIs(captured["current_user"], user)
        self.assertIsInstance(captured["payload"], AIScenarioComposeRequest)

    def test_websocket_case_generation_uses_formal_skill_package(self):
        service = object.__new__(AIWebSocketTestCaseService)
        service.permission_service = SimpleNamespace(require_project_permission=lambda *args: None)
        service.project_repository = SimpleNamespace(
            get_environment=lambda **kwargs: SimpleNamespace(
                id=2,
                name="dev",
                base_url="https://api.example.test",
                description=None,
            ),
            list_environment_variables=lambda **kwargs: [],
        )
        service.ai_service = FakeAIService({
            "source_summary": "socket api",
            "cases": [{
                "name": "join room",
                "path": "wss://api.example.test/ws/room?client=web",
                "messages": [{"type": "json", "data": {"event": "join"}}],
                "receive_count": 0,
                "assertions": [{"type": "message_count", "expected": 2}],
                "extractors": [],
            }],
            "warnings": [],
        })

        result = service.generate_test_cases(
            project_id=1,
            environment_id=2,
            payload=AIWebSocketTestCaseGenerateRequest(websocket_text="join room"),
            current_user=SimpleNamespace(id=1),
        )

        self.assertEqual(result.cases[0].path, "/ws/room?client=web")
        self.assertEqual(result.cases[0].receive_count, 2)
        self.assertIn("WebSocket 测试用例生成助手", service.ai_service.requests[0].messages[0].content)

    def test_ai_run_event_store_masks_sensitive_payloads(self):
        store = AIRunEventStore()
        run = store.create_run(
            skill_id="http-test-case",
            payload=AISkillRunRequest(
                operation="generate",
                project_id=1,
                environment_id=2,
                input={"interface_text": "GET /health"},
            ),
            user_id=7,
        )

        store.append(run.run_id, "tool.started", {
            "headers": {"Authorization": "Bearer secret-token"},
            "nested": {"password": "secret"},
        })
        events = store.get_run(run.run_id).events

        self.assertEqual(events[-1].payload["headers"]["Authorization"], "***")
        self.assertEqual(events[-1].payload["nested"]["password"], "***")

    def test_ai_run_access_is_limited_to_owner_or_admin(self):
        service = AISkillRunService()
        queued = service.create_run(
            skill_id="http-test-case",
            payload=AISkillRunRequest(
                operation="generate",
                project_id=1,
                environment_id=2,
                input={"interface_text": "GET /health"},
            ),
            current_user=SimpleNamespace(id=7, is_admin=False),
        )

        self.assertEqual(service.get_run(queued.run_id, SimpleNamespace(id=7, is_admin=False)).run_id, queued.run_id)
        self.assertEqual(service.get_run(queued.run_id, SimpleNamespace(id=8, is_admin=True)).run_id, queued.run_id)
        with self.assertRaises(HTTPException) as context:
            service.get_run(queued.run_id, SimpleNamespace(id=8, is_admin=False))
        self.assertEqual(context.exception.status_code, 403)

    def test_traced_runner_emits_model_and_validation_events(self):
        store = AIRunEventStore()
        run = store.create_run(
            skill_id="http-test-case",
            payload=AISkillRunRequest(
                operation="generate",
                project_id=1,
                environment_id=2,
                input={"interface_text": "GET /health"},
            ),
            user_id=7,
        )
        skill = get_ai_skill("http-test-case")
        runner = AISkillRunner(FakeAIService({
            "source_summary": "health",
            "cases": [{
                "name": "健康检查",
                "method": "GET",
                "path": "/health",
                "body_type": "none",
                "body": None,
            }],
            "warnings": [],
        }))

        result = runner.run_traced(
            skill,
            {
                "mode": "generate",
                "project_id": 1,
                "environment_id": 2,
                "environment": SimpleNamespace(id=2, name="dev", base_url="https://api.example.test", description=None),
                "variables": [],
                "payload": AITestCaseGenerateRequest(interface_text="GET /health"),
                "include_assertions": True,
            },
            AIRunTrace(store, run.run_id),
        )
        events = [item.event for item in store.get_run(run.run_id).events]

        self.assertEqual(result.cases[0].path, "/health")
        self.assertIn("model.started", events)
        self.assertIn("model.delta", events)
        self.assertIn("model.completed", events)
        self.assertIn("step.completed", events)

    def test_ai_run_routes_are_declared(self):
        from app.main import create_app

        paths = create_app().openapi()["paths"]

        self.assertIn("/api/v1/ai/skills/{skill_id}/runs", paths)
        self.assertIn("/api/v1/ai/skill-runs/{run_id}", paths)
        self.assertIn("/api/v1/ai/skill-runs/{run_id}/events", paths)


if __name__ == "__main__":
    unittest.main()
