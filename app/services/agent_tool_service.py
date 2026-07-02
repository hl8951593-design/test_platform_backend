from __future__ import annotations

import copy
import logging
from dataclasses import asdict, dataclass
from typing import Any, Callable

from fastapi import HTTPException, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.permissions import ProjectPermission
from app.core.response import normalize_response_data
from app.core.sensitive_data import mask_sensitive, request_fingerprint
from app.models.project import ProjectEnvironment
from app.models.test_case import TestCase
from app.models.user import User
from app.models.websocket_test_case import WebSocketTestCase
from app.schemas.ai import AIScenarioComposeRequest, AISkillRunRequest
from app.schemas.scenario import ScenarioRunRead
from app.schemas.test_case import (
    AssertionConfig,
    TestCaseCreateRequest,
    TestCaseExecutionRead,
    TestCaseRead,
    TestCaseUpdateRequest,
)
from app.schemas.websocket_test_case import (
    WebSocketAssertionConfig,
    WebSocketTestCaseCreateRequest,
    WebSocketTestCaseExecutionRead,
    WebSocketTestCaseRead,
    WebSocketTestCaseUpdateRequest,
)
from app.services.agent_loop_service import EvidenceRefResolver
from app.services.ai_skill_service import AISkillService
from app.services.permission_service import PermissionService
from app.services.scenario_service import ScenarioService
from app.services.test_case_service import TestCaseService
from app.services.test_report_service import TestReportService
from app.services.websocket_test_case_service import WebSocketTestCaseService


SAFE_SIDE_EFFECT_CLASSES = {"read_only", "deterministic_compute", "draft_only", "execution_record"}
AGENT_TOOL_SPEC_ITEM_ID_PREFIX = "agent-tool-spec"
AI_DRAFT_OPERATIONS = {
    "http-test-case": {"generate", "expand"},
    "websocket-test-case": {"generate", "expand"},
    "scenario-composer": {"compose"},
}

logger = logging.getLogger(__name__)


def _tool_spec_item_id(name: str, version: str) -> str:
    return f"{AGENT_TOOL_SPEC_ITEM_ID_PREFIX}://{name}/{version}"


@dataclass(frozen=True)
class BackendContractSpec:
    backend_name: str
    backend_operation: str
    backend_contract_version: str
    effect_capability: str
    request_schema_hash: str
    output_schema_hash: str
    reconcile_contract_version: str = "reconcile-v1"
    result_adapter_version: str = "v1"
    compatibility_status: str = "active"
    owner_team: str = "test-platform"


