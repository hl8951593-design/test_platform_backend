import argparse
import json
import sys
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, urlparse

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.services.test_case_service import TestCaseService


class BusinessState:
    def __init__(self) -> None:
        self.sessions = {"biz-token-admin": {"id": 1001, "name": "admin"}}
        self.products = {
            "SKU-BOOK-1": {"id": "SKU-BOOK-1", "name": "接口测试实战", "category": "book", "price": 80, "stock": 5},
            "SKU-COURSE-1": {"id": "SKU-COURSE-1", "name": "自动化测试课程", "category": "course", "price": 300, "stock": 2},
        }
        self.carts: dict[str, dict[str, Any]] = {}
        self.orders: dict[str, dict[str, Any]] = {}
        self.next_cart_id = 1
        self.next_order_id = 1
        self.uploads: dict[str, dict[str, Any]] = {}

    def reset(self) -> None:
        self.__init__()


BUSINESS_STATE = BusinessState()


class MockTargetHandler(BaseHTTPRequestHandler):
    server_version = "DevTestMock/1.0"

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        return

    def do_GET(self) -> None:
        self._handle_request()

    def do_POST(self) -> None:
        self._handle_request()

    def do_PUT(self) -> None:
        self._handle_request()

    def do_PATCH(self) -> None:
        self._handle_request()

    def do_DELETE(self) -> None:
        self._handle_request()

    def do_OPTIONS(self) -> None:
        self._handle_request()

    def do_HEAD(self) -> None:
        self.send_response(204)
        self.send_header("X-Mock-Method", "HEAD")
        self.end_headers()

    def _handle_request(self) -> None:
        parsed_url = urlparse(self.path)
        if parsed_url.path.startswith("/status/"):
            status_code = int(parsed_url.path.rsplit("/", 1)[-1])
            self._send_json(status_code, {"method": self.command, "status": status_code})
            return
        if parsed_url.path == "/login":
            self._send_json(200, {"token": "ctx-token-123", "user": {"id": 7, "name": "admin"}})
            return

        raw_body = self.rfile.read(int(self.headers.get("Content-Length", "0") or 0))
        body_text = raw_body.decode("utf-8", errors="replace")
        content_type = self.headers.get("Content-Type", "")
        parsed_json = None
        parsed_form = None
        if body_text and "application/json" in content_type:
            try:
                parsed_json = json.loads(body_text)
            except json.JSONDecodeError:
                parsed_json = None
        if body_text and "application/x-www-form-urlencoded" in content_type:
            parsed_form = parse_qs(body_text, keep_blank_values=True)

        if parsed_url.path.startswith("/biz/"):
            self._handle_business_request(parsed_url, body_text, parsed_json, parsed_form)
            return

        self._send_json(
            200,
            {
                "method": self.command,
                "path": parsed_url.path,
                "query": parse_qs(parsed_url.query, keep_blank_values=True),
                "headers": {
                    "authorization": self.headers.get("Authorization"),
                    "content_type": content_type,
                    "x-token": self.headers.get("X-Token"),
                },
                "body_text": body_text,
                "json": parsed_json,
                "form": parsed_form,
            },
        )

    def _handle_business_request(
        self,
        parsed_url,
        body_text: str,
        parsed_json: dict[str, Any] | None,
        parsed_form: dict[str, list[str]] | None,
    ) -> None:
        path = parsed_url.path
        if path == "/biz/login" and self.command == "POST":
            if parsed_json != {"username": "admin", "password": "admin"}:
                self._send_json(401, {"code": "INVALID_CREDENTIALS"})
                return
            self._send_json(
                200,
                {
                    "access_token": "biz-token-admin",
                    "user": {"id": 1001, "name": "admin", "role": "finance_admin"},
                },
            )
            return

        user = self._current_business_user()
        if user is None:
            self._send_json(401, {"code": "UNAUTHORIZED"})
            return

        if path == "/biz/products" and self.command == "GET":
            query = parse_qs(parsed_url.query, keep_blank_values=True)
            category = query.get("category", [None])[0]
            products = [
                product
                for product in BUSINESS_STATE.products.values()
                if category is None or product["category"] == category
            ]
            self._send_json(200, {"items": products, "total": len(products)})
            return

        if path == "/biz/cart/items" and self.command == "POST":
            product_id = (parsed_json or {}).get("product_id")
            quantity = int((parsed_json or {}).get("quantity", 0))
            product = BUSINESS_STATE.products.get(product_id)
            if product is None:
                self._send_json(404, {"code": "PRODUCT_NOT_FOUND"})
                return
            if quantity <= 0 or quantity > product["stock"]:
                self._send_json(409, {"code": "INSUFFICIENT_STOCK", "stock": product["stock"]})
                return
            product["stock"] -= quantity
            cart_id = f"CART-{BUSINESS_STATE.next_cart_id:04d}"
            BUSINESS_STATE.next_cart_id += 1
            cart = {
                "id": cart_id,
                "user_id": user["id"],
                "items": [{"product_id": product_id, "quantity": quantity, "price": product["price"]}],
                "subtotal": quantity * product["price"],
                "status": "OPEN",
            }
            BUSINESS_STATE.carts[cart_id] = cart
            self._send_json(201, {"cart": cart})
            return

        if path.startswith("/biz/cart/items/") and self.command == "DELETE":
            cart_id = path.rsplit("/", 1)[-1]
            cart = BUSINESS_STATE.carts.get(cart_id)
            if cart is None:
                self._send_json(404, {"code": "CART_NOT_FOUND"})
                return
            cart["status"] = "CANCELLED"
            self._send_json(200, {"cart_id": cart_id, "status": "CANCELLED"})
            return

        if path == "/biz/orders" and self.command == "POST":
            cart_id = (parsed_json or {}).get("cart_id")
            cart = BUSINESS_STATE.carts.get(cart_id)
            if cart is None or cart["status"] != "OPEN":
                self._send_json(400, {"code": "INVALID_CART"})
                return
            coupon_code = (parsed_json or {}).get("coupon_code")
            discount = 10 if coupon_code == "SAVE10" else 0
            total = cart["subtotal"] - discount
            order_id = f"ORDER-{BUSINESS_STATE.next_order_id:04d}"
            BUSINESS_STATE.next_order_id += 1
            order = {
                "id": order_id,
                "user_id": user["id"],
                "cart_id": cart_id,
                "status": "CREATED",
                "subtotal": cart["subtotal"],
                "discount": discount,
                "total": total,
                "attachment_uploaded": False,
                "paid": False,
                "shipping_address": (parsed_json or {}).get("shipping_address"),
            }
            BUSINESS_STATE.orders[order_id] = order
            cart["status"] = "ORDERED"
            self._send_json(201, {"order": order})
            return

        if path.startswith("/biz/orders/") and path.endswith("/attachments") and self.command == "POST":
            order_id = path.split("/")[-2]
            order = BUSINESS_STATE.orders.get(order_id)
            if order is None:
                self._send_json(404, {"code": "ORDER_NOT_FOUND"})
                return
            if "filename=\"payment-proof.txt\"" not in body_text or "proof-content" not in body_text:
                self._send_json(400, {"code": "INVALID_ATTACHMENT"})
                return
            order["attachment_uploaded"] = True
            BUSINESS_STATE.uploads[order_id] = {"filename": "payment-proof.txt"}
            self._send_json(200, {"order_id": order_id, "attachment_uploaded": True})
            return

        if path == "/biz/payments" and self.command == "POST":
            form = parsed_form or {}
            order_id = form.get("order_id", [""])[0]
            amount = int(form.get("amount", ["0"])[0])
            method = form.get("method", [""])[0]
            order = BUSINESS_STATE.orders.get(order_id)
            if order is None:
                self._send_json(404, {"code": "ORDER_NOT_FOUND"})
                return
            if not order["attachment_uploaded"]:
                self._send_json(409, {"code": "ATTACHMENT_REQUIRED"})
                return
            if amount != order["total"]:
                self._send_json(400, {"code": "AMOUNT_MISMATCH", "expected": order["total"]})
                return
            order["paid"] = True
            order["status"] = "PAID"
            self._send_json(200, {"payment": {"order_id": order_id, "amount": amount, "method": method, "status": "SUCCESS"}})
            return

        if path.startswith("/biz/orders/") and self.command == "PATCH":
            order_id = path.rsplit("/", 1)[-1]
            order = BUSINESS_STATE.orders.get(order_id)
            if order is None:
                self._send_json(404, {"code": "ORDER_NOT_FOUND"})
                return
            if not order["paid"]:
                self._send_json(409, {"code": "PAYMENT_REQUIRED"})
                return
            order["status"] = (parsed_json or {}).get("status", order["status"])
            order["note"] = (parsed_json or {}).get("note")
            self._send_json(200, {"order": order})
            return

        if path.startswith("/biz/orders/") and path.endswith("/summary") and self.command == "GET":
            order_id = path.split("/")[-2]
            order = BUSINESS_STATE.orders.get(order_id)
            if order is None:
                self._send_json(404, {"code": "ORDER_NOT_FOUND"})
                return
            self._send_json(200, {"summary": order})
            return

        if path == "/biz/statistics" and self.command == "GET":
            paid_orders = [order for order in BUSINESS_STATE.orders.values() if order["paid"]]
            self._send_json(
                200,
                {
                    "paid_order_count": len(paid_orders),
                    "revenue": sum(order["total"] for order in paid_orders),
                    "uploaded_attachment_count": len(BUSINESS_STATE.uploads),
                },
            )
            return

        self._send_json(404, {"code": "NOT_FOUND", "path": path, "method": self.command})

    def _current_business_user(self):
        authorization = self.headers.get("Authorization") or ""
        token = authorization.removeprefix("Bearer ").strip()
        return BUSINESS_STATE.sessions.get(token)

    def _send_json(self, status_code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)


