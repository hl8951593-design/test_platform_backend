import json
import re
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai_skills import get_ai_skill
from app.ai_skills.base import AISkillRunner
from app.core.permissions import ProjectPermission
from app.models.project import ProjectEnvironment
from app.models.test_case import TestCase, TestCaseExecution
from app.models.user import User
from app.models.websocket_test_case import WebSocketTestCase, WebSocketTestCaseExecution
from app.schemas.ai import (
    AIGeneratedScenarioResponse,
    AIScenarioComposeRequest,
    AIScenarioValidationAttemptRead,
)
from app.services.ai_service import AIService
from app.services.ai_run_event_service import AIRunTrace
from app.services.permission_service import PermissionService
from app.services.scenario_service import ScenarioService
from app.services.test_case_service import TestCaseService
from app.services.websocket_test_case_service import WebSocketTestCaseService


EXTERNAL_VALIDATION_BLOCKER_CODES = {401, 403, 90001, 2001}
EXTERNAL_VALIDATION_BLOCKER_TEXT_MARKERS = (
    "未授权",
    "无权限",
    "权限",
    "unauthorized",
    "forbidden",
    "permission",
    "auth",
)


class AIScenarioComposerService:
    skill_id = "scenario-composer"

    def __init__(self, db: Session):
        self.db = db
        self.permission_service = PermissionService(db)
        self.ai_service = AIService()

    def compose(
        self,
        *,
        project_id: int,
        environment_id: int,
        payload: AIScenarioComposeRequest,
        current_user: User,
        trace: AIRunTrace | None = None,
    ) -> AIGeneratedScenarioResponse:
        if trace:
            trace.step_started("校验场景组合权限")
        self.permission_service.require_project_permission(
            current_user,
            project_id,
            ProjectPermission.MANAGE_SCENARIO.value,
        )
        if payload.execute_candidates or payload.self_validate:
            self.permission_service.require_project_permission(
                current_user,
                project_id,
                ProjectPermission.EXECUTE_TEST.value,
            )
        if trace:
            trace.step_completed("校验场景组合权限")
            trace.tool_started("load_environment", environment_id=environment_id)
        environment = self.db.scalar(
            select(ProjectEnvironment).where(
                ProjectEnvironment.id == environment_id,
                ProjectEnvironment.project_id == project_id,
                ProjectEnvironment.is_deleted.is_(False),
            )
        )
        if environment is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="环境不存在")
        if trace:
            trace.tool_completed("load_environment", output_summary=f"环境: {environment.name}")

        if trace:
            trace.tool_started(
                "load_candidate_cases",
                http_test_case_ids=payload.http_test_case_ids,
                websocket_test_case_ids=payload.websocket_test_case_ids,
                include_latest_execution=payload.include_latest_execution,
                execute_candidates=payload.execute_candidates,
            )
        candidates = self._candidate_cases(
            project_id=project_id,
            environment_id=environment_id,
            http_ids=payload.http_test_case_ids,
            websocket_ids=payload.websocket_test_case_ids,
            include_latest_execution=payload.include_latest_execution,
            execute_candidates=payload.execute_candidates,
            current_user=current_user,
            trace=trace,
        )
        if not candidates:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="至少需要选择一个候选测试用例")
        if trace:
            trace.tool_completed(
                "load_candidate_cases",
                output_summary=f"候选用例 {len(candidates)} 个",
            )

        candidate_index = {
            (item["kind"], item["reference_id"]): item
            for item in candidates
        }
        context = {
            "mode": "compose",
            "project_id": project_id,
            "environment_id": environment_id,
            "environment": {
                "id": environment.id,
                "name": environment.name,
                "base_url": environment.base_url,
                "description": environment.description,
            },
            "payload": payload,
            "candidate_cases": candidates,
            "candidate_index": candidate_index,
        }
        skill = get_ai_skill(self.skill_id)
        runner = AISkillRunner(self.ai_service)
        result = runner.run_traced(skill, context, trace) if trace else runner.run(skill, context)
        self._ensure_environment_name(result, environment.name)
        if not payload.self_validate:
            return result

        validation_attempts: list[AIScenarioValidationAttemptRead] = []
        for attempt in range(1, payload.max_validation_attempts + 1):
            if trace:
                trace.tool_started(
                    "validate_unsaved_scenario",
                    attempt=attempt,
                    max_attempts=payload.max_validation_attempts,
                )
            validation = self._validate_generated_scenario(
                project_id=project_id,
                result=result,
                current_user=current_user,
                attempt=attempt,
            )
            validation_attempts.append(validation)
            result.validation_attempts = validation_attempts
            result.self_validated = validation.status == "passed"
            if trace:
                trace.tool_completed(
                    "validate_unsaved_scenario",
                    attempt=attempt,
                    status=validation.status,
                    output_summary=f"未保存场景验证: {validation.status}",
                )
            if validation.status == "passed":
                return result
            external_blockers = self._external_validation_blockers(validation)
            if external_blockers:
                result.warnings.append(
                    "external_validation_blocker: 场景自验证失败来自鉴权、权限或外部账号配置，"
                    "已停止自动重生成；请修复环境 Token/账号授权后重新验证。"
                )
                result.warnings.append(
                    "external_validation_blocker_details: "
                    + json.dumps(external_blockers[:5], ensure_ascii=False, default=str, sort_keys=True)
                )
                return result
            result.warnings.append(
                f"第 {attempt} 次场景自验证未通过，状态: {validation.status}"
            )
            if attempt >= payload.max_validation_attempts:
                return result

            repair_context = {
                **context,
                "previous_scenario": result.scenario.model_dump(mode="json"),
                "validation_feedback": validation.model_dump(mode="json"),
            }
            if trace:
                trace.step_started(f"根据第 {attempt} 次验证结果修复场景")
            result = (
                runner.run_traced(skill, repair_context, trace)
                if trace
                else runner.run(skill, repair_context)
            )
            self._ensure_environment_name(result, environment.name)
            result.validation_attempts = validation_attempts
            if trace:
                trace.step_completed(f"根据第 {attempt} 次验证结果修复场景")
        return result

    def _external_validation_blockers(self, validation: AIScenarioValidationAttemptRead) -> list[dict[str, Any]]:
        blockers: list[dict[str, Any]] = []
        for issue in validation.issues:
            if not isinstance(issue, dict) or not self._is_external_validation_blocker(issue):
                continue
            response = issue.get("response_snapshot") if isinstance(issue.get("response_snapshot"), dict) else {}
            response_json = response.get("json") if isinstance(response.get("json"), dict) else {}
            blockers.append({
                "type": "auth_or_permission",
                "step_id": issue.get("step_id"),
                "name": issue.get("name"),
                "status_code": response.get("status_code"),
                "business_code": response_json.get("code"),
                "message": response_json.get("msg") or issue.get("message"),
            })
        return blockers

    def _is_external_validation_blocker(self, issue: dict[str, Any]) -> bool:
        response = issue.get("response_snapshot") if isinstance(issue.get("response_snapshot"), dict) else {}
        response_json = response.get("json") if isinstance(response.get("json"), dict) else {}
        code = response_json.get("code", response.get("status_code"))
        if isinstance(code, int) and code in EXTERNAL_VALIDATION_BLOCKER_CODES:
            return True
        if isinstance(code, str) and code.isdigit() and int(code) in EXTERNAL_VALIDATION_BLOCKER_CODES:
            return True
        haystack = json.dumps(issue, ensure_ascii=False, default=str).lower()
        return any(marker.lower() in haystack for marker in EXTERNAL_VALIDATION_BLOCKER_TEXT_MARKERS)

    def _ensure_environment_name(self, result: AIGeneratedScenarioResponse, environment_name: str | None) -> None:
        if result.environment_name is None and environment_name is not None:
            result.environment_name = environment_name

    def _validate_generated_scenario(
        self,
        *,
        project_id: int,
        result: AIGeneratedScenarioResponse,
        current_user: User,
        attempt: int,
    ) -> AIScenarioValidationAttemptRead:
        run = ScenarioService(self.db).validate_unsaved_scenario(
            project_id=project_id,
            payload=result.scenario,
            current_user=current_user,
        )
        return AIScenarioValidationAttemptRead(
            attempt=attempt,
            status=run.status,
            run_id=run.id,
            duration_ms=run.duration_ms,
            summary=self._validation_summary(run.step_results or []),
            issues=self._validation_issues(run.step_results or []),
        )

    def _validation_summary(self, step_results: list[dict[str, Any]]) -> dict[str, Any]:
        total = len(step_results)
        return {
            "total_steps": total,
            "passed": sum(1 for item in step_results if item.get("status") == "passed"),
            "failed": sum(1 for item in step_results if item.get("status") == "failed"),
            "timeout": sum(1 for item in step_results if item.get("status") == "timeout"),
            "skipped": sum(1 for item in step_results if item.get("status") == "skipped"),
        }

    def _validation_issues(self, step_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        for item in step_results:
            step_issue: dict[str, Any] = {
                "step_id": item.get("step_id"),
                "step_index": item.get("step_index"),
                "kind": item.get("kind"),
                "name": item.get("name"),
                "status": item.get("status"),
            }
            details: list[dict[str, Any]] = []
            if item.get("status") in {"failed", "timeout"}:
                details.append({
                    "type": "step_error",
                    "message": item.get("error_message") or item.get("message"),
                })
            for extraction in item.get("extracted_variables") or []:
                if isinstance(extraction, dict) and extraction.get("error"):
                    details.append({
                        "type": "extraction_error",
                        "name": extraction.get("name"),
                        "path": extraction.get("path"),
                        "message": extraction.get("error"),
                    })
            for assertion in item.get("assertion_results") or []:
                if isinstance(assertion, dict) and assertion.get("passed") is False:
                    details.append({
                        "type": "assertion_failed",
                        "assertion": assertion.get("assertion"),
                        "actual": assertion.get("actual"),
                    })
            if details:
                response_snapshot = item.get("response_snapshot")
                if isinstance(response_snapshot, dict):
                    step_issue["response_snapshot"] = {
                        key: response_snapshot.get(key)
                        for key in ("status_code", "json", "received_messages")
                        if key in response_snapshot
                    }
                request_snapshot = item.get("request_snapshot")
                if isinstance(request_snapshot, dict):
                    step_issue["request_snapshot"] = {
                        key: request_snapshot.get(key)
                        for key in ("method", "url", "path", "headers", "query_params", "body", "messages")
                        if key in request_snapshot
                    }
                step_issue["details"] = details
                issues.append(step_issue)
        return issues[:20]

    def _candidate_cases(
        self,
        *,
        project_id: int,
        environment_id: int,
        http_ids: list[int],
        websocket_ids: list[int],
        include_latest_execution: bool,
        execute_candidates: bool,
        current_user: User,
        trace: AIRunTrace | None,
    ) -> list[dict[str, Any]]:
        cases: list[dict[str, Any]] = []
        if http_ids:
            rows = list(self.db.scalars(
                select(TestCase).where(
                    TestCase.project_id == project_id,
                    TestCase.id.in_(list(dict.fromkeys(http_ids))),
                )
            ).all())
            by_id = {item.id: item for item in rows}
            missing = [item_id for item_id in dict.fromkeys(http_ids) if item_id not in by_id]
            if missing:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"部分 HTTP 测试用例不存在: {', '.join(str(item) for item in missing)}",
                )
            for item_id in dict.fromkeys(http_ids):
                item = by_id[item_id]
                cases.append(
                    self._http_case_data(
                        item,
                        execution_sample=self._http_execution_sample(
                            project_id=project_id,
                            test_case_id=item.id,
                            environment_id=environment_id,
                            include_latest_execution=include_latest_execution,
                            execute_candidate=execute_candidates,
                            current_user=current_user,
                            trace=trace,
                        ),
                    )
                )

        if websocket_ids:
            rows = list(self.db.scalars(
                select(WebSocketTestCase).where(
                    WebSocketTestCase.project_id == project_id,
                    WebSocketTestCase.id.in_(list(dict.fromkeys(websocket_ids))),
                )
            ).all())
            by_id = {item.id: item for item in rows}
            missing = [item_id for item_id in dict.fromkeys(websocket_ids) if item_id not in by_id]
            if missing:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"部分 WebSocket 测试用例不存在: {', '.join(str(item) for item in missing)}",
                )
            for item_id in dict.fromkeys(websocket_ids):
                item = by_id[item_id]
                cases.append(
                    self._websocket_case_data(
                        item,
                        execution_sample=self._websocket_execution_sample(
                            project_id=project_id,
                            test_case_id=item.id,
                            environment_id=environment_id,
                            include_latest_execution=include_latest_execution,
                            execute_candidate=execute_candidates,
                            current_user=current_user,
                            trace=trace,
                        ),
                    )
                )
        return cases

    def _http_case_data(self, item: TestCase, *, execution_sample: dict[str, Any] | None) -> dict[str, Any]:
        data = {
            "kind": "api_case",
            "reference_id": item.id,
            "name": item.name,
            "description": item.description,
            "method": item.method,
            "path": item.path,
            "headers": item.headers or {},
            "query_params": item.query_params or {},
            "body_type": item.body_type,
            "body": item.body,
            "assertions": item.assertions or [],
            "extractors": item.extractors or [],
            "environment_id": item.environment_id,
            "environment_ids": item.environment_ids,
            "execution_sample": execution_sample,
        }
        data["composition_hints"] = self._composition_hints(data)
        return data

    def _websocket_case_data(self, item: WebSocketTestCase, *, execution_sample: dict[str, Any] | None) -> dict[str, Any]:
        data = {
            "kind": "websocket_case",
            "reference_id": item.id,
            "name": item.name,
            "description": item.description,
            "method": "WS",
            "path": item.path,
            "headers": item.headers or {},
            "subprotocols": item.subprotocols or [],
            "messages": item.messages or [],
            "receive_count": item.receive_count,
            "assertions": item.assertions or [],
            "extractors": item.extractors or [],
            "environment_id": item.environment_id,
            "environment_ids": item.environment_ids,
            "execution_sample": execution_sample,
        }
        data["composition_hints"] = self._composition_hints(data)
        return data

    def _composition_hints(self, case_data: dict[str, Any]) -> dict[str, Any]:
        response_json = self._response_json(case_data.get("execution_sample"))
        response_fields = self._json_leaf_paths(response_json)
        suggested_extractors = self._suggest_extractors(
            response_fields=response_fields,
            existing_extractors=case_data.get("extractors") or [],
        )
        baseline_assertions = self._baseline_assertions(case_data, response_json)
        request_fields = self._request_field_paths(case_data)
        request_template_variables = self._template_variables({
            "path": case_data.get("path"),
            "headers": case_data.get("headers"),
            "query_params": case_data.get("query_params"),
            "body": case_data.get("body"),
            "messages": case_data.get("messages"),
            "subprotocols": case_data.get("subprotocols"),
        })
        return {
            "role_candidates": self._role_candidates(case_data),
            "request_fields": request_fields[:120],
            "request_template_variables": request_template_variables,
            "response_fields": [item["name"] for item in response_fields[:120]],
            "suggested_extractors": suggested_extractors[:20],
            "baseline_assertions": baseline_assertions[:10],
            "dependency_inputs": request_template_variables,
            "dependency_outputs": [item["name"] for item in suggested_extractors[:20]],
        }

    def _role_candidates(self, case_data: dict[str, Any]) -> list[str]:
        text = " ".join(
            str(case_data.get(key) or "")
            for key in ("name", "description", "path", "method")
        ).lower()
        method = str(case_data.get("method") or "").upper()
        roles: list[str] = []
        if any(marker in text for marker in ("login", "auth", "token", "登录", "鉴权", "授权")):
            roles.extend(["precondition", "authentication", "data_provider"])
        if method == "GET" or any(marker in text for marker in ("list", "page", "query", "search", "get", "查询", "列表", "获取")):
            roles.extend(["data_provider", "validation"])
        if method in {"POST", "PUT", "PATCH", "DELETE"} or any(
            marker in text
            for marker in ("save", "create", "update", "delete", "cancel", "follow", "新增", "创建", "更新", "删除", "取消", "关注")
        ):
            roles.append("mutation")
        if any(marker in text for marker in ("delete", "cancel", "cleanup", "清理", "删除", "取消")):
            roles.append("cleanup_candidate")
        return list(dict.fromkeys(roles or ["main_flow"]))

    def _request_field_paths(self, case_data: dict[str, Any]) -> list[str]:
        fields: list[str] = []
        for root in ("headers", "query_params", "body", "messages", "subprotocols"):
            for path in self._value_leaf_paths(case_data.get(root)):
                fields.append(f"{root}.{path}" if path else root)
        if case_data.get("path"):
            fields.append("path")
        return fields

    def _value_leaf_paths(self, value: Any, prefix: str = "") -> list[str]:
        if isinstance(value, dict):
            paths: list[str] = []
            for key, item in value.items():
                child = f"{prefix}.{key}" if prefix else str(key)
                paths.extend(self._value_leaf_paths(item, child))
            return paths
        if isinstance(value, list):
            paths: list[str] = []
            for index, item in enumerate(value):
                child = f"{prefix}.{index}" if prefix else str(index)
                paths.extend(self._value_leaf_paths(item, child))
            return paths
        return [prefix] if prefix else []

    def _template_variables(self, value: Any) -> list[str]:
        found: list[str] = []

        def walk(item: Any) -> None:
            if isinstance(item, str):
                for match in re.finditer(r"\{\{\s*([^{}]+?)\s*\}\}", item):
                    found.append(match.group(1).strip())
            elif isinstance(item, dict):
                for child in item.values():
                    walk(child)
            elif isinstance(item, list):
                for child in item:
                    walk(child)

        walk(value)
        return list(dict.fromkeys(found))

    def _response_json(self, execution_sample: Any) -> Any:
        if not isinstance(execution_sample, dict):
            return None
        response = execution_sample.get("response_snapshot")
        if not isinstance(response, dict):
            return None
        if "json" in response:
            return response.get("json")
        messages = response.get("received_messages")
        if isinstance(messages, list) and messages:
            first = messages[0]
            if isinstance(first, dict):
                return first.get("json")
        return None

    def _json_leaf_paths(self, value: Any, prefix: str = "") -> list[dict[str, str]]:
        if isinstance(value, dict):
            fields: list[dict[str, str]] = []
            for key, item in value.items():
                child = f"{prefix}.{key}" if prefix else str(key)
                fields.extend(self._json_leaf_paths(item, child))
            return fields
        if isinstance(value, list):
            fields: list[dict[str, str]] = []
            for index, item in enumerate(value[:3]):
                child = f"{prefix}.{index}" if prefix else str(index)
                fields.extend(self._json_leaf_paths(item, child))
            return fields
        if prefix:
            return [{"name": prefix.rsplit(".", 1)[-1], "path": prefix}]
        return []

    def _suggest_extractors(
        self,
        *,
        response_fields: list[dict[str, str]],
        existing_extractors: list[Any],
    ) -> list[dict[str, str]]:
        existing_names = {
            str(item.get("name"))
            for item in existing_extractors
            if isinstance(item, dict) and item.get("name")
        }
        important_names = {
            "id",
            "token",
            "accessToken",
            "access_token",
            "companyId",
            "companyName",
            "entId",
            "ent_id",
        }
        suggestions: list[dict[str, str]] = []
        for field in response_fields:
            name = field["name"]
            normalized = re.sub(r"[^a-z0-9]", "", name.lower())
            is_important = (
                name in important_names
                or normalized.endswith("id")
                or normalized.endswith("token")
                or normalized.endswith("name")
            )
            if not is_important or name in existing_names:
                continue
            suggestions.append({"name": name, "path": field["path"]})
        return suggestions

    def _baseline_assertions(self, case_data: dict[str, Any], response_json: Any) -> list[dict[str, Any]]:
        assertions: list[dict[str, Any]] = []
        execution_sample = case_data.get("execution_sample")
        response = execution_sample.get("response_snapshot") if isinstance(execution_sample, dict) else None
        if isinstance(response, dict) and response.get("status_code") is not None:
            assertions.append({"type": "status_code", "expected": response.get("status_code")})
        if case_data.get("kind") == "websocket_case":
            messages = response.get("received_messages") if isinstance(response, dict) else None
            if isinstance(messages, list):
                assertions.append({"type": "message_count", "expected": len(messages)})
            return assertions
        if isinstance(response_json, dict):
            for key in ("code", "success", "status"):
                value = response_json.get(key)
                if value is not None and isinstance(value, (str, int, float, bool)):
                    assertions.append({"type": "json_equals", "path": key, "expected": value})
        return assertions

    def _http_execution_sample(
        self,
        *,
        project_id: int,
        test_case_id: int,
        environment_id: int,
        include_latest_execution: bool,
        execute_candidate: bool,
        current_user: User,
        trace: AIRunTrace | None,
    ) -> dict[str, Any] | None:
        if execute_candidate:
            if trace:
                trace.tool_started("execute_candidate_http_case", test_case_id=test_case_id)
            execution = TestCaseService(self.db).execute_saved_case(
                project_id=project_id,
                test_case_id=test_case_id,
                environment_id=environment_id,
                current_user=current_user,
            )
            if trace:
                trace.tool_completed(
                    "execute_candidate_http_case",
                    test_case_id=test_case_id,
                    status=execution.status,
                )
            return self._http_execution_data(execution, source="debug_execution")
        if include_latest_execution:
            if trace:
                trace.tool_started("load_latest_http_execution", test_case_id=test_case_id)
            execution = self.db.scalar(
                select(TestCaseExecution)
                .where(
                    TestCaseExecution.project_id == project_id,
                    TestCaseExecution.test_case_id == test_case_id,
                )
                .order_by(TestCaseExecution.created_at.desc(), TestCaseExecution.id.desc())
                .limit(1)
            )
            if execution is not None:
                if trace:
                    trace.tool_completed(
                        "load_latest_http_execution",
                        test_case_id=test_case_id,
                        status=execution.status,
                    )
                return self._http_execution_data(execution, source="latest_execution")
            if trace:
                trace.tool_completed("load_latest_http_execution", test_case_id=test_case_id, output_summary="无历史执行样本")
        return None

    def _websocket_execution_sample(
        self,
        *,
        project_id: int,
        test_case_id: int,
        environment_id: int,
        include_latest_execution: bool,
        execute_candidate: bool,
        current_user: User,
        trace: AIRunTrace | None,
    ) -> dict[str, Any] | None:
        if execute_candidate:
            if trace:
                trace.tool_started("execute_candidate_websocket_case", test_case_id=test_case_id)
            execution = WebSocketTestCaseService(self.db).execute_saved_case(
                project_id=project_id,
                test_case_id=test_case_id,
                environment_id=environment_id,
                current_user=current_user,
            )
            if trace:
                trace.tool_completed(
                    "execute_candidate_websocket_case",
                    test_case_id=test_case_id,
                    status=execution.status,
                )
            return self._websocket_execution_data(execution, source="debug_execution")
        if include_latest_execution:
            if trace:
                trace.tool_started("load_latest_websocket_execution", test_case_id=test_case_id)
            execution = self.db.scalar(
                select(WebSocketTestCaseExecution)
                .where(
                    WebSocketTestCaseExecution.project_id == project_id,
                    WebSocketTestCaseExecution.websocket_test_case_id == test_case_id,
                )
                .order_by(WebSocketTestCaseExecution.created_at.desc(), WebSocketTestCaseExecution.id.desc())
                .limit(1)
            )
            if execution is not None:
                if trace:
                    trace.tool_completed(
                        "load_latest_websocket_execution",
                        test_case_id=test_case_id,
                        status=execution.status,
                    )
                return self._websocket_execution_data(execution, source="latest_execution")
            if trace:
                trace.tool_completed("load_latest_websocket_execution", test_case_id=test_case_id, output_summary="无历史执行样本")
        return None

    def _http_execution_data(self, execution: TestCaseExecution, *, source: str) -> dict[str, Any]:
        return {
            "source": source,
            "status": execution.status,
            "request_snapshot": execution.request_snapshot,
            "response_snapshot": execution.response_snapshot,
            "assertion_results": execution.assertion_results or [],
            "error_message": execution.error_message,
            "duration_ms": execution.duration_ms,
        }

    def _websocket_execution_data(self, execution: WebSocketTestCaseExecution, *, source: str) -> dict[str, Any]:
        return {
            "source": source,
            "status": execution.status,
            "session_snapshot": execution.session_snapshot,
            "response_snapshot": execution.response_snapshot,
            "assertion_results": execution.assertion_results or [],
            "error_message": execution.error_message,
            "duration_ms": execution.duration_ms,
        }