@dataclass(frozen=True)
class ToolSpec:
    name: str
    version: str
    summary: str
    side_effect_class: str
    replay_policy: str
    required_permissions: tuple[str, ...]
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    backend_contract: BackendContractSpec | None = None
    backend_handler: str | None = None
    required_successful_tool_before: str | None = None
    missing_prerequisite_error_code: str | None = None
    missing_prerequisite_next_action: str | None = None
    tool_result_repair_guidance: str | None = None

    @property
    def schema_hash(self) -> str:
        return request_fingerprint({
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
        })

    @property
    def manifest_hash(self) -> str:
        return request_fingerprint(self._manifest_payload())

    def to_json(self) -> dict[str, Any]:
        payload = self._manifest_payload()
        return {
            **payload,
            "schema_hash": self.schema_hash,
            "manifest_hash": self.manifest_hash,
        }

    def _manifest_payload(self) -> dict[str, Any]:
        return {
            "item_id": _tool_spec_item_id(self.name, self.version),
            "name": self.name,
            "version": self.version,
            "summary": self.summary,
            "side_effect_class": self.side_effect_class,
            "replay_policy": self.replay_policy,
            "required_permissions": list(self.required_permissions),
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "backend_contract": asdict(self.backend_contract) if self.backend_contract else None,
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools = _build_tool_specs()
        self._validate_architecture_guards()

    def list_specs(self) -> list[ToolSpec]:
        return [self._tools[name] for name in sorted(self._tools)]

    def get(self, tool_name: str) -> ToolSpec:
        try:
            return self._tools[tool_name]
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent tool 不存在") from exc

    def registry_json(self) -> list[dict[str, Any]]:
        return [spec.to_json() for spec in self.list_specs()]

    def registry_hash(self) -> str:
        return request_fingerprint(self.registry_json())

    def manifest_bundle_hash(self) -> str:
        return request_fingerprint({
            item.name: item.manifest_hash
            for item in self.list_specs()
        })

    def runtime_hash(self) -> str:
        return request_fingerprint({
            "tool_registry_hash": self.registry_hash(),
            "manifest_bundle_hash": self.manifest_bundle_hash(),
            "policy_version_hash": "agent-policy-v1",
        })

    def _validate_architecture_guards(self) -> None:
        for spec in self._tools.values():
            if spec.side_effect_class not in SAFE_SIDE_EFFECT_CLASSES and spec.backend_contract is None:
                raise RuntimeError(f"Unsafe Agent tool lacks BackendEffectCapability: {spec.name}")


@dataclass(frozen=True)
class RoutedTool:
    spec: ToolSpec
    handler: Callable[[dict[str, Any], User], dict[str, Any]]


class AgentToolRouter:
    def __init__(self, registry: ToolRegistry | None = None) -> None:
        self.registry = registry or ToolRegistry()

    def resolve(self, *, tool_name: str, backend: Any) -> RoutedTool:
        spec = self.registry.get(tool_name)
        handler_name = spec.backend_handler
        handler = getattr(backend, handler_name, None) if handler_name else None
        if handler is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent tool backend 不存在")
        return RoutedTool(spec=spec, handler=handler)


@dataclass(frozen=True)
class ResolvedToolPolicy:
    resolved_side_effect_class: str
    resolved_replay_policy: str
    approval_required: bool
    policy_reason: dict[str, Any]


class ToolPolicyResolver:
    def resolve(self, *, spec: ToolSpec, evidence_refs: list[dict[str, Any]]) -> ResolvedToolPolicy:
        resolver = EvidenceRefResolver()
        all_refs = resolver.parse(evidence_refs)
        active_refs = resolver.select_policy_refs(evidence_refs)
        active_ref_ids = {item.evidence_ref_id for item in active_refs}
        volatile = [
            item for item in active_refs
            if item.mutability_class in {"mutable_current", "ephemeral_latest", "external_uncontrolled"}
        ]
        frozen = [
            item for item in active_refs
            if item.mutability_class in {"immutable", "versioned"}
            and (item.content_hash or item.version_id or item.snapshot_id)
        ]
        historical_volatile_excluded = [
            item for item in all_refs
            if item.evidence_ref_id not in active_ref_ids
            and item.mutability_class in {"mutable_current", "ephemeral_latest", "external_uncontrolled"}
        ]
        replay_policy = "require_revalidation" if volatile else spec.replay_policy
        approval_required = spec.side_effect_class not in SAFE_SIDE_EFFECT_CLASSES
        approval_required_reason = "unsafe_side_effect" if approval_required else "safe_initial_tool"
        policy_context = {
            "policy_version_hash": "agent-policy-v1",
            "tool_name": spec.name,
            "tool_version": spec.version,
            "base_side_effect_class": spec.side_effect_class,
            "resolved_side_effect_class": spec.side_effect_class,
            "base_replay_policy": spec.replay_policy,
            "resolved_replay_policy": replay_policy,
            "approval_policy": "unsafe_side_effect_requires_approval" if approval_required else "safe_side_effect_auto",
            "approval_required": approval_required,
            "approval_required_reason": approval_required_reason,
            "active_policy_ref_count": len(active_refs),
            "volatile_policy_ref_count": len(volatile),
            "frozen_policy_ref_count": len(frozen),
            "historical_volatile_excluded_count": len(historical_volatile_excluded),
            "mixed_volatile_frozen": bool(volatile and frozen),
        }
        policy_context["policy_hash"] = request_fingerprint(policy_context)
        return ResolvedToolPolicy(
            resolved_side_effect_class=spec.side_effect_class,
            resolved_replay_policy=replay_policy,
            approval_required=approval_required,
            policy_reason={
                "base_replay_policy": spec.replay_policy,
                "active_policy_ref_count": len(active_refs),
                "volatile_policy_ref_count": len(volatile),
                "frozen_policy_ref_count": len(frozen),
                "historical_volatile_excluded_count": len(historical_volatile_excluded),
                "mixed_volatile_frozen": bool(volatile and frozen),
                "approval_required_reason": approval_required_reason,
                "policy_context": policy_context,
            },
        )


class AgentToolBackend:
    def __init__(self, db: Session, router: AgentToolRouter | None = None):
        self.db = db
        self.permission_service = PermissionService(db)
        self.router = router or AgentToolRouter()

    def execute(self, *, tool_name: str, payload: dict[str, Any], current_user: User) -> dict[str, Any]:
        logger.info(
            "agent_tool_backend_execute_start tool_name=%s project_id=%s user_id=%s",
            tool_name,
            payload.get("project_id"),
            current_user.id,
        )
        route = self.router.resolve(tool_name=tool_name, backend=self)
        result = route.handler(payload, current_user)
        logger.info(
            "agent_tool_backend_execute_done tool_name=%s project_id=%s user_id=%s",
            tool_name,
            payload.get("project_id"),
            current_user.id,
        )
        return result

    def _project_read_context(self, payload: dict[str, Any], current_user: User) -> dict[str, Any]:
        project_id = _require_int(payload, "project_id")
        project = self.permission_service.require_project_access(current_user, project_id)
        environments = self._project_environments(project_id)
        default_environment = self._default_environment(project_id)
        return {
            "project": {
                "id": project.id,
                "name": getattr(project, "name", ""),
                "description": getattr(project, "description", None),
                "created_by_id": getattr(project, "created_by_id", None),
            },
            "environments": environments,
            "default_environment": default_environment,
        }

    def _scenario_compose_draft(self, payload: dict[str, Any], current_user: User) -> dict[str, Any]:
        project_id = _require_int(payload, "project_id")
        environment_id = _optional_int(payload, "environment_id")
        if environment_id is None:
            default_environment = self._default_environment(project_id)
            if default_environment is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={"code": "agent_default_environment_missing", "project_id": project_id},
                )
            environment_id = int(default_environment["id"])
            logger.info(
                "agent_tool_default_environment_selected tool_name=scenario.compose_draft project_id=%s environment_id=%s",
                project_id,
                environment_id,
            )
        compose_input = payload.get("input") or payload.get("compose_input") or {}
        compose_input = dict(compose_input)
        if not compose_input.get("http_test_case_ids") and not compose_input.get("websocket_test_case_ids"):
            candidate_ids = self._default_candidate_case_ids(project_id=project_id, environment_id=environment_id)
            compose_input.update(candidate_ids)
            logger.info(
                "agent_tool_default_scenario_candidates_selected project_id=%s environment_id=%s http_count=%s websocket_count=%s",
                project_id,
                environment_id,
                len(candidate_ids["http_test_case_ids"]),
                len(candidate_ids["websocket_test_case_ids"]),
            )
        request = AISkillRunRequest(
            operation="compose",
            project_id=project_id,
            environment_id=environment_id,
            input=AIScenarioComposeRequest.model_validate(compose_input).model_dump(mode="json"),
        )
        result = AISkillService(self.db).run_skill(
            skill_id="scenario-composer",
            payload=request,
            current_user=current_user,
        )
        return {"draft": normalize_response_data(result)}

    def _project_environments(self, project_id: int) -> list[dict[str, Any]]:
        environments = list(
            self.db.scalars(
                select(ProjectEnvironment)
                .where(
                    ProjectEnvironment.project_id == project_id,
                    ProjectEnvironment.is_deleted.is_(False),
                )
                .order_by(ProjectEnvironment.is_default.desc(), ProjectEnvironment.id.asc())
            ).all()
        )
        return [
            {
                "id": item.id,
                "name": item.name,
                "base_url": item.base_url,
                "description": item.description,
                "is_default": item.is_default,
            }
            for item in environments
        ]

    def _default_environment(self, project_id: int) -> dict[str, Any] | None:
        environments = self._project_environments(project_id)
        return environments[0] if environments else None

    def _default_candidate_case_ids(self, *, project_id: int, environment_id: int, limit: int = 8) -> dict[str, list[int]]:
        http_ids = [
            item.id
            for item in self.db.scalars(
                select(TestCase)
                .where(
                    TestCase.project_id == project_id,
                    (TestCase.environment_id == environment_id) | (TestCase.environment_id.is_(None)),
                )
                .order_by(TestCase.id.asc())
                .limit(limit)
            ).all()
        ]
        remaining = max(0, limit - len(http_ids))
        websocket_ids: list[int] = []
        if remaining:
            websocket_ids = [
                item.id
                for item in self.db.scalars(
                    select(WebSocketTestCase)
                    .where(
                        WebSocketTestCase.project_id == project_id,
                        (WebSocketTestCase.environment_id == environment_id)
                        | (WebSocketTestCase.environment_id.is_(None)),
                    )
                    .order_by(WebSocketTestCase.id.asc())
                    .limit(remaining)
                ).all()
            ]
        return {
            "http_test_case_ids": http_ids,
            "websocket_test_case_ids": websocket_ids,
        }

    def _testcase_query_project_cases(self, payload: dict[str, Any], current_user: User) -> dict[str, Any]:
        project_id = _require_int(payload, "project_id")
        environment_id = _optional_int(payload, "environment_id")
        include_websocket = payload.get("include_websocket", True)
        if not isinstance(include_websocket, bool):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="include_websocket must be a boolean",
            )
        self.permission_service.require_project_permission(
            current_user,
            project_id,
            ProjectPermission.VIEW_CASE.value,
        )
        http_query = select(TestCase).where(TestCase.project_id == project_id)
        if environment_id is not None:
            http_query = http_query.where(
                (TestCase.environment_id == environment_id) | (TestCase.environment_id.is_(None))
            )
        http_cases = list(self.db.scalars(http_query.order_by(TestCase.id.asc())).all())
        websocket_cases: list[WebSocketTestCase] = []
        if include_websocket:
            websocket_query = select(WebSocketTestCase).where(WebSocketTestCase.project_id == project_id)
            if environment_id is not None:
                websocket_query = websocket_query.where(
                    (WebSocketTestCase.environment_id == environment_id) | (WebSocketTestCase.environment_id.is_(None))
                )
            websocket_cases = list(self.db.scalars(websocket_query.order_by(WebSocketTestCase.id.asc())).all())
        http_ids = [item.id for item in http_cases]
        websocket_ids = [item.id for item in websocket_cases]
        http_batch_input: dict[str, Any] | None = None
        websocket_batch_input: dict[str, Any] | None = None
        if http_ids:
            http_batch_input = {"project_id": project_id, "test_case_ids": http_ids}
            if environment_id is not None:
                http_batch_input["environment_id"] = environment_id
        if websocket_ids:
            websocket_batch_input = {"project_id": project_id, "websocket_test_case_ids": websocket_ids}
            if environment_id is not None:
                websocket_batch_input["environment_id"] = environment_id
        return {
            "project_id": project_id,
            "environment_id": environment_id,
            "http_total": len(http_cases),
            "websocket_total": len(websocket_cases),
            "http_test_case_ids": http_ids,
            "websocket_test_case_ids": websocket_ids,
            "http_batch_execute_input": http_batch_input,
            "websocket_batch_execute_input": websocket_batch_input,
            "http_test_cases": [self._http_case_payload(item) for item in http_cases],
            "websocket_test_cases": [self._websocket_case_payload(item) for item in websocket_cases],
        }

    def _testcase_execute_saved(self, payload: dict[str, Any], current_user: User) -> dict[str, Any]:
        project_id = _require_int(payload, "project_id")
        test_case_id = _require_int(payload, "test_case_id")
        environment_id = _optional_int(payload, "environment_id")
        source = _agent_execution_source(payload, tool_name="testcase.execute_saved")
        service = TestCaseService(self.db)
        execution = service.enqueue_saved_case(
            project_id=project_id,
            test_case_id=test_case_id,
            environment_id=environment_id,
            current_user=current_user,
            **source,
        )
        TestCaseService.execute_queued_execution(execution.id)
        self.db.refresh(execution)
        return {
            "project_id": project_id,
            "test_case_id": test_case_id,
            "execution": normalize_response_data(TestCaseExecutionRead.model_validate(execution)),
        }

    def _testcase_create_saved(self, payload: dict[str, Any], current_user: User) -> dict[str, Any]:
        project_id = _require_int(payload, "project_id")
        case_payload = _require_dict(payload, "case")
        try:
            request = TestCaseCreateRequest.model_validate(case_payload)
        except ValidationError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.errors()) from exc
        test_case = TestCaseService(self.db).create_case(
            project_id=project_id,
            payload=request,
            current_user=current_user,
        )
        return {
            "operation": "create_saved",
            "project_id": project_id,
            "test_case_id": test_case.id,
            "test_case": normalize_response_data(TestCaseRead.model_validate(test_case)),
        }

    def _testcase_update_saved(self, payload: dict[str, Any], current_user: User) -> dict[str, Any]:
        project_id = _require_int(payload, "project_id")
        test_case_id = _require_int(payload, "test_case_id")
        case_payload = _require_dict(payload, "case")
        try:
            request = TestCaseUpdateRequest.model_validate(case_payload)
        except ValidationError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.errors()) from exc
        test_case = TestCaseService(self.db).update_case(
            project_id=project_id,
            test_case_id=test_case_id,
            payload=request,
            current_user=current_user,
        )
        return {
            "operation": "update_saved",
            "project_id": project_id,
            "test_case_id": test_case.id,
            "test_case": normalize_response_data(TestCaseRead.model_validate(test_case)),
        }

    def _testcase_update_assertions(self, payload: dict[str, Any], current_user: User) -> dict[str, Any]:
        project_id = _require_int(payload, "project_id")
        test_case_id = _require_int(payload, "test_case_id")
        assertions = _validate_assertion_list(payload.get("assertions"), AssertionConfig)
        test_case = TestCaseService(self.db).update_case_assertions(
            project_id=project_id,
            test_case_id=test_case_id,
            assertions=assertions,
            current_user=current_user,
        )
        return {
            "operation": "update_assertions",
            "project_id": project_id,
            "test_case_id": test_case.id,
            "assertions": normalize_response_data([item.model_dump() for item in assertions]),
            "test_case": normalize_response_data(TestCaseRead.model_validate(test_case)),
        }

    def _testcase_batch_update_assertions(self, payload: dict[str, Any], current_user: User) -> dict[str, Any]:
        project_id = _require_int(payload, "project_id")
        parsed_items: list[tuple[int, list[AssertionConfig]]] = []
        for index, raw_item in enumerate(_require_non_empty_object_list(payload.get("items"), "items")):
            parsed_items.append((
                _require_int(raw_item, "test_case_id"),
                _validate_assertion_list(raw_item.get("assertions"), AssertionConfig, path=f"items[{index}].assertions"),
            ))
        service = TestCaseService(self.db)
        updated_cases = [
            service.update_case_assertions(
                project_id=project_id,
                test_case_id=test_case_id,
                assertions=assertions,
                current_user=current_user,
            )
            for test_case_id, assertions in parsed_items
        ]
        return {
            "operation": "batch_update_assertions",
            "project_id": project_id,
            "updated_count": len(updated_cases),
            "test_case_ids": [item[0] for item in parsed_items],
            "test_cases": normalize_response_data(
                [TestCaseRead.model_validate(item) for item in updated_cases]
            ),
        }

    def _testcase_batch_execute(self, payload: dict[str, Any], current_user: User) -> dict[str, Any]:
        project_id = _require_int(payload, "project_id")
        raw_ids = payload.get("test_case_ids")
        if not isinstance(raw_ids, list) or not raw_ids or any(not isinstance(item, int) for item in raw_ids):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="test_case_ids must be a non-empty integer array",
            )
        environment_id = _optional_int(payload, "environment_id")
        self._require_valid_batch_case_ids(
            project_id=project_id,
            case_ids=raw_ids,
            model=TestCase,
            invalid_key="invalid_test_case_ids",
            code="agent_testcase_batch_invalid_ids",
            id_field="test_case_ids",
            environment_id=environment_id,
            current_user=current_user,
        )
        source = _agent_execution_source(payload, tool_name="testcase.batch_execute")
        service = TestCaseService(self.db)
        executions = [
            service.enqueue_saved_case(
                project_id=project_id,
                test_case_id=test_case_id,
                environment_id=environment_id,
                current_user=current_user,
                **source,
            )
            for test_case_id in raw_ids
        ]
        for execution in executions:
            TestCaseService.execute_queued_execution(execution.id)
            self.db.refresh(execution)
        return {
            "project_id": project_id,
            "requested_count": len(raw_ids),
            "test_case_ids": raw_ids,
            "executions": normalize_response_data(
                [TestCaseExecutionRead.model_validate(item) for item in executions]
            ),
        }

    def _websocket_testcase_execute_saved(self, payload: dict[str, Any], current_user: User) -> dict[str, Any]:
        project_id = _require_int(payload, "project_id")
        test_case_id = _require_int(payload, "test_case_id")
        environment_id = _optional_int(payload, "environment_id")
        source = _agent_execution_source(payload, tool_name="websocket_testcase.execute_saved")
        service = WebSocketTestCaseService(self.db)
        execution = service.enqueue_saved_case(
            project_id=project_id,
            test_case_id=test_case_id,
            environment_id=environment_id,
            current_user=current_user,
            **source,
        )
        WebSocketTestCaseService.execute_queued_execution(execution.id)
        self.db.refresh(execution)
        return {
            "project_id": project_id,
            "websocket_test_case_id": test_case_id,
            "execution": normalize_response_data(WebSocketTestCaseExecutionRead.model_validate(execution)),
        }

    def _websocket_testcase_create_saved(self, payload: dict[str, Any], current_user: User) -> dict[str, Any]:
        project_id = _require_int(payload, "project_id")
        case_payload = _require_dict(payload, "case")
        try:
            request = WebSocketTestCaseCreateRequest.model_validate(case_payload)
        except ValidationError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.errors()) from exc
        test_case = WebSocketTestCaseService(self.db).create_case(
            project_id=project_id,
            payload=request,
            current_user=current_user,
        )
        return {
            "operation": "create_saved",
            "project_id": project_id,
            "websocket_test_case_id": test_case.id,
            "websocket_test_case": normalize_response_data(WebSocketTestCaseRead.model_validate(test_case)),
        }

    def _websocket_testcase_update_saved(self, payload: dict[str, Any], current_user: User) -> dict[str, Any]:
        project_id = _require_int(payload, "project_id")
        test_case_id = _require_int(payload, "test_case_id")
        case_payload = _require_dict(payload, "case")
        try:
            request = WebSocketTestCaseUpdateRequest.model_validate(case_payload)
        except ValidationError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.errors()) from exc
        test_case = WebSocketTestCaseService(self.db).update_case(
            project_id=project_id,
            test_case_id=test_case_id,
            payload=request,
            current_user=current_user,
        )
        return {
            "operation": "update_saved",
            "project_id": project_id,
            "websocket_test_case_id": test_case.id,
            "websocket_test_case": normalize_response_data(WebSocketTestCaseRead.model_validate(test_case)),
        }

    def _websocket_testcase_update_assertions(self, payload: dict[str, Any], current_user: User) -> dict[str, Any]:
        project_id = _require_int(payload, "project_id")
        test_case_id = _require_int(payload, "test_case_id")
        assertions = _validate_assertion_list(payload.get("assertions"), WebSocketAssertionConfig)
        test_case = WebSocketTestCaseService(self.db).update_case_assertions(
            project_id=project_id,
            test_case_id=test_case_id,
            assertions=assertions,
            current_user=current_user,
        )
        return {
            "operation": "update_assertions",
            "project_id": project_id,
            "websocket_test_case_id": test_case.id,
            "assertions": normalize_response_data([item.model_dump() for item in assertions]),
            "websocket_test_case": normalize_response_data(WebSocketTestCaseRead.model_validate(test_case)),
        }

    def _websocket_testcase_batch_update_assertions(self, payload: dict[str, Any], current_user: User) -> dict[str, Any]:
        project_id = _require_int(payload, "project_id")
        parsed_items: list[tuple[int, list[WebSocketAssertionConfig]]] = []
        for index, raw_item in enumerate(_require_non_empty_object_list(payload.get("items"), "items")):
            parsed_items.append((
                _require_int(raw_item, "test_case_id"),
                _validate_assertion_list(
                    raw_item.get("assertions"),
                    WebSocketAssertionConfig,
                    path=f"items[{index}].assertions",
                ),
            ))
        service = WebSocketTestCaseService(self.db)
        updated_cases = [
            service.update_case_assertions(
                project_id=project_id,
                test_case_id=test_case_id,
                assertions=assertions,
                current_user=current_user,
            )
            for test_case_id, assertions in parsed_items
        ]
        return {
            "operation": "batch_update_assertions",
            "project_id": project_id,
            "updated_count": len(updated_cases),
            "websocket_test_case_ids": [item[0] for item in parsed_items],
            "websocket_test_cases": normalize_response_data(
                [WebSocketTestCaseRead.model_validate(item) for item in updated_cases]
            ),
        }

    def _websocket_testcase_batch_execute(self, payload: dict[str, Any], current_user: User) -> dict[str, Any]:
        project_id = _require_int(payload, "project_id")
        raw_ids = payload.get("websocket_test_case_ids")
        if not isinstance(raw_ids, list) or not raw_ids or any(not isinstance(item, int) for item in raw_ids):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="websocket_test_case_ids must be a non-empty integer array",
            )
        environment_id = _optional_int(payload, "environment_id")
        self._require_valid_batch_case_ids(
            project_id=project_id,
            case_ids=raw_ids,
            model=WebSocketTestCase,
            invalid_key="invalid_websocket_test_case_ids",
            code="agent_websocket_testcase_batch_invalid_ids",
            id_field="websocket_test_case_ids",
            environment_id=environment_id,
            current_user=current_user,
        )
        source = _agent_execution_source(payload, tool_name="websocket_testcase.batch_execute")
        service = WebSocketTestCaseService(self.db)
        executions = [
            service.enqueue_saved_case(
                project_id=project_id,
                test_case_id=test_case_id,
                environment_id=environment_id,
                current_user=current_user,
                **source,
            )
            for test_case_id in raw_ids
        ]
        for execution in executions:
            WebSocketTestCaseService.execute_queued_execution(execution.id)
            self.db.refresh(execution)
        return {
            "project_id": project_id,
            "requested_count": len(raw_ids),
            "websocket_test_case_ids": raw_ids,
            "executions": normalize_response_data(
                [WebSocketTestCaseExecutionRead.model_validate(item) for item in executions]
            ),
        }

    def _require_valid_batch_case_ids(
        self,
        *,
        project_id: int,
        case_ids: list[int],
        model: type[TestCase] | type[WebSocketTestCase],
        invalid_key: str,
        code: str,
        id_field: str,
        environment_id: int | None,
        current_user: User,
    ) -> None:
        self.permission_service.require_project_permission(
            current_user,
            project_id,
            ProjectPermission.EXECUTE_TEST.value,
        )
        unique_ids = list(dict.fromkeys(case_ids))
        existing_ids = set(
            self.db.scalars(
                select(model.id).where(model.project_id == project_id, model.id.in_(unique_ids))
            ).all()
        )
        invalid_ids = [case_id for case_id in unique_ids if case_id not in existing_ids]
        if invalid_ids:
            valid_case_ids = [case_id for case_id in unique_ids if case_id in existing_ids]
            retry_input: dict[str, Any] = {"project_id": project_id, id_field: valid_case_ids}
            if environment_id is not None:
                retry_input["environment_id"] = environment_id
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={
                    "code": code,
                    "message": "Batch execution contains case IDs that do not exist in this project.",
                    invalid_key: invalid_ids,
                    "valid_case_ids": valid_case_ids,
                    "retry_batch_execute_input": retry_input,
                    "repair_instruction": (
                        "Use retry_batch_execute_input exactly if the user still wants to run the valid cases. "
                        "Do not infer case IDs from numeric ranges."
                    ),
                },
            )

    @staticmethod
    def _http_case_payload(item: TestCase) -> dict[str, Any]:
        return {
            "id": item.id,
            "name": item.name,
            "description": item.description,
            "method": item.method,
            "path": item.path,
            "environment_id": item.environment_id,
            "environment_ids": item.environment_ids,
            "headers": mask_sensitive(item.headers or {}),
            "query_params": mask_sensitive(item.query_params or {}),
            "body_type": item.body_type,
            "body": mask_sensitive(item.body),
            "assertions": mask_sensitive(item.assertions or []),
            "extractors": mask_sensitive(item.extractors or []),
            "last_execution_status": item.last_execution_status,
        }

    @staticmethod
    def _websocket_case_payload(item: WebSocketTestCase) -> dict[str, Any]:
        return {
            "id": item.id,
            "name": item.name,
            "description": item.description,
            "path": item.path,
            "environment_id": item.environment_id,
            "environment_ids": item.environment_ids,
            "headers": mask_sensitive(item.headers or {}),
            "subprotocols": mask_sensitive(item.subprotocols or []),
            "messages": mask_sensitive(item.messages or []),
            "receive_count": item.receive_count,
            "assertions": mask_sensitive(item.assertions or []),
            "extractors": mask_sensitive(item.extractors or []),
            "last_execution_status": item.last_execution_status,
        }

    def _ai_skill_run_draft(self, payload: dict[str, Any], current_user: User) -> dict[str, Any]:
        project_id = _require_int(payload, "project_id")
        skill_id = _require_str(payload, "skill_id")
        operation = _require_str(payload, "operation")
        if operation not in AI_DRAFT_OPERATIONS.get(skill_id, set()):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "ai_skill_operation_not_allowed_for_agent_draft"},
            )
        request = AISkillRunRequest(
            operation=operation,
            project_id=project_id,
            environment_id=_optional_int(payload, "environment_id"),
            source_id=_optional_int(payload, "source_id"),
            input=dict(payload.get("input") or {}),
        )
        result = AISkillService(self.db).run_skill(
            skill_id=skill_id,
            payload=request,
            current_user=current_user,
        )
        return {
            "skill_id": skill_id,
            "operation": operation,
            "draft": normalize_response_data(result),
        }

    def _scenario_execute_dry_run(self, payload: dict[str, Any], current_user: User) -> dict[str, Any]:
        project_id = _require_int(payload, "project_id")
        scenario_id = _require_int(payload, "scenario_id")
        dataset_ids = payload.get("dataset_ids")
        if dataset_ids is not None and not (
            isinstance(dataset_ids, list) and all(isinstance(item, str) for item in dataset_ids)
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="dataset_ids must be a list of strings",
            )
        runs = ScenarioService(self.db).execute_scenario(
            project_id=project_id,
            scenario_id=scenario_id,
            environment_id=_optional_int(payload, "environment_id"),
            dataset_ids=dataset_ids,
            idempotency_key=_optional_str(payload, "idempotency_key"),
            current_user=current_user,
            trigger_type="agent_dry_run",
            scenario_version=_optional_int(payload, "scenario_version"),
        )
        return {
            "scenario_id": scenario_id,
            "run_ids": [item.id for item in runs],
            "runs": normalize_response_data([ScenarioRunRead.model_validate(item) for item in runs]),
        }

    def _testcase_validate_schema(self, payload: dict[str, Any], current_user: User) -> dict[str, Any]:
        project_id = _require_int(payload, "project_id")
        self.permission_service.require_project_access(current_user, project_id)
        raw_case = payload.get("case") or {}
        try:
            parsed = TestCaseCreateRequest.model_validate(raw_case)
        except ValidationError as exc:
            return {
                "valid": False,
                "issues": exc.errors(),
            }
        return {
            "valid": True,
            "case": parsed.model_dump(mode="json"),
            "issues": [],
        }

    def _report_read_summary(self, payload: dict[str, Any], current_user: User) -> dict[str, Any]:
        project_id = _require_int(payload, "project_id")
        source_type = _optional_report_source_type(payload, "source_type")
        status_filter = _optional_str(payload, "status")
        environment_id = _optional_int(payload, "environment_id")
        page_size = _optional_int(payload, "page_size") or 5
        if page_size < 1 or page_size > 20:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="page_size must be between 1 and 20",
            )

        page = TestReportService(self.db).list_reports(
            project_id=project_id,
            current_user=current_user,
            source_type=source_type,
            status_filter=status_filter,
            environment_id=environment_id,
            started_from=None,
            started_to=None,
            page=1,
            page_size=page_size,
        )
        report_items = normalize_response_data(page.items)
        status_counts: dict[str, int] = {}
        totals = {"total": 0, "passed": 0, "failed": 0, "skipped": 0}
        failure_reports: list[dict[str, Any]] = []
        for item in report_items:
            item_status = str(item.get("status") or "unknown")
            status_counts[item_status] = status_counts.get(item_status, 0) + 1
            totals["total"] += int(item.get("total_count") or 0)
            totals["passed"] += int(item.get("passed_count") or 0)
            totals["failed"] += int(item.get("failed_count") or 0)
            totals["skipped"] += int(item.get("skipped_count") or 0)
            if int(item.get("failed_count") or 0) > 0 or item_status in {"failed", "timeout", "error"}:
                failure_reports.append(item)

        return {
            "project_id": project_id,
            "filters": {
                "source_type": source_type,
                "status": status_filter,
                "environment_id": environment_id,
                "page": 1,
                "page_size": page_size,
            },
            "report_count": page.total,
            "returned_report_count": len(report_items),
            "status_counts": status_counts,
            "returned_case_totals": {
                **totals,
                "pass_rate": round(totals["passed"] * 100 / totals["total"], 2) if totals["total"] else 0.0,
            },
            "latest_reports": report_items,
            "failure_reports": failure_reports[:3],
        }


