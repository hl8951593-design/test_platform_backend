from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.async_response import public_execution_status
from app.core.execution_worker import execution_worker
from app.core.response import normalize_response_data
from app.core.sensitive_data import mask_sensitive, request_fingerprint
from app.models.agent import AgentEvent, AgentRun, AgentToolCall
from app.models.test_plan import TestPlanRun
from app.models.user import User
from app.schemas.ai import AIExecutionDiagnoseRequest
from app.schemas.defect import (
    DefectCreateRequest,
    DefectRead,
    DefectStatusUpdateRequest,
    DefectUpdateRequest,
)
from app.schemas.test_plan import (
    TestPlanCreateRequest,
    TestPlanRead,
    TestPlanUpdateRequest,
)
from app.schemas.visual_flow import (
    FlowCreateRequest,
    FlowDefinition,
    FlowExecutionRead,
    FlowUpdateRequest,
)
from app.services.ai_browser_capture_service import AIBrowserCaptureService
from app.services.defect_service import DefectService
from app.services.execution_record_service import ExecutionRecordService
from app.services.permission_service import PermissionService
from app.services.test_plan_service import TestPlanService
from app.services.visual_flow_service import VisualFlowService


_OBJECT_REF_ID_RE = re.compile(r"/(?P<object_id>\d+)$")
_EXECUTION_TYPES = {"http", "websocket", "scenario", "flow"}
_AGENT_DIAGNOSTIC_EVENT_TYPES = {
    "run.started",
    "run.completed",
    "run.failed",
    "run.cancelled",
    "planner.llm_decision_started",
    "planner.llm_decision_invalid",
    "planner.llm_decision_retrying",
    "planner.llm_decision_failed",
    "planner.llm_decision_completed",
    "planner.capability_plan_created",
    "tool.created",
    "tool.completed",
    "tool.failed",
    "approval.created",
    "approval.approved",
    "approval.rejected",
    "approval.expired",
}
_AGENT_DIAGNOSTIC_EVENT_FIELDS = {
    "code",
    "reason_code",
    "requested_effect_scope",
    "model_requested_effect_scope",
    "required_effect_scope",
    "effect_scope_normalized",
    "tool_names",
    "details",
    "error_code",
    "error_message",
    "next_attempt",
    "tool_call_id",
    "approval_id",
    "approval_epoch",
    "status",
    "iteration",
    "revision",
    "source",
}


