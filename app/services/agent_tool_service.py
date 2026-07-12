from __future__ import annotations

import copy
import json
import logging
import re
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Callable

from fastapi import HTTPException, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.permissions import ProjectPermission
from app.core.response import normalize_response_data
from app.core.sensitive_data import mask_sensitive, request_fingerprint
from app.models.agent import AgentRun, AgentToolCall
from app.models.project import ProjectEnvironment
from app.models.test_case import TestCase
from app.models.user import User
from app.models.websocket_test_case import WebSocketTestCase
from app.schemas.ai import AIScenarioComposeRequest, AISkillRunRequest
from app.schemas.defect import DefectCreateRequest, DefectStatusUpdateRequest, DefectUpdateRequest
from app.schemas.project import (
    ProjectEnvironmentCreateRequest,
    ProjectEnvironmentRead,
    ProjectEnvironmentUpdateRequest,
    ProjectEnvironmentVariableUpsertRequest,
)
from app.schemas.scenario import ScenarioCreateRequest, ScenarioRunRead, ScenarioUpdateRequest
from app.schemas.test_plan import TestPlanCreateRequest, TestPlanUpdateRequest
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
from app.schemas.visual_flow import FlowCreateRequest, FlowDefinition, FlowUpdateRequest
from app.services.agent_loop_service import EvidenceRefResolver
from app.services.agent_platform_tool_service import AgentPlatformToolBackend
from app.services.agent_scenario_source_service import AgentScenarioSourceService, ResolvedScenarioSource
from app.services.agent_scenario_draft_validator import AgentScenarioDraftValidator
from app.services.agent_trace import (
    trace_error,
    trace_full_payload,
    trace_info,
    trace_payload_summary,
    trace_verbose_payload,
)
from app.ai_skills.registry import get_ai_skill
from app.services.ai_skill_service import AISkillService
from app.services.permission_service import PermissionService
from app.services.project_service import ProjectService
from app.services.scenario_service import ScenarioService
from app.services.scenario_graph_validator import ScenarioGraphValidator
from app.services.test_case_service import TestCaseService
from app.services.test_report_service import TestReportService
from app.services.websocket_test_case_service import WebSocketTestCaseService


SAFE_SIDE_EFFECT_CLASSES = {"read_only", "deterministic_compute", "draft_only", "execution_record"}
AGENT_TOOL_SPEC_ITEM_ID_PREFIX = "agent-tool-spec"
ENVIRONMENT_ID_SOURCE_RULE = "Use only ids from project.read_context.object_reference_manifest.environment_ids"
ENVIRONMENT_ID_SCHEMA_DESCRIPTION = (
    f"Optional environment id. {ENVIRONMENT_ID_SOURCE_RULE}. "
    "Call project.read_context first when the current conversation has no fresh environment snapshot."
)
AI_DRAFT_OPERATIONS = {
    "http-test-case": {"generate", "expand"},
    "websocket-test-case": {"generate", "expand"},
    "scenario-composer": {"compose"},
}

logger = logging.getLogger(__name__)

_SCENARIO_COMPOSE_TOP_LEVEL_INPUT_FIELDS = frozenset(AIScenarioComposeRequest.model_fields)
_SCENARIO_COMPOSE_STRUCTURED_HINT_KEYS = frozenset({
    "nodes",
    "_scenario_context",
    "before_actions",
    "after_actions",
    "datasets",
})
_SCENARIO_COMPOSE_STRUCTURED_REQUIREMENT = (
    "根据已有用例创建自动化测试场景草稿，保留用户提供的节点顺序、变量提取、下游绑定、"
    "前置后置动作和断言意图。"
)
_SCENARIO_COMPOSE_STRUCTURED_EXTRA_REQUIREMENTS_MAX_CHARS = 8000
_SCENARIO_COMPOSE_DEFAULT_CANDIDATE_LIMIT = 8
_SCENARIO_COMPOSE_FULL_CANDIDATE_LIMIT = 50
_SCENARIO_COMPOSE_FULL_INTENT_MARKERS = (
    "全量",
    "全部",
    "所有",
    "覆盖所有",
    "全场景",
    "all ",
    "all-",
    "all_",
    "all.",
    "every",
    "full",
    "entire",
)
_OBJECT_REF_ID_RE = re.compile(r"/(?P<object_id>\d+)$")


def _tool_spec_item_id(name: str, version: str) -> str:
    return f"{AGENT_TOOL_SPEC_ITEM_ID_PREFIX}://{name}/{version}"


def _object_reference(*, object_family: str, object_type: str, object_id: int, snapshot_id: str) -> str:
    snapshot_token = request_fingerprint({"snapshot_id": snapshot_id})[:12]
    return f"object-ref://{object_family}/{object_type}/{snapshot_token}/{object_id}"


def _normalize_scenario_compose_input(payload: dict[str, Any]) -> dict[str, Any]:
    raw_input = payload.get("input") if "input" in payload else payload.get("compose_input")
    if raw_input is None:
        compose_input: dict[str, Any] = {}
    elif isinstance(raw_input, str):
        requirement = raw_input.strip()
        if not requirement:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "agent_scenario_compose_input_invalid",
                    "message": "scenario.compose_draft input string must not be empty",
                },
            )
        compose_input = {"requirement": requirement}
    elif isinstance(raw_input, dict):
        compose_input = dict(raw_input)
    else:
        try:
            compose_input = dict(raw_input)
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "agent_scenario_compose_input_invalid",
                    "message": "scenario.compose_draft input must be an object or a non-empty requirement string",
                    "input_type": type(raw_input).__name__,
                },
            ) from exc

    for field_name in _SCENARIO_COMPOSE_TOP_LEVEL_INPUT_FIELDS:
        if field_name in payload and field_name not in compose_input:
            compose_input[field_name] = payload[field_name]
    _repair_structured_scenario_compose_input(compose_input)
    return compose_input


def _repair_structured_scenario_compose_input(compose_input: dict[str, Any]) -> None:
    if compose_input.get("requirement"):
        return
    if not _looks_like_structured_scenario_compose_hint(compose_input):
        return
    compose_input["requirement"] = _SCENARIO_COMPOSE_STRUCTURED_REQUIREMENT
    http_case_ids, websocket_case_ids = _scenario_case_ids_from_structured_hint(compose_input)
    if http_case_ids and not compose_input.get("http_test_case_ids"):
        compose_input["http_test_case_ids"] = http_case_ids
    if websocket_case_ids and not compose_input.get("websocket_test_case_ids"):
        compose_input["websocket_test_case_ids"] = websocket_case_ids
    extra = _structured_scenario_compose_extra_requirements(compose_input)
    existing_extra = compose_input.get("extra_requirements")
    if isinstance(existing_extra, str) and existing_extra.strip():
        compose_input["extra_requirements"] = f"{existing_extra.strip()}\n\n{extra}"
    else:
        compose_input["extra_requirements"] = extra


def _looks_like_structured_scenario_compose_hint(compose_input: dict[str, Any]) -> bool:
    return any(key in compose_input for key in _SCENARIO_COMPOSE_STRUCTURED_HINT_KEYS)


def _scenario_case_ids_from_structured_hint(compose_input: dict[str, Any]) -> tuple[list[int], list[int]]:
    nodes = compose_input.get("nodes")
    if not isinstance(nodes, list):
        return [], []
    http_ids: list[int] = []
    websocket_ids: list[int] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        reference = node.get("reference_id")
        if reference is None and isinstance(node.get("test_case"), dict):
            reference = node["test_case"].get("reference_id")
        object_id = _object_id_from_reference(reference)
        if object_id is None:
            continue
        target = websocket_ids if isinstance(reference, str) and "/websocket" in reference else http_ids
        if object_id not in target:
            target.append(object_id)
    return http_ids, websocket_ids


def _object_id_from_reference(reference: Any) -> int | None:
    if isinstance(reference, int):
        return reference
    if not isinstance(reference, str):
        return None
    match = _OBJECT_REF_ID_RE.search(reference.strip())
    if match is None:
        return None
    return int(match.group("object_id"))


def _normalize_ai_skill_run_draft_input(raw_input: Any) -> dict[str, Any]:
    if raw_input is None:
        return {}
    if isinstance(raw_input, dict):
        return dict(raw_input)
    if isinstance(raw_input, str):
        text = raw_input.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "agent_ai_skill_run_input_invalid",
                    "message": "ai_skill.run_draft input string must be a JSON object",
                },
            ) from exc
        if not isinstance(parsed, dict):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "agent_ai_skill_run_input_invalid",
                    "message": "ai_skill.run_draft input JSON must decode to an object",
                },
            )
        return parsed
    try:
        return dict(raw_input)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "agent_ai_skill_run_input_invalid",
                "message": "ai_skill.run_draft input must be an object or JSON object string",
            },
        ) from exc


def _structured_scenario_compose_extra_requirements(compose_input: dict[str, Any]) -> str:
    structured_hint = {
        key: compose_input[key]
        for key in sorted(_SCENARIO_COMPOSE_STRUCTURED_HINT_KEYS)
        if key in compose_input
    }
    encoded = json.dumps(structured_hint, ensure_ascii=False, default=str, sort_keys=True)
    if len(encoded) > _SCENARIO_COMPOSE_STRUCTURED_EXTRA_REQUIREMENTS_MAX_CHARS:
        encoded = (
            encoded[:_SCENARIO_COMPOSE_STRUCTURED_EXTRA_REQUIREMENTS_MAX_CHARS]
            + "\n[structured_scenario_compose_hint_truncated]"
        )
    return (
        "模型上一轮把结构化场景意图误放入 scenario.compose_draft.input。"
        "请把以下内容作为场景编排要求参考，生成正式草稿；不要把该 JSON 原样作为保存入参：\n"
        f"{encoded}"
    )

def _scenario_compose_requests_full_candidate_pool(compose_input: dict[str, Any]) -> bool:
    text_parts = [
        compose_input.get("requirement"),
        compose_input.get("scenario_name"),
        compose_input.get("extra_requirements"),
    ]
    text = "\n".join(str(part) for part in text_parts if part is not None).lower()
    padded = f" {text} "
    return any(marker in padded for marker in _SCENARIO_COMPOSE_FULL_INTENT_MARKERS)


def _merge_int_lists(first: Any, second: Any) -> list[int]:
    result: list[int] = []
    for raw_items in (first, second):
        if not isinstance(raw_items, list):
            continue
        for item in raw_items:
            if isinstance(item, bool) or not isinstance(item, int):
                continue
            if item not in result:
                result.append(item)
    return result


def _expand_scenario_compose_max_nodes(compose_input: dict[str, Any], candidate_ids: dict[str, list[int]]) -> None:
    total = len(candidate_ids.get("http_test_case_ids") or []) + len(candidate_ids.get("websocket_test_case_ids") or [])
    if total <= 0:
        return
    current = compose_input.get("max_nodes")
    if not isinstance(current, int) or isinstance(current, bool) or current < total:
        compose_input["max_nodes"] = min(total, _SCENARIO_COMPOSE_FULL_CANDIDATE_LIMIT)


def _append_scenario_compose_extra_requirement(compose_input: dict[str, Any], requirement: str) -> None:
    existing = compose_input.get("extra_requirements")
    if isinstance(existing, str) and existing.strip():
        if requirement not in existing:
            compose_input["extra_requirements"] = f"{existing.strip()}\n{requirement}"
        return
    compose_input["extra_requirements"] = requirement


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
class ToolContextRequirementSource:
    source_type: str
    tool_name: str | None = None
    artifact_type: str | None = None
    artifact_class: str | None = None
    scope: str = "run"