def _require_int(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"{key} 必须是整数")
    return value


def _optional_int(payload: dict[str, Any], key: str) -> int | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, int):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"{key} must be an integer")
    return value


def _require_dict(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{key} must be an object",
        )
    return value


def _require_non_empty_object_list(value: Any, key: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{key} must be a non-empty array",
        )
    items: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"{key}[{index}] must be an object",
            )
        items.append(item)
    return items


def _validate_assertion_list(value: Any, schema_type: type, *, path: str = "assertions") -> list[Any]:
    if not isinstance(value, list):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{path} must be an array",
        )
    try:
        return [schema_type.model_validate(item) for item in value]
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.errors()) from exc


def _require_str(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{key} must be a non-empty string",
        )
    return value


def _optional_str(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{key} must be a non-empty string",
        )
    return value


def _agent_execution_source(payload: dict[str, Any], *, tool_name: str) -> dict[str, str | None]:
    return {
        "trigger_source": "agent",
        "agent_run_id": _optional_str(payload, "_agent_run_id"),
        "agent_tool_call_id": _optional_str(payload, "_agent_tool_call_id"),
        "trigger_tool_name": tool_name,
    }


def _optional_report_source_type(payload: dict[str, Any], key: str) -> str | None:
    value = _optional_str(payload, key)
    if value is None:
        return None
    if value not in {"plan", "flow"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{key} must be one of: plan, flow",
        )
    return value