class AgentPlatformToolBackend:
    """Agent handlers for platform domains outside the original case/scenario tool set."""

    def __init__(self, db: Session):
        self.db = db

    def _agent_run_read_summary(self, payload: dict[str, Any], current_user: User) -> dict[str, Any]:
        project_id = _require_int(payload, "project_id")
        run_id = _require_str(payload, "run_id")
        PermissionService(self.db).require_project_access(current_user, project_id)
        run = self.db.scalar(
            select(AgentRun).where(
                AgentRun.project_id == project_id,
                AgentRun.run_id == run_id,
            )
        )
        if run is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent run 不存在")

        events = list(
            self.db.scalars(
                select(AgentEvent)
                .where(
                    AgentEvent.run_id == run_id,
                    AgentEvent.event_type.in_(_AGENT_DIAGNOSTIC_EVENT_TYPES),
                )
                .order_by(AgentEvent.event_seq.asc())
                .limit(100)
            ).all()
        )
        calls = list(
            self.db.scalars(
                select(AgentToolCall)
                .where(AgentToolCall.run_id == run_id)
                .order_by(AgentToolCall.step_index.asc(), AgentToolCall.id.asc())
                .limit(100)
            ).all()
        )
        return {
            "project_id": project_id,
            "run": {
                "run_id": run.run_id,
                "conversation_id": run.conversation_id,
                "intent": _bounded_masked_text(run.intent, 800),
                "status": run.status,
                "error_code": run.error_code,
                "error_message": _bounded_masked_text(run.error_message, 512),
                "current_iteration": run.current_iteration,
                "current_step_index": run.current_step_index,
                "last_event_sequence": run.last_event_sequence,
                "started_at": _isoformat(run.started_at),
                "completed_at": _isoformat(run.completed_at),
                "created_at": _isoformat(run.created_at),
            },
            "diagnostic_events": [_agent_diagnostic_event_view(item) for item in events],
            "tool_calls": [_agent_tool_call_summary(item) for item in calls],
            "diagnostic_contract": {
                "schema_version": "agent_run_diagnostic_summary_v1",
                "bounded": True,
                "raw_prompts_included": False,
                "raw_tool_payloads_included": False,
            },
        }

    def _execution_query_records(self, payload: dict[str, Any], current_user: User) -> dict[str, Any]:
        project_id = _require_int(payload, "project_id")
        execution_type = _optional_execution_type(payload, "execution_type")
        page, page_size = _page_bounds(payload)
        page_result = ExecutionRecordService(self.db).list_records(
            project_id=project_id,
            current_user=current_user,
            execution_type=execution_type,
            status_filter=_optional_str(payload, "status"),
            environment_id=_optional_int(payload, "environment_id"),
            trigger_user_id=_optional_int(payload, "trigger_user_id"),
            started_from=_optional_datetime(payload, "started_from"),
            started_to=_optional_datetime(payload, "started_to"),
            keyword=_optional_str(payload, "keyword"),
            page=page,
            page_size=page_size,
        )
        normalized = normalize_response_data(page_result)
        rows = normalized.get("items") or []
        snapshot, references = _snapshot_and_references(
            object_family="execution",
            project_id=project_id,
            rows=rows,
            object_type_getter=lambda item: str(item.get("execution_type") or "execution"),
            name_getter=lambda item: item.get("resource_name") or item.get("id"),
        )
        references_by_key = {
            (item["object_type"], item["id"]): item["object_ref"]
            for item in references
        }
        executions = [
            {
                **item,
                "object_ref": references_by_key.get((str(item.get("execution_type")), item.get("execution_id"))),
            }
            for item in rows
        ]
        return {
            "project_id": project_id,
            "filters": {
                "execution_type": execution_type,
                "status": _optional_str(payload, "status"),
                "environment_id": _optional_int(payload, "environment_id"),
                "trigger_user_id": _optional_int(payload, "trigger_user_id"),
                "keyword": _optional_str(payload, "keyword"),
                "page": page,
                "page_size": page_size,
            },
            "total": normalized.get("total", 0),
            "page": normalized.get("page", page),
            "page_size": normalized.get("page_size", page_size),
            "execution_snapshot": snapshot,
            "object_reference_manifest": _object_reference_manifest(
                object_family="execution",
                query_tool="execution.query_records",
                snapshot=snapshot,
                references=references,
            ),
            "executions": executions,
        }

    def _execution_read_detail(self, payload: dict[str, Any], current_user: User) -> dict[str, Any]:
        project_id = _require_int(payload, "project_id")
        execution_type = _require_execution_type(payload, "execution_type")
        execution_id = _entity_id(payload, id_key="execution_id")
        detail = ExecutionRecordService(self.db).get_detail(
            project_id=project_id,
            execution_type=execution_type,
            execution_id=execution_id,
            current_user=current_user,
        )
        return {
            "project_id": project_id,
            "execution_type": execution_type,
            "execution_id": execution_id,
            "execution": normalize_response_data(detail),
        }

    def _execution_diagnose(self, payload: dict[str, Any], current_user: User) -> dict[str, Any]:
        project_id = _require_int(payload, "project_id")
        execution_type = _require_execution_type(payload, "execution_type")
        execution_id = _entity_id(payload, id_key="execution_id")
        detail = ExecutionRecordService(self.db).get_detail(
            project_id=project_id,
            execution_type=execution_type,
            execution_id=execution_id,
            current_user=current_user,
        )
        execution_data = mask_sensitive(normalize_response_data(detail))
        summary = execution_data.get("summary") if isinstance(execution_data, dict) else {}
        request = AIExecutionDiagnoseRequest(
            protocol=execution_type,
            draft_data={
                "resource_id": summary.get("resource_id") if isinstance(summary, dict) else None,
                "resource_name": summary.get("resource_name") if isinstance(summary, dict) else None,
            },
            execution_data=execution_data,
        )
        diagnosis = AIBrowserCaptureService(self.db).diagnose_execution(
            project_id=project_id,
            payload=request,
            current_user=current_user,
        )
        return {
            "project_id": project_id,
            "execution_type": execution_type,
            "execution_id": execution_id,
            "diagnosis": normalize_response_data(diagnosis),
            "source": "execution.read_detail",
        }

    def _plan_query_project_plans(self, payload: dict[str, Any], current_user: User) -> dict[str, Any]:
        project_id = _require_int(payload, "project_id")
        page, page_size = _page_bounds(payload)
        detail_level = _detail_level(payload, allowed={"summary", "full"})
        result = TestPlanService(self.db).list_plans(
            project_id=project_id,
            current_user=current_user,
            keyword=_optional_str(payload, "keyword"),
            enabled=_optional_bool(payload, "enabled"),
            trigger_type=_optional_str(payload, "trigger_type"),
            page=page,
            page_size=page_size,
        )
        full_rows = [normalize_response_data(TestPlanRead.model_validate(item)) for item in result["items"]]
        rows = [self._plan_view(item, detail_level=detail_level) for item in full_rows]
        snapshot, references = _snapshot_and_references(
            object_family="test_plan",
            project_id=project_id,
            rows=rows,
            name_getter=lambda item: item.get("name"),
        )
        plans = _attach_references(rows, references)
        plan_ids = [item["id"] for item in plans]
        return {
            "project_id": project_id,
            "detail_level": detail_level,
            "total": result["total"],
            "page": result["page"],
            "page_size": result["page_size"],
            "statistics": normalize_response_data(result.get("statistics") or {}),
            "plan_snapshot": snapshot,
            "plan_ids": plan_ids,
            "object_reference_manifest": {
                **_object_reference_manifest(
                    object_family="test_plan",
                    query_tool="plan.query_project_plans",
                    snapshot=snapshot,
                    references=references,
                ),
                "plan_ids": plan_ids,
                "plan_refs": [item["object_ref"] for item in references],
            },
            "plans": plans,
        }

    def _plan_create_saved(self, payload: dict[str, Any], current_user: User) -> dict[str, Any]:
        project_id = _require_int(payload, "project_id")
        request = _validate_model(TestPlanCreateRequest, payload.get("plan"), path="plan")
        plan = TestPlanService(self.db).create_plan(
            project_id=project_id,
            payload=request,
            current_user=current_user,
        )
        return {
            "operation": "create_saved",
            "project_id": project_id,
            "plan_id": plan.id,
            "plan": normalize_response_data(TestPlanRead.model_validate(plan)),
        }

    def _plan_update_saved(self, payload: dict[str, Any], current_user: User) -> dict[str, Any]:
        project_id = _require_int(payload, "project_id")
        plan_id = _entity_id(payload, id_key="plan_id")
        request = _validate_model(TestPlanUpdateRequest, payload.get("plan"), path="plan")
        plan = TestPlanService(self.db).update_plan(
            project_id=project_id,
            plan_id=plan_id,
            payload=request,
            current_user=current_user,
        )
        return {
            "operation": "update_saved",
            "project_id": project_id,
            "plan_id": plan_id,
            "plan": normalize_response_data(TestPlanRead.model_validate(plan)),
        }

    def _plan_set_enabled(self, payload: dict[str, Any], current_user: User) -> dict[str, Any]:
        project_id = _require_int(payload, "project_id")
        plan_id = _entity_id(payload, id_key="plan_id")
        enabled = _require_bool(payload, "enabled")
        plan = TestPlanService(self.db).set_enabled(
            project_id=project_id,
            plan_id=plan_id,
            enabled=enabled,
            version=_optional_int(payload, "version"),
            current_user=current_user,
        )
        return {
            "operation": "enabled" if enabled else "disabled",
            "project_id": project_id,
            "plan_id": plan_id,
            "plan": normalize_response_data(TestPlanRead.model_validate(plan)),
        }

    def _plan_execute_saved(self, payload: dict[str, Any], current_user: User) -> dict[str, Any]:
        project_id = _require_int(payload, "project_id")
        plan_id = _entity_id(payload, id_key="plan_id")
        environment_id = _require_int(payload, "environment_id")
        source = _agent_execution_source(payload)
        run = TestPlanService(self.db).create_plan_run(
            project_id=project_id,
            plan_id=plan_id,
            environment_id=environment_id,
            idempotency_key=_optional_str(payload, "idempotency_key"),
            current_user=current_user,
            trigger="agent",
            request_context=source,
        )
        if run.status == "pending" and not execution_worker.submit(TestPlanService.execute_queued_run, run.id):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="执行队列已满，请稍后重试",
            )
        return {
            "operation": "execute_saved",
            "accepted": True,
            "project_id": project_id,
            "plan_id": plan_id,
            "run_id": run.id,
            "run": self._plan_run_view(run, include_results=True),
        }

    def _plan_query_runs(self, payload: dict[str, Any], current_user: User) -> dict[str, Any]:
        project_id = _require_int(payload, "project_id")
        page, page_size = _page_bounds(payload)
        result = TestPlanService(self.db).list_runs(
            project_id=project_id,
            current_user=current_user,
            page=page,
            page_size=page_size,
        )
        rows = [self._plan_run_view(item, include_results=False) for item in result["items"]]
        snapshot, references = _snapshot_and_references(
            object_family="test_plan_run",
            project_id=project_id,
            rows=rows,
            name_getter=lambda item: item.get("plan_name"),
        )
        runs = _attach_references(rows, references)
        run_ids = [item["id"] for item in runs]
        return {
            "project_id": project_id,
            "total": result["total"],
            "page": result["page"],
            "page_size": result["page_size"],
            "plan_run_snapshot": snapshot,
            "plan_run_ids": run_ids,
            "object_reference_manifest": {
                **_object_reference_manifest(
                    object_family="test_plan_run",
                    query_tool="plan.query_runs",
                    snapshot=snapshot,
                    references=references,
                ),
                "plan_run_ids": run_ids,
                "plan_run_refs": [item["object_ref"] for item in references],
            },
            "runs": runs,
        }

    def _plan_read_run(self, payload: dict[str, Any], current_user: User) -> dict[str, Any]:
        project_id = _require_int(payload, "project_id")
        run_id = _entity_id(payload, id_key="run_id")
        run = TestPlanService(self.db).get_run(
            project_id=project_id,
            run_id=run_id,
            current_user=current_user,
        )
        return {
            "project_id": project_id,
            "run_id": run_id,
            "run": self._plan_run_view(run, include_results=True),
        }

    def _flow_query_project_flows(self, payload: dict[str, Any], current_user: User) -> dict[str, Any]:
        project_id = _require_int(payload, "project_id")
        page, page_size = _page_bounds(payload)
        detail_level = _detail_level(payload, allowed={"summary", "full"})
        service = VisualFlowService(self.db)
        result = service.list_flows(
            project_id=project_id,
            current_user=current_user,
            keyword=_optional_str(payload, "keyword"),
            flow_status=_optional_str(payload, "status"),
            page=page,
            page_size=page_size,
        )
        rows = normalize_response_data(result["items"])
        if detail_level == "full":
            rows = [
                normalize_response_data(
                    service.get_flow(project_id=project_id, flow_id=item["id"], current_user=current_user)
                )
                for item in rows
            ]
        snapshot, references = _snapshot_and_references(
            object_family="visual_flow",
            project_id=project_id,
            rows=rows,
            name_getter=lambda item: item.get("name"),
        )
        flows = _attach_references(rows, references)
        flow_ids = [item["id"] for item in flows]
        return {
            "project_id": project_id,
            "detail_level": detail_level,
            "total": result["total"],
            "page": result["page"],
            "page_size": result["page_size"],
            "flow_snapshot": snapshot,
            "flow_ids": flow_ids,
            "object_reference_manifest": {
                **_object_reference_manifest(
                    object_family="visual_flow",
                    query_tool="flow.query_project_flows",
                    snapshot=snapshot,
                    references=references,
                ),
                "flow_ids": flow_ids,
                "flow_refs": [item["object_ref"] for item in references],
            },
            "flows": flows,
        }

    def _flow_validate_graph(self, payload: dict[str, Any], current_user: User) -> dict[str, Any]:
        project_id = _require_int(payload, "project_id")
        definition = _validate_model(FlowDefinition, payload.get("definition"), path="definition")
        return VisualFlowService(self.db).validate_definition(
            project_id=project_id,
            definition=definition,
            executable=_optional_bool(payload, "executable") is not False,
            current_user=current_user,
        )

    def _flow_create_saved(self, payload: dict[str, Any], current_user: User) -> dict[str, Any]:
        project_id = _require_int(payload, "project_id")
        request = _validate_model(FlowCreateRequest, payload.get("flow"), path="flow")
        flow = VisualFlowService(self.db).create_flow(
            project_id=project_id,
            payload=request,
            current_user=current_user,
        )
        return {
            "operation": "create_saved",
            "project_id": project_id,
            "flow_id": flow["id"],
            "flow": normalize_response_data(flow),
        }

    def _flow_update_saved(self, payload: dict[str, Any], current_user: User) -> dict[str, Any]:
        project_id = _require_int(payload, "project_id")
        flow_id = _entity_id(payload, id_key="flow_id")
        request = _validate_model(FlowUpdateRequest, payload.get("flow"), path="flow")
        flow = VisualFlowService(self.db).update_flow(
            project_id=project_id,
            flow_id=flow_id,
            payload=request,
            current_user=current_user,
        )
        return {
            "operation": "update_saved",
            "project_id": project_id,
            "flow_id": flow_id,
            "flow": normalize_response_data(flow),
        }

    def _flow_execute_saved(self, payload: dict[str, Any], current_user: User) -> dict[str, Any]:
        project_id = _require_int(payload, "project_id")
        flow_id = _entity_id(payload, id_key="flow_id")
        service = VisualFlowService(self.db)
        execution, flow_version, node_executions = service.enqueue_saved(
            project_id=project_id,
            flow_id=flow_id,
            environment_id=_optional_int(payload, "environment_id"),
            idempotency_key=_optional_str(payload, "idempotency_key"),
            current_user=current_user,
        )
        if execution.status == "queued" and not execution_worker.submit(
            VisualFlowService.execute_queued_execution,
            execution.id,
        ):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="执行队列已满，请稍后重试",
            )
        response = FlowExecutionRead(
            execution_id=execution.id,
            flow_id=execution.flow_id,
            flow_version=flow_version,
            project_id=execution.project_id,
            environment_id=execution.environment_id,
            status=public_execution_status(execution.status),
            started_at=execution.started_at,
            finished_at=execution.finished_at,
            node_executions=node_executions,
        )
        return {
            "operation": "execute_saved",
            "accepted": True,
            "project_id": project_id,
            "flow_id": flow_id,
            "execution_id": execution.id,
            "execution": normalize_response_data(response),
        }

    def _defect_query_project_defects(self, payload: dict[str, Any], current_user: User) -> dict[str, Any]:
        project_id = _require_int(payload, "project_id")
        page, page_size = _page_bounds(payload)
        detail_level = _detail_level(payload, allowed={"summary", "full"})
        result = DefectService(self.db).list_defects(
            project_id=project_id,
            current_user=current_user,
            keyword=_optional_str(payload, "keyword"),
            status=_optional_str(payload, "status"),
            urgency=_optional_str(payload, "urgency"),
            page=page,
            page_size=page_size,
        )
        full_rows = [normalize_response_data(DefectRead.model_validate(item)) for item in result["items"]]
        rows = [self._defect_view(item, detail_level=detail_level) for item in full_rows]
        snapshot, references = _snapshot_and_references(
            object_family="defect",
            project_id=project_id,
            rows=rows,
            name_getter=lambda item: item.get("title"),
        )
        defects = _attach_references(rows, references)
        defect_ids = [item["id"] for item in defects]
        return {
            "project_id": project_id,
            "detail_level": detail_level,
            "total": result["total"],
            "page": result["page"],
            "page_size": result["page_size"],
            "defect_snapshot": snapshot,
            "defect_ids": defect_ids,
            "object_reference_manifest": {
                **_object_reference_manifest(
                    object_family="defect",
                    query_tool="defect.query_project_defects",
                    snapshot=snapshot,
                    references=references,
                ),
                "defect_ids": defect_ids,
                "defect_refs": [item["object_ref"] for item in references],
            },
            "defects": defects,
        }

    def _defect_create_saved(self, payload: dict[str, Any], current_user: User) -> dict[str, Any]:
        project_id = _require_int(payload, "project_id")
        request = _validate_model(DefectCreateRequest, payload.get("defect"), path="defect")
        defect = DefectService(self.db).create_defect(
            project_id=project_id,
            payload=request,
            current_user=current_user,
        )
        return {
            "operation": "create_saved",
            "project_id": project_id,
            "defect_id": defect.id,
            "defect": normalize_response_data(DefectRead.model_validate(defect)),
        }

    def _defect_update_saved(self, payload: dict[str, Any], current_user: User) -> dict[str, Any]:
        project_id = _require_int(payload, "project_id")
        defect_id = _entity_id(payload, id_key="defect_id")
        request = _validate_model(DefectUpdateRequest, payload.get("defect"), path="defect")
        defect = DefectService(self.db).update_defect(
            project_id=project_id,
            defect_id=defect_id,
            payload=request,
            current_user=current_user,
        )
        return {
            "operation": "update_saved",
            "project_id": project_id,
            "defect_id": defect_id,
            "defect": normalize_response_data(DefectRead.model_validate(defect)),
        }

    def _defect_transition_status(self, payload: dict[str, Any], current_user: User) -> dict[str, Any]:
        project_id = _require_int(payload, "project_id")
        defect_id = _entity_id(payload, id_key="defect_id")
        request = _validate_model(
            DefectStatusUpdateRequest,
            {"status": _require_str(payload, "status")},
            path="status",
        )
        defect = DefectService(self.db).transition_status(
            project_id=project_id,
            defect_id=defect_id,
            payload=request,
            current_user=current_user,
        )
        return {
            "operation": "transition_status",
            "project_id": project_id,
            "defect_id": defect_id,
            "defect": normalize_response_data(DefectRead.model_validate(defect)),
        }

    @staticmethod
    def _plan_view(item: dict[str, Any], *, detail_level: str) -> dict[str, Any]:
        if detail_level == "full":
            return item
        return {
            key: item.get(key)
            for key in (
                "id",
                "project_id",
                "version",
                "name",
                "description",
                "enabled",
                "trigger_type",
                "execution_mode",
                "failure_policy",
                "environment_ids",
                "tags",
                "last_run_at",
                "next_run_at",
                "updated_at",
            )
        } | {"target_count": len(item.get("targets") or [])}

    @staticmethod
    def _plan_run_view(run: TestPlanRun, *, include_results: bool) -> dict[str, Any]:
        return normalize_response_data({
            "id": run.id,
            "plan_id": run.plan_id,
            "plan_name": run.plan_name,
            "plan_version": run.plan_version,
            "project_id": run.project_id,
            "environment_id": run.environment_id,
            "environment_name": run.environment_name,
            "status": run.status,
            "trigger": run.trigger,
            "scheduled_at": run.scheduled_at,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
            "duration_ms": run.duration_ms,
            "target_count": run.target_count,
            "passed_count": run.passed_count,
            "failed_count": run.failed_count,
            "error_message": run.error_message,
            "operator": {
                "id": run.operator_id,
                "name": run.operator.username if run.operator else str(run.operator_id),
            },
            **({"target_results": run.target_results} if include_results else {}),
        })

    @staticmethod
    def _defect_view(item: dict[str, Any], *, detail_level: str) -> dict[str, Any]:
        if detail_level == "full":
            return item
        return {
            key: item.get(key)
            for key in (
                "id",
                "project_id",
                "title",
                "assignee_name",
                "bug_type",
                "urgency",
                "status",
                "reporter_name",
                "created_at",
                "updated_at",
            )
        } | {"attachment_count": len(item.get("attachments") or [])}