@dataclass
class ExecutionResult:
    status: str
    request_snapshot: dict[str, Any]
    response_snapshot: dict[str, Any] | None
    assertion_results: list[dict[str, Any]] | None
    error_message: str | None
    duration_ms: int


class FakeRepository:
    def __init__(self, *, base_url: str, variables: dict[str, str]):
        self.environment = SimpleNamespace(id=1, base_url=base_url)
        self.variables = variables
        self.executions: list[ExecutionResult] = []
        self.test_cases: dict[int, SimpleNamespace] = {}

    def get_environment(self, *, project_id: int, environment_id: int):
        if project_id == 1 and environment_id == 1:
            return self.environment
        return None

    def get_environment_variables(self, *, environment_id: int) -> dict[str, str]:
        if environment_id == 1:
            return self.variables
        return {}

    def get_by_id(self, *, project_id: int, test_case_id: int):
        test_case = self.test_cases.get(test_case_id)
        if test_case is not None and test_case.project_id == project_id:
            return test_case
        return None

    def create_execution(
        self,
        *,
        project_id: int,
        test_case_id: int | None,
        environment_id: int | None,
        executed_by_id: int,
        status: str,
        request_snapshot: dict[str, Any],
        response_snapshot: dict[str, Any] | None,
        assertion_results: list[dict[str, Any]] | None,
        error_message: str | None,
        duration_ms: int | None,
    ) -> ExecutionResult:
        result = ExecutionResult(
            status=status,
            request_snapshot=request_snapshot,
            response_snapshot=response_snapshot,
            assertion_results=assertion_results,
            error_message=error_message,
            duration_ms=duration_ms or 0,
        )
        self.executions.append(result)
        return result