def _build_tool_specs() -> dict[str, ToolSpec]:
    schemas = {
        "project_input": {
            "type": "object",
            "required": ["project_id"],
            "properties": {"project_id": {"type": "integer"}},
        },
        "report_summary_input": {
            "type": "object",
            "required": ["project_id"],
            "properties": {
                "project_id": {"type": "integer"},
                "source_type": {"type": "string", "enum": ["plan", "flow"]},
                "status": {"type": "string"},
                "environment_id": {"type": "integer"},
                "page_size": {
                    "type": "integer",
                    "description": "Number of recent reports to summarize, from 1 to 20. Defaults to 5.",
                },
            },
        },
        "scenario_compose_input": {
            "type": "object",
            "required": ["project_id", "input"],
            "properties": {
                "project_id": {"type": "integer"},
                "environment_id": {
                    "type": "integer",
                    "description": "Optional for Agent; backend selects the project default environment when omitted.",
                },
                "input": AIScenarioComposeRequest.model_json_schema(),
            },
        },
        "ai_skill_run_draft_input": {
            "type": "object",
            "required": ["project_id", "skill_id", "operation", "input"],
            "properties": {
                "project_id": {"type": "integer"},
                "environment_id": {"type": "integer"},
                "source_id": {"type": "integer"},
                "skill_id": {"type": "string", "enum": sorted(AI_DRAFT_OPERATIONS)},
                "operation": {"type": "string"},
                "input": {"type": "object"},
            },
        },
        "scenario_execute_dry_run_input": {
            "type": "object",
            "required": ["project_id", "scenario_id"],
            "properties": {
                "project_id": {"type": "integer"},
                "scenario_id": {"type": "integer"},
                "environment_id": {"type": "integer"},
                "scenario_version": {"type": "integer"},
                "dataset_ids": {"type": "array", "items": {"type": "string"}},
                "idempotency_key": {"type": "string"},
            },
        },
        "testcase_query_project_cases_input": {
            "type": "object",
            "required": ["project_id"],
            "properties": {
                "project_id": {"type": "integer"},
                "environment_id": {
                    "type": "integer",
                    "description": "Optional environment filter. Omit it to return all project test cases.",
                },
                "include_websocket": {"type": "boolean", "default": True},
            },
        },
        "testcase_execute_saved_input": {
            "type": "object",
            "required": ["project_id", "test_case_id"],
            "properties": {
                "project_id": {"type": "integer"},
                "test_case_id": {"type": "integer"},
                "environment_id": {"type": "integer"},
            },
        },
        "testcase_create_saved_input": {
            "type": "object",
            "required": ["project_id", "case"],
            "properties": {
                "project_id": {"type": "integer"},
                "case": TestCaseCreateRequest.model_json_schema(),
            },
        },
        "testcase_update_saved_input": {
            "type": "object",
            "required": ["project_id", "test_case_id", "case"],
            "properties": {
                "project_id": {"type": "integer"},
                "test_case_id": {"type": "integer"},
                "case": TestCaseUpdateRequest.model_json_schema(),
            },
        },
        "testcase_update_assertions_input": {
            "type": "object",
            "required": ["project_id", "test_case_id", "assertions"],
            "properties": {
                "project_id": {"type": "integer"},
                "test_case_id": {"type": "integer"},
                "assertions": {
                    "type": "array",
                    "items": AssertionConfig.model_json_schema(),
                    "description": "Replacement assertions for this saved HTTP test case. Other case fields are preserved.",
                },
            },
        },
        "testcase_batch_update_assertions_input": {
            "type": "object",
            "required": ["project_id", "items"],
            "properties": {
                "project_id": {"type": "integer"},
                "items": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "required": ["test_case_id", "assertions"],
                        "properties": {
                            "test_case_id": {"type": "integer"},
                            "assertions": {
                                "type": "array",
                                "items": AssertionConfig.model_json_schema(),
                            },
                        },
                    },
                    "description": "Assertion patches for saved HTTP test cases. Use ids from testcase.query_project_cases.",
                },
            },
        },
        "testcase_batch_execute_input": {
            "type": "object",
            "required": ["project_id", "test_case_ids"],
            "properties": {
                "project_id": {"type": "integer"},
                "test_case_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "minItems": 1,
                    "description": (
                        "HTTP test case ids to execute in order. Use testcase.query_project_cases.http_test_case_ids "
                        "or http_batch_execute_input exactly; never infer a continuous numeric range."
                    ),
                },
                "environment_id": {"type": "integer"},
            },
        },
        "websocket_testcase_execute_saved_input": {
            "type": "object",
            "required": ["project_id", "test_case_id"],
            "properties": {
                "project_id": {"type": "integer"},
                "test_case_id": {"type": "integer"},
                "environment_id": {"type": "integer"},
            },
        },
        "websocket_testcase_create_saved_input": {
            "type": "object",
            "required": ["project_id", "case"],
            "properties": {
                "project_id": {"type": "integer"},
                "case": WebSocketTestCaseCreateRequest.model_json_schema(),
            },
        },
        "websocket_testcase_update_saved_input": {
            "type": "object",
            "required": ["project_id", "test_case_id", "case"],
            "properties": {
                "project_id": {"type": "integer"},
                "test_case_id": {"type": "integer"},
                "case": WebSocketTestCaseUpdateRequest.model_json_schema(),
            },
        },
        "websocket_testcase_update_assertions_input": {
            "type": "object",
            "required": ["project_id", "test_case_id", "assertions"],
            "properties": {
                "project_id": {"type": "integer"},
                "test_case_id": {"type": "integer"},
                "assertions": {
                    "type": "array",
                    "items": WebSocketAssertionConfig.model_json_schema(),
                    "description": "Replacement assertions for this saved WebSocket test case. Other case fields are preserved.",
                },
            },
        },
        "websocket_testcase_batch_update_assertions_input": {
            "type": "object",
            "required": ["project_id", "items"],
            "properties": {
                "project_id": {"type": "integer"},
                "items": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "required": ["test_case_id", "assertions"],
                        "properties": {
                            "test_case_id": {"type": "integer"},
                            "assertions": {
                                "type": "array",
                                "items": WebSocketAssertionConfig.model_json_schema(),
                            },
                        },
                    },
                    "description": "Assertion patches for saved WebSocket test cases. Use ids from testcase.query_project_cases.",
                },
            },
        },
        "websocket_testcase_batch_execute_input": {
            "type": "object",
            "required": ["project_id", "websocket_test_case_ids"],
            "properties": {
                "project_id": {"type": "integer"},
                "websocket_test_case_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "minItems": 1,
                    "description": (
                        "WebSocket test case ids to execute in order. Use "
                        "testcase.query_project_cases.websocket_test_case_ids or websocket_batch_execute_input exactly; "
                        "never infer a continuous numeric range."
                    ),
                },
                "environment_id": {"type": "integer"},
            },
        },
        "testcase_validate_input": {
            "type": "object",
            "required": ["project_id", "case"],
            "properties": {
                "project_id": {"type": "integer"},
                "case": TestCaseCreateRequest.model_json_schema(),
            },
        },
    }
    return {
        "project.read_context": ToolSpec(
            name="project.read_context",
            version="1.0.0",
            summary="Read project metadata for planning context.",
            side_effect_class="read_only",
            replay_policy="reuse_allowed",
            required_permissions=(ProjectPermission.VIEW_PROJECT.value,),
            input_schema=schemas["project_input"],
            output_schema={"type": "object"},
            backend_contract=BackendContractSpec(
                backend_name="project-service",
                backend_operation="read_context",
                backend_contract_version="v1",
                effect_capability="idempotency_index_only",
                request_schema_hash=request_fingerprint(schemas["project_input"]),
                output_schema_hash=request_fingerprint({"type": "object"}),
            ),
            backend_handler="_project_read_context",
        ),
        "ai_skill.run_draft": ToolSpec(
            name="ai_skill.run_draft",
            version="1.0.0",
            summary="Run an allowlisted AISkill operation and return draft output without saving business entities.",
            side_effect_class="draft_only",
            replay_policy="reuse_allowed",
            required_permissions=(ProjectPermission.EXECUTE_TEST.value,),
            input_schema=schemas["ai_skill_run_draft_input"],
            output_schema={"type": "object"},
            backend_contract=BackendContractSpec(
                backend_name="ai-skill-service",
                backend_operation="run_draft",
                backend_contract_version="v1",
                effect_capability="idempotency_index_only",
                request_schema_hash=request_fingerprint(schemas["ai_skill_run_draft_input"]),
                output_schema_hash=request_fingerprint({"type": "object"}),
            ),
            backend_handler="_ai_skill_run_draft",
            tool_result_repair_guidance=(
                "优先复用同一 skill_id/operation 再次调用 ai_skill.run_draft；在 input.extra_requirements 中写清 warnings/issues 的修复要求，"
                "保持原始用户目标、接口文本、生成数量和环境上下文稳定。"
            ),
        ),
        "scenario.compose_draft": ToolSpec(
            name="scenario.compose_draft",
            version="1.0.0",
            summary="Compose a scenario draft through AISkillService without saving it.",
            side_effect_class="draft_only",
            replay_policy="reuse_allowed",
            required_permissions=(ProjectPermission.VIEW_SCENARIO.value, ProjectPermission.EXECUTE_TEST.value),
            input_schema=schemas["scenario_compose_input"],
            output_schema={"type": "object"},
            backend_contract=BackendContractSpec(
                backend_name="ai-skill-service",
                backend_operation="scenario.compose_draft",
                backend_contract_version="v1",
                effect_capability="idempotency_index_only",
                request_schema_hash=request_fingerprint(schemas["scenario_compose_input"]),
                output_schema_hash=request_fingerprint({"type": "object"}),
            ),
            backend_handler="_scenario_compose_draft",
            required_successful_tool_before="testcase.query_project_cases",
            missing_prerequisite_error_code="scenario_compose_requires_case_query",
            missing_prerequisite_next_action=(
                "Call testcase.query_project_cases for the current project, then use the returned "
                "test case ids when calling scenario.compose_draft."
            ),
            tool_result_repair_guidance=(
                "继续遵守 query-first。先分析候选用例用途、请求字段、响应样本和最近执行结果；"
                "可修复项通过下一次 scenario.compose_draft 的 input.extra_requirements 明确补充提取器、变量绑定、断言、数据集或字段来源，"
                "必要且安全时可设置 input.execute_candidates=true 获取样本，保留 self_validate=true。"
            ),
        ),
        "scenario.execute_dry_run": ToolSpec(
            name="scenario.execute_dry_run",
            version="1.0.0",
            summary="Execute a scenario through ScenarioService as an auditable dry-run execution record.",
            side_effect_class="execution_record",
            replay_policy="require_revalidation",
            required_permissions=(ProjectPermission.VIEW_SCENARIO.value, ProjectPermission.EXECUTE_TEST.value),
            input_schema=schemas["scenario_execute_dry_run_input"],
            output_schema={"type": "object"},
            backend_contract=BackendContractSpec(
                backend_name="scenario-service",
                backend_operation="execute_dry_run",
                backend_contract_version="v1",
                effect_capability="idempotency_index_only",
                request_schema_hash=request_fingerprint(schemas["scenario_execute_dry_run_input"]),
                output_schema_hash=request_fingerprint({"type": "object"}),
            ),
            backend_handler="_scenario_execute_dry_run",
            tool_result_repair_guidance=(
                "不要无意义重复执行相同场景。先根据执行失败、断言差异或变量缺失定位草稿问题，"
                "通过 compose/validate/read 类工具生成修复版后，再在安全可行时执行 dry-run 验证。"
            ),
        ),
        "testcase.query_project_cases": ToolSpec(
            name="testcase.query_project_cases",
            version="1.0.0",
            summary=(
                "Query all HTTP and WebSocket test cases in the current project for scenario composition planning. "
                "Call this before scenario.compose_draft or batch execution. Use returned http_batch_execute_input "
                "and websocket_batch_execute_input exactly; do not infer ids from ranges."
            ),
            side_effect_class="read_only",
            replay_policy="reuse_allowed",
            required_permissions=(ProjectPermission.VIEW_CASE.value,),
            input_schema=schemas["testcase_query_project_cases_input"],
            output_schema={"type": "object"},
            backend_contract=BackendContractSpec(
                backend_name="testcase-service",
                backend_operation="query_project_cases",
                backend_contract_version="v1",
                effect_capability="receipt_first",
                request_schema_hash=request_fingerprint(schemas["testcase_query_project_cases_input"]),
                output_schema_hash=request_fingerprint({"type": "object"}),
            ),
            backend_handler="_testcase_query_project_cases",
        ),
        "testcase.execute_saved": ToolSpec(
            name="testcase.execute_saved",
            version="1.0.0",
            summary="Execute one saved HTTP test case and persist an auditable execution record.",
            side_effect_class="execution_record",
            replay_policy="require_revalidation",
            required_permissions=(ProjectPermission.EXECUTE_TEST.value,),
            input_schema=schemas["testcase_execute_saved_input"],
            output_schema={"type": "object"},
            backend_contract=BackendContractSpec(
                backend_name="testcase-service",
                backend_operation="execute_saved",
                backend_contract_version="v1",
                effect_capability="idempotency_index_only",
                request_schema_hash=request_fingerprint(schemas["testcase_execute_saved_input"]),
                output_schema_hash=request_fingerprint({"type": "object"}),
            ),
            backend_handler="_testcase_execute_saved",
            tool_result_repair_guidance=(
                "真实执行会产生业务执行记录。不要重复执行同一用例；先读取返回的 execution.status、assertion_results 和 error_message "
                "判断是否需要用户确认环境、鉴权或数据前置条件。"
            ),
        ),
        "testcase.create_saved": ToolSpec(
            name="testcase.create_saved",
            version="1.0.0",
            summary=(
                "Create a saved HTTP test case through TestCaseService. This persists business data and requires "
                "human approval before execution."
            ),
            side_effect_class="business_update",
            replay_policy="require_revalidation",
            required_permissions=(ProjectPermission.MANAGE_CASE.value,),
            input_schema=schemas["testcase_create_saved_input"],
            output_schema={"type": "object"},
            backend_contract=BackendContractSpec(
                backend_name="testcase-service",
                backend_operation="create_saved",
                backend_contract_version="v1",
                effect_capability="idempotency_index_only",
                request_schema_hash=request_fingerprint(schemas["testcase_create_saved_input"]),
                output_schema_hash=request_fingerprint({"type": "object"}),
            ),
            backend_handler="_testcase_create_saved",
            tool_result_repair_guidance=(
                "该工具会新增已保存 HTTP 测试用例，必须等待用户审批；审批前不要声称已保存。"
                "如果返回校验错误，先修正 case 字段结构，再重新提交审批。"
            ),
        ),
        "testcase.update_saved": ToolSpec(
            name="testcase.update_saved",
            version="1.0.0",
            summary=(
                "Update a saved HTTP test case through TestCaseService. This persists business data and requires "
                "human approval before execution."
            ),
            side_effect_class="business_update",
            replay_policy="require_revalidation",
            required_permissions=(ProjectPermission.MANAGE_CASE.value,),
            input_schema=schemas["testcase_update_saved_input"],
            output_schema={"type": "object"},
            backend_contract=BackendContractSpec(
                backend_name="testcase-service",
                backend_operation="update_saved",
                backend_contract_version="v1",
                effect_capability="idempotency_index_only",
                request_schema_hash=request_fingerprint(schemas["testcase_update_saved_input"]),
                output_schema_hash=request_fingerprint({"type": "object"}),
            ),
            backend_handler="_testcase_update_saved",
            tool_result_repair_guidance=(
                "该工具会覆盖已保存 HTTP 测试用例，必须等待用户审批；审批前不要声称已更新。"
                "更新前应使用真实 test_case_id，不能按范围或名称猜测 ID。"
            ),
        ),
        "testcase.update_assertions": ToolSpec(
            name="testcase.update_assertions",
            version="1.0.0",
            summary=(
                "Patch only the assertions of one saved HTTP test case. This persists business data, preserves the "
                "request configuration, and requires human approval before execution."
            ),
            side_effect_class="business_update",
            replay_policy="require_revalidation",
            required_permissions=(ProjectPermission.MANAGE_CASE.value,),
            input_schema=schemas["testcase_update_assertions_input"],
            output_schema={"type": "object"},
            backend_contract=BackendContractSpec(
                backend_name="testcase-service",
                backend_operation="update_assertions",
                backend_contract_version="v1",
                effect_capability="idempotency_index_only",
                request_schema_hash=request_fingerprint(schemas["testcase_update_assertions_input"]),
                output_schema_hash=request_fingerprint({"type": "object"}),
            ),
            backend_handler="_testcase_update_assertions",
            tool_result_repair_guidance=(
                "该工具只替换 HTTP 测试用例 assertions 字段，不覆盖 method/path/headers/body/query_params/extractors。"
                "必须使用真实 test_case_id，审批完成前不要声称已保存断言。"
            ),
        ),
        "testcase.batch_update_assertions": ToolSpec(
            name="testcase.batch_update_assertions",
            version="1.0.0",
            summary=(
                "Patch assertions for multiple saved HTTP test cases. This persists business data, preserves each "
                "request configuration, and requires human approval before execution."
            ),
            side_effect_class="business_update",
            replay_policy="require_revalidation",
            required_permissions=(ProjectPermission.MANAGE_CASE.value,),
            input_schema=schemas["testcase_batch_update_assertions_input"],
            output_schema={"type": "object"},
            backend_contract=BackendContractSpec(
                backend_name="testcase-service",
                backend_operation="batch_update_assertions",
                backend_contract_version="v1",
                effect_capability="idempotency_index_only",
                request_schema_hash=request_fingerprint(schemas["testcase_batch_update_assertions_input"]),
                output_schema_hash=request_fingerprint({"type": "object"}),
            ),
            backend_handler="_testcase_batch_update_assertions",
            tool_result_repair_guidance=(
                "批量保存 HTTP 断言必须基于同一会话工作上下文或 testcase.query_project_cases 返回的真实 ID；"
                "该工具仅替换 assertions，不覆盖请求配置。审批前不要声称已保存。"
            ),
        ),
        "testcase.batch_execute": ToolSpec(
            name="testcase.batch_execute",
            version="1.0.0",
            summary="Execute saved HTTP test cases in input order and persist auditable execution records.",
            side_effect_class="execution_record",
            replay_policy="require_revalidation",
            required_permissions=(ProjectPermission.EXECUTE_TEST.value,),
            input_schema=schemas["testcase_batch_execute_input"],
            output_schema={"type": "object"},
            backend_contract=BackendContractSpec(
                backend_name="testcase-service",
                backend_operation="batch_execute",
                backend_contract_version="v1",
                effect_capability="idempotency_index_only",
                request_schema_hash=request_fingerprint(schemas["testcase_batch_execute_input"]),
                output_schema_hash=request_fingerprint({"type": "object"}),
            ),
            backend_handler="_testcase_batch_execute",
            tool_result_repair_guidance=(
                "批量真实执行会产生多条业务执行记录。输入 ID 必须来自 testcase.query_project_cases.http_test_case_ids "
                "或 http_batch_execute_input；禁止按最小/最大 ID 推断连续区间。若返回 retry_batch_execute_input，"
                "仅在用户仍要求执行有效用例时原样使用该对象重试；不要自行重组 ID。失败后先按 executions 中的 execution id "
                "和 error/assertion 归因，不要无确认重复整批执行。"
            ),
        ),
        "websocket_testcase.execute_saved": ToolSpec(
            name="websocket_testcase.execute_saved",
            version="1.0.0",
            summary="Execute one saved WebSocket test case and persist an auditable execution record.",
            side_effect_class="execution_record",
            replay_policy="require_revalidation",
            required_permissions=(ProjectPermission.EXECUTE_TEST.value,),
            input_schema=schemas["websocket_testcase_execute_saved_input"],
            output_schema={"type": "object"},
            backend_contract=BackendContractSpec(
                backend_name="websocket-testcase-service",
                backend_operation="execute_saved",
                backend_contract_version="v1",
                effect_capability="idempotency_index_only",
                request_schema_hash=request_fingerprint(schemas["websocket_testcase_execute_saved_input"]),
                output_schema_hash=request_fingerprint({"type": "object"}),
            ),
            backend_handler="_websocket_testcase_execute_saved",
            tool_result_repair_guidance=(
                "真实 WebSocket 执行会产生业务执行记录。不要重复执行同一用例；先检查连接错误、收到消息和断言结果。"
            ),
        ),
        "websocket_testcase.create_saved": ToolSpec(
            name="websocket_testcase.create_saved",
            version="1.0.0",
            summary=(
                "Create a saved WebSocket test case through WebSocketTestCaseService. This persists business data "
                "and requires human approval before execution."
            ),
            side_effect_class="business_update",
            replay_policy="require_revalidation",
            required_permissions=(ProjectPermission.MANAGE_CASE.value,),
            input_schema=schemas["websocket_testcase_create_saved_input"],
            output_schema={"type": "object"},
            backend_contract=BackendContractSpec(
                backend_name="websocket-testcase-service",
                backend_operation="create_saved",
                backend_contract_version="v1",
                effect_capability="idempotency_index_only",
                request_schema_hash=request_fingerprint(schemas["websocket_testcase_create_saved_input"]),
                output_schema_hash=request_fingerprint({"type": "object"}),
            ),
            backend_handler="_websocket_testcase_create_saved",
            tool_result_repair_guidance=(
                "该工具会新增已保存 WebSocket 测试用例，必须等待用户审批；审批前不要声称已保存。"
                "如果返回校验错误，先修正 case 字段结构，再重新提交审批。"
            ),
        ),
        "websocket_testcase.update_saved": ToolSpec(
            name="websocket_testcase.update_saved",
            version="1.0.0",
            summary=(
                "Update a saved WebSocket test case through WebSocketTestCaseService. This persists business data "
                "and requires human approval before execution."
            ),
            side_effect_class="business_update",
            replay_policy="require_revalidation",
            required_permissions=(ProjectPermission.MANAGE_CASE.value,),
            input_schema=schemas["websocket_testcase_update_saved_input"],
            output_schema={"type": "object"},
            backend_contract=BackendContractSpec(
                backend_name="websocket-testcase-service",
                backend_operation="update_saved",
                backend_contract_version="v1",
                effect_capability="idempotency_index_only",
                request_schema_hash=request_fingerprint(schemas["websocket_testcase_update_saved_input"]),
                output_schema_hash=request_fingerprint({"type": "object"}),
            ),
            backend_handler="_websocket_testcase_update_saved",
            tool_result_repair_guidance=(
                "该工具会覆盖已保存 WebSocket 测试用例，必须等待用户审批；审批前不要声称已更新。"
                "更新前应使用真实 test_case_id，不能按范围或名称猜测 ID。"
            ),
        ),
        "websocket_testcase.update_assertions": ToolSpec(
            name="websocket_testcase.update_assertions",
            version="1.0.0",
            summary=(
                "Patch only the assertions of one saved WebSocket test case. This persists business data, preserves "
                "connection/messages configuration, and requires human approval before execution."
            ),
            side_effect_class="business_update",
            replay_policy="require_revalidation",
            required_permissions=(ProjectPermission.MANAGE_CASE.value,),
            input_schema=schemas["websocket_testcase_update_assertions_input"],
            output_schema={"type": "object"},
            backend_contract=BackendContractSpec(
                backend_name="websocket-testcase-service",
                backend_operation="update_assertions",
                backend_contract_version="v1",
                effect_capability="idempotency_index_only",
                request_schema_hash=request_fingerprint(schemas["websocket_testcase_update_assertions_input"]),
                output_schema_hash=request_fingerprint({"type": "object"}),
            ),
            backend_handler="_websocket_testcase_update_assertions",
            tool_result_repair_guidance=(
                "该工具只替换 WebSocket 测试用例 assertions 字段，不覆盖 path/headers/subprotocols/messages/timeout/extractors。"
                "必须使用真实 test_case_id，审批完成前不要声称已保存断言。"
            ),
        ),
        "websocket_testcase.batch_update_assertions": ToolSpec(
            name="websocket_testcase.batch_update_assertions",
            version="1.0.0",
            summary=(
                "Patch assertions for multiple saved WebSocket test cases. This persists business data, preserves "
                "connection/messages configuration, and requires human approval before execution."
            ),
            side_effect_class="business_update",
            replay_policy="require_revalidation",
            required_permissions=(ProjectPermission.MANAGE_CASE.value,),
            input_schema=schemas["websocket_testcase_batch_update_assertions_input"],
            output_schema={"type": "object"},
            backend_contract=BackendContractSpec(
                backend_name="websocket-testcase-service",
                backend_operation="batch_update_assertions",
                backend_contract_version="v1",
                effect_capability="idempotency_index_only",
                request_schema_hash=request_fingerprint(schemas["websocket_testcase_batch_update_assertions_input"]),
                output_schema_hash=request_fingerprint({"type": "object"}),
            ),
            backend_handler="_websocket_testcase_batch_update_assertions",
            tool_result_repair_guidance=(
                "批量保存 WebSocket 断言必须基于同一会话工作上下文或 testcase.query_project_cases 返回的真实 ID；"
                "该工具仅替换 assertions，不覆盖连接配置。审批前不要声称已保存。"
            ),
        ),
        "websocket_testcase.batch_execute": ToolSpec(
            name="websocket_testcase.batch_execute",
            version="1.0.0",
            summary="Execute saved WebSocket test cases in input order and persist auditable execution records.",
            side_effect_class="execution_record",
            replay_policy="require_revalidation",
            required_permissions=(ProjectPermission.EXECUTE_TEST.value,),
            input_schema=schemas["websocket_testcase_batch_execute_input"],
            output_schema={"type": "object"},
            backend_contract=BackendContractSpec(
                backend_name="websocket-testcase-service",
                backend_operation="batch_execute",
                backend_contract_version="v1",
                effect_capability="idempotency_index_only",
                request_schema_hash=request_fingerprint(schemas["websocket_testcase_batch_execute_input"]),
                output_schema_hash=request_fingerprint({"type": "object"}),
            ),
            backend_handler="_websocket_testcase_batch_execute",
            tool_result_repair_guidance=(
                "批量真实 WebSocket 执行会产生多条业务执行记录。输入 ID 必须来自 "
                "testcase.query_project_cases.websocket_test_case_ids 或 websocket_batch_execute_input；"
                "禁止按最小/最大 ID 推断连续区间。若返回 retry_batch_execute_input，"
                "仅在用户仍要求执行有效用例时原样使用该对象重试；不要自行重组 ID。失败后先按 executions 中的 execution id "
                "和连接/断言摘要归因，不要无确认重复整批执行。"
            ),
        ),
        "testcase.validate_schema": ToolSpec(
            name="testcase.validate_schema",
            version="1.0.0",
            summary="Validate a test case draft against platform schema.",
            side_effect_class="deterministic_compute",
            replay_policy="reuse_allowed",
            required_permissions=(ProjectPermission.VIEW_CASE.value,),
            input_schema=schemas["testcase_validate_input"],
            output_schema={"type": "object"},
            backend_contract=BackendContractSpec(
                backend_name="testcase-service",
                backend_operation="validate_schema",
                backend_contract_version="v1",
                effect_capability="idempotency_index_only",
                request_schema_hash=request_fingerprint(schemas["testcase_validate_input"]),
                output_schema_hash=request_fingerprint({"type": "object"}),
            ),
            backend_handler="_testcase_validate_schema",
            tool_result_repair_guidance=(
                "先根据 issues 修正 input.case 的字段、类型、断言或提取器结构，再再次调用 testcase.validate_schema；"
                "如果缺少真实环境、鉴权或业务私有值，只把这些阻断项交给用户。"
            ),
        ),
        "report.read_summary": ToolSpec(
            name="report.read_summary",
            version="1.0.0",
            summary="Read recent test report summaries and failure context for the current project.",
            side_effect_class="read_only",
            replay_policy="reuse_allowed",
            required_permissions=(ProjectPermission.VIEW_REPORT.value,),
            input_schema=schemas["report_summary_input"],
            output_schema={"type": "object"},
            backend_contract=BackendContractSpec(
                backend_name="report-service",
                backend_operation="read_summary",
                backend_contract_version="v1",
                effect_capability="idempotency_index_only",
                request_schema_hash=request_fingerprint(schemas["report_summary_input"]),
                output_schema_hash=request_fingerprint({"type": "object"}),
            ),
            backend_handler="_report_read_summary",
        ),
    }