def _require_int(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"{key} must be an integer")
    return value


def _optional_int(payload: dict[str, Any], key: str) -> int | None:
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"{key} must be an integer")
    return value


def _require_bool(payload: dict[str, Any], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"{key} must be a boolean")
    return value


def _optional_bool(payload: dict[str, Any], key: str) -> bool | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"{key} must be a boolean")
    return value


def _require_str(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"{key} must be a non-empty string")
    return value.strip()


def _optional_str(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"{key} must be a non-empty string")
    return value.strip()


def _optional_datetime(payload: dict[str, Any], key: str) -> datetime | None:
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"{key} must be an ISO datetime")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{key} must be an ISO datetime",
        ) from exc


def _bounded_masked_text(value: Any, max_chars: int) -> str | None:
    if value is None:
        return None
    masked = str(mask_sensitive(value))
    return masked if len(masked) <= max_chars else f"{masked[:max_chars]}[agent_diagnostic_truncated]"


def _bounded_diagnostic_value(value: Any, *, depth: int = 0) -> Any:
    if depth >= 4:
        return "[agent_diagnostic_depth_limited]"
    masked = mask_sensitive(value)
    if isinstance(masked, str):
        return _bounded_masked_text(masked, 512)
    if isinstance(masked, dict):
        return {
            str(key): _bounded_diagnostic_value(item, depth=depth + 1)
            for key, item in list(masked.items())[:20]
        }
    if isinstance(masked, (list, tuple)):
        return [_bounded_diagnostic_value(item, depth=depth + 1) for item in list(masked)[:20]]
    if isinstance(masked, (int, float, bool)) or masked is None:
        return masked
    return _bounded_masked_text(masked, 512)