@dataclass(frozen=True)
class ToolContextRequirement:
    name: str
    sources: tuple[ToolContextRequirementSource, ...]
    missing_error_code: str | None = None
    missing_next_action: str | None = None

    @property
    def primary_required_tool(self) -> str | None:
        for source in self.sources:
            if source.tool_name:
                return source.tool_name
        return None


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
    required_context_requirements: tuple[ToolContextRequirement, ...] = ()
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
        self.platform_backend = AgentPlatformToolBackend(db)

    def __getattr__(self, name: str):
        platform_backend = self.__dict__.get("platform_backend")
        if platform_backend is not None:
            handler = getattr(platform_backend, name, None)
            if callable(handler):
                return handler
        raise AttributeError(name)

    def execute(self, *, tool_name: str, payload: dict[str, Any], current_user: User) -> dict[str, Any]:
        started = time.perf_counter()
        trace_payload = _redact_agent_tool_payload_for_trace(tool_name=tool_name, payload=payload)
        trace_info(
            "agent_trace_tool_backend_start",
            tool_name=tool_name,
            project_id=payload.get("project_id"),
            user_id=current_user.id,
            **trace_payload_summary(payload, prefix="payload"),
        )
        trace_full_payload(
            "agent_trace_tool_backend_input_full_payload",
            trace_payload,
            prefix="payload",
            mask=True,
            tool_name=tool_name,
            project_id=payload.get("project_id"),
            user_id=current_user.id,
        )
        logger.info(
            "agent_tool_backend_execute_start tool_name=%s project_id=%s user_id=%s",
            tool_name,
            payload.get("project_id"),
            current_user.id,
        )
        try:
            route = self.router.resolve(tool_name=tool_name, backend=self)
            result = route.handler(payload, current_user)
        except Exception as exc:
            duration_ms = int((time.perf_counter() - started) * 1000)
            trace_error(
                "agent_trace_tool_backend_failed",
                tool_name=tool_name,
                project_id=payload.get("project_id"),
                user_id=current_user.id,
                duration_ms=duration_ms,
                error_type=type(exc).__name__,
                **trace_payload_summary(payload, prefix="payload"),
            )
            raise
        duration_ms = int((time.perf_counter() - started) * 1000)
        trace_info(
            "agent_trace_tool_backend_done",
            tool_name=tool_name,
            project_id=payload.get("project_id"),
            user_id=current_user.id,
            duration_ms=duration_ms,
            **trace_payload_summary(payload, prefix="payload"),
            **trace_payload_summary(result, prefix="result"),
        )
        trace_verbose_payload(
            "agent_trace_tool_backend_result_payload",
            result,
            prefix="result",
            mask=True,
            tool_name=tool_name,
            project_id=payload.get("project_id"),
            user_id=current_user.id,
            duration_ms=duration_ms,
        )
        trace_full_payload(
            "agent_trace_tool_backend_result_full_payload",
            result,
            prefix="result",
            mask=True,
            tool_name=tool_name,
            project_id=payload.get("project_id"),
            user_id=current_user.id,
            duration_ms=duration_ms,
        )
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
        environment_ids = [item["id"] for item in environments]
        generated_at = datetime.now(UTC).isoformat()
        environment_snapshot_seed = {
            "project_id": project_id,
            "environment_ids": environment_ids,
            "generated_at": generated_at,
        }
        environment_snapshot = {
            "snapshot_id": f"environment-snapshot://{request_fingerprint(environment_snapshot_seed)}",
            "object_family": "environment",
            "project_id": project_id,
            "generated_at": generated_at,
            "validity_scope": "current_agent_conversation_latest_query",
            "identity_semantics": "environment ids are volatile database row locators; re-query before execution.",
            "authoritative_for_tool_input": True,
        }
        environments_with_refs = [
            {
                **item,
                "object_ref": _object_reference(
                    object_family="environment",
                    object_type="default",
                    object_id=item["id"],
                    snapshot_id=environment_snapshot["snapshot_id"],
                ),
            }
            for item in environments
        ]
        environment_object_references = [
            {
                "id": item["id"],
                "object_ref": item["object_ref"],
                "object_type": "environment",
                "name": item["name"],
                "snapshot_id": environment_snapshot["snapshot_id"],
            }
            for item in environments_with_refs
        ]
        environment_id_manifest = {
            "environment_ids": environment_ids,
            "environment_execute_ids": environment_ids,
            "environment_refs": [item["object_ref"] for item in environments_with_refs],
            "id_source_rule": (
                "Use only these explicit environment ids from the latest project context snapshot; never infer ids "
                "from older conversation prose."
            ),
            "snapshot_id": environment_snapshot["snapshot_id"],
            "validity_scope": environment_snapshot["validity_scope"],
        }
        return {
            "project": {
                "id": project.id,
                "name": getattr(project, "name", ""),
                "description": getattr(project, "description", None),
                "created_by_id": getattr(project, "created_by_id", None),
            },
            "environments": environments_with_refs,
            "default_environment": default_environment,
            "environment_snapshot": environment_snapshot,
            "environment_id_manifest": environment_id_manifest,
            "object_reference_manifest": {
                "object_family": "environment",
                "query_tool": "project.read_context",
                **environment_id_manifest,
                "object_references": environment_object_references,
            },
        }

    def _environment_query_project_configs(self, payload: dict[str, Any], current_user: User) -> dict[str, Any]:
        project_id = _require_int(payload, "project_id")
        environment_id = self._resolve_environment_id(payload, project_id=project_id, allow_default=False)
        include_variables = _optional_bool(payload, "include_variables")
        if include_variables is None:
            include_variables = True
        service = ProjectService(self.db)
        if environment_id is not None:
            environments = [
                service.get_environment_config(
                    project_id=project_id,
                    environment_id=environment_id,
                    current_user=current_user,
                )
            ]
        else:
            environments = service.list_environment_configs(project_id=project_id, current_user=current_user)

        serialized = normalize_response_data(environments)
        if not include_variables:
            for item in serialized:
                if isinstance(item, dict):
                    item.pop("variables", None)
        environment_ids = [item.get("id") for item in serialized if isinstance(item.get("id"), int)]
        generated_at = datetime.now(UTC).isoformat()
        snapshot = {
            "snapshot_id": f"environment-config-snapshot://{request_fingerprint({'project_id': project_id, 'environment_ids': environment_ids, 'generated_at': generated_at})}",
            "object_family": "environment",
            "project_id": project_id,
            "generated_at": generated_at,
            "validity_scope": "current_agent_conversation_latest_query",
            "authoritative_for_tool_input": True,
        }
        object_references = [
            {
                "id": item["id"],
                "object_ref": _object_reference(
                    object_family="environment",
                    object_type="default",
                    object_id=item["id"],
                    snapshot_id=snapshot["snapshot_id"],
                ),
                "object_type": "environment",
                "name": item.get("name"),
                "snapshot_id": snapshot["snapshot_id"],
            }
            for item in serialized
            if isinstance(item.get("id"), int)
        ]
        return {
            "project_id": project_id,
            "environment_snapshot": snapshot,
            "environment_ids": environment_ids,
            "environments": serialized,
            "object_reference_manifest": {
                "object_family": "environment",
                "query_tool": "environment.query_project_configs",
                "environment_ids": environment_ids,
                "environment_refs": [item["object_ref"] for item in object_references],
                "snapshot_id": snapshot["snapshot_id"],
                "object_references": object_references,
            },
        }

    def _environment_create_config(self, payload: dict[str, Any], current_user: User) -> dict[str, Any]:
        project_id = _require_int(payload, "project_id")
        try:
            request = ProjectEnvironmentCreateRequest.model_validate(_require_dict(payload, "config"))
        except ValidationError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.errors()) from exc
        environment = ProjectService(self.db).create_environment(
            project_id=project_id,
            payload=request,
            current_user=current_user,
        )
        return {
            "project_id": project_id,
            "environment": normalize_response_data(ProjectEnvironmentRead.model_validate(environment)),
            "operation": "created",
        }

    def _environment_update_config(self, payload: dict[str, Any], current_user: User) -> dict[str, Any]:
        project_id = _require_int(payload, "project_id")
        environment_id = self._require_environment_selector(payload, project_id=project_id)
        try:
            request = ProjectEnvironmentUpdateRequest.model_validate(_require_dict(payload, "config"))
        except ValidationError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.errors()) from exc
        environment = ProjectService(self.db).update_environment(
            project_id=project_id,
            environment_id=environment_id,
            payload=request,
            current_user=current_user,
        )
        return {
            "project_id": project_id,
            "environment": normalize_response_data(ProjectEnvironmentRead.model_validate(environment)),
            "operation": "updated",
        }

    def _environment_delete_config(self, payload: dict[str, Any], current_user: User) -> dict[str, Any]:
        project_id = _require_int(payload, "project_id")
        environment_id = self._require_environment_selector(payload, project_id=project_id)
        ProjectService(self.db).delete_environment(
            project_id=project_id,
            environment_id=environment_id,
            current_user=current_user,
        )
        return {
            "project_id": project_id,
            "environment_id": environment_id,
            "operation": "deleted",
        }

    def _environment_upsert_variable(self, payload: dict[str, Any], current_user: User) -> dict[str, Any]:
        project_id = _require_int(payload, "project_id")
        environment_id = self._require_environment_selector(payload, project_id=project_id, allow_default=True)
        name = _require_str(payload, "name")
        value = _require_str(payload, "value")
        is_secret = _optional_bool(payload, "is_secret")
        if is_secret is None:
            is_secret = _looks_like_secret(name) or _looks_like_secret(value)
        request = ProjectEnvironmentVariableUpsertRequest(
            name=name,
            value=value,
            is_secret=is_secret,
        )
        variable = ProjectService(self.db).upsert_environment_variable(
            project_id=project_id,
            environment_id=environment_id,
            payload=request,
            current_user=current_user,
        )
        return {
            "project_id": project_id,
            "environment_id": environment_id,
            "variable": normalize_response_data(variable),
            "operation": "upserted",
        }

    def _environment_delete_variable(self, payload: dict[str, Any], current_user: User) -> dict[str, Any]:
        project_id = _require_int(payload, "project_id")
        environment_id = self._require_environment_selector(payload, project_id=project_id)
        variable_id = _optional_int(payload, "variable_id")
        variable_name = _optional_str(payload, "name")
        if variable_id is None:
            if variable_name is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="variable_id or name is required",
                )
            variables = ProjectService(self.db).list_environment_variables(
                project_id=project_id,
                environment_id=environment_id,
                current_user=current_user,
            )
            match = next((item for item in variables if item.get("name") == variable_name), None)
            if match is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="环境变量不存在")
            variable_id = int(match["id"])
        ProjectService(self.db).delete_environment_variable(
            project_id=project_id,
            environment_id=environment_id,
            variable_id=variable_id,
            current_user=current_user,
        )
        return {
            "project_id": project_id,
            "environment_id": environment_id,
            "variable_id": variable_id,
            "operation": "deleted",
        }

    def _tool_result_read_full(self, payload: dict[str, Any], current_user: User) -> dict[str, Any]:
        tool_call_id = _require_str(payload, "tool_call_id")
        output_path = _optional_str(payload, "path")
        max_chars = _optional_int(payload, "max_chars") or 64000
        if max_chars < 1000 or max_chars > 256000:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="max_chars must be between 1000 and 256000",
            )
        call = self.db.scalar(select(AgentToolCall).where(AgentToolCall.tool_call_id == tool_call_id))
        if call is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ToolCall 不存在")
        run = self.db.scalar(select(AgentRun).where(AgentRun.run_id == call.run_id))
        if run is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent run 不存在")
        self.permission_service.require_project_access(current_user, run.project_id)

        output: Any = call.output_json_redacted
        selected_output = _json_path_get(output, output_path) if output_path else output
        encoded = json.dumps(selected_output, ensure_ascii=False, default=str, sort_keys=True)
        truncated = len(encoded) > max_chars
        return {
            "tool_call_id": call.tool_call_id,
            "tool_name": call.tool_name,
            "run_id": call.run_id,
            "status": call.status,
            "path": output_path,
            "output": encoded[:max_chars] if truncated else selected_output,
            "output_truncated": truncated,
            "output_size_chars": len(encoded),
            "output_hash": call.output_hash,
            "redaction": "output_json_redacted",
        }

    def _scenario_compose_draft(self, payload: dict[str, Any], current_user: User) -> dict[str, Any]:
        project_id = _require_int(payload, "project_id")
        compose_input = _normalize_scenario_compose_input(payload)
        selector_payload = {**payload, **compose_input}
        environment_id = self._resolve_environment_id(
            selector_payload,
            project_id=project_id,
            allow_default=True,
        )
        if environment_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"code": "agent_default_environment_missing", "project_id": project_id},
            )
        resolved_source: ResolvedScenarioSource | None = None
        raw_case_source = compose_input.get("case_source")
        if isinstance(raw_case_source, dict):
            conversation_id = None
            agent_run_id = str(payload.get("_agent_run_id") or "").strip()
            if agent_run_id:
                source_run = self.db.scalar(
                    select(AgentRun).where(
                        AgentRun.run_id == agent_run_id,
                        AgentRun.project_id == project_id,
                        AgentRun.user_id == current_user.id,
                    )
                )
                if source_run is None:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                        detail={"code": "agent_scenario_case_source_invalid", "reason": "agent_run_not_accessible"},
                    )
                conversation_id = source_run.conversation_id
            resolved_source = AgentScenarioSourceService(self.db).resolve(
                project_id=project_id,
                user_id=current_user.id,
                conversation_id=conversation_id,
                case_source=raw_case_source,
                environment_id=environment_id,
            )
            explicit_http_ids = set(_merge_int_lists(compose_input.get("http_test_case_ids"), []))
            explicit_websocket_ids = set(_merge_int_lists(compose_input.get("websocket_test_case_ids"), []))
            invalid_http_ids = sorted(explicit_http_ids - set(resolved_source.http_case_ids))
            invalid_websocket_ids = sorted(explicit_websocket_ids - set(resolved_source.websocket_case_ids))
            if invalid_http_ids or invalid_websocket_ids:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail={
                        "code": "agent_scenario_case_source_invalid",
                        "reason": "explicit_case_ids_not_in_source",
                        "invalid_http_test_case_ids": invalid_http_ids,
                        "invalid_websocket_test_case_ids": invalid_websocket_ids,
                    },
                )
            compose_input["http_test_case_ids"] = list(resolved_source.http_case_ids)
            compose_input["websocket_test_case_ids"] = list(resolved_source.websocket_case_ids)
        full_candidate_pool = _scenario_compose_requests_full_candidate_pool(compose_input)
        if not compose_input.get("http_test_case_ids") and not compose_input.get("websocket_test_case_ids"):
            candidate_ids = self._default_candidate_case_ids(
                project_id=project_id,
                environment_id=environment_id,
                limit=(
                    _SCENARIO_COMPOSE_FULL_CANDIDATE_LIMIT
                    if full_candidate_pool
                    else _SCENARIO_COMPOSE_DEFAULT_CANDIDATE_LIMIT
                ),
            )
            compose_input.update(candidate_ids)
            if full_candidate_pool:
                _expand_scenario_compose_max_nodes(compose_input, candidate_ids)
                _append_scenario_compose_extra_requirement(
                    compose_input,
                    "Full-coverage request: cover every candidate case supplied by the backend candidate pool unless the case is invalid or unavailable.",
                )
            logger.info(
                "agent_tool_default_scenario_candidates_selected project_id=%s environment_id=%s http_count=%s websocket_count=%s",
                project_id,
                environment_id,
                len(candidate_ids["http_test_case_ids"]),
                len(candidate_ids["websocket_test_case_ids"]),
            )
        elif full_candidate_pool:
            candidate_ids = self._default_candidate_case_ids(
                project_id=project_id,
                environment_id=environment_id,
                limit=_SCENARIO_COMPOSE_FULL_CANDIDATE_LIMIT,
            )
            compose_input["http_test_case_ids"] = _merge_int_lists(
                compose_input.get("http_test_case_ids"),
                candidate_ids["http_test_case_ids"],
            )
            compose_input["websocket_test_case_ids"] = _merge_int_lists(
                compose_input.get("websocket_test_case_ids"),
                candidate_ids["websocket_test_case_ids"],
            )
            _expand_scenario_compose_max_nodes(compose_input, candidate_ids)
            _append_scenario_compose_extra_requirement(
                compose_input,
                "Full-coverage request: backend expanded the candidate id set from current project inventory; do not omit supplied candidates because of model context truncation.",
            )
        # scenario.compose_draft is declared draft_only. Candidate execution and
        # self-validation belong to explicit execution tools and must never cross
        # this Tool's effect boundary, even when the model requests them.
        compose_input["execute_candidates"] = False
        compose_input["self_validate"] = False
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
        draft = normalize_response_data(result)
        if isinstance(draft, dict) and resolved_source is not None:
            draft["evidence_sources"] = [dict(item) for item in resolved_source.evidence_sources]
            draft["case_source_summary"] = {
                "case_snapshot_id": resolved_source.case_snapshot_id,
                "http_test_case_ids": list(resolved_source.http_case_ids),
                "websocket_test_case_ids": list(resolved_source.websocket_case_ids),
                "case_count": len(resolved_source.case_snapshots),
            }
        if isinstance(draft, dict) and isinstance(draft.get("scenario"), dict):
            graph_result = ScenarioGraphValidator().validate_and_repair(draft["scenario"])
            draft["scenario"] = graph_result.scenario
            draft["graph_validation"] = graph_result.validation
            draft["graph_repair"] = graph_result.repair
            if resolved_source is not None:
                validator = AgentScenarioDraftValidator()
                grounding_result = validator.ground(
                    draft=draft["scenario"],
                    source=resolved_source,
                )
                draft["scenario_grounding"] = grounding_result.grounding
                quality_result = validator.validate(
                    draft=grounding_result.scenario,
                    source=resolved_source,
                )
                draft["scenario"] = quality_result.scenario
                draft["scenario_validation"] = quality_result.validation
                draft["graph_validation"] = quality_result.validation["graph_validation"]
                draft["graph_repair"] = quality_result.validation["graph_repair"]
                if not quality_result.valid:
                    draft["error"] = {
                        "code": "agent_scenario_draft_invalid",
                        "message": "Scenario draft failed authoritative reference and evidence validation.",
                    }
        return {"draft": draft}

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

    def _require_environment_selector(
        self,
        payload: dict[str, Any],
        *,
        project_id: int,
        allow_default: bool = False,
    ) -> int:
        environment_id = self._resolve_environment_id(
            payload,
            project_id=project_id,
            allow_default=allow_default,
        )
        if environment_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "environment_id, environment_reference, or environment_name is required. "
                    "Call project.read_context or environment.query_project_configs first."
                ),
            )
        return environment_id

    def _resolve_environment_id(
        self,
        payload: dict[str, Any],
        *,
        project_id: int,
        allow_default: bool,
    ) -> int | None:
        environment_id = _optional_int(payload, "environment_id")
        if environment_id is not None:
            return environment_id

        environment_reference = _optional_str(payload, "environment_reference")
        if environment_reference is not None:
            object_id = _object_id_from_reference(environment_reference)
            if object_id is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="environment_reference must be an object-ref returned by project.read_context or environment.query_project_configs",
                )
            return object_id

        environment_name = _optional_str(payload, "environment_name")
        if environment_name is not None:
            normalized = environment_name.casefold()
            for environment in self._project_environments(project_id):
                if str(environment.get("name") or "").casefold() == normalized:
                    return int(environment["id"])
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="环境不存在")

        if allow_default:
            default_environment = self._default_environment(project_id)
            if default_environment is not None:
                return int(default_environment["id"])
        return None

    def _default_candidate_case_ids(
        self,
        *,
        project_id: int,
        environment_id: int,
        limit: int = _SCENARIO_COMPOSE_DEFAULT_CANDIDATE_LIMIT,
    ) -> dict[str, list[int]]:
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
        detail_level = _optional_str(payload, "detail_level") or "summary"
        if detail_level not in {"summary", "assertions", "selected", "full", "execution_ready"}:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="detail_level must be one of: summary, assertions, selected, full, execution_ready",
            )
        payload_detail_level = "assertions" if detail_level == "selected" else detail_level
        requested_http_ids = _optional_int_array(payload, "test_case_ids")
        requested_websocket_ids = _optional_int_array(payload, "websocket_test_case_ids")
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
        if requested_http_ids is not None:
            http_query = http_query.where(TestCase.id.in_(requested_http_ids))
        http_cases = list(self.db.scalars(http_query.order_by(TestCase.id.asc())).all())
        websocket_cases: list[WebSocketTestCase] = []
        if include_websocket:
            websocket_query = select(WebSocketTestCase).where(WebSocketTestCase.project_id == project_id)
            if environment_id is not None:
                websocket_query = websocket_query.where(
                    (WebSocketTestCase.environment_id == environment_id) | (WebSocketTestCase.environment_id.is_(None))
                )
            if requested_websocket_ids is not None:
                websocket_query = websocket_query.where(WebSocketTestCase.id.in_(requested_websocket_ids))
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
        generated_at = datetime.now(UTC).isoformat()
        snapshot_seed = {
            "project_id": project_id,
            "environment_id": environment_id,
            "include_websocket": include_websocket,
            "detail_level": detail_level,
            "requested_http_test_case_ids": requested_http_ids,
            "requested_websocket_test_case_ids": requested_websocket_ids,
            "http_test_case_ids": http_ids,
            "websocket_test_case_ids": websocket_ids,
            "generated_at": generated_at,
        }
        case_snapshot = {
            "snapshot_id": f"case-snapshot://{request_fingerprint(snapshot_seed)}",
            "object_family": "test_case",
            "project_id": project_id,
            "environment_id": environment_id,
            "generated_at": generated_at,
            "validity_scope": "current_agent_conversation_latest_query",
            "intent": detail_level,
            "execution_ready": detail_level == "execution_ready",
            "identity_semantics": "test case ids are volatile database row locators; re-query before writes or execution.",
            "authoritative_for_tool_input": True,
        }
        http_case_payloads = [
            self._http_case_payload_for_detail_level(
                item,
                object_ref=_object_reference(
                    object_family="test_case",
                    object_type="http",
                    object_id=item.id,
                    snapshot_id=case_snapshot["snapshot_id"],
                ),
                detail_level=payload_detail_level,
            )
            for item in http_cases
        ]
        websocket_case_payloads = [
            self._websocket_case_payload_for_detail_level(
                item,
                object_ref=_object_reference(
                    object_family="test_case",
                    object_type="websocket",
                    object_id=item.id,
                    snapshot_id=case_snapshot["snapshot_id"],
                ),
                detail_level=payload_detail_level,
            )
            for item in websocket_cases
        ]
        http_refs = [item["object_ref"] for item in http_case_payloads]
        websocket_refs = [item["object_ref"] for item in websocket_case_payloads]
        if http_batch_input is not None:
            http_batch_input["object_references"] = http_refs
            http_batch_input["case_snapshot_id"] = case_snapshot["snapshot_id"]
        if websocket_batch_input is not None:
            websocket_batch_input["object_references"] = websocket_refs
            websocket_batch_input["case_snapshot_id"] = case_snapshot["snapshot_id"]
        object_references = [
            {
                "id": item["id"],
                "object_ref": item["object_ref"],
                "object_type": "http_test_case",
                "name": item["name"],
                "method": item["method"],
                "path": item["path"],
                "snapshot_id": case_snapshot["snapshot_id"],
            }
            for item in http_case_payloads
        ] + [
            {
                "id": item["id"],
                "object_ref": item["object_ref"],
                "object_type": "websocket_test_case",
                "name": item["name"],
                "path": item["path"],
                "snapshot_id": case_snapshot["snapshot_id"],
            }
            for item in websocket_case_payloads
        ]
        case_id_manifest = {
            "http_test_case_ids": http_ids,
            "websocket_test_case_ids": websocket_ids,
            "http_assertion_update_ids": http_ids,
            "websocket_assertion_update_ids": websocket_ids,
            "http_test_case_refs": http_refs,
            "websocket_test_case_refs": websocket_refs,
            "id_source_rule": (
                "Use only these explicit ids from the latest query snapshot; never infer continuous numeric ranges "
                "or reuse ids from older conversation prose."
            ),
            "snapshot_id": case_snapshot["snapshot_id"],
            "validity_scope": case_snapshot["validity_scope"],
        }
        object_reference_manifest = {
            "object_family": "test_case",
            "query_tool": "testcase.query_project_cases",
            **case_id_manifest,
            "object_references": object_references,
        }
        case_display_rows = [
            self._case_display_row(item, case_type="http")
            for item in http_case_payloads
        ] + [
            self._case_display_row(item, case_type="websocket")
            for item in websocket_case_payloads
        ]
        return {
            "project_id": project_id,
            "environment_id": environment_id,
            "detail_level": detail_level,
            "http_total": len(http_cases),
            "websocket_total": len(websocket_cases),
            "case_result_policy": {
                "detail_level": detail_level,
                "default_detail_level": "summary",
                "available_detail_levels": ["summary", "assertions", "selected", "full", "execution_ready"],
                "query_mode_semantics": {
                    "summary": "Inventory and display mode. Returns the full id/name/status manifest with large request fields omitted.",
                    "assertions": "Selected-case analysis mode. Use with explicit ids when assertion/extractor details are needed.",
                    "selected": "Alias of assertions for selected-case analysis.",
                    "full": "Selected-case deep inspection mode. Use only for a small explicit id set.",
                    "execution_ready": "Action manifest mode. Required immediately before batch execute or batch assertion save tools.",
                },
                "execution_ready": detail_level == "execution_ready",
                "summary_mode_omits": ["headers", "query_params", "body", "assertions", "extractors"],
                "assertions_mode_omits": ["headers", "query_params", "body"],
                "detail_fetch_hint": (
                    "For assertion or extractor analysis, call detail_level='summary' first, then re-query selected "
                    "test_case_ids or websocket_test_case_ids with detail_level='assertions' or 'full'. Before any "
                    "batch execution or batch assertion save, re-query the exact target set with "
                    "detail_level='execution_ready' and copy the returned *_batch_execute_input/case_snapshot_id."
                ),
                "large_task_strategy": {
                    "strategy_id": "summary_then_selected_detail_then_execution_ready_action",
                    "steps": [
                        "query_inventory_with_detail_level_summary",
                        "iterate_explicit_case_ids_from_case_id_manifest",
                        "query_one_case_with_detail_level_assertions",
                        "deduplicate_or_repair_that_case_assertions",
                        "before_batch_side_effect_requery_targets_with_detail_level_execution_ready",
                        "copy_execution_ready_snapshot_id_and_object_references_into_batch_tool_input",
                        "continue_with_next_case_id",
                        "summarize_after_all_cases_finish",
                    ],
                    "avoid": [
                        "do_not_requery_all_cases_with_full_detail_after_truncation",
                        "do_not_ask_user_to_confirm_missing_case_details_caused_by_truncation",
                        "do_not_infer_continuous_case_id_ranges",
                        "do_not_rename_or_translate_case_names_when_summarizing",
                    ],
                },
                "display_rule": (
                    "When summarizing test cases, copy id/name/method/path/status exactly from case_display_rows "
                    "or http_test_cases/websocket_test_cases. Never infer, translate, rewrite, or reuse names "
                    "from older conversation text for a returned id."
                ),
            },
            "case_snapshot": case_snapshot,
            "case_id_manifest": case_id_manifest,
            "object_reference_manifest": object_reference_manifest,
            "case_display_rows": case_display_rows,
            "case_status_summary": self._case_status_summary(case_display_rows),
            "case_attention_rows": self._case_attention_rows(case_display_rows),
            "http_test_case_ids": http_ids,
            "websocket_test_case_ids": websocket_ids,
            "http_batch_execute_input": http_batch_input,
            "websocket_batch_execute_input": websocket_batch_input,
            "http_test_cases": http_case_payloads,
            "websocket_test_cases": websocket_case_payloads,
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
        case_payload = _normalize_case_payload_for_model_validation(_require_dict(payload, "case"))
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
        case_payload = _normalize_case_payload_for_model_validation(_require_dict(payload, "case"))
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
        case_payload = _normalize_case_payload_for_model_validation(_require_dict(payload, "case"))
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
        case_payload = _normalize_case_payload_for_model_validation(_require_dict(payload, "case"))
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
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={
                    "code": code,
                    "message": (
                        "Batch execution contains stale or deleted case IDs. Re-query project cases before retrying."
                    ),
                    invalid_key: invalid_ids,
                    "valid_case_ids": [case_id for case_id in unique_ids if case_id in existing_ids],
                    "required_tool": "testcase.query_project_cases",
                    "next_action": "refresh_case_snapshot_before_retry",
                    "repair_instruction": (
                        "Call testcase.query_project_cases again and retry only with ids from the latest snapshot. "
                        "Do not filter stale ids and continue from historical prose."
                    ),
                },
            )

    @staticmethod
    def _http_case_payload(item: TestCase, *, object_ref: str | None = None) -> dict[str, Any]:
        return {
            "id": item.id,
            "object_ref": object_ref,
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

    @classmethod
    def _http_case_payload_for_detail_level(
        cls,
        item: TestCase,
        *,
        object_ref: str | None,
        detail_level: str,
    ) -> dict[str, Any]:
        full = cls._http_case_payload(item, object_ref=object_ref)
        if detail_level == "full":
            return full
        summary = {
            "id": full["id"],
            "object_ref": full["object_ref"],
            "name": full["name"],
            "description": full["description"],
            "method": full["method"],
            "path": full["path"],
            "environment_id": full["environment_id"],
            "environment_ids": full["environment_ids"],
            "last_execution_status": full["last_execution_status"],
            "assertion_count": len(full["assertions"] or []),
            "extractor_count": len(full["extractors"] or []),
            "has_headers": bool(full["headers"]),
            "has_query_params": bool(full["query_params"]),
            "has_body": full["body"] is not None,
        }
        if detail_level == "assertions":
            summary["assertions"] = full["assertions"]
            summary["extractors"] = full["extractors"]
        return summary

    @staticmethod
    def _case_display_row(item: dict[str, Any], *, case_type: str) -> dict[str, Any]:
        row = {
            "case_type": case_type,
            "id": item["id"],
            "object_ref": item.get("object_ref"),
            "name": item["name"],
            "path": item["path"],
            "environment_id": item.get("environment_id"),
            "environment_ids": item.get("environment_ids") or [],
            "last_execution_status": item.get("last_execution_status"),
            "display_name": f"{item['name']}（ID: {item['id']}）",
            "name_source": "testcase.query_project_cases",
        }
        if case_type == "http":
            row["method"] = item.get("method")
        return row

    @staticmethod
    def _case_status_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "total": len(rows),
            "by_type": {},
            "by_status": {},
        }
        for row in rows:
            case_type = row["case_type"]
            status_value = row.get("last_execution_status") or "status_missing"
            summary["by_type"][case_type] = summary["by_type"].get(case_type, 0) + 1
            summary["by_status"][status_value] = summary["by_status"].get(status_value, 0) + 1
        return summary

    @staticmethod
    def _case_attention_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        attention_rows: list[dict[str, Any]] = []
        for row in rows:
            status_value = row.get("last_execution_status")
            if status_value == "passed":
                continue
            attention = dict(row)
            if status_value == "failed":
                attention["attention_reason"] = "last_execution_failed"
            elif status_value == "untested":
                attention["attention_reason"] = "not_executed"
            else:
                attention["attention_reason"] = "status_missing"
            attention_rows.append(attention)
        return attention_rows

    @staticmethod
    def _websocket_case_payload(item: WebSocketTestCase, *, object_ref: str | None = None) -> dict[str, Any]:
        return {
            "id": item.id,
            "object_ref": object_ref,
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

    @classmethod
    def _websocket_case_payload_for_detail_level(
        cls,
        item: WebSocketTestCase,
        *,
        object_ref: str | None,
        detail_level: str,
    ) -> dict[str, Any]:
        full = cls._websocket_case_payload(item, object_ref=object_ref)
        if detail_level == "full":
            return full
        summary = {
            "id": full["id"],
            "object_ref": full["object_ref"],
            "name": full["name"],
            "description": full["description"],
            "path": full["path"],
            "environment_id": full["environment_id"],
            "environment_ids": full["environment_ids"],
            "receive_count": full["receive_count"],
            "last_execution_status": full["last_execution_status"],
            "assertion_count": len(full["assertions"] or []),
            "extractor_count": len(full["extractors"] or []),
            "message_count": len(full["messages"] or []),
            "has_headers": bool(full["headers"]),
            "has_subprotocols": bool(full["subprotocols"]),
        }
        if detail_level == "assertions":
            summary["assertions"] = full["assertions"]
            summary["extractors"] = full["extractors"]
        return summary

    def _ai_skill_run_draft(self, payload: dict[str, Any], current_user: User) -> dict[str, Any]:
        project_id = _require_int(payload, "project_id")
        skill_id = _require_str(payload, "skill_id")
        operation = _require_str(payload, "operation")
        if operation not in AI_DRAFT_OPERATIONS.get(skill_id, set()):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "ai_skill_operation_not_allowed_for_agent_draft"},
            )
        environment_id = _optional_int(payload, "environment_id")
        if environment_id is None and self._ai_skill_operation_requires_environment(
            skill_id=skill_id,
            operation=operation,
        ):
            default_environment = self._default_environment(project_id)
            if default_environment is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={"code": "agent_default_environment_missing", "project_id": project_id},
                )
            environment_id = int(default_environment["id"])
            logger.info(
                "agent_tool_default_environment_selected tool_name=ai_skill.run_draft project_id=%s "
                "skill_id=%s operation=%s environment_id=%s",
                project_id,
                skill_id,
                operation,
                environment_id,
            )
        request = AISkillRunRequest(
            operation=operation,
            project_id=project_id,
            environment_id=environment_id,
            source_id=_optional_int(payload, "source_id"),
            input=_normalize_ai_skill_run_draft_input(payload.get("input")),
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

    def _ai_skill_operation_requires_environment(self, *, skill_id: str, operation: str) -> bool:
        try:
            skill = get_ai_skill(skill_id)
        except KeyError:
            return False
        for item in skill.package.info().operations:
            if isinstance(item, dict) and item.get("name") == operation:
                return bool(item.get("requires_environment"))
        return False

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

    def _scenario_create_saved(self, payload: dict[str, Any], current_user: User) -> dict[str, Any]:
        project_id = _require_int(payload, "project_id")
        try:
            request = ScenarioCreateRequest.model_validate(_require_dict(payload, "scenario"))
        except ValidationError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.errors()) from exc
        scenario = ScenarioService(self.db).create_scenario(
            project_id=project_id,
            payload=request,
            current_user=current_user,
        )
        return {
            "operation": "create_saved",
            "project_id": project_id,
            "scenario_id": scenario["id"],
            "scenario": normalize_response_data(scenario),
        }

    def _scenario_update_saved(self, payload: dict[str, Any], current_user: User) -> dict[str, Any]:
        project_id = _require_int(payload, "project_id")
        scenario_id = _require_int(payload, "scenario_id")
        try:
            request = ScenarioUpdateRequest.model_validate(_require_dict(payload, "scenario"))
        except ValidationError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.errors()) from exc
        scenario = ScenarioService(self.db).update_scenario(
            project_id=project_id,
            scenario_id=scenario_id,
            payload=request,
            current_user=current_user,
        )
        return {
            "operation": "update_saved",
            "project_id": project_id,
            "scenario_id": scenario_id,
            "scenario": normalize_response_data(scenario),
        }

    def _scenario_query_project_scenarios(self, payload: dict[str, Any], current_user: User) -> dict[str, Any]:
        project_id = _require_int(payload, "project_id")
        keyword = _optional_str(payload, "keyword")
        detail_level = _optional_str(payload, "detail_level") or "full"
        if detail_level not in {"summary", "full"}:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="detail_level must be one of: summary, full",
            )
        page_size = _optional_int(payload, "page_size") or 100
        page_size = max(1, min(page_size, 200))
        result = ScenarioService(self.db).list_scenarios(
            project_id=project_id,
            current_user=current_user,
            keyword=keyword,
            page=1,
            page_size=page_size,
        )
        scenarios = result["items"]
        scenario_ids = [item["id"] for item in scenarios]
        generated_at = datetime.now(UTC).isoformat()
        snapshot_seed = {
            "project_id": project_id,
            "keyword": keyword,
            "scenario_ids": scenario_ids,
            "generated_at": generated_at,
        }
        scenario_snapshot = {
            "snapshot_id": f"scenario-snapshot://{request_fingerprint(snapshot_seed)}",
            "object_family": "scenario",
            "project_id": project_id,
            "keyword": keyword,
            "generated_at": generated_at,
            "validity_scope": "current_agent_conversation_latest_query",
            "identity_semantics": "scenario ids are volatile database row locators; re-query before execution.",
            "authoritative_for_tool_input": True,
        }
        scenarios_with_refs = [
            {
                **self._scenario_payload_for_detail_level(item, detail_level=detail_level),
                "object_ref": _object_reference(
                    object_family="scenario",
                    object_type="default",
                    object_id=item["id"],
                    snapshot_id=scenario_snapshot["snapshot_id"],
                ),
            }
            for item in scenarios
        ]
        scenarios_with_refs = normalize_response_data(scenarios_with_refs)
        scenario_object_references = [
            {
                "id": item["id"],
                "object_ref": item["object_ref"],
                "object_type": "scenario",
                "name": item.get("name"),
                "snapshot_id": scenario_snapshot["snapshot_id"],
            }
            for item in scenarios_with_refs
        ]
        scenario_id_manifest = {
            "scenario_ids": scenario_ids,
            "scenario_execute_ids": scenario_ids,
            "scenario_refs": [item["object_ref"] for item in scenarios_with_refs],
            "id_source_rule": (
                "Use only these explicit scenario ids from the latest query snapshot; never infer continuous numeric "
                "ranges or reuse ids from older conversation prose."
            ),
            "snapshot_id": scenario_snapshot["snapshot_id"],
            "validity_scope": scenario_snapshot["validity_scope"],
        }
        object_reference_manifest = {
            "object_family": "scenario",
            "query_tool": "scenario.query_project_scenarios",
            **scenario_id_manifest,
            "object_references": scenario_object_references,
        }
        return {
            "project_id": project_id,
            "keyword": keyword,
            "detail_level": detail_level,
            "scenario_total": len(scenarios),
            "total": result["total"],
            "page": result["page"],
            "page_size": result["page_size"],
            "scenario_result_policy": {
                "detail_level": detail_level,
                "available_detail_levels": ["summary", "full"],
                "summary_mode_omits": ["nodes", "datasets"],
                "detail_fetch_hint": (
                    "For large projects, query summary first, then re-query with keyword/page_size or detail_level='full' "
                    "only for scenarios that need inspection."
                ),
            },
            "scenario_snapshot": scenario_snapshot,
            "scenario_id_manifest": scenario_id_manifest,
            "object_reference_manifest": object_reference_manifest,
            "scenario_ids": scenario_ids,
            "scenarios": scenarios_with_refs,
        }

    @staticmethod
    def _scenario_payload_for_detail_level(item: dict[str, Any], *, detail_level: str) -> dict[str, Any]:
        if detail_level == "full":
            return item
        nodes = item.get("nodes") or []
        datasets = item.get("datasets") or []
        return {
            "id": item.get("id"),
            "project_id": item.get("project_id"),
            "environment_id": item.get("environment_id"),
            "environment_name": item.get("environment_name"),
            "current_version": item.get("current_version"),
            "name": item.get("name"),
            "description": item.get("description"),
            "tags": item.get("tags") or [],
            "created_at": item.get("created_at"),
            "updated_at": item.get("updated_at"),
            "last_run_at": item.get("last_run_at"),
            "definition_summary": {
                "node_count": len(nodes),
                "dataset_count": len(datasets),
                "test_case_count": sum(1 for node in nodes if isinstance(node, dict) and node.get("test_case")),
                "tag_count": len(item.get("tags") or []),
            },
        }

    def _testcase_validate_schema(self, payload: dict[str, Any], current_user: User) -> dict[str, Any]:
        project_id = _require_int(payload, "project_id")
        self.permission_service.require_project_access(current_user, project_id)
        raw_case = _normalize_case_payload_for_model_validation(payload.get("case") or {})
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


