import ast
import copy
import hashlib
import json
import time
from datetime import datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.permissions import ProjectPermission
from app.core.variable_renderer import render_variables
from app.db.session import SessionLocal
from app.models.user import User
from app.models.visual_flow import VisualFlow, VisualFlowExecution, VisualFlowVersion
from app.repositories.visual_flow_repository import VisualFlowRepository
from app.schemas.test_case import TestCaseRequestConfig
from app.schemas.visual_flow import FlowDefinition, FlowNode
from app.schemas.websocket_test_case import WebSocketTestCaseConfig
from app.services.permission_service import PermissionService
from app.services.test_case_service import TestCaseService
from app.services.websocket_test_case_service import WebSocketTestCaseService


_MISSING = object()
_TARGET_ROOTS = {"pathParams", "query", "headers", "body", "variables", "messages"}
_HTTP_CASE_OVERRIDE_FIELDS = {
    "method", "path", "headers", "query_params", "body_type",
    "body", "assertions", "extractors", "retry_policy",
}
_WEBSOCKET_CASE_OVERRIDE_FIELDS = {
    "path", "headers", "subprotocols", "messages", "receive_count",
    "connect_timeout_ms", "receive_timeout_ms", "assertions", "extractors",
    "retry_policy",
}
_CASE_OVERRIDE_ALIASES = {
    "query": "query_params",
    "queryParams": "query_params",
    "bodyType": "body_type",
    "receiveCount": "receive_count",
    "connectTimeoutMs": "connect_timeout_ms",
    "receiveTimeoutMs": "receive_timeout_ms",
    "retryPolicy": "retry_policy",
}


class DotMap(dict):
    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