def _isoformat(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return _bounded_masked_text(value, 64)


def _agent_diagnostic_event_view(event: AgentEvent) -> dict[str, Any]:
    payload = event.payload_json if isinstance(event.payload_json, dict) else {}
    details = {
        key: _bounded_diagnostic_value(payload[key])
        for key in _AGENT_DIAGNOSTIC_EVENT_FIELDS
        if payload.get(key) is not None
    }
    return {
        "event_seq": event.event_seq,
        "event_type": event.event_type,
        "details": details,
        "created_at": _isoformat(event.created_at),
    }


def _agent_tool_call_summary(call: AgentToolCall) -> dict[str, Any]:
    return {
        "tool_call_id": call.tool_call_id,
        "tool_name": call.tool_name,
        "status": call.status,
        "side_effect_class": call.resolved_side_effect_class,
        "approval_required": bool(call.approval_required),
        "approved": bool(call.approved_approval_id),
        "error_code": call.error_code,
        "error_message": _bounded_masked_text(call.error_message, 512),
    }


def _page_bounds(payload: dict[str, Any]) -> tuple[int, int]:
    page = _optional_int(payload, "page") or 1
    page_size = _optional_int(payload, "page_size") or 20
    if page < 1 or page_size < 1 or page_size > 100:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="page must be >= 1 and page_size must be between 1 and 100",
        )
    return page, page_size


