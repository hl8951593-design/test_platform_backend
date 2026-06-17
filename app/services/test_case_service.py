import json
import copy
import uuid
import time
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.permissions import ProjectPermission
from app.core.sensitive_data import mask_sensitive
from app.core.variable_renderer import render_variables
from app.models.test_case import TestCase, TestCaseExecution
from app.models.user import User
from app.repositories.test_case_repository import TestCaseRepository
from app.runner.assertion_engine import json_values_equal
from app.runner.retry import (
    failed_assertions_are_retryable,
    method_allows_retry,
    retry_delay_seconds,
)
from app.schemas.test_case import (
    BatchExecuteRequest,
    TestCaseCreateRequest,
    TestCaseRequestConfig,
    TestCaseUpdateRequest,
    UnsavedTestCaseExecuteRequest,
)
from app.services.permission_service import PermissionService


class TestCaseService:
    def __init__(self, db: Session):
        self.db = db
        self.repository = TestCaseRepository(db)
        self.permission_service = PermissionService(db)
        self._environment_context_cache: dict[int, tuple[Any, dict[str, str]]] = {}

    def list_cases(
        self,
        *,
        project_id: int,
        current_user: User,
        keyword: str | None,
        environment_id: int | None,
        page: int,
        page_size: int,
    ) -> dict[str, Any]:
        self.permission_service.require_project_permission(
            current_user,
            project_id,
            ProjectPermission.VIEW_CASE.value,
        )
        items, total = self.repository.list_by_project(
            project_id=project_id,
            keyword=keyword,
            environment_id=environment_id,
            page=page,
            page_size=page_size,
        )
        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    def create_case(self, *, project_id: int, payload: TestCaseCreateRequest, current_user: User) -> TestCase:
        self.permission_service.require_project_permission(
            current_user,
            project_id,
            ProjectPermission.MANAGE_CASE.value,
        )
        environment_id, environment_ids = self._resolve_environment_ids(project_id=project_id, payload=payload)
        return self.repository.create(
            project_id=project_id,
            environment_id=environment_id,
            environment_ids=environment_ids,
            name=payload.name,
            description=payload.description,
            method=payload.method,
            path=payload.path,
            headers=payload.headers,
            query_params=payload.query_params,
            body_type=payload.body_type,
            body=payload.body,
            assertions=[item.model_dump() for item in payload.assertions],
            extractors=[item.model_dump() for item in payload.extractors],
            retry_policy=payload.retry_policy.model_dump(),
            created_by_id=current_user.id,
        )

    def update_case(
        self,
        *,
        project_id: int,
        test_case_id: int,
        payload: TestCaseUpdateRequest,
        current_user: User,
    ) -> TestCase:
        self.permission_service.require_project_permission(
            current_user,
            project_id,
            ProjectPermission.MANAGE_CASE.value,
        )
        test_case = self._get_case_or_404(project_id=project_id, test_case_id=test_case_id)
        environment_id, environment_ids = self._resolve_environment_ids(project_id=project_id, payload=payload)
        return self.repository.update(
            test_case=test_case,
            environment_id=environment_id,
            environment_ids=environment_ids,
            name=payload.name,
            description=payload.description,
            method=payload.method,
            path=payload.path,
            headers=payload.headers,
            query_params=payload.query_params,
            body_type=payload.body_type,
            body=payload.body,
            assertions=[item.model_dump() for item in payload.assertions],
            extractors=[item.model_dump() for item in payload.extractors],
            retry_policy=payload.retry_policy.model_dump(),
        )

    def delete_case(self, *, project_id: int, test_case_id: int, current_user: User) -> None:
        self.permission_service.require_project_permission(
            current_user,
            project_id,
            ProjectPermission.MANAGE_CASE.value,
        )
        test_case = self._get_case_or_404(project_id=project_id, test_case_id=test_case_id)
        flow_names = self.repository.referencing_flow_names(
            project_id=project_id,
            test_case_id=test_case_id,
        )
        if flow_names:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "message": "测试用例已被可视化流程引用，不能删除",
                    "flows": flow_names,
                },
            )
        self.repository.delete(test_case)

    def execute_saved_case(
        self,
        *,
        project_id: int,
        test_case_id: int,
        environment_id: int | None,
        current_user: User,
    ) -> TestCaseExecution:
        self.permission_service.require_project_permission(
            current_user,
            project_id,
            ProjectPermission.EXECUTE_TEST.value,
        )
        return self._execute_saved_case(
            project_id=project_id,
            test_case_id=test_case_id,
            environment_id=environment_id,
            current_user=current_user,
        )

    def _execute_saved_case(
        self,
        *,
        project_id: int,
        test_case_id: int,
        environment_id: int | None,
        current_user: User,
    ) -> TestCaseExecution:
        test_case = self._get_case_or_404(project_id=project_id, test_case_id=test_case_id)
        selected_environment_id = environment_id or test_case.environment_id
        payload = TestCaseRequestConfig(
            environment_id=selected_environment_id,
            method=test_case.method,
            path=test_case.path,
            headers=test_case.headers,
            query_params=test_case.query_params,
            body_type=test_case.body_type,
            body=test_case.body,
            assertions=test_case.assertions or [],
            extractors=test_case.extractors or [],
            retry_policy=test_case.retry_policy or {},
        )
        return self._execute(
            project_id=project_id,
            test_case_id=test_case_id,
            payload=payload,
            current_user=current_user,
        )

    def execute_unsaved_case(
        self,
        *,
        project_id: int,
        payload: UnsavedTestCaseExecuteRequest,
        current_user: User,
    ) -> TestCaseExecution:
        self.permission_service.require_project_permission(
            current_user,
            project_id,
            ProjectPermission.EXECUTE_TEST.value,
        )
        return self._execute(project_id=project_id, test_case_id=None, payload=payload, current_user=current_user)

    def batch_execute(
        self,
        *,
        project_id: int,
        payload: BatchExecuteRequest,
        current_user: User,
    ) -> list[TestCaseExecution]:
        self.permission_service.require_project_permission(
            current_user,
            project_id,
            ProjectPermission.EXECUTE_TEST.value,
        )
        executions: list[TestCaseExecution] = []
        for test_case_id in payload.test_case_ids:
            executions.append(
                self._execute_saved_case(
                    project_id=project_id,
                    test_case_id=test_case_id,
                    environment_id=payload.environment_id,
                    current_user=current_user,
                )
            )
        return executions

    def _execute(
        self,
        *,
        project_id: int,
        test_case_id: int | None,
        payload: TestCaseRequestConfig | UnsavedTestCaseExecuteRequest,
        current_user: User,
        scenario_run_id: int | None = None,
        timeout_seconds: float | None = None,
    ) -> TestCaseExecution:
        environment, variables = self._load_environment_context(
            project_id=project_id,
            environment_id=payload.environment_id,
        )
        request_snapshot = self._build_request_snapshot(payload=payload, base_url=environment.base_url if environment else None, variables=variables)

        started_at = time.perf_counter()
        response_snapshot: dict[str, Any] | None = None
        assertion_results: list[dict[str, Any]] | None = None
        attempt_history: list[dict[str, Any]] = []
        error_message: str | None = None
        status_value = "passed"
        policy = payload.retry_policy
        retry_allowed_for_method = method_allows_retry(payload.method, policy)
        execution_deadline = (
            time.monotonic() + timeout_seconds
            if timeout_seconds is not None
            else None
        )

        for attempt in range(1, policy.attempts + 1):
            attempt_started = time.perf_counter()
            attempt_detail: dict[str, Any] = {
                "attempt": attempt,
                "status": "running",
                "retry_reason": None,
                "wait_ms": 0,
            }
            response_snapshot = None
            assertion_results = None
            retry_reason: str | None = None
            response_headers: dict[str, Any] | None = None
            try:
                remaining = (
                    execution_deadline - time.monotonic()
                    if execution_deadline is not None
                    else timeout_seconds
                )
                if remaining is not None and remaining <= 0:
                    raise httpx.TimeoutException("Scenario execution deadline exceeded")
                response_snapshot = self._send_request(
                    request_snapshot,
                    timeout_seconds=remaining,
                )
                response_headers = response_snapshot.get("headers") or {}
                attempt_detail["status_code"] = response_snapshot["status_code"]
                if (
                    policy.enabled
                    and retry_allowed_for_method
                    and response_snapshot["status_code"] in policy.status_codes
                ):
                    retry_reason = f"http_status_{response_snapshot['status_code']}"
                    status_value = "failed"
                    error_message = (
                        f"HTTP {response_snapshot['status_code']} is retryable"
                    )
                else:
                    assertion_results = self._run_assertions(
                        payload.assertions, response_snapshot
                    )
                    attempt_detail["assertion_results"] = copy.deepcopy(
                        assertion_results
                    )
                    if any(not result["passed"] for result in assertion_results):
                        status_value = "failed"
                        error_message = "Assertion failed"
                        if (
                            policy.enabled
                            and retry_allowed_for_method
                            and failed_assertions_are_retryable(assertion_results)
                        ):
                            retry_reason = "polling_assertion_failed"
                    else:
                        self._run_extractors(
                            payload.extractors, response_snapshot, variables
                        )
                        status_value = "passed"
                        error_message = None
            except httpx.TimeoutException as exc:
                status_value = "error"
                error_message = str(exc)
                if (
                    policy.enabled
                    and retry_allowed_for_method
                    and policy.retry_timeouts
                ):
                    retry_reason = "timeout"
            except httpx.RequestError as exc:
                status_value = "error"
                error_message = str(exc)
                if (
                    policy.enabled
                    and retry_allowed_for_method
                    and policy.retry_network_errors
                ):
                    retry_reason = "network_error"
            except Exception as exc:  # noqa: BLE001
                status_value = "error"
                error_message = str(exc)

            can_retry = retry_reason is not None and attempt < policy.attempts
            attempt_detail["status"] = (
                "retrying"
                if can_retry
                else "passed"
                if status_value == "passed"
                else "failed"
            )
            attempt_detail["retry_reason"] = retry_reason
            attempt_detail["error_message"] = error_message
            attempt_detail["duration_ms"] = int(
                (time.perf_counter() - attempt_started) * 1000
            )

            if can_retry:
                wait_seconds = retry_delay_seconds(
                    policy,
                    attempt=attempt,
                    response_headers=response_headers,
                )
                if (
                    execution_deadline is not None
                    and time.monotonic() + wait_seconds >= execution_deadline
                ):
                    attempt_detail["status"] = "failed"
                    attempt_detail["retry_reason"] = "deadline_exceeded"
                    error_message = "Scenario execution deadline exceeded"
                    status_value = "error"
                    attempt_history.append(attempt_detail)
                    break
                attempt_detail["wait_ms"] = int(wait_seconds * 1000)
                attempt_history.append(attempt_detail)
                if wait_seconds > 0:
                    time.sleep(wait_seconds)
                continue

            attempt_history.append(attempt_detail)
            break

        duration_ms = int((time.perf_counter() - started_at) * 1000)
        return self.repository.create_execution(
            project_id=project_id,
            test_case_id=test_case_id,
            environment_id=payload.environment_id,
            scenario_run_id=scenario_run_id,
            executed_by_id=current_user.id,
            status=status_value,
            request_snapshot=mask_sensitive(request_snapshot),
            response_snapshot=response_snapshot,
            assertion_results=assertion_results,
            attempt_history=attempt_history,
            error_message=error_message,
            duration_ms=duration_ms,
        )

    def _validate_environment(self, *, project_id: int, environment_id: int | None) -> None:
        if environment_id is not None and self.repository.get_environment(project_id=project_id, environment_id=environment_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="环境不存在")

    def _resolve_environment_ids(
        self,
        *,
        project_id: int,
        payload: TestCaseRequestConfig,
    ) -> tuple[int | None, list[int]]:
        environment_ids = list(dict.fromkeys(payload.environment_ids or []))
        if payload.environment_id is not None and payload.environment_id not in environment_ids:
            environment_ids.insert(0, payload.environment_id)

        default_environment_id = payload.environment_id
        if default_environment_id is None and environment_ids:
            default_environment_id = environment_ids[0]

        for environment_id in environment_ids:
            self._validate_environment(project_id=project_id, environment_id=environment_id)
        if default_environment_id is not None:
            self._validate_environment(project_id=project_id, environment_id=default_environment_id)

        return default_environment_id, environment_ids

    def _get_case_or_404(self, *, project_id: int, test_case_id: int) -> TestCase:
        test_case = self.repository.get_by_id(project_id=project_id, test_case_id=test_case_id)
        if test_case is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="测试用例不存在")
        return test_case

    def _load_environment_context(self, *, project_id: int, environment_id: int | None):
        if environment_id is None:
            return None, {}
        if environment_id in self._environment_context_cache:
            return self._environment_context_cache[environment_id]
        environment = self.repository.get_environment(project_id=project_id, environment_id=environment_id)
        if environment is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="环境不存在")
        context = environment, self.repository.get_environment_variables(environment_id=environment_id)
        self._environment_context_cache[environment_id] = context
        return context

    def _build_request_snapshot(self, *, payload: TestCaseRequestConfig, base_url: str | None, variables: dict[str, str]) -> dict[str, Any]:
        path = self._render_value(payload.path, variables)
        if path.startswith(("http://", "https://")):
            url = path
        elif base_url:
            url = base_url.rstrip("/") + "/" + path.lstrip("/")
        else:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="未绑定环境时 path 必须是完整 URL")

        query_params = self._render_value(payload.query_params or {}, variables)
        if query_params:
            url = url + ("&" if "?" in url else "?") + urlencode(query_params, doseq=True)

        return {
            "method": payload.method,
            "url": url,
            "headers": self._render_value(payload.headers or {}, variables),
            "body_type": payload.body_type,
            "body": self._render_value(payload.body, variables),
        }

    def _render_value(self, value: Any, variables: dict[str, str]) -> Any:
        return render_variables(value, variables)

    def _send_request_legacy(self, request_snapshot: dict[str, Any]) -> dict[str, Any]:
        return self._send_request(request_snapshot)
        body = request_snapshot["body"]
        data = None
        headers = dict(request_snapshot["headers"] or {})
        body_type = request_snapshot.get("body_type", "json")
        if body_type != "none" and body is not None:
            data, generated_content_type = self._encode_body(body_type=body_type, body=body)
            if generated_content_type:
                headers.setdefault("Content-Type", generated_content_type)
        try:
            with urlopen(request, timeout=20) as response:  # noqa: S310
                raw_body = response.read().decode("utf-8", errors="replace")
                return {
                    "status_code": response.status,
                    "headers": dict(response.headers.items()),
                    "body": raw_body,
                    "json": self._safe_json(raw_body),
                }
        except HTTPError as exc:
            raw_body = exc.read().decode("utf-8", errors="replace")
            return {
                "status_code": exc.code,
                "headers": dict(exc.headers.items()),
                "body": raw_body,
                "json": self._safe_json(raw_body),
            }
        except URLError as exc:
            raise RuntimeError(f"请求失败: {exc.reason}") from exc

    def _send_request(
        self, request_snapshot: dict[str, Any], *, timeout_seconds: float | None = None
    ) -> dict[str, Any]:
        body = request_snapshot["body"]
        data = None
        headers = dict(request_snapshot["headers"] or {})
        body_type = request_snapshot.get("body_type", "json")
        if body_type != "none" and body is not None:
            data, generated_content_type = self._encode_body(body_type=body_type, body=body)
            if generated_content_type:
                headers.setdefault("Content-Type", generated_content_type)

        response = httpx.request(
            request_snapshot["method"],
            request_snapshot["url"],
            content=data,
            headers=headers,
            timeout=max(min(timeout_seconds or 20, 20), 0.1),
            follow_redirects=True,
        )

        raw_body = response.text
        return {
            "status_code": response.status_code,
            "headers": dict(response.headers.items()),
            "body": raw_body,
            "json": self._safe_json(raw_body),
        }

    def _encode_body(self, *, body_type: str, body: Any) -> tuple[bytes | None, str | None]:
        if body_type == "json":
            return json.dumps(body, ensure_ascii=False).encode("utf-8"), "application/json"
        if body_type == "raw_json":
            raw_json = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
            return raw_json.encode("utf-8"), "application/json"
        if body_type == "raw_text":
            return str(body).encode("utf-8"), "text/plain; charset=utf-8"
        if body_type == "form_urlencoded":
            if not isinstance(body, dict):
                raise ValueError("form_urlencoded 请求体必须是对象")
            return urlencode(body, doseq=True).encode("utf-8"), "application/x-www-form-urlencoded"
        if body_type == "multipart":
            if not isinstance(body, dict):
                raise ValueError("multipart 请求体必须是对象")
            return self._encode_multipart(body)
        raise ValueError(f"不支持的请求体格式: {body_type}")

    def _encode_multipart(self, body: dict[str, Any]) -> tuple[bytes, str]:
        boundary = "----devtestbackend-" + uuid.uuid4().hex
        chunks: list[bytes] = []
        for name, value in body.items():
            chunks.append(f"--{boundary}\r\n".encode("utf-8"))
            if isinstance(value, dict) and "filename" in value:
                filename = str(value["filename"])
                content = value.get("content", "")
                content_type = value.get("content_type", "application/octet-stream")
                chunks.append(
                    (
                        f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
                        f"Content-Type: {content_type}\r\n\r\n"
                    ).encode("utf-8")
                )
                chunks.append(str(content).encode("utf-8"))
                chunks.append(b"\r\n")
            else:
                chunks.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
                chunks.append(str(value).encode("utf-8"))
                chunks.append(b"\r\n")
        chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
        return b"".join(chunks), f"multipart/form-data; boundary={boundary}"

    def _run_assertions(self, assertions: list[Any], response_snapshot: dict[str, Any]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for assertion in assertions:
            item = assertion if isinstance(assertion, dict) else assertion.model_dump()
            actual = None
            passed = False
            if item["type"] == "status_code":
                actual = response_snapshot["status_code"]
                passed = actual == item["expected"]
            elif item["type"] == "body_contains":
                actual = response_snapshot["body"]
                passed = str(item["expected"]) in actual
            elif item["type"] == "json_equals":
                actual = self._get_json_path(response_snapshot.get("json"), item.get("path"))
                passed = json_values_equal(actual, item["expected"])
            results.append({"assertion": item, "actual": actual, "passed": passed})
        return results

    def _run_extractors(
        self,
        extractors: list[Any],
        response_snapshot: dict[str, Any],
        variables: dict[str, str],
    ) -> None:
        for extractor in extractors:
            item = extractor if isinstance(extractor, dict) else extractor.model_dump()
            actual = self._get_json_path(response_snapshot.get("json"), item.get("path"))
            if actual is not None:
                variables[item["name"]] = str(actual)

    def _safe_json(self, raw_body: str) -> Any:
        try:
            return json.loads(raw_body)
        except json.JSONDecodeError:
            return None

    def _get_json_path(self, data: Any, path: str | None) -> Any:
        if not path:
            return data
        current = data
        for part in path.split("."):
            if isinstance(current, dict):
                current = current.get(part)
            elif isinstance(current, list) and part.isdigit():
                current = current[int(part)]
            else:
                return None
        return current