class VisualFlowService:
    def __init__(self, db: Session):
        self.db = db
        self.repository = VisualFlowRepository(db)
        self.permission_service = PermissionService(db)

    def list_flows(
        self,
        *,
        project_id: int,
        current_user: User,
        keyword: str | None,
        flow_status: str | None,
        page: int,
        page_size: int,
    ) -> dict[str, Any]:
        self._require(current_user, project_id, ProjectPermission.VIEW_FLOW.value)
        result = []
        flows, total = self.repository.list_by_project(
            project_id=project_id,
            keyword=keyword,
            flow_status=flow_status,
            page=page,
            page_size=page_size,
        )
        for flow in flows:
            version = self.repository.get_version(flow_id=flow.id, version=flow.current_version)
            result.append(
                {
                    "id": flow.id,
                    "name": flow.name,
                    "description": flow.description,
                    "status": flow.status,
                    "node_count": len((version.definition if version else {}).get("nodes", [])),
                    "current_version": flow.current_version,
                    "updated_at": flow.updated_at,
                }
            )
        return {
            "items": result,
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    def get_flow(self, *, project_id: int, flow_id: int, current_user: User) -> dict[str, Any]:
        self._require(current_user, project_id, ProjectPermission.VIEW_FLOW.value)
        flow = self._get_flow(project_id, flow_id)
        version = self.repository.get_version(flow_id=flow.id, version=flow.current_version)
        if version is None:
            raise HTTPException(status_code=404, detail="Flow version not found")
        return self._detail(flow, version.definition)

    def create_flow(self, *, project_id: int, payload, current_user: User) -> dict[str, Any]:
        self._require(current_user, project_id, ProjectPermission.MANAGE_FLOW.value)
        definition = self._prepare_definition(payload.definition, project_id=project_id)
        self._validate(definition, project_id=project_id, executable=False)
        stored = self._stored_definition(definition)
        flow, _ = self.repository.create_flow(
            project_id=project_id,
            name=payload.name,
            description=payload.description,
            definition=stored,
            definition_hash=self._hash(stored),
            user_id=current_user.id,
        )
        return self._detail(flow, stored)

    def update_flow(self, *, project_id: int, flow_id: int, payload, current_user: User) -> dict[str, Any]:
        self._require(current_user, project_id, ProjectPermission.MANAGE_FLOW.value)
        flow = self._get_flow(project_id, flow_id)
        if flow.current_version != payload.expected_version:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"message": "Flow version conflict", "current_version": flow.current_version},
            )
        definition = self._prepare_definition(payload.definition, project_id=project_id)
        self._validate(definition, project_id=project_id, executable=False)
        stored = self._stored_definition(definition)
        version = self.repository.update_flow(
            flow=flow,
            expected_version=payload.expected_version,
            name=payload.name,
            description=payload.description,
            definition=stored,
            definition_hash=self._hash(stored),
            user_id=current_user.id,
        )
        if version is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Flow version conflict")
        return self._detail(flow, stored)

    def delete_flow(self, *, project_id: int, flow_id: int, current_user: User) -> None:
        self._require(current_user, project_id, ProjectPermission.MANAGE_FLOW.value)
        flow = self._get_flow(project_id, flow_id)
        self.repository.delete_flow(flow=flow)

    def execute_saved(
        self,
        *,
        project_id: int,
        flow_id: int,
        environment_id: int | None,
        idempotency_key: str | None,
        current_user: User,
    ) -> tuple[VisualFlowExecution, int | None, list]:
        self._require(current_user, project_id, ProjectPermission.EXECUTE_TEST.value)
        existing = self._idempotent(project_id, idempotency_key)
        if existing:
            return existing, self._version_number(existing), self.repository.list_node_executions(existing.id)
        flow = self._get_flow(project_id, flow_id)
        version = self.repository.get_version(flow_id=flow.id, version=flow.current_version)
        if version is None:
            raise HTTPException(status_code=404, detail="Flow version not found")
        definition = FlowDefinition.model_validate(version.definition)
        execution = self._execute(
            definition=definition,
            project_id=project_id,
            environment_id=environment_id,
            flow_id=flow.id,
            flow_version_id=version.id,
            idempotency_key=idempotency_key,
            current_user=current_user,
        )
        return execution, version.version, self.repository.list_node_executions(execution.id)

    def enqueue_saved(
        self,
        *,
        project_id: int,
        flow_id: int,
        environment_id: int | None,
        idempotency_key: str | None,
        current_user: User,
    ) -> tuple[VisualFlowExecution, int | None, list]:
        self._require(current_user, project_id, ProjectPermission.EXECUTE_TEST.value)
        existing = self._idempotent(project_id, idempotency_key)
        if existing:
            return existing, self._version_number(existing), self.repository.list_node_executions(existing.id)
        flow = self._get_flow(project_id, flow_id)
        version = self.repository.get_version(flow_id=flow.id, version=flow.current_version)
        if version is None:
            raise HTTPException(status_code=404, detail="Flow version not found")
        definition = FlowDefinition.model_validate(version.definition)
        selected_environment_id = environment_id or definition.environment_id
        self._validate(definition, project_id=project_id, executable=True)
        if selected_environment_id is not None:
            self._require_environment(project_id, selected_environment_id)
        case_snapshots = self._case_snapshots(definition, project_id)
        execution = self.repository.create_execution(
            flow_id=flow.id,
            flow_version_id=version.id,
            project_id=project_id,
            environment_id=selected_environment_id,
            user_id=current_user.id,
            idempotency_key=idempotency_key,
            context_snapshot={
                "definition": self._mask(self._stored_definition(definition)),
                "referencedCases": self._mask(case_snapshots),
            },
            status="queued",
        )
        return execution, version.version, []

    @staticmethod
    def execute_queued_execution(execution_id: int) -> None:
        with SessionLocal() as db:
            execution = db.get(VisualFlowExecution, execution_id)
            if execution is None or execution.status not in {"queued", "running"}:
                return
            current_user = db.get(User, execution.trigger_user_id)
            if current_user is None or not current_user.is_active:
                execution.status = "failed"
                execution.finished_at = datetime.utcnow()
                db.commit()
                return
            if execution.flow_version_id is None:
                execution.status = "failed"
                execution.finished_at = datetime.utcnow()
                db.commit()
                return
            version = db.get(VisualFlowVersion, execution.flow_version_id)
            if version is None:
                execution.status = "failed"
                execution.finished_at = datetime.utcnow()
                db.commit()
                return
            try:
                definition = FlowDefinition.model_validate(version.definition)
                VisualFlowService(db)._execute(
                    definition=definition,
                    project_id=execution.project_id,
                    environment_id=execution.environment_id,
                    flow_id=execution.flow_id,
                    flow_version_id=execution.flow_version_id,
                    idempotency_key=execution.idempotency_key,
                    current_user=current_user,
                    existing_execution=execution,
                )
            except Exception:  # noqa: BLE001
                db.rollback()
                failed = db.get(VisualFlowExecution, execution_id)
                if failed is not None and failed.status in {"queued", "running"}:
                    failed.status = "failed"
                    failed.finished_at = datetime.utcnow()
                    db.commit()

    def execute_unsaved(
        self,
        *,
        project_id: int,
        definition: FlowDefinition,
        environment_id: int | None,
        idempotency_key: str | None,
        current_user: User,
    ) -> tuple[VisualFlowExecution, None, list]:
        self._require(current_user, project_id, ProjectPermission.EXECUTE_TEST.value)
        existing = self._idempotent(project_id, idempotency_key)
        if existing:
            return existing, None, self.repository.list_node_executions(existing.id)
        prepared = self._prepare_definition(definition, project_id=project_id)
        execution = self._execute(
            definition=prepared,
            project_id=project_id,
            environment_id=environment_id,
            flow_id=None,
            flow_version_id=None,
            idempotency_key=idempotency_key,
            current_user=current_user,
        )
        return execution, None, self.repository.list_node_executions(execution.id)

    def _execute(
        self,
        *,
        definition: FlowDefinition,
        project_id: int,
        environment_id: int | None,
        flow_id: int | None,
        flow_version_id: int | None,
        idempotency_key: str | None,
        current_user: User,
        existing_execution: VisualFlowExecution | None = None,
    ) -> VisualFlowExecution:
        selected_environment_id = environment_id or definition.environment_id
        self._validate(definition, project_id=project_id, executable=True)
        if selected_environment_id is not None:
            self._require_environment(project_id, selected_environment_id)

        case_snapshots = self._case_snapshots(definition, project_id)
        flow_variables = (
            self.repository.get_environment_variables(environment_id=selected_environment_id)
            if selected_environment_id is not None
            else {}
        )
        if existing_execution is None:
            execution = self.repository.create_execution(
                flow_id=flow_id,
                flow_version_id=flow_version_id,
                project_id=project_id,
                environment_id=selected_environment_id,
                user_id=current_user.id,
                idempotency_key=idempotency_key,
                context_snapshot={
                    "definition": self._mask(self._stored_definition(definition)),
                    "referencedCases": self._mask(case_snapshots),
                },
            )
        else:
            execution = existing_execution
            execution.status = "running"
            execution.started_at = datetime.utcnow()
            execution.finished_at = None
            self.db.commit()
        nodes = {node.id: node for node in definition.nodes}
        incoming = {node_id: [] for node_id in nodes}
        outgoing = {node_id: [] for node_id in nodes}
        for edge in definition.edges:
            incoming[edge.target].append(edge)
            outgoing[edge.source].append(edge)

        active_edges: set[str] = set()
        outputs: dict[str, dict[str, Any]] = {}
        fatal_failure = False
        for node_id in self._topological_order(definition):
            node = nodes[node_id]
            active = node.kind == "start" or any(edge.id in active_edges for edge in incoming[node_id])
            if not active:
                now = datetime.utcnow()
                output = self._node_output(node_id, "skipped", now, now, 0)
                outputs[node_id] = output
                self.repository.create_node_execution(
                    execution_id=execution.id,
                    node_id=node_id,
                    status="skipped",
                    request_snapshot=None,
                    output_snapshot=output,
                    error=None,
                    started_at=now,
                    finished_at=now,
                )
                continue

            started = datetime.utcnow()
            request_snapshot = None
            error = None
            try:
                output, request_snapshot = self._execute_node(
                    node=node,
                    project_id=project_id,
                    environment_id=selected_environment_id,
                    outputs=outputs,
                    flow_variables=flow_variables,
                    current_user=current_user,
                )
            except Exception as exc:  # noqa: BLE001
                finished = datetime.utcnow()
                error = {"message": str(exc)}
                output = self._node_output(
                    node_id,
                    "error",
                    started,
                    finished,
                    int((finished - started).total_seconds() * 1000),
                    error=error,
                )
            outputs[node_id] = output
            node_failed = output["status"] in {"failed", "error"}
            if node_failed and not node.config.continue_on_failure:
                fatal_failure = True
            for edge in outgoing[node_id]:
                if self._route_matches(edge.route, node, output):
                    active_edges.add(edge.id)
            self.repository.create_node_execution(
                execution_id=execution.id,
                node_id=node_id,
                status=output["status"],
                request_snapshot=self._mask(request_snapshot),
                output_snapshot=self._mask(output),
                error=error,
                started_at=started,
                finished_at=datetime.utcnow(),
            )
        return self.repository.finish_execution(
            execution=execution,
            status="failed" if fatal_failure else "passed",
        )

    def _execute_node(
        self,
        *,
        node: FlowNode,
        project_id: int,
        environment_id: int | None,
        outputs: dict[str, dict[str, Any]],
        flow_variables: dict[str, Any],
        current_user: User,
    ) -> tuple[dict[str, Any], dict | None]:
        started = datetime.utcnow()
        if node.kind in {"start", "end"}:
            finished = datetime.utcnow()
            return self._node_output(node.id, "passed", started, finished, 0), None
        if node.kind == "delay":
            time.sleep((node.config.delay_ms or 0) / 1000)
            finished = datetime.utcnow()
            return self._node_output(
                node.id, "passed", started, finished, int((finished - started).total_seconds() * 1000)
            ), None
        if node.kind == "condition":
            condition_variables = copy.deepcopy(flow_variables)
            for binding in node.config.input_bindings:
                if not binding.target.startswith("variables."):
                    continue
                value = self._read_path(outputs.get(binding.source_node_id), binding.source_path)
                if value is _MISSING:
                    if binding.fallback is None:
                        raise ValueError(f"Binding sourcePath not found: {binding.source_path}")
                    value = binding.fallback
                self._write_path(condition_variables, binding.target.split(".")[1:], value)
            result = self._evaluate_condition(node.config.condition or "", outputs, condition_variables)
            finished = datetime.utcnow()
            output = self._node_output(
                node.id, "passed", started, finished, int((finished - started).total_seconds() * 1000)
            )
            output["result"] = result
            return output, {"condition": node.config.condition}
        if node.kind == "api_case":
            return self._execute_http_node(node, project_id, environment_id, outputs, current_user)
        if node.kind == "websocket_case":
            return self._execute_websocket_node(node, project_id, environment_id, outputs, current_user)
        raise ValueError(f"Unsupported node kind: {node.kind}")

    def _execute_http_node(self, node, project_id, environment_id, outputs, current_user):
        case = self.repository.get_http_case(project_id=project_id, case_id=int(node.reference_id))
        if case is None:
            raise ValueError(f"HTTP test case not found: {node.reference_id}")
        data = self._http_case_data(case, environment_id=environment_id)
        self._apply_case_overrides(data, node, allowed_fields=_HTTP_CASE_OVERRIDE_FIELDS)
        self._apply_bindings(data, node, outputs, websocket=False)
        payload = TestCaseRequestConfig.model_validate(data)
        result = TestCaseService(self.db)._execute(
            project_id=project_id, test_case_id=None, payload=payload, current_user=current_user
        )
        output = self._normalize_case_result(node.id, result, websocket=False)
        return output, result.request_snapshot

    def _execute_websocket_node(self, node, project_id, environment_id, outputs, current_user):
        case = self.repository.get_websocket_case(project_id=project_id, case_id=int(node.reference_id))
        if case is None:
            raise ValueError(f"WebSocket test case not found: {node.reference_id}")
        data = self._websocket_case_data(case, environment_id=environment_id)
        self._apply_case_overrides(data, node, allowed_fields=_WEBSOCKET_CASE_OVERRIDE_FIELDS)
        self._apply_bindings(data, node, outputs, websocket=True)
        payload = WebSocketTestCaseConfig.model_validate(data)
        result = WebSocketTestCaseService(self.db)._execute(project_id, None, payload, current_user)
        output = self._normalize_case_result(node.id, result, websocket=True)
        return output, result.session_snapshot

    def _http_case_data(self, case, *, environment_id: int | None) -> dict[str, Any]:
        return {
            "environment_id": environment_id or case.environment_id,
            "method": case.method,
            "path": case.path,
            "headers": copy.deepcopy(case.headers or {}),
            "query_params": copy.deepcopy(case.query_params or {}),
            "body_type": case.body_type,
            "body": copy.deepcopy(case.body),
            "assertions": copy.deepcopy(case.assertions or []),
            "extractors": copy.deepcopy(case.extractors or []),
            "retry_policy": copy.deepcopy(getattr(case, "retry_policy", None) or {}),
        }

    def _websocket_case_data(self, case, *, environment_id: int | None) -> dict[str, Any]:
        return {
            "environment_id": environment_id or case.environment_id,
            "path": case.path,
            "headers": copy.deepcopy(case.headers or {}),
            "subprotocols": copy.deepcopy(case.subprotocols or []),
            "messages": copy.deepcopy(case.messages or []),
            "receive_count": case.receive_count,
            "connect_timeout_ms": case.connect_timeout_ms,
            "receive_timeout_ms": case.receive_timeout_ms,
            "assertions": copy.deepcopy(case.assertions or []),
            "extractors": copy.deepcopy(case.extractors or []),
            "retry_policy": copy.deepcopy(getattr(case, "retry_policy", None) or {}),
        }

    def _apply_bindings(self, data: dict, node: FlowNode, outputs: dict, *, websocket: bool) -> None:
        variables: dict[str, Any] = {}
        for binding in node.config.input_bindings:
            value = self._read_path(outputs.get(binding.source_node_id), binding.source_path)
            if value is _MISSING:
                if binding.fallback is None:
                    raise ValueError(f"Binding sourcePath not found: {binding.source_path}")
                value = binding.fallback
            target = binding.target.split(".")
            root = target[0]
            mapped_root = {"query": "query_params", "pathParams": "path", "messages": "messages"}.get(root, root)
            if root in {"variables", "pathParams"}:
                self._write_path(variables, target[1:], value)
            else:
                if root == "messages" and not websocket:
                    raise ValueError("messages bindings are only valid for WebSocket nodes")
                self._write_path(data, [mapped_root, *target[1:]], value)
        if variables:
            rendered = self._render_variables(data, variables)
            data.clear()
            data.update(rendered)

    def _apply_case_overrides(self, data: dict[str, Any], node: FlowNode, *, allowed_fields: set[str]) -> None:
        for override_data in (node.config.case_config, node.config.case_overrides):
            if not override_data:
                continue
            for raw_key, value in override_data.items():
                key = _CASE_OVERRIDE_ALIASES.get(raw_key, raw_key)
                if key in allowed_fields:
                    data[key] = copy.deepcopy(value)

    def _invalid_override_fields(
        self, override_data: dict[str, Any] | None, allowed_fields: set[str]
    ) -> list[str]:
        if not override_data:
            return []
        return sorted(
            raw_key
            for raw_key in override_data
            if _CASE_OVERRIDE_ALIASES.get(raw_key, raw_key) not in allowed_fields
        )

    def _validate(self, definition: FlowDefinition, *, project_id: int, executable: bool) -> None:
        issues: list[dict[str, Any]] = []
        nodes = {node.id: node for node in definition.nodes}
        node_ids = [node.id for node in definition.nodes]
        edge_ids = [edge.id for edge in definition.edges]
        if len(node_ids) != len(set(node_ids)):
            issues.append({"code": "duplicate_node_id", "message": "Node IDs must be unique"})
        if len(edge_ids) != len(set(edge_ids)):
            issues.append({"code": "duplicate_edge_id", "message": "Edge IDs must be unique"})

        pairs: set[tuple[str, str]] = set()
        incoming = {node_id: [] for node_id in nodes}
        outgoing = {node_id: [] for node_id in nodes}
        for edge in definition.edges:
            if edge.source not in nodes or edge.target not in nodes:
                issues.append({"code": "dangling_edge", "message": "Edge references a missing node", "edgeId": edge.id})
                continue
            if edge.source == edge.target:
                issues.append({"code": "self_edge", "message": "Self edges are not allowed", "edgeId": edge.id})
            if (edge.source, edge.target) in pairs:
                issues.append({"code": "duplicate_edge", "message": "Duplicate edges are not allowed", "edgeId": edge.id})
            pairs.add((edge.source, edge.target))
            incoming[edge.target].append(edge)
            outgoing[edge.source].append(edge)
            if nodes[edge.source].kind != "condition" and edge.route in {"true", "false"}:
                issues.append({"code": "invalid_route", "message": "true/false routes require a condition node", "edgeId": edge.id})

        if not issues and len(self._topological_order(definition)) != len(nodes):
            issues.append({"code": "cycle", "message": "Flow must be a directed acyclic graph"})

        for node in definition.nodes:
            if node.kind in {"api_case", "websocket_case"}:
                try:
                    reference_id = int(node.reference_id)
                except (TypeError, ValueError):
                    issues.append({"code": "missing_reference", "message": "Case node requires a numeric referenceId", "nodeId": node.id})
                    continue
                case = (
                    self.repository.get_http_case(project_id=project_id, case_id=reference_id)
                    if node.kind == "api_case"
                    else self.repository.get_websocket_case(project_id=project_id, case_id=reference_id)
                )
                if case is None:
                    issues.append({"code": "invalid_reference", "message": "Referenced case is missing or cross-project", "nodeId": node.id})
                allowed_fields = (
                    _HTTP_CASE_OVERRIDE_FIELDS if node.kind == "api_case" else _WEBSOCKET_CASE_OVERRIDE_FIELDS
                )
                for field_name, override_data in (
                    ("caseConfig", node.config.case_config),
                    ("caseOverrides", node.config.case_overrides),
                ):
                    invalid_fields = self._invalid_override_fields(override_data, allowed_fields)
                    if invalid_fields:
                        issues.append(
                            {
                                "code": "invalid_case_override",
                                "message": f"{field_name} contains unsupported fields: {', '.join(invalid_fields)}",
                                "nodeId": node.id,
                            }
                        )
                if case is not None and not any(
                    issue.get("code") == "invalid_case_override" and issue.get("nodeId") == node.id
                    for issue in issues
                ):
                    try:
                        if node.kind == "api_case":
                            override_case_data = self._http_case_data(case, environment_id=None)
                            self._apply_case_overrides(
                                override_case_data, node, allowed_fields=_HTTP_CASE_OVERRIDE_FIELDS
                            )
                            validated_override = TestCaseRequestConfig.model_validate(override_case_data)
                        else:
                            override_case_data = self._websocket_case_data(case, environment_id=None)
                            self._apply_case_overrides(
                                override_case_data, node, allowed_fields=_WEBSOCKET_CASE_OVERRIDE_FIELDS
                            )
                            validated_override = WebSocketTestCaseConfig.model_validate(override_case_data)
                        if validated_override.environment_id is not None and self.repository.get_environment(
                            project_id=project_id, environment_id=validated_override.environment_id
                        ) is None:
                            issues.append(
                                {
                                    "code": "invalid_case_override_environment",
                                    "message": "Node-local case environment is missing or cross-project",
                                    "nodeId": node.id,
                                }
                            )
                    except Exception as exc:  # noqa: BLE001
                        issues.append(
                            {
                                "code": "invalid_case_override_value",
                                "message": f"Node-local case configuration is invalid: {exc}",
                                "nodeId": node.id,
                            }
                        )
            if node.kind == "condition" and not (node.config.condition or "").strip():
                issues.append({"code": "missing_condition", "message": "Condition expression is required", "nodeId": node.id})
            direct_upstream = {edge.source for edge in incoming.get(node.id, [])}
            binding_ids = [binding.id for binding in node.config.input_bindings]
            if len(binding_ids) != len(set(binding_ids)):
                issues.append({"code": "duplicate_binding_id", "message": "Binding IDs must be unique within a node", "nodeId": node.id})
            for binding in node.config.input_bindings:
                if "." not in binding.target or binding.target.split(".", 1)[0] not in _TARGET_ROOTS:
                    issues.append({"code": "invalid_binding_target", "message": "Unsupported binding target", "nodeId": node.id})
                if binding.source_node_id not in direct_upstream:
                    issues.append({"code": "invalid_binding_source", "message": "Binding source must be a direct upstream node", "nodeId": node.id})
                    continue
                source_node = nodes[binding.source_node_id]
                if not any(
                    binding.source_path == path or binding.source_path.startswith(path + ".")
                    for path in source_node.config.output_paths
                ):
                    issues.append({"code": "undeclared_output", "message": "Binding sourcePath is not declared by source node", "nodeId": node.id})

        if definition.environment_id is not None and self.repository.get_environment(
            project_id=project_id, environment_id=definition.environment_id
        ) is None:
            issues.append({"code": "invalid_environment", "message": "Environment is missing or cross-project"})

        if executable:
            starts = [node for node in definition.nodes if node.kind == "start"]
            ends = [node for node in definition.nodes if node.kind == "end"]
            if len(starts) != 1:
                issues.append({"code": "start_count", "message": "Executable flow requires exactly one start node"})
            if not ends:
                issues.append({"code": "end_count", "message": "Executable flow requires at least one end node"})
            for node in starts:
                if incoming[node.id]:
                    issues.append({"code": "start_incoming", "message": "Start node cannot have incoming edges", "nodeId": node.id})
            for node in ends:
                if outgoing[node.id]:
                    issues.append({"code": "end_outgoing", "message": "End node cannot have outgoing edges", "nodeId": node.id})
            for node in definition.nodes:
                if node.kind == "condition":
                    routes = [edge.route for edge in outgoing[node.id]]
                    if routes.count("true") != 1 or routes.count("false") != 1 or len(routes) != 2:
                        issues.append({"code": "condition_routes", "message": "Condition node requires exactly true and false routes", "nodeId": node.id})
            if len(starts) == 1:
                reachable = self._reachable(starts[0].id, outgoing)
                if len(reachable) != len(nodes):
                    issues.append({"code": "unreachable_node", "message": "All nodes must be reachable from start"})
            if ends:
                reverse = self._reverse_reachable({node.id for node in ends}, incoming)
                if len(reverse) != len(nodes):
                    issues.append({"code": "no_end_path", "message": "Every node must reach an end node"})
        if issues:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"message": "Flow validation failed", "issues": issues})

    def _topological_order(self, definition: FlowDefinition) -> list[str]:
        node_ids = [node.id for node in definition.nodes]
        indegree = {node_id: 0 for node_id in node_ids}
        outgoing = {node_id: [] for node_id in node_ids}
        for edge in definition.edges:
            if edge.source in outgoing and edge.target in indegree:
                outgoing[edge.source].append(edge.target)
                indegree[edge.target] += 1
        queue = [node_id for node_id in node_ids if indegree[node_id] == 0]
        order: list[str] = []
        while queue:
            node_id = queue.pop(0)
            order.append(node_id)
            for target in outgoing[node_id]:
                indegree[target] -= 1
                if indegree[target] == 0:
                    queue.append(target)
        return order

    def _route_matches(self, route: str, node: FlowNode, output: dict[str, Any]) -> bool:
        failed = output["status"] in {"failed", "error"}
        if failed and not node.config.continue_on_failure:
            return route == "failure"
        if route == "always":
            return True
        if route == "success":
            return not failed
        if route == "failure":
            return failed
        if route == "true":
            return output.get("result") is True
        if route == "false":
            return output.get("result") is False
        return False

    def _evaluate_condition(
        self, expression: str, outputs: dict[str, dict[str, Any]], variables: dict[str, Any] | None = None
    ) -> bool:
        tree = ast.parse(expression, mode="eval")
        result = self._eval_ast(
            tree.body,
            {"outputs": self._dot(outputs), "variables": self._dot(variables or {})},
        )
        if not isinstance(result, bool):
            raise ValueError("Condition expression must return a boolean")
        return result

    def _eval_ast(self, node: ast.AST, context: dict[str, Any]) -> Any:
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name) and node.id in context:
            return context[node.id]
        if isinstance(node, ast.Name) and node.id in {"true", "false"}:
            return node.id == "true"
        if isinstance(node, ast.Attribute):
            return getattr(self._eval_ast(node.value, context), node.attr)
        if isinstance(node, ast.Subscript):
            return self._eval_ast(node.value, context)[self._eval_ast(node.slice, context)]
        if isinstance(node, ast.BoolOp):
            values = [bool(self._eval_ast(value, context)) for value in node.values]
            return all(values) if isinstance(node.op, ast.And) else any(values)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return not self._eval_ast(node.operand, context)
        if isinstance(node, ast.Compare):
            left = self._eval_ast(node.left, context)
            for operator, comparator in zip(node.ops, node.comparators, strict=True):
                right = self._eval_ast(comparator, context)
                if isinstance(operator, ast.Eq):
                    matched = left == right
                elif isinstance(operator, ast.NotEq):
                    matched = left != right
                elif isinstance(operator, ast.Gt):
                    matched = left > right
                elif isinstance(operator, ast.GtE):
                    matched = left >= right
                elif isinstance(operator, ast.Lt):
                    matched = left < right
                elif isinstance(operator, ast.LtE):
                    matched = left <= right
                elif isinstance(operator, ast.In):
                    matched = left in right
                elif isinstance(operator, ast.NotIn):
                    matched = left not in right
                else:
                    raise ValueError("Unsupported condition operator")
                if not matched:
                    return False
                left = right
            return True
        raise ValueError("Condition expression contains unsupported syntax")

    def _normalize_case_result(self, node_id: str, result, *, websocket: bool) -> dict[str, Any]:
        created = getattr(result, "created_at", None) or datetime.utcnow()
        duration = result.duration_ms or 0
        response = result.response_snapshot or {}
        if websocket:
            normalized_response = {"messages": response.get("received_messages", []), **response}
        else:
            normalized_response = {
                "status": response.get("status_code"),
                "headers": response.get("headers", {}),
                "body": response.get("json") if response.get("json") is not None else response.get("body"),
            }
        return self._node_output(
            node_id,
            result.status,
            created,
            created,
            duration,
            response=normalized_response,
            assertions=result.assertion_results or [],
            error={"message": result.error_message} if result.error_message else None,
        )

    def _node_output(self, node_id, status_value, started, finished, duration, *, response=None, assertions=None, error=None):
        return {
            "nodeId": node_id,
            "status": status_value,
            "startedAt": started.isoformat(),
            "finishedAt": finished.isoformat(),
            "durationMs": duration,
            "response": response,
            "assertions": assertions or [],
            "error": error,
        }

    def _read_path(self, data: Any, path: str) -> Any:
        current = data
        for part in path.split("."):
            if isinstance(current, dict) and part in current:
                current = current[part]
            elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
                current = current[int(part)]
            else:
                return _MISSING
        return current

    def _write_path(self, data: Any, parts: list[str], value: Any) -> None:
        if not parts:
            raise ValueError("Binding target must include a field path")
        current = data
        for part in parts[:-1]:
            if isinstance(current, list):
                index = int(part)
                while len(current) <= index:
                    current.append({})
                current = current[index]
            else:
                if not isinstance(current.get(part), (dict, list)):
                    current[part] = {}
                current = current[part]
        if isinstance(current, list):
            index = int(parts[-1])
            while len(current) <= index:
                current.append(None)
            current[index] = value
        else:
            current[parts[-1]] = value

    def _render_variables(self, value: Any, variables: dict[str, Any]) -> Any:
        return render_variables(value, variables)

    def _prepare_definition(self, definition: FlowDefinition, *, project_id: int) -> FlowDefinition:
        data = definition.model_dump(by_alias=True, mode="python", exclude={"id", "project_id", "updated_at"})
        data["projectId"] = project_id
        return FlowDefinition.model_validate(data)

    def _stored_definition(self, definition: FlowDefinition) -> dict:
        return definition.model_dump(by_alias=True, mode="json", exclude={"id", "updated_at"})

    def _detail(self, flow: VisualFlow, stored_definition: dict) -> dict[str, Any]:
        definition = copy.deepcopy(stored_definition)
        definition.update(
            {
                "id": flow.id,
                "projectId": flow.project_id,
                "name": flow.name,
                "description": flow.description or "",
                "currentVersion": flow.current_version,
                "updatedAt": flow.updated_at.isoformat(),
            }
        )
        return definition

    def _case_snapshots(self, definition: FlowDefinition, project_id: int) -> dict[str, Any]:
        result = {}
        for node in definition.nodes:
            if node.kind == "api_case":
                case = self.repository.get_http_case(project_id=project_id, case_id=int(node.reference_id))
                result[node.id] = {
                    "kind": node.kind, "referenceId": case.id, "method": case.method, "path": case.path,
                    "headers": case.headers, "queryParams": case.query_params, "bodyType": case.body_type,
                    "body": case.body, "assertions": case.assertions, "extractors": case.extractors,
                    "retryPolicy": getattr(case, "retry_policy", None),
                }
            elif node.kind == "websocket_case":
                case = self.repository.get_websocket_case(project_id=project_id, case_id=int(node.reference_id))
                result[node.id] = {
                    "kind": node.kind, "referenceId": case.id, "path": case.path, "headers": case.headers,
                    "subprotocols": case.subprotocols, "messages": case.messages, "receiveCount": case.receive_count,
                    "connectTimeoutMs": case.connect_timeout_ms, "receiveTimeoutMs": case.receive_timeout_ms,
                    "assertions": case.assertions, "extractors": case.extractors,
                    "retryPolicy": getattr(case, "retry_policy", None),
                }
        return result

    def _reachable(self, start: str, outgoing: dict) -> set[str]:
        seen = set()
        stack = [start]
        while stack:
            node_id = stack.pop()
            if node_id in seen:
                continue
            seen.add(node_id)
            stack.extend(edge.target for edge in outgoing[node_id])
        return seen

    def _reverse_reachable(self, ends: set[str], incoming: dict) -> set[str]:
        seen = set()
        stack = list(ends)
        while stack:
            node_id = stack.pop()
            if node_id in seen:
                continue
            seen.add(node_id)
            stack.extend(edge.source for edge in incoming[node_id])
        return seen

    def _dot(self, value: Any) -> Any:
        if isinstance(value, dict):
            return DotMap({key: self._dot(item) for key, item in value.items()})
        if isinstance(value, list):
            return [self._dot(item) for item in value]
        return value

    def _hash(self, definition: dict) -> str:
        raw = json.dumps(definition, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _mask(self, value: Any) -> Any:
        sensitive = ("authorization", "token", "password", "secret", "cookie", "api_key", "apikey")
        if isinstance(value, dict):
            return {
                key: "***" if any(item in key.lower() for item in sensitive) else self._mask(item_value)
                for key, item_value in value.items()
            }
        if isinstance(value, list):
            return [self._mask(item) for item in value]
        return value

    def _get_flow(self, project_id: int, flow_id: int) -> VisualFlow:
        flow = self.repository.get_flow(project_id=project_id, flow_id=flow_id)
        if flow is None:
            raise HTTPException(status_code=404, detail="Flow not found")
        return flow

    def _require_environment(self, project_id: int, environment_id: int) -> None:
        if self.repository.get_environment(project_id=project_id, environment_id=environment_id) is None:
            raise HTTPException(status_code=404, detail="Environment not found")

    def _require(self, user: User, project_id: int, permission: str) -> None:
        self.permission_service.require_project_permission(user, project_id, permission)

    def _idempotent(self, project_id: int, key: str | None) -> VisualFlowExecution | None:
        if not key:
            return None
        return self.repository.get_execution_by_idempotency_key(project_id=project_id, idempotency_key=key)

    def _version_number(self, execution: VisualFlowExecution) -> int | None:
        if execution.flow_id is None or execution.flow_version_id is None:
            return None
        version = self.db.get(VisualFlowVersion, execution.flow_version_id)
        return version.version if version else None
