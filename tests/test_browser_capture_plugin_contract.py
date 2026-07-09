import json
import unittest
from datetime import datetime
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.core.permissions import NORMAL_TESTER_GRANTABLE_PERMISSIONS, ProjectPermission
from app.db.base import Base
from app.models.project import Project, ProjectEnvironment
from app.models.test_case import TestCase
from app.models.user import User
from app.schemas.ai import AIChatResponse, AIBrowserCaptureAnalyzeRequest, AIBrowserCaptureBatchAnalyzeRequest
from app.schemas.browser_capture import (
    BrowserCaptureCreateRequest,
    BrowserCaptureEntryBatchRequest,
    BrowserCaptureImportRequest,
)
from app.services.ai_browser_capture_service import AIBrowserCaptureService
from app.services.browser_capture_service import BrowserCaptureService


class BrowserCapturePluginContractTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()

        self.owner = User(
            username="当前用户",
            account="owner",
            password_hash="hash",
            phone="10000000000",
            email="owner@example.com",
        )
        self.db.add(self.owner)
        self.db.flush()

        self.project = Project(name="插件采集项目", created_by_id=self.owner.id)
        self.db.add(self.project)
        self.db.flush()

        self.environment = ProjectEnvironment(
            project_id=self.project.id,
            name="test",
            base_url="https://api.example.test",
            is_default=True,
            created_by_id=self.owner.id,
        )
        self.db.add(self.environment)
        self.db.commit()

        self.capture_service = BrowserCaptureService(self.db)

    def tearDown(self):
        self.db.close()

    def _create_capture(self):
        return self.capture_service.create_capture(
            project_id=self.project.id,
            payload=BrowserCaptureCreateRequest(
                environment_id=self.environment.id,
                name="订单创建流程采集",
                source_url="https://test.example.com/orders",
            ),
            current_user=self.owner,
        )

    def _plugin_http_entry(self, *, client_entry_id="entry-1", url="https://test.example.com/api/orders?page=1"):
        return {
            "client_entry_id": client_entry_id,
            "protocol": "http",
            "method": "POST",
            "url": url,
            "request_headers": {
                "Authorization": "Bearer secret-token",
                "Content-Type": "application/json",
            },
            "request_body_type": "json",
            "request_body": {"product_id": 1001},
            "response_status": 200,
            "response_headers": {"content-type": "application/json"},
            "response_body": {"code": 0, "data": {"order_id": "ORD-001"}},
            "duration_ms": 128,
            "fingerprint": f"sha256-{client_entry_id}",
            "captured_at": "2026-06-11T10:00:00+08:00",
        }

    def _captured_entry(
        self,
        *,
        client_entry_id: str,
        method: str,
        url: str,
        request_body=None,
        response_body=None,
        captured_at: str = "2026-06-11T10:00:00+08:00",
    ):
        return {
            "client_entry_id": client_entry_id,
            "protocol": "http",
            "method": method,
            "url": url,
            "request_headers": {"Authorization": "Bearer secret-token"},
            "request_body_type": "json",
            "request_body": request_body,
            "response_status": 200,
            "response_headers": {"content-type": "application/json"},
            "response_body": response_body or {"code": 0},
            "duration_ms": 128,
            "fingerprint": f"sha256-{client_entry_id}",
            "captured_at": captured_at,
        }

    def test_plugin_native_batch_payload_is_normalized_and_filterable(self):
        capture = self._create_capture()

        entries = self.capture_service.upsert_entries(
            project_id=self.project.id,
            capture_id=capture.id,
            payload=BrowserCaptureEntryBatchRequest(entries=[self._plugin_http_entry()]),
            current_user=self.owner,
        )

        entry = entries[0]
        self.assertEqual(entry.name, "POST /api/orders")
        self.assertEqual(entry.path, "/api/orders")
        self.assertEqual(entry.source_url, "https://test.example.com/api/orders?page=1")
        self.assertEqual(entry.request_data["headers"]["Authorization"], "Bearer secret-token")
        self.assertEqual(entry.request_data["query_params"], {"page": "1"})
        self.assertEqual(entry.response_data["status_code"], 200)
        self.assertEqual(entry.draft_data["duration_ms"], 128)

        filtered = self.capture_service.list_entries(
            project_id=self.project.id,
            capture_id=capture.id,
            current_user=self.owner,
            status_filter="captured",
            protocol="http",
            method="POST",
            domain="test.example.com",
            keyword="orders",
        )
        self.assertEqual([item.id for item in filtered], [entry.id])

    def test_import_entries_creates_http_case_and_marks_duplicate_on_reimport(self):
        capture = self._create_capture()
        entry = self.capture_service.upsert_entries(
            project_id=self.project.id,
            capture_id=capture.id,
            payload=BrowserCaptureEntryBatchRequest(entries=[self._plugin_http_entry()]),
            current_user=self.owner,
        )[0]

        result = self.capture_service.import_entries(
            project_id=self.project.id,
            capture_id=capture.id,
            payload=BrowserCaptureImportRequest(
                entry_ids=[entry.id],
                environment_id=self.environment.id,
                create_environment_variables=True,
                create_scenario=False,
            ),
            current_user=self.owner,
        )

        self.assertEqual(result["success_count"], 1)
        imported = result["results"][0]
        self.assertTrue(imported["ok"])
        self.assertEqual(imported["status"], "success")
        self.assertEqual(imported["asset_type"], "http")

        case = self.db.scalar(select(TestCase).where(TestCase.id == imported["asset_id"]))
        self.assertIsNotNone(case)
        self.assertEqual(case.method, "POST")
        self.assertEqual(case.path, "/api/orders")
        self.assertEqual(case.headers["Content-Type"], "application/json")
        self.assertEqual(case.query_params, {"page": "1"})

        duplicate = self.capture_service.import_entries(
            project_id=self.project.id,
            capture_id=capture.id,
            payload=BrowserCaptureImportRequest(entry_ids=[entry.id], environment_id=self.environment.id),
            current_user=self.owner,
        )
        self.assertEqual(duplicate["duplicate_count"], 1)
        self.assertEqual(duplicate["results"][0]["status"], "duplicate")

    def test_local_analyze_masks_sensitive_values_and_returns_structured_defaults(self):
        captured_prompts = []

        def fake_chat(payload):
            captured_prompts.append(json.dumps(payload.model_dump(), ensure_ascii=False))
            return AIChatResponse(
                provider="deepseek",
                model="deepseek-test",
                content=json.dumps({
                    "summary": {
                        "name": "查询订单列表",
                        "purpose": "按查询条件分页返回订单",
                        "business_domain": "订单",
                        "operation_type": "query",
                        "confidence": 2,
                    },
                    "request": {"description": "分页参数"},
                    "response": {"description": "订单分页结果"},
                    "test_points": [
                        {"priority": "low", "title": "低优先级", "category": "normal"},
                        {"priority": "high", "title": "高优先级", "category": "boundary"},
                    ],
                    "risks": [
                        {"level": "medium", "title": "越权查询"},
                        {"level": "high", "title": "数据泄露"},
                    ],
                    "automation": {},
                }, ensure_ascii=False),
            )

        with patch("app.services.ai_browser_capture_service.AIService.chat", side_effect=fake_chat):
            result = AIBrowserCaptureService(self.db).analyze_draft(
                project_id=self.project.id,
                environment_id=self.environment.id,
                payload=AIBrowserCaptureAnalyzeRequest(
                    protocol="http",
                    draft_data={
                        "method": "GET",
                        "url": "https://test.example.com/api/orders",
                        "headers": {"Authorization": "Bearer secret-token"},
                        "response_body": {"access_token": "abc123"},
                    },
                    analysis_focus=["semantics", "automation"],
                    include_examples=True,
                ),
                current_user=self.owner,
            )

        prompt = "\n".join(captured_prompts)
        self.assertNotIn("secret-token", prompt)
        self.assertNotIn("abc123", prompt)
        self.assertIn("***", prompt)
        self.assertEqual(result["summary"]["confidence"], 1)
        request_paths = {field["path"]: field for field in result["request"]["fields"]}
        self.assertEqual(request_paths["headers.Authorization"]["example"], "***")
        response_paths = {field["path"]: field for field in result["response"]["fields"]}
        self.assertEqual(response_paths["body.access_token"]["example"], "***")
        self.assertIn("断言响应结构包含关键字段", result["automation"]["assertions"])
        self.assertEqual([item["priority"] for item in result["test_points"]], ["high", "low"])
        self.assertEqual([item["level"] for item in result["risks"]], ["high", "medium"])
        self.assertEqual(result["model"], "deepseek-test")
        self.assertIn("analyzed_at", result)

    def test_local_analyze_large_response_keeps_prompt_context_sections(self):
        captured_payloads = []

        def fake_chat(payload):
            captured_payloads.append(payload.model_dump())
            return AIChatResponse(
                provider="deepseek",
                model="deepseek-test",
                content=json.dumps({
                    "summary": {
                        "purpose": "分页查询订单列表",
                        "confidence": 0.8,
                    },
                    "request": {"fields": []},
                    "response": {"fields": []},
                    "test_points": [],
                    "risks": [],
                    "automation": {},
                    "warnings": [],
                }, ensure_ascii=False),
            )

        large_response = {f"field_{index}": index for index in range(500)}
        with patch("app.services.ai_browser_capture_service.AIService.chat", side_effect=fake_chat):
            result = AIBrowserCaptureService(self.db).analyze_draft(
                project_id=self.project.id,
                environment_id=self.environment.id,
                payload=AIBrowserCaptureAnalyzeRequest(
                    protocol="http",
                    draft_data={
                        "method": "GET",
                        "url": "https://test.example.com/api/orders?page=1",
                        "response_status": 200,
                        "response_body": {"code": 0, "data": large_response},
                    },
                ),
                current_user=self.owner,
            )

        user_payload = json.loads(captured_payloads[0]["messages"][1]["content"])
        self.assertEqual(user_payload["request_context"]["path"], "/api/orders")
        self.assertIn("response_schema", user_payload)
        self.assertIn("automation_hints", user_payload)
        self.assertEqual(result["summary"]["purpose"], "分页查询订单列表")

    def test_local_analyze_prompt_declares_strict_output_contract(self):
        captured_payloads = []

        def fake_chat(payload):
            captured_payloads.append(payload.model_dump())
            return AIChatResponse(
                provider="deepseek",
                model="deepseek-test",
                content=json.dumps({
                    "summary": {"purpose": "Query orders by page."},
                    "request": {"fields": []},
                    "response": {"fields": []},
                    "test_points": [],
                    "risks": [],
                    "automation": {},
                    "warnings": [],
                }, ensure_ascii=False),
            )

        with patch("app.services.ai_browser_capture_service.AIService.chat", side_effect=fake_chat):
            AIBrowserCaptureService(self.db).analyze_draft(
                project_id=self.project.id,
                environment_id=self.environment.id,
                payload=AIBrowserCaptureAnalyzeRequest(
                    protocol="http",
                    draft_data={"method": "GET", "url": "https://test.example.com/api/orders?page=1"},
                ),
                current_user=self.owner,
            )

        system_prompt = captured_payloads[0]["messages"][0]["content"]
        user_payload = json.loads(captured_payloads[0]["messages"][1]["content"])
        self.assertIn("严格返回一个 JSON object", system_prompt)
        self.assertIn("summary 必须是 object", system_prompt)
        self.assertIn("summary.purpose", system_prompt)
        self.assertIn("不要把完整 JSON", system_prompt)
        self.assertIn("expected_output_contract", user_payload)
        self.assertIn("output_limits", user_payload)
        self.assertLessEqual(user_payload["output_limits"]["max_test_points"], 6)
        self.assertLessEqual(user_payload["output_limits"]["max_risks"], 6)
        self.assertLessEqual(user_payload["output_limits"]["max_summary_purpose_chars"], 120)
        contract = user_payload["expected_output_contract"]
        self.assertEqual(
            set(contract.keys()),
            {"summary", "request", "response", "test_points", "risks", "automation", "warnings"},
        )
        self.assertIsInstance(contract["summary"], dict)
        self.assertIsInstance(contract["request"]["fields"], list)
        self.assertIsInstance(contract["response"]["fields"], list)
        self.assertIsInstance(contract["test_points"], list)
        self.assertIsInstance(contract["risks"], list)
        self.assertIsInstance(contract["automation"], dict)

    def test_local_analyze_tolerates_model_summary_string_instead_of_500(self):
        def fake_chat(payload):
            return AIChatResponse(
                provider="deepseek",
                model="deepseek-test",
                content=json.dumps({
                    "summary": "GET request to retrieve CT profile count for the given company ID.",
                    "request": "companyId query parameter",
                    "response": "business response with code and data",
                    "test_points": "missing companyId should be rejected",
                    "risks": "authorization may expire",
                    "automation": None,
                }, ensure_ascii=False),
            )

        with patch("app.services.ai_browser_capture_service.AIService.chat", side_effect=fake_chat):
            result = AIBrowserCaptureService(self.db).analyze_draft(
                project_id=self.project.id,
                environment_id=self.environment.id,
                payload=AIBrowserCaptureAnalyzeRequest(
                    protocol="http",
                    draft_data={"method": "GET", "url": "https://test.example.com/api/company"},
                ),
                current_user=self.owner,
            )

        self.assertEqual(
            result["summary"]["purpose"],
            "GET request to retrieve CT profile count for the given company ID.",
        )
        self.assertEqual(result["request"]["description"], "companyId query parameter")
        self.assertEqual(result["response"]["description"], "business response with code and data")
        self.assertEqual(result["test_points"][0]["title"], "missing companyId should be rejected")
        self.assertEqual(result["risks"][0]["title"], "authorization may expire")
        self.assertEqual(result["automation"]["assertions"], [])
        self.assertIn("AI 返回字段 summary 类型已归一化", result["warnings"])

    def test_local_analyze_caps_overly_long_test_points_and_risks(self):
        def fake_chat(payload):
            return AIChatResponse(
                provider="deepseek",
                model="deepseek-test",
                content=json.dumps({
                    "summary": {"purpose": "Query software copyright records."},
                    "request": {"fields": []},
                    "response": {"fields": []},
                    "test_points": [
                        {"title": f"point-{index}", "priority": "medium"}
                        for index in range(10)
                    ],
                    "risks": [
                        {"title": f"risk-{index}", "level": "medium"}
                        for index in range(10)
                    ],
                    "automation": {},
                    "warnings": [],
                }, ensure_ascii=False),
            )

        with patch("app.services.ai_browser_capture_service.AIService.chat", side_effect=fake_chat):
            result = AIBrowserCaptureService(self.db).analyze_draft(
                project_id=self.project.id,
                environment_id=self.environment.id,
                payload=AIBrowserCaptureAnalyzeRequest(
                    protocol="http",
                    draft_data={"method": "GET", "url": "https://test.example.com/api/software"},
                ),
                current_user=self.owner,
            )

        self.assertEqual(len(result["test_points"]), 6)
        self.assertEqual(len(result["risks"]), 6)

    def test_local_analyze_does_not_place_malformed_json_payload_in_purpose(self):
        def fake_chat(payload):
            return AIChatResponse(
                provider="deepseek",
                model="deepseek-test",
                content=(
                    '{"summary": {"purpose": "{\\n'
                    '  \\"summary\\": \\"This endpoint lists software copyright records.\\",\\n'
                    '  \\"request\\": {\\"method\\": \\"GET\\", \\"url\\": \\"/api/software\\"},\\n'
                    '  \\"response\\": {\\"body\\": {\\"code\\": 200}},\\n'
                ),
            )

        with patch("app.services.ai_browser_capture_service.AIService.chat", side_effect=fake_chat):
            result = AIBrowserCaptureService(self.db).analyze_draft(
                project_id=self.project.id,
                environment_id=self.environment.id,
                payload=AIBrowserCaptureAnalyzeRequest(
                    protocol="http",
                    draft_data={
                        "method": "GET",
                        "url": "https://test.example.com/api/software?companyId=200121",
                        "response_status": 200,
                        "response_body": {"code": 200, "data": {"records": []}},
                    },
                ),
                current_user=self.owner,
            )

        purpose = result["summary"]["purpose"]
        self.assertEqual(purpose, "GET /api/software 接口。")
        self.assertNotIn('"request"', purpose)
        self.assertNotIn('"response"', purpose)
        self.assertNotIn("{", purpose)
        self.assertIn("AI 返回内容不是合法 JSON，已降级保存摘要。", result["warnings"])

    def test_local_analyze_fallback_extracts_alias_query_and_response_body_text(self):
        def fake_chat(payload):
            return AIChatResponse(
                provider="deepseek",
                model="deepseek-test",
                content='{"summary": {"purpose": "truncated"',
            )

        with patch("app.services.ai_browser_capture_service.AIService.chat", side_effect=fake_chat):
            result = AIBrowserCaptureService(self.db).analyze_draft(
                project_id=self.project.id,
                environment_id=self.environment.id,
                payload=AIBrowserCaptureAnalyzeRequest(
                    protocol="http",
                    draft_data={
                        "request": {
                            "method": "GET",
                            "url": "https://www.lingxidata.cn/api/lingxi-bigdata/multiscan/intelprop/getSoftwareCopyrightPage",
                            "query": {
                                "regYear": "",
                                "current": "1",
                                "size": "10",
                                "companyId": "20012112190009470941",
                            },
                            "headers": {
                                "Accept": "application/json, text/plain, */*",
                                "Authorization": "Bearer secret-token",
                                "lingxi-auth": "secret-lingxi-token",
                            },
                        },
                        "response": {
                            "status": 200,
                            "headers": {"content-type": "application/json;charset=UTF-8"},
                            "bodyText": json.dumps({
                                "code": 200,
                                "success": True,
                                "data": {
                                    "records": [],
                                    "total": 0,
                                    "size": 10,
                                    "current": 1,
                                },
                                "msg": "操作成功",
                            }, ensure_ascii=False),
                        },
                    },
                ),
                current_user=self.owner,
            )

        request_paths = {field["path"]: field for field in result["request"]["fields"]}
        response_paths = {field["path"]: field for field in result["response"]["fields"]}
        self.assertIn("query.companyId", request_paths)
        self.assertEqual(request_paths["query.companyId"]["meaning"], "企业标识")
        self.assertIn("query.current", request_paths)
        self.assertEqual(request_paths["headers.Authorization"]["example"], "***")
        self.assertIn("status_code", response_paths)
        self.assertIn("body.code", response_paths)
        self.assertIn("body.data.records", response_paths)
        self.assertIn("body.data.total", response_paths)
        self.assertIn("断言响应结构包含关键字段", result["automation"]["assertions"])
        self.assertIn("准备有效 companyId 测试数据", result["automation"]["data_setup"])

    def test_local_analyze_fallback_understands_plugin_camelcase_search_capture(self):
        captured_payloads = []

        def fake_chat(payload):
            captured_payloads.append(payload.model_dump())
            return AIChatResponse(
                provider="deepseek",
                model="deepseek-test",
                content='{"summary": {"purpose": "truncated"',
            )

        with patch("app.services.ai_browser_capture_service.AIService.chat", side_effect=fake_chat):
            result = AIBrowserCaptureService(self.db).analyze_draft(
                project_id=self.project.id,
                environment_id=self.environment.id,
                payload=AIBrowserCaptureAnalyzeRequest(
                    protocol="http",
                    draft_data={
                        "protocol": "http",
                        "name": "GET /s",
                        "sourceUrl": (
                            "https://www.baidu.com/s?ie=utf-8&mod=1&isbd=1&"
                            "tn=baidu&wd=%E5%A4%AE%E8%A7%86%E8%8A%82%E7%9B%AE%20"
                            "%E4%B8%80%E5%B9%B4%E5%8F%88%E4%B8%80%E5%B9%B42005%E5%B9%B4"
                        ),
                        "method": "GET",
                        "path": "https://www.baidu.com/s",
                        "headers": {
                            "Accept": "*/*",
                            "X-Requested-With": "XMLHttpRequest",
                            "is_xhr": "1",
                        },
                        "queryParams": {
                            "ie": "utf-8",
                            "tn": "baidu",
                            "wd": "央视节目 一年又一年2005年",
                        },
                        "bodyType": "none",
                        "body": None,
                        "responseStatus": 200,
                        "responseHeaders": {
                            "Content-Type": "text/html;charset=utf-8",
                            "Traceid": "1783585206041124890611815602683681828278",
                        },
                    },
                ),
                current_user=self.owner,
            )

        user_payload = json.loads(captured_payloads[0]["messages"][1]["content"])
        self.assertEqual(user_payload["request_context"]["path"], "/s")
        self.assertEqual(user_payload["request_context"]["query_params"]["wd"], "央视节目 一年又一年2005年")

        self.assertIn("百度搜索", result["summary"]["purpose"])
        self.assertIn("央视节目 一年又一年2005年", result["summary"]["purpose"])
        self.assertEqual(result["summary"]["business_domain"], "www.baidu.com")

        request_paths = {field["path"]: field for field in result["request"]["fields"]}
        self.assertEqual(request_paths["query.wd"]["meaning"], "搜索关键词")
        self.assertIn("query.ie", request_paths)
        self.assertEqual(request_paths["headers.X-Requested-With"]["meaning"], "XHR 请求标识")

        response_paths = {field["path"]: field for field in result["response"]["fields"]}
        self.assertIn("status_code", response_paths)
        self.assertEqual(response_paths["headers.Content-Type"]["meaning"], "响应内容类型")
        self.assertIn("body", response_paths)
        self.assertEqual(response_paths["body"]["meaning"], "HTML 文档内容")

        self.assertTrue(result["test_points"])
        self.assertTrue(any("wd" in item for item in result["automation"]["data_setup"]))
        self.assertIn("断言响应 Content-Type 包含 text/html", result["automation"]["assertions"])

    def test_local_analyze_enriches_sparse_ai_result_from_request_and_response_details(self):
        captured_prompts = []

        def fake_chat(payload):
            captured_prompts.append(json.dumps(payload.model_dump(), ensure_ascii=False))
            return AIChatResponse(
                provider="deepseek",
                model="deepseek-test",
                content=json.dumps({
                    "summary": {
                        "purpose": "GET request to retrieve paginated mortgage risk data for a specific company.",
                    },
                    "request": {"description": "", "fields": []},
                    "response": {"description": "", "fields": []},
                    "test_points": [
                        {
                            "category": "functional",
                            "title": "",
                            "description": "Verify successful response with valid companyId",
                            "priority": "high",
                        }
                    ],
                    "risks": [{"level": "medium", "title": "", "description": "Authorization bypass risk"}],
                    "automation": {
                        "assertions": [],
                        "extractors": [],
                        "dependencies": [],
                        "data_setup": [],
                        "cleanup": [],
                    },
                    "warnings": [],
                }, ensure_ascii=False),
            )

        with patch("app.services.ai_browser_capture_service.AIService.chat", side_effect=fake_chat):
            result = AIBrowserCaptureService(self.db).analyze_draft(
                project_id=self.project.id,
                environment_id=self.environment.id,
                payload=AIBrowserCaptureAnalyzeRequest(
                    protocol="http",
                    draft_data={
                        "method": "GET",
                        "url": (
                            "https://www.lingxidata.cn/api/lingxi-bigdata/multiscan/"
                            "risk/getChattelMortgagePage?companyId=200121&page=1&size=10"
                        ),
                        "request_headers": {
                            "Authorization": "Bearer secret-token",
                            "lingxi-auth": "lingxi-secret",
                        },
                        "response_status": 200,
                        "response_headers": {"content-type": "application/json"},
                        "response_body": {
                            "code": 200,
                            "success": True,
                            "data": {"records": [], "total": 0, "page": 1, "size": 10},
                        },
                    },
                ),
                current_user=self.owner,
            )

        prompt = "\n".join(captured_prompts)
        self.assertIn("request_context", prompt)
        self.assertIn("response_schema", prompt)
        self.assertNotIn("secret-token", prompt)
        self.assertNotIn("lingxi-secret", prompt)

        self.assertTrue(result["summary"]["name"])
        self.assertEqual(result["summary"]["operation_type"], "query")
        request_paths = {field["path"] for field in result["request"]["fields"]}
        self.assertIn("query.companyId", request_paths)
        self.assertIn("query.page", request_paths)
        self.assertIn("headers.Authorization", request_paths)
        self.assertIn("headers.lingxi-auth", request_paths)

        response_paths = {field["path"] for field in result["response"]["fields"]}
        self.assertIn("status_code", response_paths)
        self.assertIn("body.code", response_paths)
        self.assertIn("body.data.records", response_paths)
        self.assertIn("body.data.total", response_paths)

        self.assertTrue(result["automation"]["assertions"])
        self.assertTrue(any("Authorization" in item for item in result["automation"]["dependencies"]))
        self.assertTrue(any("companyId" in item for item in result["automation"]["data_setup"]))
        self.assertEqual(result["test_points"][0]["title"], "Verify successful response with valid companyId")
        self.assertEqual(result["risks"][0]["title"], "Authorization bypass risk")

    def test_batch_analyze_context_dependencies_detects_selected_entry_bindings(self):
        capture = self._create_capture()
        entries = self.capture_service.upsert_entries(
            project_id=self.project.id,
            capture_id=capture.id,
            payload=BrowserCaptureEntryBatchRequest(entries=[
                self._captured_entry(
                    client_entry_id="create-order",
                    method="POST",
                    url="https://test.example.com/api/orders",
                    request_body={"product_id": 1001},
                    response_body={"code": 0, "data": {"order_id": "ORD-001", "user_id": 88}},
                    captured_at="2026-06-11T10:00:00+08:00",
                ),
                self._captured_entry(
                    client_entry_id="order-detail",
                    method="GET",
                    url="https://test.example.com/api/orders/detail?order_id=ORD-001",
                    response_body={"code": 0, "data": {"order_id": "ORD-001", "status": "created"}},
                    captured_at="2026-06-11T10:00:01+08:00",
                ),
                self._captured_entry(
                    client_entry_id="pay-order",
                    method="POST",
                    url="https://test.example.com/api/payments",
                    request_body={"order_id": "ORD-001", "amount": 20},
                    response_body={"code": 0, "data": {"payment_id": "PAY-001"}},
                    captured_at="2026-06-11T10:00:02+08:00",
                ),
            ]),
            current_user=self.owner,
        )

        result = AIBrowserCaptureService(self.db).analyze_batch_context(
            project_id=self.project.id,
            capture_id=capture.id,
            payload=AIBrowserCaptureBatchAnalyzeRequest(entry_ids=[entry.id for entry in entries]),
            current_user=self.owner,
        )

        self.assertEqual(result["capture_id"], capture.id)
        self.assertEqual(result["entry_ids"], [entry.id for entry in entries])
        self.assertEqual([node["entry_id"] for node in result["nodes"]], [entry.id for entry in entries])

        order_dependencies = [
            item for item in result["dependencies"]
            if item["variable"] == "order_id"
        ]
        self.assertGreaterEqual(len(order_dependencies), 2)
        self.assertTrue(any(item["consumer_entry_id"] == entries[1].id for item in order_dependencies))
        self.assertTrue(any(item["consumer_entry_id"] == entries[2].id for item in order_dependencies))
        self.assertTrue(any(item["request_target"] == "query" for item in order_dependencies))
        self.assertTrue(any(item["request_target"] == "body" for item in order_dependencies))
        self.assertTrue(all(item["replacement"] == "{{order_id}}" for item in order_dependencies))

        producer = next(node for node in result["nodes"] if node["entry_id"] == entries[0].id)
        self.assertIn("body.data.order_id", {item["path"] for item in producer["produces"]})
        detail = next(node for node in result["nodes"] if node["entry_id"] == entries[1].id)
        self.assertIn("query_params.order_id", {item["path"] for item in detail["consumes"]})
        self.assertTrue(result["suggested_bindings"])
        self.assertEqual(result["summary"]["dependency_count"], len(result["dependencies"]))

    def test_capture_and_ai_permissions_are_exposed_to_project_permission_catalog(self):
        expected = {
            ProjectPermission.VIEW_CAPTURE.value,
            ProjectPermission.MANAGE_CAPTURE.value,
            ProjectPermission.IMPORT_CAPTURE.value,
            ProjectPermission.ANALYZE_AI.value,
        }

        self.assertTrue(expected.issubset({permission.value for permission in ProjectPermission}))
        self.assertTrue(expected.issubset(NORMAL_TESTER_GRANTABLE_PERMISSIONS))


if __name__ == "__main__":
    unittest.main()
