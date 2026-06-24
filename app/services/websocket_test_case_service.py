import json
import copy
import time
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import websocket
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.permissions import ProjectPermission
from app.core.sensitive_data import mask_sensitive
from app.core.variable_renderer import render_variables
from app.db.session import SessionLocal
from app.models.user import User
from app.models.websocket_test_case import WebSocketTestCase, WebSocketTestCaseExecution
from app.repositories.websocket_test_case_repository import WebSocketTestCaseRepository
from app.runner.assertion_engine import json_values_equal
from app.runner.retry import failed_assertions_are_retryable, retry_delay_seconds
from app.schemas.retry import RetryPolicyConfig
from app.schemas.websocket_test_case import (
    UnsavedWebSocketTestCaseExecuteRequest,
    WebSocketBatchExecuteRequest,
    WebSocketTestCaseConfig,
    WebSocketTestCaseCreateRequest,
    WebSocketTestCaseUpdateRequest,
)
from app.services.permission_service import PermissionService


class WebSocketTestCaseService:
    def __init__(self, db: Session):
        self.repository = WebSocketTestCaseRepository(db)
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
        self._require(current_user, project_id, ProjectPermission.VIEW_CASE.value)
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

    def create_case(self, *, project_id: int, payload: WebSocketTestCaseCreateRequest, current_user: User) -> WebSocketTestCase:
        self._require(current_user, project_id, ProjectPermission.MANAGE_CASE.value)
        environment_id, environment_ids = self._resolve_environment_ids(project_id, payload)
        test_case = WebSocketTestCase(project_id=project_id, created_by_id=current_user.id)
        self._apply_payload(test_case, payload, environment_id)
        return self.repository.save(test_case=test_case, environment_ids=environment_ids)

    def update_case(self, *, project_id: int, test_case_id: int, payload: WebSocketTestCaseUpdateRequest, current_user: User) -> WebSocketTestCase:
        self._require(current_user, project_id, ProjectPermission.MANAGE_CASE.value)
        test_case = self._get_case(project_id, test_case_id)
        environment_id, environment_ids = self._resolve_environment_ids(project_id, payload)
        self._apply_payload(test_case, payload, environment_id)
        return self.repository.save(test_case=test_case, environment_ids=environment_ids)

    def delete_case(self, *, project_id: int, test_case_id: int, current_user: User) -> None:
        self._require(current_user, project_id, ProjectPermission.MANAGE_CASE.value)
        test_case = self._get_case(project_id, test_case_id)
        flow_names = self.repository.referencing_flow_names(
            project_id=project_id,
            test_case_id=test_case_id,
        )
        if flow_names:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "message": "WebSocket 测试用例已被可视化流程引用，不能删除",
                    "flows": flow_names,
                },
            )
        self.repository.delete(test_case)

    def execute_saved_case(self, *, project_id: int, test_case_id: int, environment_id: int | None, current_user: User) -> WebSocketTestCaseExecution:
        self._require(current_user, project_id, ProjectPermission.EXECUTE_TEST.value)
        return self._execute_saved(project_id, test_case_id, environment_id, current_user)

    def execute_unsaved_case(self, *, project_id: int, payload: UnsavedWebSocketTestCaseExecuteRequest, current_user: User) -> WebSocketTestCaseExecution:
        self._require(current_user, project_id, ProjectPermission.EXECUTE_TEST.value)
        return self._execute(project_id, None, payload, current_user)

    def batch_execute(self, *, project_id: int, payload: WebSocketBatchExecuteRequest, current_user: User) -> list[WebSocketTestCaseExecution]:
        self._require(current_user, project_id, ProjectPermission.EXECUTE_TEST.value)
        return [self._execute_saved(project_id, case_id, payload.environment_id, current_user) for case_id in payload.websocket_test_case_ids]

    def _execute_saved(self, project_id: int, test_case_id: int, environment_id: int | None, current_user: User):
        case = self._get_case(project_id, test_case_id)
        payload = self._saved_case_payload(case, environment_id=environment_id or case.environment_id)
        return self._execute(project_id, test_case_id, payload, current_user)

    def enqueue_saved_case(
        self,
        *,
        project_id: int,
        test_case_id: int,
        environment_id: int | None,
        current_user: User,
    ) -> WebSocketTestCaseExecution:
        self._require(current_user, project_id, ProjectPermission.EXECUTE_TEST.value)
        case = self._get_case(project_id, test_case_id)
        payload = self._saved_case_payload(case, environment_id=environment_id or case.environment_id)
        environment, variables = self._load_environment_context(project_id, payload.environment_id)
        snapshot = self._build_session_snapshot(payload, environment.base_url if environment else None, variables)
        execution = WebSocketTestCaseExecution(
            project_id=project_id,
            websocket_test_case_id=test_case_id,
            environment_id=payload.environment_id,
            scenario_run_id=None,
            executed_by_id=current_user.id,
            status="queued",
            session_snapshot=mask_sensitive(snapshot),
            response_snapshot=None,
            assertion_results=None,
            attempt_history=[],
            error_message=None,
            duration_ms=None,
        )
        case.last_execution_status = "running"
        case.last_executed_at = datetime.utcnow()
        self.repository.db.add(execution)
        self.repository.db.commit()
        self.repository.db.refresh(execution)
        return execution

    @staticmethod
    def execute_queued_execution(execution_id: int) -> None:
        with SessionLocal() as db:
            execution = db.get(WebSocketTestCaseExecution, execution_id)
            if execution is None or execution.status not in {"queued", "running"}:
                return
            current_user = db.get(User, execution.executed_by_id)
            if current_user is None or not current_user.is_active:
                execution.status = "failed"
                execution.error_message = "执行用户不存在或已停用"
                execution.duration_ms = 0
                db.commit()
                return
            if execution.websocket_test_case_id is None:
                execution.status = "failed"
                execution.error_message = "异步执行暂不支持未保存 WebSocket 测试用例"
                execution.duration_ms = 0
                db.commit()
                return
            try:
                service = WebSocketTestCaseService(db)
                case = service._get_case(execution.project_id, execution.websocket_test_case_id)
                payload = service._saved_case_payload(case, environment_id=execution.environment_id)
                execution.status = "running"
                db.commit()
                service._execute(
                    execution.project_id,
                    execution.websocket_test_case_id,
                    payload,
                    current_user,
                    queued_execution_id=execution.id,
                )
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                failed = db.get(WebSocketTestCaseExecution, execution_id)
                if failed is not None and failed.status in {"queued", "running"}:
                    failed.status = "failed"
                    failed.error_message = str(exc)
                    failed.duration_ms = 0
                    db.commit()

    def _execute(
        self,
        project_id: int,
        test_case_id: int | None,
        payload: WebSocketTestCaseConfig,
        current_user: User,
        scenario_run_id: int | None = None,
        timeout_seconds: float | None = None,
        queued_execution_id: int | None = None,
    ):
        environment, variables = self._load_environment_context(project_id, payload.environment_id)
        snapshot = self._build_session_snapshot(payload, environment.base_url if environment else None, variables)
        started_at = time.perf_counter()
        response_snapshot = None
        assertion_results = None
        attempt_history: list[dict[str, Any]] = []
        error_message = None
        status_value = "passed"
        policy = getattr(payload, "retry_policy", None) or RetryPolicyConfig()
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
            try:
                remaining = (
                    execution_deadline - time.monotonic()
                    if execution_deadline is not None
                    else timeout_seconds
                )
                if remaining is not None and remaining <= 0:
                    raise websocket.WebSocketTimeoutException(
                        "Scenario execution deadline exceeded"
                    )
                response_snapshot = self._run_session(
                    snapshot, timeout_seconds=remaining
                )
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
                        and failed_assertions_are_retryable(assertion_results)
                    ):
                        retry_reason = "polling_assertion_failed"
                else:
                    self._run_extractors(
                        payload.extractors, response_snapshot, variables
                    )
                    status_value = "passed"
                    error_message = None
            except (websocket.WebSocketTimeoutException, TimeoutError) as exc:
                status_value = "error"
                error_message = str(exc)
                if policy.enabled and policy.retry_timeouts:
                    retry_reason = "timeout"
            except (websocket.WebSocketException, OSError) as exc:
                status_value = "error"
                error_message = str(exc)
                if policy.enabled and policy.retry_network_errors:
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
                wait_seconds = retry_delay_seconds(policy, attempt=attempt)
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
        if queued_execution_id is not None:
            execution = self.repository.db.get(WebSocketTestCaseExecution, queued_execution_id)
            if execution is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="WebSocket 测试用例执行记录不存在",
                )
            execution.status = status_value
            execution.session_snapshot = mask_sensitive(snapshot)
            execution.response_snapshot = response_snapshot
            execution.assertion_results = assertion_results
            execution.attempt_history = attempt_history
            execution.error_message = error_message
            execution.duration_ms = duration_ms
            if test_case_id is not None:
                case = self.repository.db.get(WebSocketTestCase, test_case_id)
                if case is not None and case.project_id == project_id:
                    case.last_execution_status = status_value
                    case.last_executed_at = datetime.utcnow()
            self.repository.db.commit()
            self.repository.db.refresh(execution)
            return execution

        return self.repository.create_execution(
            project_id=project_id, websocket_test_case_id=test_case_id, environment_id=payload.environment_id,
            scenario_run_id=scenario_run_id, executed_by_id=current_user.id, status=status_value,
            session_snapshot=mask_sensitive(snapshot),
            response_snapshot=response_snapshot, assertion_results=assertion_results,
            attempt_history=attempt_history, error_message=error_message,
            duration_ms=duration_ms,
        )

    @staticmethod
    def _saved_case_payload(
        case: WebSocketTestCase,
        *,
        environment_id: int | None,
    ) -> WebSocketTestCaseConfig:
        return WebSocketTestCaseConfig(
            environment_id=environment_id,
            path=case.path,
            headers=case.headers,
            subprotocols=case.subprotocols or [],
            messages=case.messages or [],
            receive_count=case.receive_count,
            connect_timeout_ms=case.connect_timeout_ms,
            receive_timeout_ms=case.receive_timeout_ms,
            assertions=case.assertions or [],
            extractors=case.extractors or [],
            retry_policy=getattr(case, "retry_policy", None) or {},
        )

    def _run_session(self, snapshot: dict[str, Any], *, timeout_seconds: float | None = None) -> dict[str, Any]:
        headers = [f"{key}: {value}" for key, value in snapshot["headers"].items()]
        connection = websocket.create_connection(
            snapshot["url"], header=headers, subprotocols=snapshot["subprotocols"] or None,
            timeout=max(min(snapshot["connect_timeout_ms"] / 1000, timeout_seconds or float("inf")), 0.1),
        )
        sent: list[dict[str, Any]] = []
        received: list[dict[str, Any]] = []
        try:
            connection.settimeout(
                max(min(snapshot["receive_timeout_ms"] / 1000, timeout_seconds or float("inf")), 0.1)
            )
            for message in snapshot["messages"]:
                data = json.dumps(message["data"], ensure_ascii=False) if message["type"] == "json" else str(message["data"])
                connection.send(data)
                sent.append({"type": message["type"], "data": message["data"], "raw": data})
            for _ in range(snapshot["receive_count"]):
                raw = connection.recv()
                if isinstance(raw, bytes):
                    received.append({"type": "binary", "data": raw.hex(), "json": None})
                else:
                    received.append({"type": "text", "data": raw, "json": self._safe_json(raw)})
        finally:
            connection.close()
        return {"sent_messages": sent, "received_messages": received, "negotiated_subprotocol": connection.subprotocol}

    def _build_session_snapshot(self, payload: WebSocketTestCaseConfig, base_url: str | None, variables: dict[str, str]) -> dict[str, Any]:
        path = self._render(payload.path, variables)
        if path.startswith(("ws://", "wss://")):
            url = path
        elif base_url:
            parts = urlsplit(base_url)
            scheme = "wss" if parts.scheme == "https" else "ws"
            base_path = parts.path.rstrip("/") + "/" + path.lstrip("/")
            url = urlunsplit((scheme, parts.netloc, base_path, "", ""))
        else:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="path must be a full ws/wss URL without an environment")
        return {
            "url": url, "headers": self._render(payload.headers or {}, variables),
            "subprotocols": self._render(payload.subprotocols, variables),
            "messages": self._render([item.model_dump() for item in payload.messages], variables),
            "receive_count": payload.receive_count, "connect_timeout_ms": payload.connect_timeout_ms,
            "receive_timeout_ms": payload.receive_timeout_ms,
        }

    def _run_assertions(self, assertions, response_snapshot):
        messages = response_snapshot["received_messages"]
        results = []
        for assertion in assertions:
            item = assertion if isinstance(assertion, dict) else assertion.model_dump()
            actual = None
            if item["type"] == "message_count":
                actual = len(messages)
            elif item["message_index"] < len(messages):
                message = messages[item["message_index"]]
                actual = message["data"] if item["type"] == "message_contains" else self._get_json_path(message["json"], item.get("path"))
            passed = (
                str(item["expected"]) in str(actual)
                if item["type"] == "message_contains"
                else json_values_equal(actual, item["expected"])
            )
            results.append({"assertion": item, "actual": actual, "passed": passed})
        return results

    def _run_extractors(self, extractors, response_snapshot, variables):
        messages = response_snapshot["received_messages"]
        for extractor in extractors:
            item = extractor if isinstance(extractor, dict) else extractor.model_dump()
            if item["message_index"] < len(messages):
                value = self._get_json_path(messages[item["message_index"]]["json"], item["path"])
                if value is not None:
                    variables[item["name"]] = str(value)

    def _resolve_environment_ids(self, project_id: int, payload: WebSocketTestCaseConfig):
        ids = list(dict.fromkeys(payload.environment_ids or []))
        if payload.environment_id is not None and payload.environment_id not in ids:
            ids.insert(0, payload.environment_id)
        default_id = payload.environment_id if payload.environment_id is not None else (ids[0] if ids else None)
        for environment_id in ids:
            if self.repository.get_environment(project_id=project_id, environment_id=environment_id) is None:
                raise HTTPException(status_code=404, detail="environment not found")
        return default_id, ids

    def _load_environment_context(self, project_id: int, environment_id: int | None):
        if environment_id is None:
            return None, {}
        if environment_id not in self._environment_context_cache:
            environment = self.repository.get_environment(project_id=project_id, environment_id=environment_id)
            if environment is None:
                raise HTTPException(status_code=404, detail="environment not found")
            self._environment_context_cache[environment_id] = (environment, self.repository.get_environment_variables(environment_id=environment_id))
        return self._environment_context_cache[environment_id]

    def _get_case(self, project_id: int, test_case_id: int):
        case = self.repository.get_by_id(project_id=project_id, test_case_id=test_case_id)
        if case is None:
            raise HTTPException(status_code=404, detail="WebSocket test case not found")
        return case

    def _apply_payload(self, test_case, payload, environment_id):
        test_case.environment_id = environment_id
        for field in ("name", "description", "path", "headers", "subprotocols", "receive_count", "connect_timeout_ms", "receive_timeout_ms"):
            setattr(test_case, field, getattr(payload, field))
        test_case.messages = [item.model_dump() for item in payload.messages]
        test_case.assertions = [item.model_dump() for item in payload.assertions]
        test_case.extractors = [item.model_dump() for item in payload.extractors]
        test_case.retry_policy = payload.retry_policy.model_dump()

    def _require(self, user, project_id, permission):
        self.permission_service.require_project_permission(user, project_id, permission)

    def _render(self, value, variables):
        return render_variables(value, variables)

    def _safe_json(self, value):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return None

    def _get_json_path(self, data, path):
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