def _optional_bool(payload: dict[str, Any], key: str) -> bool | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"{key} must be a boolean")
    return value


def _optional_int_array(payload: dict[str, Any], key: str) -> list[int] | None:
    value = payload.get(key)
    if value is None:
        return None
    if (
        not isinstance(value, list)
        or any(not isinstance(item, int) or isinstance(item, bool) for item in value)
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{key} must be an integer array",
        )
    return list(dict.fromkeys(value))


def _require_dict(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{key} must be an object",
        )
    return value


def _normalize_case_payload_for_model_validation(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    if normalized.get("retry_policy") is None:
        normalized.pop("retry_policy", None)
    return normalized


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


def _looks_like_secret(value: object) -> bool:
    normalized = str(value or "").casefold()
    return any(
        marker in normalized
        for marker in (
            "authorization",
            "auth",
            "bearer ",
            "cookie",
            "jwt",
            "password",
            "secret",
            "token",
            "api_key",
            "apikey",
            "access_key",
            "client_secret",
            "lingxi-auth",
        )
    )


def _redact_agent_tool_payload_for_trace(*, tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    redacted = mask_sensitive(payload)
    if (
        tool_name == "environment.upsert_variable"
        and isinstance(redacted, dict)
        and (
            payload.get("is_secret") is True
            or _looks_like_secret(payload.get("name"))
            or _looks_like_secret(payload.get("value"))
        )
    ):
        redacted["value"] = "***"
    return redacted


def _json_path_get(payload: Any, path: str | None) -> Any:
    if not path:
        return payload
    current = payload
    for raw_segment in path.split("."):
        segment = raw_segment.strip()
        if not segment:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="path contains an empty segment",
            )
        if isinstance(current, dict):
            if segment not in current:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"path segment not found: {segment}",
                )
            current = current[segment]
            continue
        if isinstance(current, list) and segment.isdigit():
            index = int(segment)
            if index >= len(current):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"path index out of range: {segment}",
                )
            current = current[index]
            continue
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"path segment cannot be applied: {segment}",
        )
    return current


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