class ExecutionEngineTester:
    def __init__(self, *, mock_base: str):
        self.mock_base = mock_base.rstrip("/")
        self.failures: list[str] = []
        self.repository = FakeRepository(
            base_url=self.mock_base,
            variables={
                "token": "mock-token",
                "user_id": "42",
                "username": "admin",
            },
        )
        self.service = object.__new__(TestCaseService)
        self.service.repository = self.repository
        self.service._environment_context_cache = {}
        self.service.permission_service = SimpleNamespace(require_project_permission=lambda *args, **kwargs: True)
        self.current_user = SimpleNamespace(id=1)

    def check(self, name: str, condition: bool, detail: str = "") -> None:
        if condition:
            print(f"[PASS] {name}")
            return
        message = f"[FAIL] {name}"
        if detail:
            message += f" - {detail}"
        print(message)
        self.failures.append(message)

    def execute(self, case: dict[str, Any]) -> ExecutionResult:
        started_at = time.perf_counter()
        case = {"extractors": [], **case}
        try:
            return self.service._execute(
                project_id=1,
                test_case_id=None,
                payload=SimpleNamespace(**case),
                current_user=self.current_user,
            )
        except Exception as exc:  # noqa: BLE001
            return ExecutionResult(
                status="error",
                request_snapshot={},
                response_snapshot=None,
                assertion_results=None,
                error_message=str(exc),
                duration_ms=int((time.perf_counter() - started_at) * 1000),
            )

    def run_success_matrix(self) -> None:
        cases = [
            {
                "name": "GET + query + header variable",
                "environment_id": 1,
                "method": "GET",
                "path": "/echo/{{user_id}}",
                "headers": {"X-Token": "{{token}}"},
                "query_params": {"q": "{{token}}", "items": ["a", "b"]},
                "body_type": "none",
                "body": None,
                "assertions": [
                    {"type": "status_code", "expected": 200},
                    {"type": "json_equals", "path": "method", "expected": "GET"},
                    {"type": "json_equals", "path": "path", "expected": "/echo/42"},
                    {"type": "json_equals", "path": "query.q", "expected": ["mock-token"]},
                    {"type": "json_equals", "path": "headers.x-token", "expected": "mock-token"},
                ],
            },
            {
                "name": "POST + json body",
                "environment_id": 1,
                "method": "POST",
                "path": "/echo",
                "headers": {"Content-Type": "application/json"},
                "query_params": {},
                "body_type": "json",
                "body": {"username": "{{username}}", "token": "{{token}}"},
                "assertions": [
                    {"type": "status_code", "expected": 200},
                    {"type": "json_equals", "path": "json.username", "expected": "admin"},
                    {"type": "json_equals", "path": "json.token", "expected": "mock-token"},
                ],
            },
            {
                "name": "PUT + raw_json string body",
                "environment_id": 1,
                "method": "PUT",
                "path": "/echo",
                "headers": {},
                "query_params": {},
                "body_type": "raw_json",
                "body": "{\"raw\": true, \"user_id\": \"{{user_id}}\"}",
                "assertions": [
                    {"type": "status_code", "expected": 200},
                    {"type": "json_equals", "path": "json.raw", "expected": True},
                    {"type": "json_equals", "path": "json.user_id", "expected": "42"},
                ],
            },
            {
                "name": "PATCH + raw_text body",
                "environment_id": 1,
                "method": "PATCH",
                "path": "/echo",
                "headers": {},
                "query_params": {},
                "body_type": "raw_text",
                "body": "plain {{token}}",
                "assertions": [
                    {"type": "status_code", "expected": 200},
                    {"type": "body_contains", "expected": "plain mock-token"},
                ],
            },
            {
                "name": "POST + form_urlencoded body",
                "environment_id": 1,
                "method": "POST",
                "path": "/echo",
                "headers": {},
                "query_params": {},
                "body_type": "form_urlencoded",
                "body": {"a": "1", "b": ["2", "3"]},
                "assertions": [
                    {"type": "status_code", "expected": 200},
                    {"type": "json_equals", "path": "form.b", "expected": ["2", "3"]},
                ],
            },
            {
                "name": "POST + multipart body",
                "environment_id": 1,
                "method": "POST",
                "path": "/echo",
                "headers": {},
                "query_params": {},
                "body_type": "multipart",
                "body": {
                    "file": {
                        "filename": "demo.txt",
                        "content": "hello multipart",
                        "content_type": "text/plain",
                    },
                    "remark": "upload-demo",
                },
                "assertions": [
                    {"type": "status_code", "expected": 200},
                    {"type": "body_contains", "expected": "demo.txt"},
                    {"type": "body_contains", "expected": "upload-demo"},
                ],
            },
            {
                "name": "DELETE + no body",
                "environment_id": 1,
                "method": "DELETE",
                "path": "/echo",
                "headers": {},
                "query_params": {},
                "body_type": "none",
                "body": None,
                "assertions": [
                    {"type": "status_code", "expected": 200},
                    {"type": "json_equals", "path": "method", "expected": "DELETE"},
                ],
            },
            {
                "name": "OPTIONS + no body",
                "environment_id": 1,
                "method": "OPTIONS",
                "path": "/echo",
                "headers": {},
                "query_params": {},
                "body_type": "none",
                "body": None,
                "assertions": [
                    {"type": "status_code", "expected": 200},
                    {"type": "json_equals", "path": "method", "expected": "OPTIONS"},
                ],
            },
            {
                "name": "HEAD + no response body",
                "environment_id": 1,
                "method": "HEAD",
                "path": "/echo",
                "headers": {},
                "query_params": {},
                "body_type": "none",
                "body": None,
                "assertions": [{"type": "status_code", "expected": 204}],
            },
        ]

        for case in cases:
            result = self.execute(case)
            self.check(f"{case['name']} status passed", result.status == "passed", str(result))
            self.check(f"{case['name']} has request snapshot", bool(result.request_snapshot))
            self.check(
                f"{case['name']} duration recorded",
                isinstance(result.duration_ms, int) and result.duration_ms >= 0,
            )

    def run_failure_matrix(self) -> None:
        failed = self.execute(
            {
                "environment_id": 1,
                "method": "GET",
                "path": "/status/418",
                "headers": {},
                "query_params": {},
                "body_type": "none",
                "body": None,
                "assertions": [{"type": "status_code", "expected": 200}],
            }
        )
        self.check("HTTP 418 with expected 200 should be failed", failed.status == "failed")
        self.check(
            "failed execution keeps response status_code",
            failed.response_snapshot is not None and failed.response_snapshot.get("status_code") == 418,
        )

        no_assertions = self.execute(
            {
                "environment_id": 1,
                "method": "GET",
                "path": "/status/500",
                "headers": {},
                "query_params": {},
                "body_type": "none",
                "body": None,
                "assertions": [],
            }
        )
        self.check(
            "HTTP 500 without assertions currently passes",
            no_assertions.status == "passed",
            "当前业务逻辑是无断言时不按 HTTP 状态自动失败",
        )

        bad_environment = self.execute(
            {
                "environment_id": 999,
                "method": "GET",
                "path": "/echo",
                "headers": {},
                "query_params": {},
                "body_type": "none",
                "body": None,
                "assertions": [],
            }
        )
        self.check("missing environment should be error", bad_environment.status == "error")
        self.check("missing environment records error message", bool(bad_environment.error_message))

        relative_without_environment = self.execute(
            {
                "environment_id": None,
                "method": "GET",
                "path": "/relative",
                "headers": {},
                "query_params": {},
                "body_type": "none",
                "body": None,
                "assertions": [],
            }
        )
        self.check("relative path without environment should be error", relative_without_environment.status == "error")

        full_url_without_environment = self.execute(
            {
                "environment_id": None,
                "method": "GET",
                "path": f"{self.mock_base}/echo",
                "headers": {},
                "query_params": {},
                "body_type": "none",
                "body": None,
                "assertions": [{"type": "status_code", "expected": 200}],
            }
        )
        self.check("full URL without environment should pass", full_url_without_environment.status == "passed")

        invalid_body_type = self.execute(
            {
                "environment_id": 1,
                "method": "POST",
                "path": "/echo",
                "headers": {},
                "query_params": {},
                "body_type": "form_urlencoded",
                "body": "not-a-dict",
                "assertions": [],
            }
        )
        self.check("invalid form_urlencoded body should be error", invalid_body_type.status == "error")

    def run_context_matrix(self) -> None:
        login_result = self.execute(
            {
                "environment_id": 1,
                "method": "POST",
                "path": "/login",
                "headers": {"Content-Type": "application/json"},
                "query_params": {},
                "body_type": "json",
                "body": {"username": "admin", "password": "admin"},
                "assertions": [
                    {"type": "status_code", "expected": 200},
                    {"type": "json_equals", "path": "user.id", "expected": 7},
                ],
                "extractors": [
                    {"name": "session_token", "path": "token"},
                    {"name": "login_user_id", "path": "user.id"},
                ],
            }
        )
        self.check("context login step passed", login_result.status == "passed", str(login_result))
        self.check(
            "extractor writes session_token",
            self.repository.variables.get("session_token") == "ctx-token-123",
            str(self.repository.variables),
        )
        self.check(
            "extractor converts numeric value to string",
            self.repository.variables.get("login_user_id") == "7",
            str(self.repository.variables),
        )

        linked_result = self.execute(
            {
                "environment_id": 1,
                "method": "GET",
                "path": "/echo/{{login_user_id}}",
                "headers": {"Authorization": "Bearer {{session_token}}"},
                "query_params": {"token": "{{session_token}}"},
                "body_type": "none",
                "body": None,
                "assertions": [
                    {"type": "status_code", "expected": 200},
                    {"type": "json_equals", "path": "path", "expected": "/echo/7"},
                    {
                        "type": "json_equals",
                        "path": "headers.authorization",
                        "expected": "Bearer ctx-token-123",
                    },
                    {"type": "json_equals", "path": "query.token", "expected": ["ctx-token-123"]},
                ],
                "extractors": [],
            }
        )
        self.check("context linked step passed", linked_result.status == "passed", str(linked_result))

    def run_batch_matrix(self) -> None:
        self.repository.test_cases = {
            101: SimpleNamespace(
                id=101,
                project_id=1,
                environment_id=1,
                method="POST",
                path="/login",
                headers={"Content-Type": "application/json"},
                query_params={},
                body_type="json",
                body={"username": "admin", "password": "admin"},
                assertions=[{"type": "status_code", "expected": 200}],
                extractors=[{"name": "batch_token", "path": "token"}],
            ),
            102: SimpleNamespace(
                id=102,
                project_id=1,
                environment_id=1,
                method="GET",
                path="/echo",
                headers={"Authorization": "Bearer {{batch_token}}"},
                query_params={"token": "{{batch_token}}"},
                body_type="none",
                body=None,
                assertions=[
                    {"type": "status_code", "expected": 200},
                    {
                        "type": "json_equals",
                        "path": "headers.authorization",
                        "expected": "Bearer ctx-token-123",
                    },
                    {"type": "json_equals", "path": "query.token", "expected": ["ctx-token-123"]},
                ],
                extractors=[],
            ),
        }
        payload = SimpleNamespace(test_case_ids=[101, 102], environment_id=1)
        results = self.service.batch_execute(project_id=1, payload=payload, current_user=self.current_user)
        self.check("batch execution returns two results", len(results) == 2)
        self.check("batch execution preserves order", results[0].request_snapshot["url"].endswith("/login"))
        self.check("batch execution first step passed", results[0].status == "passed", str(results[0]))
        self.check("batch execution second step uses extracted token", results[1].status == "passed", str(results[1]))

    def run_file_upload_matrix(self) -> None:
        result = self.execute(
            {
                "environment_id": 1,
                "method": "POST",
                "path": "/echo",
                "headers": {},
                "query_params": {},
                "body_type": "multipart",
                "body": {
                    "file": {
                        "filename": "report.csv",
                        "content": "id,name\n1,Alice",
                        "content_type": "text/csv",
                    },
                    "meta": "{\"source\":\"script\",\"token\":\"{{token}}\"}",
                },
                "assertions": [
                    {"type": "status_code", "expected": 200},
                    {"type": "body_contains", "expected": "report.csv"},
                    {"type": "body_contains", "expected": "Content-Type: text/csv"},
                    {"type": "body_contains", "expected": "id,name"},
                    {"type": "body_contains", "expected": "mock-token"},
                ],
                "extractors": [],
            }
        )
        self.check("multipart file upload passed", result.status == "passed", str(result))

    def run_business_workflow_matrix(self) -> None:
        BUSINESS_STATE.reset()
        self.repository.variables.update(
            {
                "biz_username": "admin",
                "biz_password": "admin",
                "product_id": "SKU-BOOK-1",
                "quantity": "2",
                "coupon_code": "SAVE10",
                "shipping_address": "Shanghai Test Road 100",
            }
        )

        cases = [
            {
                "name": "业务登录并提取 token",
                "environment_id": 1,
                "method": "POST",
                "path": "/biz/login",
                "headers": {"Content-Type": "application/json"},
                "query_params": {},
                "body_type": "json",
                "body": {"username": "{{biz_username}}", "password": "{{biz_password}}"},
                "assertions": [
                    {"type": "status_code", "expected": 200},
                    {"type": "json_equals", "path": "user.role", "expected": "finance_admin"},
                ],
                "extractors": [
                    {"name": "biz_access_token", "path": "access_token"},
                    {"name": "biz_user_id", "path": "user.id"},
                ],
            },
            {
                "name": "查询商品并校验库存",
                "environment_id": 1,
                "method": "GET",
                "path": "/biz/products",
                "headers": {"Authorization": "Bearer {{biz_access_token}}"},
                "query_params": {"category": "book"},
                "body_type": "none",
                "body": None,
                "assertions": [
                    {"type": "status_code", "expected": 200},
                    {"type": "json_equals", "path": "items.0.id", "expected": "SKU-BOOK-1"},
                    {"type": "json_equals", "path": "items.0.stock", "expected": 5},
                ],
                "extractors": [
                    {"name": "selected_product_id", "path": "items.0.id"},
                    {"name": "selected_product_price", "path": "items.0.price"},
                ],
            },
            {
                "name": "加入购物车并扣减库存",
                "environment_id": 1,
                "method": "POST",
                "path": "/biz/cart/items",
                "headers": {"Authorization": "Bearer {{biz_access_token}}", "Content-Type": "application/json"},
                "query_params": {},
                "body_type": "json",
                "body": {"product_id": "{{selected_product_id}}", "quantity": 2},
                "assertions": [
                    {"type": "status_code", "expected": 201},
                    {"type": "json_equals", "path": "cart.status", "expected": "OPEN"},
                    {"type": "json_equals", "path": "cart.subtotal", "expected": 160},
                ],
                "extractors": [
                    {"name": "cart_id", "path": "cart.id"},
                    {"name": "cart_subtotal", "path": "cart.subtotal"},
                ],
            },
            {
                "name": "创建订单并应用优惠券",
                "environment_id": 1,
                "method": "POST",
                "path": "/biz/orders",
                "headers": {"Authorization": "Bearer {{biz_access_token}}", "Content-Type": "application/json"},
                "query_params": {},
                "body_type": "json",
                "body": {
                    "cart_id": "{{cart_id}}",
                    "coupon_code": "{{coupon_code}}",
                    "shipping_address": "{{shipping_address}}",
                },
                "assertions": [
                    {"type": "status_code", "expected": 201},
                    {"type": "json_equals", "path": "order.status", "expected": "CREATED"},
                    {"type": "json_equals", "path": "order.total", "expected": 150},
                    {"type": "json_equals", "path": "order.discount", "expected": 10},
                ],
                "extractors": [
                    {"name": "order_id", "path": "order.id"},
                    {"name": "order_total", "path": "order.total"},
                ],
            },
            {
                "name": "上传订单支付凭证",
                "environment_id": 1,
                "method": "POST",
                "path": "/biz/orders/{{order_id}}/attachments",
                "headers": {"Authorization": "Bearer {{biz_access_token}}"},
                "query_params": {},
                "body_type": "multipart",
                "body": {
                    "file": {
                        "filename": "payment-proof.txt",
                        "content": "proof-content order={{order_id}} amount={{order_total}}",
                        "content_type": "text/plain",
                    },
                    "scene": "payment",
                },
                "assertions": [
                    {"type": "status_code", "expected": 200},
                    {"type": "json_equals", "path": "attachment_uploaded", "expected": True},
                ],
                "extractors": [],
            },
            {
                "name": "支付订单",
                "environment_id": 1,
                "method": "POST",
                "path": "/biz/payments",
                "headers": {"Authorization": "Bearer {{biz_access_token}}"},
                "query_params": {},
                "body_type": "form_urlencoded",
                "body": {"order_id": "{{order_id}}", "amount": "{{order_total}}", "method": "balance"},
                "assertions": [
                    {"type": "status_code", "expected": 200},
                    {"type": "json_equals", "path": "payment.status", "expected": "SUCCESS"},
                    {"type": "json_equals", "path": "payment.amount", "expected": 150},
                ],
                "extractors": [],
            },
            {
                "name": "确认订单",
                "environment_id": 1,
                "method": "PATCH",
                "path": "/biz/orders/{{order_id}}",
                "headers": {"Authorization": "Bearer {{biz_access_token}}"},
                "query_params": {},
                "body_type": "raw_json",
                "body": "{\"status\":\"CONFIRMED\",\"note\":\"confirmed by case {{order_id}}\"}",
                "assertions": [
                    {"type": "status_code", "expected": 200},
                    {"type": "json_equals", "path": "order.status", "expected": "CONFIRMED"},
                ],
                "extractors": [],
            },
            {
                "name": "查询订单汇总",
                "environment_id": 1,
                "method": "GET",
                "path": "/biz/orders/{{order_id}}/summary",
                "headers": {"Authorization": "Bearer {{biz_access_token}}"},
                "query_params": {},
                "body_type": "none",
                "body": None,
                "assertions": [
                    {"type": "status_code", "expected": 200},
                    {"type": "json_equals", "path": "summary.status", "expected": "CONFIRMED"},
                    {"type": "json_equals", "path": "summary.paid", "expected": True},
                    {"type": "json_equals", "path": "summary.attachment_uploaded", "expected": True},
                ],
                "extractors": [],
            },
            {
                "name": "查询业务统计",
                "environment_id": 1,
                "method": "GET",
                "path": "/biz/statistics",
                "headers": {"Authorization": "Bearer {{biz_access_token}}"},
                "query_params": {"customer_id": "{{biz_user_id}}"},
                "body_type": "none",
                "body": None,
                "assertions": [
                    {"type": "status_code", "expected": 200},
                    {"type": "json_equals", "path": "paid_order_count", "expected": 1},
                    {"type": "json_equals", "path": "revenue", "expected": 150},
                    {"type": "json_equals", "path": "uploaded_attachment_count", "expected": 1},
                ],
                "extractors": [],
            },
        ]

        for case in cases:
            result = self.execute(case)
            self.check(f"complex workflow: {case['name']}", result.status == "passed", str(result))

        self.check(
            "complex workflow changes product stock",
            BUSINESS_STATE.products["SKU-BOOK-1"]["stock"] == 3,
            str(BUSINESS_STATE.products["SKU-BOOK-1"]),
        )
        self.check(
            "complex workflow order final state",
            BUSINESS_STATE.orders.get(self.repository.variables.get("order_id"), {}).get("status") == "CONFIRMED",
            str(BUSINESS_STATE.orders),
        )

    def run_business_negative_matrix(self) -> None:
        BUSINESS_STATE.reset()
        self.repository.variables.update({"biz_access_token": "biz-token-admin"})
        invalid_stock = self.execute(
            {
                "environment_id": 1,
                "method": "POST",
                "path": "/biz/cart/items",
                "headers": {"Authorization": "Bearer {{biz_access_token}}", "Content-Type": "application/json"},
                "query_params": {},
                "body_type": "json",
                "body": {"product_id": "SKU-COURSE-1", "quantity": 99},
                "assertions": [
                    {"type": "status_code", "expected": 409},
                    {"type": "json_equals", "path": "code", "expected": "INSUFFICIENT_STOCK"},
                ],
                "extractors": [],
            }
        )
        self.check("business negative: insufficient stock", invalid_stock.status == "passed", str(invalid_stock))

        unauthorized = self.execute(
            {
                "environment_id": 1,
                "method": "GET",
                "path": "/biz/products",
                "headers": {"Authorization": "Bearer wrong-token"},
                "query_params": {},
                "body_type": "none",
                "body": None,
                "assertions": [
                    {"type": "status_code", "expected": 401},
                    {"type": "json_equals", "path": "code", "expected": "UNAUTHORIZED"},
                ],
                "extractors": [],
            }
        )
        self.check("business negative: unauthorized token", unauthorized.status == "passed", str(unauthorized))

    def run(self) -> int:
        self.run_success_matrix()
        self.run_context_matrix()
        self.run_batch_matrix()
        self.run_file_upload_matrix()
        self.run_business_workflow_matrix()
        self.run_business_negative_matrix()
        self.run_failure_matrix()
        if self.failures:
            print(f"\n完成，失败 {len(self.failures)} 项。")
            return 1
        print("\n完成，测试用例执行方法覆盖测试全部通过。")
        return 0


def start_mock_server(host: str, port: int) -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer((host, port), MockTargetHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://{host}:{server.server_address[1]}"


def main() -> int:
    parser = argparse.ArgumentParser(description="测试测试用例执行方法是否覆盖主要场景")
    parser.add_argument("--mock-host", default="127.0.0.1")
    parser.add_argument("--mock-port", type=int, default=18080)
    args = parser.parse_args()

    mock_server, mock_base = start_mock_server(args.mock_host, args.mock_port)
    print(f"Mock target server: {mock_base}")
    started_at = time.perf_counter()
    try:
        tester = ExecutionEngineTester(mock_base=mock_base)
        return tester.run()
    finally:
        mock_server.shutdown()
        mock_server.server_close()
        print(f"Elapsed: {int((time.perf_counter() - started_at) * 1000)}ms")


if __name__ == "__main__":
    sys.exit(main())
