from __future__ import annotations

import copy
from dataclasses import asdict, dataclass
from typing import Any, Callable

from fastapi import HTTPException, status
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.permissions import ProjectPermission
from app.core.response import normalize_response_data
from app.core.sensitive_data import request_fingerprint
from app.models.user import User
from app.schemas.ai import AIScenarioComposeRequest, AISkillRunRequest
from app.schemas.scenario import ScenarioRunRead
from app.schemas.test_case import TestCaseCreateRequest
from app.services.agent_loop_service import EvidenceRefResolver
from app.services.ai_skill_service import AISkillService
from app.services.permission_service import PermissionService
from app.services.scenario_service import ScenarioService


SAFE_SIDE_EFFECT_CLASSES = {"read_only", "deterministic_compute", "draft_only", "execution_record"}
AI_DRAFT_OPERATIONS = {
    "http-test-case": {"generate", "expand"},
    "websocket-test-case": {"generate", "expand"},
    "scenario-composer": {"compose"},
}


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
class ResolvedToolPolicy:
    resolved_side_effect_class: str
    resolved_replay_policy: str
    approval_required: bool
    policy_reason: dict[str, Any]


class ToolPolicyResolver:
    def resolve(self, *, spec: ToolSpec, evidence_refs: list[dict[str, Any]]) -> ResolvedToolPolicy:
        active_refs = EvidenceRefResolver().select_policy_refs(evidence_refs)
        volatile = [
            item for item in active_refs
            if item.mutability_class in {"mutable_current", "ephemeral_latest", "external_uncontrolled"}
        ]
        replay_policy = "require_revalidation" if volatile else spec.replay_policy
        approval_required = spec.side_effect_class not in SAFE_SIDE_EFFECT_CLASSES
        return ResolvedToolPolicy(
            resolved_side_effect_class=spec.side_effect_class,
            resolved_replay_policy=replay_policy,
            approval_required=approval_required,
            policy_reason={
                "base_replay_policy": spec.replay_policy,
                "active_policy_ref_count": len(active_refs),
                "volatile_policy_ref_count": len(volatile),
                "approval_required_reason": "unsafe_side_effect" if approval_required else "safe_initial_tool",
            },
        )


class AgentToolBackend:
    def __init__(self, db: Session):
        self.db = db
        self.permission_service = PermissionService(db)

    def execute(self, *, tool_name: str, payload: dict[str, Any], current_user: User) -> dict[str, Any]:
        handlers: dict[str, Callable[[dict[str, Any], User], dict[str, Any]]] = {
            "project.read_context": self._project_read_context,
            "ai_skill.run_draft": self._ai_skill_run_draft,
            "scenario.compose_draft": self._scenario_compose_draft,
            "scenario.execute_dry_run": self._scenario_execute_dry_run,
            "testcase.validate_schema": self._testcase_validate_schema,
            "report.read_summary": self._report_read_summary,
        }
        try:
            return handlers[tool_name](payload, current_user)
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent tool backend 不存在") from exc

    def _project_read_context(self, payload: dict[str, Any], current_user: User) -> dict[str, Any]:
        project_id = _require_int(payload, "project_id")
        project = self.permission_service.require_project_access(current_user, project_id)
        return {
            "project": {
                "id": project.id,
                "name": getattr(project, "name", ""),
                "description": getattr(project, "description", None),
                "created_by_id": getattr(project, "created_by_id", None),
            }
        }

    def _scenario_compose_draft(self, payload: dict[str, Any], current_user: User) -> dict[str, Any]:
        project_id = _require_int(payload, "project_id")
        environment_id = _require_int(payload, "environment_id")
        compose_input = payload.get("input") or payload.get("compose_input") or {}
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
        self.permission_service.require_project_permission(
            current_user,
            project_id,
            ProjectPermission.VIEW_REPORT.value,
        )
        return {
            "project_id": project_id,
            "summary": {},
            "note": "report.read_summary framework adapter is ready; detailed aggregation is deferred",
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


def _build_tool_specs() -> dict[str, ToolSpec]:
    schemas = {
        "project_input": {
            "type": "object",
            "required": ["project_id"],
            "properties": {"project_id": {"type": "integer"}},
        },
        "scenario_compose_input": {
            "type": "object",
            "required": ["project_id", "environment_id", "input"],
            "properties": {
                "project_id": {"type": "integer"},
                "environment_id": {"type": "integer"},
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
        ),
        "report.read_summary": ToolSpec(
            name="report.read_summary",
            version="1.0.0",
            summary="Read report summary context.",
            side_effect_class="read_only",
            replay_policy="reuse_allowed",
            required_permissions=(ProjectPermission.VIEW_REPORT.value,),
            input_schema=copy.deepcopy(schemas["project_input"]),
            output_schema={"type": "object"},
            backend_contract=BackendContractSpec(
                backend_name="report-service",
                backend_operation="read_summary",
                backend_contract_version="v1",
                effect_capability="idempotency_index_only",
                request_schema_hash=request_fingerprint(schemas["project_input"]),
                output_schema_hash=request_fingerprint({"type": "object"}),
            ),
        ),
    }