def _detail_level(payload: dict[str, Any], *, allowed: set[str]) -> str:
    detail_level = _optional_str(payload, "detail_level") or "summary"
    if detail_level not in allowed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"detail_level must be one of: {', '.join(sorted(allowed))}",
        )
    return detail_level


def _require_execution_type(payload: dict[str, Any], key: str) -> str:
    value = _require_str(payload, key)
    if value not in _EXECUTION_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{key} must be one of: {', '.join(sorted(_EXECUTION_TYPES))}",
        )
    return value


def _optional_execution_type(payload: dict[str, Any], key: str) -> str | None:
    value = _optional_str(payload, key)
    if value is None:
        return None
    if value not in _EXECUTION_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{key} must be one of: {', '.join(sorted(_EXECUTION_TYPES))}",
        )
    return value


def _entity_id(payload: dict[str, Any], *, id_key: str, ref_key: str = "object_reference") -> int:
    value = _optional_int(payload, id_key)
    if value is not None:
        return value
    reference = _optional_str(payload, ref_key)
    if reference:
        match = _OBJECT_REF_ID_RE.search(reference)
        if match:
            return int(match.group("object_id"))
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=f"{id_key} or {ref_key} is required",
    )


def _validate_model(model_type: type[Any], value: Any, *, path: str):
    if not isinstance(value, dict):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"{path} must be an object")
    try:
        return model_type.model_validate(value)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.errors()) from exc