def _schema_with_environment_reference_guidance(schema: dict[str, Any]) -> dict[str, Any]:
    guided = copy.deepcopy(schema)
    properties = guided.get("properties")
    if isinstance(properties, dict):
        for key in ("environment_id", "environment_ids"):
            field_schema = properties.get(key)
            if isinstance(field_schema, dict):
                existing_description = str(field_schema.get("description") or "").strip()
                suffix = ENVIRONMENT_ID_SCHEMA_DESCRIPTION
                if key == "environment_ids":
                    suffix = (
                        f"Environment id list. {ENVIRONMENT_ID_SOURCE_RULE}. "
                        "Call project.read_context first when the current conversation has no fresh environment snapshot."
                    )
                if ENVIRONMENT_ID_SOURCE_RULE not in existing_description:
                    field_schema["description"] = (
                        f"{existing_description} {suffix}".strip()
                        if existing_description
                        else suffix
                    )
    return guided


def _build_tool_specs() -> dict[str, ToolSpec]:
    environment_id_schema = {"type": "integer", "description": ENVIRONMENT_ID_SCHEMA_DESCRIPTION}
    case_snapshot_id_schema = {
        "type": "string",
        "description": (
            "Optional snapshot id for test case references. Use "
            "testcase.query_project_cases.object_reference_manifest.snapshot_id from the latest query."
        ),
    }
    case_object_reference_schema = {
        "type": "string",
        "description": (
            "Optional object reference handle for one saved test case. Use an object_ref from "
            "testcase.query_project_cases.object_reference_manifest.object_references in the latest query; "
            "do not invent or edit the handle."
        ),
    }
    case_object_references_schema = {
        "type": "array",
        "items": {"type": "string"},
        "minItems": 1,
        "description": (
            "Optional object reference handles for saved test cases. Use object_ref values from "
            "testcase.query_project_cases.object_reference_manifest.object_references in the latest query; "
            "do not infer handles from ids or numeric ranges."
        ),
    }
    scenario_snapshot_id_schema = {
        "type": "string",
        "description": (
            "Optional snapshot id for scenario references. Use "
            "scenario.query_project_scenarios.object_reference_manifest.snapshot_id from the latest query."
        ),
    }
    scenario_object_reference_schema = {
        "type": "string",
        "description": (
            "Optional object reference handle for one saved scenario. Use an object_ref from "
            "scenario.query_project_scenarios.object_reference_manifest.object_references in the latest query; "
            "do not invent or edit the handle."
        ),
    }
    environment_snapshot_id_schema = {
        "type": "string",
        "description": (
            "Optional snapshot id for environment references. Use "
            "project.read_context.object_reference_manifest.snapshot_id from the latest project context."
        ),
    }
    environment_object_reference_schema = {
        "type": "string",
        "description": (
            "Optional object reference handle for one environment. Use an object_ref from "
            "project.read_context.object_reference_manifest.object_references in the latest project context; "
            "do not invent or edit the handle."
        ),
    }
    environment_filter_schema = {
        "type": "integer",
        "description": (
            f"Optional environment filter. {ENVIRONMENT_ID_SOURCE_RULE}. "
            "Omit it to return all project objects when no fresh environment snapshot is available."
        ),
    }
    schemas = {
        "project_input": {
            "type": "object",
            "required": ["project_id"],
            "properties": {"project_id": {"type": "integer"}},
        },
        "environment_query_project_configs_input": {
            "type": "object",
            "required": ["project_id"],
            "properties": {
                "project_id": {"type": "integer"},
                "environment_id": environment_id_schema,
                "environment_reference": environment_object_reference_schema,
                "environment_name": {
                    "type": "string",
                    "description": "Optional exact environment name such as test. Prefer ids/refs from the latest environment query when available.",
                },
                "include_variables": {
                    "type": "boolean",
                    "default": True,
                    "description": "Whether to include masked environment variables in the result. Secret values are always returned as ***.",
                },
            },
        },
        "environment_create_config_input": {
            "type": "object",
            "required": ["project_id", "config"],
            "properties": {
                "project_id": {"type": "integer"},
                "config": ProjectEnvironmentCreateRequest.model_json_schema(),
            },
        },
        "environment_update_config_input": {
            "type": "object",
            "required": ["project_id", "config"],
            "properties": {
                "project_id": {"type": "integer"},
                "environment_id": environment_id_schema,
                "environment_reference": environment_object_reference_schema,
                "environment_name": {
                    "type": "string",
                    "description": "Optional exact environment name. Prefer ids/refs from the latest environment query when available.",
                },
                "config": ProjectEnvironmentUpdateRequest.model_json_schema(),
            },
        },
        "environment_delete_config_input": {
            "type": "object",
            "required": ["project_id"],
            "properties": {
                "project_id": {"type": "integer"},
                "environment_id": environment_id_schema,
                "environment_reference": environment_object_reference_schema,
                "environment_name": {
                    "type": "string",
                    "description": "Optional exact environment name. Prefer ids/refs from the latest environment query when available.",
                },
            },
        },
        "environment_upsert_variable_input": {
            "type": "object",
            "required": ["project_id", "name", "value"],
            "properties": {
                "project_id": {"type": "integer"},
                "environment_id": environment_id_schema,
                "environment_reference": environment_object_reference_schema,
                "environment_name": {
                    "type": "string",
                    "description": "Optional exact environment name such as test. Prefer ids/refs from the latest environment query when available.",
                },
                "name": {"type": "string", "description": "Environment variable name, for example Lingxi-Auth."},
                "value": {
                    "type": "string",
                    "description": "New variable value. For bearer tokens, include the complete value exactly as supplied by the user.",
                },
                "is_secret": {
                    "type": "boolean",
                    "description": "Whether the variable is secret. Defaults to true for auth/token/cookie-like names or values.",
                },
            },
        },
        "environment_delete_variable_input": {
            "type": "object",
            "required": ["project_id"],
            "properties": {
                "project_id": {"type": "integer"},
                "environment_id": environment_id_schema,
                "environment_reference": environment_object_reference_schema,
                "environment_name": {
                    "type": "string",
                    "description": "Optional exact environment name. Prefer ids/refs from the latest environment query when available.",
                },
                "variable_id": {"type": "integer"},
                "name": {"type": "string", "description": "Variable name to delete when variable_id is unavailable."},
            },
        },
        "tool_result_read_full_input": {
            "type": "object",
            "required": ["tool_call_id"],
            "properties": {
                "tool_call_id": {
                    "type": "string",
                    "description": "ToolCall id whose redacted output_json should be read.",
                },
                "path": {
                    "type": "string",
                    "description": "Optional simple dot path inside output_json_redacted, such as case_display_rows or http_test_cases.0.",
                },
                "max_chars": {
                    "type": "integer",
                    "description": "Maximum serialized output chars to return, between 1000 and 256000. Defaults to 64000.",
                },
            },
        },
        "report_summary_input": {
            "type": "object",
            "required": ["project_id"],
            "properties": {
                "project_id": {"type": "integer"},
                "source_type": {"type": "string", "enum": ["plan", "flow"]},
                "status": {"type": "string"},
                "environment_id": environment_id_schema,
                "page_size": {
                    "type": "integer",
                    "description": "Number of recent reports to summarize, from 1 to 20. Defaults to 5.",
                },
            },
        },
        "scenario_compose_input": {
            "type": "object",
            "required": ["project_id"],
            "anyOf": [
                {"required": ["input"]},
                {"required": ["requirement"]},
            ],
            "properties": {
                "project_id": {"type": "integer"},
                "environment_id": {
                    "type": "integer",
                    "description": (
                        f"Optional for Agent; backend selects the project default environment when omitted. "
                        f"{ENVIRONMENT_ID_SOURCE_RULE}."
                    ),
                },
                "environment_reference": {
                    "type": "string",
                    "description": "Environment object-ref returned by project.read_context.",
                },
                "case_source": {
                    "type": "object",
                    "properties": {
                        "artifact_id": {"type": "string"},
                        "output_hash": {"type": "string"},
                    },
                    "required": ["artifact_id", "output_hash"],
                    "additionalProperties": False,
                },
                "requirement": {"type": "string", "minLength": 1},
                "input": {
                    "oneOf": [
                        AIScenarioComposeRequest.model_json_schema(),
                        {
                            "type": "string",
                            "minLength": 1,
                            "description": (
                                "Natural language scenario composition requirement. The backend normalizes this to "
                                "AIScenarioComposeRequest.requirement."
                            ),
                        },
                    ],
                },
            },
        },
        "scenario_query_project_scenarios_input": {
            "type": "object",
            "required": ["project_id"],
            "properties": {
                "project_id": {"type": "integer"},
                "keyword": {"type": "string"},
                "detail_level": {
                    "type": "string",
                    "enum": ["summary", "full"],
                    "description": (
                        "Controls returned scenario detail. Use summary for large projects; use full only when "
                        "the scenario definition is needed."
                    ),
                },
                "page_size": {
                    "type": "integer",
                    "description": "Number of scenarios to expose to the Agent, from 1 to 200. Defaults to 100.",
                },
            },
        },
        "scenario_create_saved_input": {
            "type": "object",
            "required": ["project_id"],
            "properties": {
                "project_id": {"type": "integer"},
                "scenario": _schema_with_environment_reference_guidance(
                    ScenarioCreateRequest.model_json_schema()
                ),
                "scenario_source": {
                    "type": "object",
                    "description": (
                        "Reference a same-project successful scenario.compose_draft artifact instead of copying full "
                        "draft JSON. Prefer artifact_id from active_artifact_handles; the backend "
                        "resolves the artifact through the ToolCall ledger before approval."
                    ),
                    "properties": {
                        "artifact_id": {"type": "string"},
                        "tool_call_id": {"type": "string"},
                        "path": {"type": "string", "default": "draft.scenario"},
                        "output_hash": {"type": "string"},
                    },
                    "anyOf": [
                        {"required": ["artifact_id", "output_hash"]},
                        {"required": ["tool_call_id", "path", "output_hash"]},
                    ],
                },
                "source_artifact": {
                    "type": "object",
                    "description": (
                        "Alias of scenario_source for artifact-native saves. Prefer scenario_source unless an "
                        "orchestrator emits the generic source_artifact envelope."
                    ),
                    "properties": {
                        "artifact_id": {"type": "string"},
                        "output_hash": {"type": "string"},
                    },
                    "required": ["artifact_id", "output_hash"],
                },
                "environment_snapshot_id": environment_snapshot_id_schema,
            },
        },
        "scenario_update_saved_input": {
            "type": "object",
            "required": ["project_id", "scenario_id"],
            "properties": {
                "project_id": {"type": "integer"},
                "scenario_id": {"type": "integer"},
                "object_reference": scenario_object_reference_schema,
                "scenario_snapshot_id": scenario_snapshot_id_schema,
                "scenario": _schema_with_environment_reference_guidance(
                    ScenarioUpdateRequest.model_json_schema()
                ),
                "scenario_source": {
                    "type": "object",
                    "description": (
                        "Reference a same-project successful scenario.compose_draft artifact instead of copying full "
                        "draft JSON. Prefer artifact_id from active_artifact_handles; the backend "
                        "resolves the artifact through the ToolCall ledger before approval."
                    ),
                    "properties": {
                        "artifact_id": {"type": "string"},
                        "tool_call_id": {"type": "string"},
                        "path": {"type": "string", "default": "draft.scenario"},
                        "output_hash": {"type": "string"},
                    },
                    "anyOf": [
                        {"required": ["artifact_id", "output_hash"]},
                        {"required": ["tool_call_id", "path", "output_hash"]},
                    ],
                },
                "source_artifact": {
                    "type": "object",
                    "description": (
                        "Alias of scenario_source for artifact-native updates. Prefer scenario_source unless an "
                        "orchestrator emits the generic source_artifact envelope."
                    ),
                    "properties": {
                        "artifact_id": {"type": "string"},
                        "output_hash": {"type": "string"},
                    },
                    "required": ["artifact_id", "output_hash"],
                },
                "environment_snapshot_id": environment_snapshot_id_schema,
            },
        },
        "ai_skill_run_draft_input": {
            "type": "object",
            "required": ["project_id", "skill_id", "operation", "input"],
            "properties": {
                "project_id": {"type": "integer"},
                "environment_id": environment_id_schema,
                "source_id": {"type": "integer"},
                "skill_id": {"type": "string", "enum": sorted(AI_DRAFT_OPERATIONS)},
                "operation": {"type": "string"},
                "input": {
                    "oneOf": [{"type": "object"}, {"type": "string"}],
                    "description": "AI skill input object. A JSON-encoded object string is accepted for model repair tolerance.",
                },
            },
        },
        "scenario_execute_dry_run_input": {
            "type": "object",
            "required": ["project_id"],
            "properties": {
                "project_id": {"type": "integer"},
                "scenario_id": {"type": "integer"},
                "object_reference": scenario_object_reference_schema,
                "environment_id": environment_id_schema,
                "environment_reference": environment_object_reference_schema,
                "scenario_snapshot_id": scenario_snapshot_id_schema,
                "environment_snapshot_id": environment_snapshot_id_schema,
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
                "environment_id": environment_filter_schema,
                "include_websocket": {"type": "boolean", "default": True},
                "detail_level": {
                    "type": "string",
                    "enum": ["summary", "assertions", "selected", "full", "execution_ready"],
                    "default": "summary",
                    "description": (
                        "Controls returned case detail. Defaults to summary. Use summary for inventory; assertions "
                        "or selected for explicit selected-case assertion/extractor analysis; full only for selected "
                        "cases that need request headers/body; execution_ready immediately before batch execute or "
                        "batch assertion save, then copy the returned *_batch_execute_input/case_snapshot_id."
                    ),
                },
                "test_case_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Optional HTTP case ids to return. Use ids from the latest case snapshot only.",
                },
                "websocket_test_case_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Optional WebSocket case ids to return. Use ids from the latest case snapshot only.",
                },
            },
        },
        "testcase_execute_saved_input": {
            "type": "object",
            "required": ["project_id"],
            "properties": {
                "project_id": {"type": "integer"},
                "test_case_id": {"type": "integer"},
                "object_reference": case_object_reference_schema,
                "environment_id": environment_id_schema,
                "case_snapshot_id": case_snapshot_id_schema,
                "environment_snapshot_id": environment_snapshot_id_schema,
            },
        },
        "testcase_create_saved_input": {
            "type": "object",
            "required": ["project_id", "case"],
            "properties": {
                "project_id": {"type": "integer"},
                "case": _schema_with_environment_reference_guidance(TestCaseCreateRequest.model_json_schema()),
                "environment_snapshot_id": environment_snapshot_id_schema,
            },
        },
        "testcase_update_saved_input": {
            "type": "object",
            "required": ["project_id", "case"],
            "properties": {
                "project_id": {"type": "integer"},
                "test_case_id": {"type": "integer"},
                "object_reference": case_object_reference_schema,
                "case": _schema_with_environment_reference_guidance(TestCaseUpdateRequest.model_json_schema()),
                "case_snapshot_id": case_snapshot_id_schema,
                "environment_snapshot_id": environment_snapshot_id_schema,
            },
        },
        "testcase_update_assertions_input": {
            "type": "object",
            "required": ["project_id", "assertions"],
            "properties": {
                "project_id": {"type": "integer"},
                "test_case_id": {"type": "integer"},
                "object_reference": case_object_reference_schema,
                "case_snapshot_id": case_snapshot_id_schema,
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
                "case_snapshot_id": case_snapshot_id_schema,
                "items": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "required": ["assertions"],
                        "properties": {
                            "test_case_id": {"type": "integer"},
                            "object_reference": case_object_reference_schema,
                            "assertions": {
                                "type": "array",
                                "items": AssertionConfig.model_json_schema(),
                            },
                        },
                    },
                    "description": (
                        "Assertion patches for saved HTTP test cases. Use only ids from "
                        "testcase.query_project_cases.case_id_manifest.http_assertion_update_ids "
                        "or http_test_case_ids; never infer a continuous numeric range."
                    ),
                },
            },
        },
        "testcase_batch_execute_input": {
            "type": "object",
            "required": ["project_id"],
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
                "object_references": case_object_references_schema,
                "environment_id": environment_id_schema,
                "case_snapshot_id": case_snapshot_id_schema,
                "environment_snapshot_id": environment_snapshot_id_schema,
            },
        },
        "websocket_testcase_execute_saved_input": {
            "type": "object",
            "required": ["project_id"],
            "properties": {
                "project_id": {"type": "integer"},
                "test_case_id": {"type": "integer"},
                "object_reference": case_object_reference_schema,
                "environment_id": environment_id_schema,
                "case_snapshot_id": case_snapshot_id_schema,
                "environment_snapshot_id": environment_snapshot_id_schema,
            },
        },
        "websocket_testcase_create_saved_input": {
            "type": "object",
            "required": ["project_id", "case"],
            "properties": {
                "project_id": {"type": "integer"},
                "case": _schema_with_environment_reference_guidance(
                    WebSocketTestCaseCreateRequest.model_json_schema()
                ),
                "environment_snapshot_id": environment_snapshot_id_schema,
            },
        },
        "websocket_testcase_update_saved_input": {
            "type": "object",
            "required": ["project_id", "case"],
            "properties": {
                "project_id": {"type": "integer"},
                "test_case_id": {"type": "integer"},
                "object_reference": case_object_reference_schema,
                "case": _schema_with_environment_reference_guidance(
                    WebSocketTestCaseUpdateRequest.model_json_schema()
                ),
                "case_snapshot_id": case_snapshot_id_schema,
                "environment_snapshot_id": environment_snapshot_id_schema,
            },
        },
        "websocket_testcase_update_assertions_input": {
            "type": "object",
            "required": ["project_id", "assertions"],
            "properties": {
                "project_id": {"type": "integer"},
                "test_case_id": {"type": "integer"},
                "object_reference": case_object_reference_schema,
                "case_snapshot_id": case_snapshot_id_schema,
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
                "case_snapshot_id": case_snapshot_id_schema,
                "items": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "required": ["assertions"],
                        "properties": {
                            "test_case_id": {"type": "integer"},
                            "object_reference": case_object_reference_schema,
                            "assertions": {
                                "type": "array",
                                "items": WebSocketAssertionConfig.model_json_schema(),
                            },
                        },
                    },
                    "description": (
                        "Assertion patches for saved WebSocket test cases. Use only ids from "
                        "testcase.query_project_cases.case_id_manifest.websocket_assertion_update_ids "
                        "or websocket_test_case_ids; never infer a continuous numeric range."
                    ),
                },
            },
        },
        "websocket_testcase_batch_execute_input": {
            "type": "object",
            "required": ["project_id"],
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
                "object_references": case_object_references_schema,
                "environment_id": environment_id_schema,
                "case_snapshot_id": case_snapshot_id_schema,
                "environment_snapshot_id": environment_snapshot_id_schema,
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

    entity_reference_schema = {
        "type": "string",
        "description": "Use an object_ref from the latest matching query tool result; do not invent or edit it.",
    }
    entity_snapshot_schema = {
        "type": "string",
        "description": "Use object_reference_manifest.snapshot_id from the latest matching query tool result.",
    }
    execution_type_schema = {
        "type": "string",
        "enum": ["http", "websocket", "scenario", "flow"],
    }
    page_properties = {
        "page": {"type": "integer", "minimum": 1, "default": 1},
        "page_size": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
    }
    schemas.update({
        "agent_run_read_summary_input": {
            "type": "object",
            "required": ["project_id", "run_id"],
            "properties": {
                "project_id": {"type": "integer"},
                "run_id": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 64,
                    "pattern": "^agent-run-[A-Za-z0-9_-]+$",
                },
            },
        },
        "execution_query_records_input": {
            "type": "object",
            "required": ["project_id"],
            "properties": {
                "project_id": {"type": "integer"},
                "execution_type": execution_type_schema,
                "status": {"type": "string"},
                "environment_id": environment_filter_schema,
                "trigger_user_id": {"type": "integer"},
                "started_from": {"type": "string", "format": "date-time"},
                "started_to": {"type": "string", "format": "date-time"},
                "keyword": {"type": "string"},
                "pagination_mode": {
                    "type": "string",
                    "enum": ["page", "cursor"],
                    "default": "page",
                },
                "cursor": {"type": "string", "maxLength": 512},
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 200,
                    "default": 50,
                },
                "include_total": {"type": "boolean", "default": False},
                **page_properties,
            },
        },
        "execution_read_detail_input": {
            "type": "object",
            "required": ["project_id", "execution_type"],
            "properties": {
                "project_id": {"type": "integer"},
                "execution_type": execution_type_schema,
                "execution_id": {"type": "integer"},
                "object_reference": entity_reference_schema,
                "view": {
                    "type": "string",
                    "enum": ["summary", "failures", "steps", "step", "artifact", "full"],
                },
                "selector": {
                    "type": "object",
                    "properties": {
                        "statuses": {
                            "type": "array",
                            "items": {"type": "string"},
                            "maxItems": 8,
                        },
                        "first_failure": {"type": "boolean"},
                        "step_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "maxItems": 200,
                        },
                        "artifact_ref": {"type": "string", "maxLength": 128},
                        "offset": {"type": "integer", "minimum": 0},
                        "max_bytes": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 65536,
                        },
                    },
                },
                "include": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": [
                            "assertions",
                            "response_summary",
                            "bindings",
                            "extractors",
                            "retries",
                            "upstream",
                        ],
                    },
                    "maxItems": 8,
                },
                "cursor": {"type": "string", "maxLength": 512},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200},
                "max_chars": {"type": "integer", "minimum": 1000, "maximum": 24000},
            },
        },
        "execution_diagnose_input": {
            "type": "object",
            "required": ["project_id", "execution_type"],
            "properties": {
                "project_id": {"type": "integer"},
                "execution_type": execution_type_schema,
                "execution_id": {"type": "integer"},
                "object_reference": entity_reference_schema,
            },
        },
        "plan_query_project_plans_input": {
            "type": "object",
            "required": ["project_id"],
            "properties": {
                "project_id": {"type": "integer"},
                "keyword": {"type": "string"},
                "enabled": {"type": "boolean"},
                "trigger_type": {"type": "string", "enum": ["manual", "cron", "webhook"]},
                "detail_level": {"type": "string", "enum": ["summary", "full"], "default": "summary"},
                **page_properties,
            },
        },
        "plan_create_saved_input": {
            "type": "object",
            "required": ["project_id", "plan"],
            "properties": {
                "project_id": {"type": "integer"},
                "plan": TestPlanCreateRequest.model_json_schema(),
                "environment_snapshot_id": environment_snapshot_id_schema,
                "scenario_snapshot_id": scenario_snapshot_id_schema,
            },
        },
        "plan_update_saved_input": {
            "type": "object",
            "required": ["project_id", "plan"],
            "properties": {
                "project_id": {"type": "integer"},
                "plan_id": {"type": "integer"},
                "object_reference": entity_reference_schema,
                "plan_snapshot_id": entity_snapshot_schema,
                "plan": TestPlanUpdateRequest.model_json_schema(),
                "environment_snapshot_id": environment_snapshot_id_schema,
                "scenario_snapshot_id": scenario_snapshot_id_schema,
            },
        },
        "plan_set_enabled_input": {
            "type": "object",
            "required": ["project_id", "enabled"],
            "properties": {
                "project_id": {"type": "integer"},
                "plan_id": {"type": "integer"},
                "object_reference": entity_reference_schema,
                "plan_snapshot_id": entity_snapshot_schema,
                "enabled": {"type": "boolean"},
                "version": {"type": "integer", "minimum": 1},
            },
        },
        "plan_execute_saved_input": {
            "type": "object",
            "required": ["project_id", "environment_id"],
            "properties": {
                "project_id": {"type": "integer"},
                "plan_id": {"type": "integer"},
                "object_reference": entity_reference_schema,
                "plan_snapshot_id": entity_snapshot_schema,
                "environment_id": environment_id_schema,
                "environment_reference": environment_object_reference_schema,
                "environment_snapshot_id": environment_snapshot_id_schema,
                "idempotency_key": {"type": "string", "minLength": 1, "maxLength": 128},
            },
        },
        "plan_query_runs_input": {
            "type": "object",
            "required": ["project_id"],
            "properties": {"project_id": {"type": "integer"}, **page_properties},
        },
        "plan_read_run_input": {
            "type": "object",
            "required": ["project_id"],
            "properties": {
                "project_id": {"type": "integer"},
                "run_id": {"type": "integer"},
                "object_reference": entity_reference_schema,
                "plan_run_snapshot_id": entity_snapshot_schema,
            },
        },
        "flow_query_project_flows_input": {
            "type": "object",
            "required": ["project_id"],
            "properties": {
                "project_id": {"type": "integer"},
                "keyword": {"type": "string"},
                "status": {"type": "string"},
                "detail_level": {"type": "string", "enum": ["summary", "full"], "default": "summary"},
                **page_properties,
            },
        },
        "flow_validate_graph_input": {
            "type": "object",
            "required": ["project_id", "definition"],
            "properties": {
                "project_id": {"type": "integer"},
                "definition": FlowDefinition.model_json_schema(),
                "executable": {"type": "boolean", "default": True},
            },
        },
        "flow_create_saved_input": {
            "type": "object",
            "required": ["project_id", "flow"],
            "properties": {
                "project_id": {"type": "integer"},
                "flow": FlowCreateRequest.model_json_schema(),
                "environment_snapshot_id": environment_snapshot_id_schema,
                "case_snapshot_id": case_snapshot_id_schema,
            },
        },
        "flow_update_saved_input": {
            "type": "object",
            "required": ["project_id", "flow"],
            "properties": {
                "project_id": {"type": "integer"},
                "flow_id": {"type": "integer"},
                "object_reference": entity_reference_schema,
                "flow_snapshot_id": entity_snapshot_schema,
                "flow": FlowUpdateRequest.model_json_schema(),
                "environment_snapshot_id": environment_snapshot_id_schema,
                "case_snapshot_id": case_snapshot_id_schema,
            },
        },
        "flow_execute_saved_input": {
            "type": "object",
            "required": ["project_id"],
            "properties": {
                "project_id": {"type": "integer"},
                "flow_id": {"type": "integer"},
                "object_reference": entity_reference_schema,
                "flow_snapshot_id": entity_snapshot_schema,
                "environment_id": environment_id_schema,
                "environment_reference": environment_object_reference_schema,
                "environment_snapshot_id": environment_snapshot_id_schema,
                "idempotency_key": {"type": "string", "minLength": 1, "maxLength": 128},
            },
        },
        "defect_query_project_defects_input": {
            "type": "object",
            "required": ["project_id"],
            "properties": {
                "project_id": {"type": "integer"},
                "keyword": {"type": "string"},
                "status": DefectStatusUpdateRequest.model_json_schema()["properties"]["status"],
                "urgency": DefectCreateRequest.model_json_schema()["properties"]["urgency"],
                "detail_level": {"type": "string", "enum": ["summary", "full"], "default": "summary"},
                **page_properties,
            },
        },
        "defect_create_saved_input": {
            "type": "object",
            "required": ["project_id", "defect"],
            "properties": {
                "project_id": {"type": "integer"},
                "defect": DefectCreateRequest.model_json_schema(),
            },
        },
        "defect_update_saved_input": {
            "type": "object",
            "required": ["project_id", "defect"],
            "properties": {
                "project_id": {"type": "integer"},
                "defect_id": {"type": "integer"},
                "object_reference": entity_reference_schema,
                "defect_snapshot_id": entity_snapshot_schema,
                "defect": DefectUpdateRequest.model_json_schema(),
            },
        },
        "defect_transition_status_input": {
            "type": "object",
            "required": ["project_id", "status"],
            "properties": {
                "project_id": {"type": "integer"},
                "defect_id": {"type": "integer"},
                "object_reference": entity_reference_schema,
                "defect_snapshot_id": entity_snapshot_schema,
                "status": DefectStatusUpdateRequest.model_json_schema()["properties"]["status"],
            },
        },
    })

    def platform_tool_spec(
        *,
        name: str,
        summary: str,
        side_effect_class: str,
        required_permissions: tuple[str, ...],
        schema_key: str,
        backend_name: str,
        backend_operation: str,
        backend_handler: str,
        repair_guidance: str | None = None,
    ) -> ToolSpec:
        input_schema = schemas[schema_key]
        output_schema = {"type": "object"}
        return ToolSpec(
            name=name,
            version="1.0.0",
            summary=summary,
            side_effect_class=side_effect_class,
            replay_policy="reuse_allowed" if side_effect_class in {"read_only", "deterministic_compute", "draft_only"} else "require_revalidation",
            required_permissions=required_permissions,
            input_schema=input_schema,
            output_schema=output_schema,
            backend_contract=BackendContractSpec(
                backend_name=backend_name,
                backend_operation=backend_operation,
                backend_contract_version="v1",
                effect_capability="idempotency_index_only",
                request_schema_hash=request_fingerprint(input_schema),
                output_schema_hash=request_fingerprint(output_schema),
            ),
            backend_handler=backend_handler,
            tool_result_repair_guidance=repair_guidance,
        )

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
        "environment.query_project_configs": ToolSpec(
            name="environment.query_project_configs",
            version="1.0.0",
            summary="Read project environment configs and masked variables for environment planning or updates.",
            side_effect_class="read_only",
            replay_policy="reuse_allowed",
            required_permissions=(ProjectPermission.VIEW_ENVIRONMENT.value,),
            input_schema=schemas["environment_query_project_configs_input"],
            output_schema={"type": "object"},
            backend_contract=BackendContractSpec(
                backend_name="project-service",
                backend_operation="environment.query_project_configs",
                backend_contract_version="v1",
                effect_capability="idempotency_index_only",
                request_schema_hash=request_fingerprint(schemas["environment_query_project_configs_input"]),
                output_schema_hash=request_fingerprint({"type": "object"}),
            ),
            backend_handler="_environment_query_project_configs",
        ),
        "environment.create_config": ToolSpec(
            name="environment.create_config",
            version="1.0.0",
            summary="Create a project environment config through ProjectService. Requires human approval.",
            side_effect_class="business_update",
            replay_policy="require_revalidation",
            required_permissions=(ProjectPermission.MANAGE_ENVIRONMENT.value,),
            input_schema=schemas["environment_create_config_input"],
            output_schema={"type": "object"},
            backend_contract=BackendContractSpec(
                backend_name="project-service",
                backend_operation="environment.create_config",
                backend_contract_version="v1",
                effect_capability="idempotency_index_only",
                request_schema_hash=request_fingerprint(schemas["environment_create_config_input"]),
                output_schema_hash=request_fingerprint({"type": "object"}),
            ),
            backend_handler="_environment_create_config",
            tool_result_repair_guidance="该工具会新增环境配置，必须等待用户审批；审批前不要声称已创建。",
        ),
        "environment.update_config": ToolSpec(
            name="environment.update_config",
            version="1.0.0",
            summary="Update a project environment config through ProjectService. Requires human approval.",
            side_effect_class="business_update",
            replay_policy="require_revalidation",
            required_permissions=(ProjectPermission.MANAGE_ENVIRONMENT.value,),
            input_schema=schemas["environment_update_config_input"],
            output_schema={"type": "object"},
            backend_contract=BackendContractSpec(
                backend_name="project-service",
                backend_operation="environment.update_config",
                backend_contract_version="v1",
                effect_capability="idempotency_index_only",
                request_schema_hash=request_fingerprint(schemas["environment_update_config_input"]),
                output_schema_hash=request_fingerprint({"type": "object"}),
            ),
            backend_handler="_environment_update_config",
            tool_result_repair_guidance="该工具会修改环境配置，必须等待用户审批；审批前不要声称已更新。",
        ),
        "environment.delete_config": ToolSpec(
            name="environment.delete_config",
            version="1.0.0",
            summary="Delete a project environment config through ProjectService. Requires human approval.",
            side_effect_class="business_update",
            replay_policy="require_revalidation",
            required_permissions=(ProjectPermission.MANAGE_ENVIRONMENT.value,),
            input_schema=schemas["environment_delete_config_input"],
            output_schema={"type": "object"},
            backend_contract=BackendContractSpec(
                backend_name="project-service",
                backend_operation="environment.delete_config",
                backend_contract_version="v1",
                effect_capability="idempotency_index_only",
                request_schema_hash=request_fingerprint(schemas["environment_delete_config_input"]),
                output_schema_hash=request_fingerprint({"type": "object"}),
            ),
            backend_handler="_environment_delete_config",
            tool_result_repair_guidance="该工具会删除环境配置，必须等待用户审批；审批前不要声称已删除。",
        ),
        "environment.upsert_variable": ToolSpec(
            name="environment.upsert_variable",
            version="1.0.0",
            summary="Create or update a project environment variable such as Lingxi-Auth. Secret values are masked in outputs. Requires human approval.",
            side_effect_class="business_update",
            replay_policy="require_revalidation",
            required_permissions=(ProjectPermission.MANAGE_ENVIRONMENT.value,),
            input_schema=schemas["environment_upsert_variable_input"],
            output_schema={"type": "object"},
            backend_contract=BackendContractSpec(
                backend_name="project-service",
                backend_operation="environment.upsert_variable",
                backend_contract_version="v1",
                effect_capability="idempotency_index_only",
                request_schema_hash=request_fingerprint(schemas["environment_upsert_variable_input"]),
                output_schema_hash=request_fingerprint({"type": "object"}),
            ),
            backend_handler="_environment_upsert_variable",
            tool_result_repair_guidance=(
                "该工具会新增或更新环境变量，必须等待用户审批；审批前不要声称已更新。"
                "认证、Token、Cookie、密码类变量必须设置 is_secret=true，最终回复不得回显明文。"
            ),
        ),
        "environment.delete_variable": ToolSpec(
            name="environment.delete_variable",
            version="1.0.0",
            summary="Delete a project environment variable by id or exact name. Requires human approval.",
            side_effect_class="business_update",
            replay_policy="require_revalidation",
            required_permissions=(ProjectPermission.MANAGE_ENVIRONMENT.value,),
            input_schema=schemas["environment_delete_variable_input"],
            output_schema={"type": "object"},
            backend_contract=BackendContractSpec(
                backend_name="project-service",
                backend_operation="environment.delete_variable",
                backend_contract_version="v1",
                effect_capability="idempotency_index_only",
                request_schema_hash=request_fingerprint(schemas["environment_delete_variable_input"]),
                output_schema_hash=request_fingerprint({"type": "object"}),
            ),
            backend_handler="_environment_delete_variable",
            tool_result_repair_guidance="该工具会删除环境变量，必须等待用户审批；审批前不要声称已删除。",
        ),
        "tool_result.read_full": ToolSpec(
            name="tool_result.read_full",
            version="1.0.0",
            summary=(
                "Read a previous ToolCall's redacted full output_json for model reasoning when compact model context "
                "or previews are insufficient."
            ),
            side_effect_class="read_only",
            replay_policy="reuse_allowed",
            required_permissions=(ProjectPermission.VIEW_PROJECT.value,),
            input_schema=schemas["tool_result_read_full_input"],
            output_schema={"type": "object"},
            backend_contract=BackendContractSpec(
                backend_name="agent-ledger",
                backend_operation="tool_result.read_full",
                backend_contract_version="v1",
                effect_capability="receipt_first",
                request_schema_hash=request_fingerprint(schemas["tool_result_read_full_input"]),
                output_schema_hash=request_fingerprint({"type": "object"}),
            ),
            backend_handler="_tool_result_read_full",
            tool_result_repair_guidance=(
                "Use this only to inspect already-redacted ToolCall output. If the returned output is still truncated, "
                "read a narrower path instead of guessing missing fields."
            ),
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
            required_context_requirements=(
                ToolContextRequirement(
                    name="case_inventory_context",
                    sources=(
                        ToolContextRequirementSource(
                            source_type="fresh_tool_execution",
                            tool_name="testcase.query_project_cases",
                            scope="run",
                        ),
                        ToolContextRequirementSource(
                            source_type="run_artifact",
                            artifact_type="test_case_query_snapshot",
                            artifact_class="AUTHORITATIVE",
                            scope="run",
                        ),
                        ToolContextRequirementSource(
                            source_type="conversation_artifact",
                            artifact_type="test_case_query_snapshot",
                            artifact_class="AUTHORITATIVE",
                            scope="conversation",
                        ),
                    ),
                    missing_error_code="scenario_compose_requires_case_query",
                    missing_next_action=(
                        "Call testcase.query_project_cases for the current project, then use the returned "
                        "test case ids when calling scenario.compose_draft."
                    ),
                ),
            ),
            missing_prerequisite_error_code="scenario_compose_requires_case_query",
            missing_prerequisite_next_action=(
                "Call testcase.query_project_cases for the current project, then use the returned "
                "test case ids when calling scenario.compose_draft."
            ),
            tool_result_repair_guidance=(
                "继续遵守 query-first。先分析候选用例用途、请求字段、响应样本和最近执行结果；"
                "场景是独立编排 artifact，测试用例只是候选资源；可修复项通过下一次 scenario.compose_draft 的 "
                "input.extra_requirements 明确补充 scenario-level before_actions、after_actions、"
                "test_case.config._scenario_context.extractions、test_case.config._scenario_context.bindings、"
                "下游 {{variable}} 请求绑定、断言、数据集或字段来源，"
                "必要且安全时可设置 input.execute_candidates=true 获取样本，保留 self_validate=true。"
            ),
        ),
        "scenario.create_saved": ToolSpec(
            name="scenario.create_saved",
            version="1.0.0",
            summary=(
                "Create a saved test scenario through ScenarioService. This persists business data and requires "
                "human approval before execution."
            ),
            side_effect_class="business_update",
            replay_policy="require_revalidation",
            required_permissions=(ProjectPermission.MANAGE_SCENARIO.value,),
            input_schema=schemas["scenario_create_saved_input"],
            output_schema={"type": "object"},
            backend_contract=BackendContractSpec(
                backend_name="scenario-service",
                backend_operation="create_saved",
                backend_contract_version="v1",
                effect_capability="idempotency_index_only",
                request_schema_hash=request_fingerprint(schemas["scenario_create_saved_input"]),
                output_schema_hash=request_fingerprint({"type": "object"}),
            ),
            backend_handler="_scenario_create_saved",
            tool_result_repair_guidance=(
                "该工具会新增正式测试场景，必须等待用户审批；审批前不要声称已经保存。"
                "如果用户要求保存同会话刚生成的草稿，复用最新 scenario.compose_draft 的 draft.scenario，"
                "不要从可见摘要重构简化 nodes。多节点依赖/上下文/前置/后置场景必须保留 "
                "_scenario_context.extractions、_scenario_context.bindings、before_actions、after_actions 和请求中的 {{variable}}。"
                "如果返回校验错误，先修正 scenario.nodes/datasets/environment_id/version 等字段后重新提交审批。"
            ),
        ),
        "scenario.update_saved": ToolSpec(
            name="scenario.update_saved",
            version="1.0.0",
            summary=(
                "Update a saved test scenario through ScenarioService. This persists business data and requires "
                "human approval before execution."
            ),
            side_effect_class="business_update",
            replay_policy="require_revalidation",
            required_permissions=(ProjectPermission.MANAGE_SCENARIO.value,),
            input_schema=schemas["scenario_update_saved_input"],
            output_schema={"type": "object"},
            backend_contract=BackendContractSpec(
                backend_name="scenario-service",
                backend_operation="update_saved",
                backend_contract_version="v1",
                effect_capability="idempotency_index_only",
                request_schema_hash=request_fingerprint(schemas["scenario_update_saved_input"]),
                output_schema_hash=request_fingerprint({"type": "object"}),
            ),
            backend_handler="_scenario_update_saved",
            tool_result_repair_guidance=(
                "该工具会覆盖正式测试场景并创建新版本，必须等待用户审批；审批前不要声称已经保存。"
                "如果用户要求把同会话草稿更新为正式场景，复用最新 scenario.compose_draft 的 draft.scenario，并保留 update version。"
                "不要把场景退化为仅包含 reference_id 的测试用例列表。"
                "更新前使用最新 scenario.query_project_scenarios 返回的 scenario_id/object_ref 和 current_version。"
            ),
        ),
        "scenario.query_project_scenarios": ToolSpec(
            name="scenario.query_project_scenarios",
            version="1.0.0",
            summary=(
                "Query saved scenarios in the current project and return explicit scenario ids for scenario dry-run."
            ),
            side_effect_class="read_only",
            replay_policy="reuse_allowed",
            required_permissions=(ProjectPermission.VIEW_SCENARIO.value,),
            input_schema=schemas["scenario_query_project_scenarios_input"],
            output_schema={"type": "object"},
            backend_contract=BackendContractSpec(
                backend_name="scenario-service",
                backend_operation="query_project_scenarios",
                backend_contract_version="v1",
                effect_capability="receipt_first",
                request_schema_hash=request_fingerprint(schemas["scenario_query_project_scenarios_input"]),
                output_schema_hash=request_fingerprint({"type": "object"}),
            ),
            backend_handler="_scenario_query_project_scenarios",
            tool_result_repair_guidance=(
                "执行 scenario.execute_dry_run 前必须使用最新 scenario.query_project_scenarios 返回的显式 scenario_ids；"
                "不要按数字范围、旧消息或用户口述猜测场景 ID。"
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
                "Use summary for inventory, assertions/full for selected detail, and execution_ready immediately "
                "before batch execution or batch assertion updates. Copy returned batch inputs exactly; do not infer ids."
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
            tool_result_repair_guidance=(
                "如果 compact view 仍缺少需要的字段，重新调用 testcase.query_project_cases，"
                "并显式传入 test_case_ids/websocket_test_case_ids 与 detail_level=selected/assertions/execution_ready。"
                "模型路径不要读取完整 ToolCall 输出；完整账本只供后端 Runtime 或前端详情查看。"
            ),
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
                "提交前必须重新调用 testcase.query_project_cases(detail_level=execution_ready) 获取目标集合的 "
                "case_snapshot_id/object_references；该工具仅替换 assertions，不覆盖请求配置。审批前不要声称已保存。"
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
                "或 http_batch_execute_input；提交前必须重新调用 testcase.query_project_cases(detail_level=execution_ready) "
                "获取目标集合的 case_snapshot_id/object_references；禁止按最小/最大 ID 推断连续区间。若 ID 校验失败，必须先重新调用 "
                "testcase.query_project_cases 获取最新 execution-ready case_snapshot，再只使用最新显式 ID 重试；不要自行过滤、重组或复用旧 ID。"
                "失败后先按 executions 中的 execution id 和 error/assertion 归因，不要无确认重复整批执行。"
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
                "提交前必须重新调用 testcase.query_project_cases(detail_level=execution_ready) 获取目标集合的 "
                "case_snapshot_id/object_references；该工具仅替换 assertions，不覆盖连接配置。审批前不要声称已保存。"
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
                "提交前必须重新调用 testcase.query_project_cases(detail_level=execution_ready) 获取目标集合的 "
                "case_snapshot_id/object_references；禁止按最小/最大 ID 推断连续区间。若 ID 校验失败，必须先重新调用 testcase.query_project_cases "
                "获取最新 execution-ready case_snapshot，再只使用最新显式 ID 重试；不要自行过滤、重组或复用旧 ID。失败后先按 executions "
                "中的 execution id 和连接/断言摘要归因，不要无确认重复整批执行。"
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
        "agent.run.read_summary": platform_tool_spec(
            name="agent.run.read_summary",
            summary="Read a bounded project-scoped Agent run diagnostic summary without raw prompts or Tool payloads.",
            side_effect_class="read_only",
            required_permissions=(ProjectPermission.VIEW_PROJECT.value,),
            schema_key="agent_run_read_summary_input",
            backend_name="agent-runtime-service",
            backend_operation="read_summary",
            backend_handler="_agent_run_read_summary",
        ),
        "execution.query_records": platform_tool_spec(
            name="execution.query_records",
            summary="Query unified HTTP, WebSocket, scenario, and visual-flow execution records with filters and stable object references.",
            side_effect_class="read_only",
            required_permissions=(ProjectPermission.VIEW_REPORT.value,),
            schema_key="execution_query_records_input",
            backend_name="execution-record-service",
            backend_operation="query_records",
            backend_handler="_execution_query_records",
        ),
        "execution.read_detail": platform_tool_spec(
            name="execution.read_detail",
            summary="Read protocol-specific request, response, assertion, retry, scenario, or flow details for one execution record.",
            side_effect_class="read_only",
            required_permissions=(ProjectPermission.VIEW_REPORT.value,),
            schema_key="execution_read_detail_input",
            backend_name="execution-record-service",
            backend_operation="read_detail",
            backend_handler="_execution_read_detail",
        ),
        "execution.diagnose": platform_tool_spec(
            name="execution.diagnose",
            summary="Use the configured AI provider to diagnose one real execution record without changing business data.",
            side_effect_class="draft_only",
            required_permissions=(ProjectPermission.VIEW_REPORT.value, ProjectPermission.ANALYZE_AI.value),
            schema_key="execution_diagnose_input",
            backend_name="ai-execution-diagnosis-service",
            backend_operation="diagnose",
            backend_handler="_execution_diagnose",
            repair_guidance="Call execution.read_detail first when evidence is incomplete; never invent logs, responses, or credentials.",
        ),
        "plan.query_project_plans": platform_tool_spec(
            name="plan.query_project_plans",
            summary="Query current project test plans and return a fresh plan snapshot with object references for later actions.",
            side_effect_class="read_only",
            required_permissions=(ProjectPermission.VIEW_PLAN.value,),
            schema_key="plan_query_project_plans_input",
            backend_name="test-plan-service",
            backend_operation="query_project_plans",
            backend_handler="_plan_query_project_plans",
        ),
        "plan.create_saved": platform_tool_spec(
            name="plan.create_saved",
            summary="Create a persisted test plan from validated scenario targets and environments; requires human approval.",
            side_effect_class="business_update",
            required_permissions=(ProjectPermission.CREATE_PLAN.value,),
            schema_key="plan_create_saved_input",
            backend_name="test-plan-service",
            backend_operation="create_saved",
            backend_handler="_plan_create_saved",
            repair_guidance="Query project environments and scenarios before creating the plan; fix validation errors before resubmitting approval.",
        ),
        "plan.update_saved": platform_tool_spec(
            name="plan.update_saved",
            summary="Update one persisted test plan using its current version and a fresh plan reference; requires human approval.",
            side_effect_class="business_update",
            required_permissions=(ProjectPermission.UPDATE_PLAN.value,),
            schema_key="plan_update_saved_input",
            backend_name="test-plan-service",
            backend_operation="update_saved",
            backend_handler="_plan_update_saved",
            repair_guidance="Refresh plan.query_project_plans after a version conflict and preserve validated targets and environment bindings.",
        ),
        "plan.set_enabled": platform_tool_spec(
            name="plan.set_enabled",
            summary="Enable or disable one persisted test plan and recalculate its schedule; requires human approval.",
            side_effect_class="business_update",
            required_permissions=(ProjectPermission.UPDATE_PLAN.value,),
            schema_key="plan_set_enabled_input",
            backend_name="test-plan-service",
            backend_operation="set_enabled",
            backend_handler="_plan_set_enabled",
            repair_guidance="Refresh the latest plan snapshot and version before retrying a conflicting enable or disable request.",
        ),
        "plan.execute_saved": platform_tool_spec(
            name="plan.execute_saved",
            summary="Queue one saved test plan for asynchronous execution and return its persisted run identity.",
            side_effect_class="execution_record",
            required_permissions=(ProjectPermission.RUN_PLAN.value,),
            schema_key="plan_execute_saved_input",
            backend_name="test-plan-service",
            backend_operation="execute_saved",
            backend_handler="_plan_execute_saved",
            repair_guidance="Use a fresh plan and environment snapshot; after acceptance inspect plan.query_runs instead of submitting duplicates.",
        ),
        "plan.query_runs": platform_tool_spec(
            name="plan.query_runs",
            summary="Query persisted test-plan run history and return fresh run references for detailed inspection.",
            side_effect_class="read_only",
            required_permissions=(ProjectPermission.VIEW_PLAN.value,),
            schema_key="plan_query_runs_input",
            backend_name="test-plan-service",
            backend_operation="query_runs",
            backend_handler="_plan_query_runs",
        ),
        "plan.read_run": platform_tool_spec(
            name="plan.read_run",
            summary="Read one test-plan run including target results, counts, status, timing, and failure information.",
            side_effect_class="read_only",
            required_permissions=(ProjectPermission.VIEW_PLAN.value,),
            schema_key="plan_read_run_input",
            backend_name="test-plan-service",
            backend_operation="read_run",
            backend_handler="_plan_read_run",
        ),
        "flow.query_project_flows": platform_tool_spec(
            name="flow.query_project_flows",
            summary="Query project visual flows and return a fresh flow snapshot with object references for later actions.",
            side_effect_class="read_only",
            required_permissions=(ProjectPermission.VIEW_FLOW.value,),
            schema_key="flow_query_project_flows_input",
            backend_name="visual-flow-service",
            backend_operation="query_project_flows",
            backend_handler="_flow_query_project_flows",
        ),
        "flow.validate_graph": platform_tool_spec(
            name="flow.validate_graph",
            summary="Deterministically validate a visual-flow DAG, node references, bindings, routes, and executable structure without saving it.",
            side_effect_class="deterministic_compute",
            required_permissions=(ProjectPermission.VIEW_FLOW.value,),
            schema_key="flow_validate_graph_input",
            backend_name="visual-flow-service",
            backend_operation="validate_graph",
            backend_handler="_flow_validate_graph",
            repair_guidance="Repair every returned graph issue and call flow.validate_graph again before requesting a save.",
        ),
        "flow.create_saved": platform_tool_spec(
            name="flow.create_saved",
            summary="Create a persisted versioned visual flow from a validated graph; requires human approval.",
            side_effect_class="business_update",
            required_permissions=(ProjectPermission.MANAGE_FLOW.value,),
            schema_key="flow_create_saved_input",
            backend_name="visual-flow-service",
            backend_operation="create_saved",
            backend_handler="_flow_create_saved",
            repair_guidance="Call flow.validate_graph first and use only real case and environment references from current project queries.",
        ),
        "flow.update_saved": platform_tool_spec(
            name="flow.update_saved",
            summary="Create a new version of one saved visual flow using optimistic locking; requires human approval.",
            side_effect_class="business_update",
            required_permissions=(ProjectPermission.MANAGE_FLOW.value,),
            schema_key="flow_update_saved_input",
            backend_name="visual-flow-service",
            backend_operation="update_saved",
            backend_handler="_flow_update_saved",
            repair_guidance="Refresh the flow snapshot after version conflicts and validate the graph before resubmitting approval.",
        ),
        "flow.execute_saved": platform_tool_spec(
            name="flow.execute_saved",
            summary="Queue one saved visual flow for asynchronous execution and return its persisted execution identity.",
            side_effect_class="execution_record",
            required_permissions=(ProjectPermission.EXECUTE_TEST.value,),
            schema_key="flow_execute_saved_input",
            backend_name="visual-flow-service",
            backend_operation="execute_saved",
            backend_handler="_flow_execute_saved",
            repair_guidance="Use fresh flow and environment references; inspect execution.read_detail before retrying a failed execution.",
        ),
        "defect.query_project_defects": platform_tool_spec(
            name="defect.query_project_defects",
            summary="Query project defects and return a fresh defect snapshot with object references for updates and transitions.",
            side_effect_class="read_only",
            required_permissions=(ProjectPermission.VIEW_DEFECT.value,),
            schema_key="defect_query_project_defects_input",
            backend_name="defect-service",
            backend_operation="query_project_defects",
            backend_handler="_defect_query_project_defects",
        ),
        "defect.create_saved": platform_tool_spec(
            name="defect.create_saved",
            summary="Create a persisted project defect from evidence-backed triage content; requires human approval.",
            side_effect_class="business_update",
            required_permissions=(ProjectPermission.CREATE_DEFECT.value,),
            schema_key="defect_create_saved_input",
            backend_name="defect-service",
            backend_operation="create_saved",
            backend_handler="_defect_create_saved",
            repair_guidance="Keep evidence factual and redacted; correct invalid fields or media ownership before resubmitting approval.",
        ),
        "defect.update_saved": platform_tool_spec(
            name="defect.update_saved",
            summary="Update one persisted defect using a fresh defect reference; requires human approval.",
            side_effect_class="business_update",
            required_permissions=(ProjectPermission.UPDATE_DEFECT.value,),
            schema_key="defect_update_saved_input",
            backend_name="defect-service",
            backend_operation="update_saved",
            backend_handler="_defect_update_saved",
            repair_guidance="Refresh defect.query_project_defects before retrying and preserve evidence that the user did not ask to replace.",
        ),
        "defect.transition_status": platform_tool_spec(
            name="defect.transition_status",
            summary="Apply one validated defect lifecycle transition using a fresh defect reference; requires human approval.",
            side_effect_class="business_update",
            required_permissions=(ProjectPermission.TRANSITION_DEFECT.value,),
            schema_key="defect_transition_status_input",
            backend_name="defect-service",
            backend_operation="transition_status",
            backend_handler="_defect_transition_status",
            repair_guidance="Use the current defect status and follow the backend lifecycle transition rules; do not skip required states.",
        ),
    }