def _snapshot_and_references(
    *,
    object_family: str,
    project_id: int,
    rows: list[dict[str, Any]],
    name_getter,
    object_type_getter=None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    generated_at = datetime.now(UTC).isoformat()
    identities = [
        {
            "object_type": object_type_getter(item) if object_type_getter else object_family,
            "id": item.get("execution_id") if object_family == "execution" else item.get("id"),
        }
        for item in rows
    ]
    snapshot_id = f"{object_family}-snapshot://{request_fingerprint({'project_id': project_id, 'identities': identities, 'generated_at': generated_at})}"
    snapshot = {
        "snapshot_id": snapshot_id,
        "object_family": object_family,
        "project_id": project_id,
        "generated_at": generated_at,
        "validity_scope": "current_agent_conversation_latest_query",
        "authoritative_for_tool_input": True,
    }
    references = []
    for item, identity in zip(rows, identities):
        object_id = identity["id"]
        if not isinstance(object_id, int):
            continue
        object_type = str(identity["object_type"] or object_family)
        references.append({
            "id": object_id,
            "object_ref": _object_reference(
                object_family=object_family,
                object_type=object_type,
                object_id=object_id,
                snapshot_id=snapshot_id,
            ),
            "object_type": object_type,
            "name": name_getter(item),
            "snapshot_id": snapshot_id,
        })
    return snapshot, references


def _object_reference(
    *,
    object_family: str,
    object_type: str,
    object_id: int,
    snapshot_id: str,
) -> str:
    snapshot_token = request_fingerprint({"snapshot_id": snapshot_id})[:12]
    return f"object-ref://{object_family}/{object_type}/{snapshot_token}/{object_id}"


def _object_reference_manifest(
    *,
    object_family: str,
    query_tool: str,
    snapshot: dict[str, Any],
    references: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "object_family": object_family,
        "query_tool": query_tool,
        "snapshot_id": snapshot["snapshot_id"],
        "validity_scope": snapshot["validity_scope"],
        "id_source_rule": "Use only explicit ids or object_ref handles from the latest query snapshot.",
        "object_references": references,
    }


def _attach_references(
    rows: list[dict[str, Any]],
    references: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    refs = {item["id"]: item["object_ref"] for item in references}
    return [{**item, "object_ref": refs.get(item.get("id"))} for item in rows]


def _agent_execution_source(payload: dict[str, Any]) -> dict[str, str | None]:
    return {
        "trigger_source": "agent",
        "agent_run_id": payload.get("_agent_run_id") if isinstance(payload.get("_agent_run_id"), str) else None,
        "agent_tool_call_id": (
            payload.get("_agent_tool_call_id") if isinstance(payload.get("_agent_tool_call_id"), str) else None
        ),
    }
