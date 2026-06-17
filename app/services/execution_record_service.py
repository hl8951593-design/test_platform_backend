from datetime import datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.permissions import ProjectPermission
from app.models.user import User
from app.repositories.execution_record_repository import ExecutionRecordRepository
from app.schemas.execution_record import (
    ExecutionRecordDetail,
    ExecutionRecordPage,
    ExecutionRecordSummary,
    ExecutionType,
)
from app.services.permission_service import PermissionService


class ExecutionRecordService:
    def __init__(self, db: Session):
        self.repository = ExecutionRecordRepository(db)
        self.permission_service = PermissionService(db)

    def _require_view(self, current_user: User, project_id: int) -> None:
        self.permission_service.require_project_permission(
            current_user,
            project_id,
            ProjectPermission.VIEW_REPORT.value,
        )

    @staticmethod
    def _summary(values: dict[str, Any]) -> ExecutionRecordSummary:
        execution_type = values["execution_type"]
        scenario_run_id = values.get("scenario_run_id")
        trigger_type = values["scenario_trigger"]
        duration_ms = values.get("duration_ms")
        if execution_type in {"http", "websocket"}:
            trigger_type = "scenario" if scenario_run_id is not None else "manual"
        elif (
            execution_type == "flow"
            and duration_ms is None
            and values.get("started_at") is not None
            and values.get("finished_at") is not None
        ):
            duration_ms = max(
                int(
                    (
                        values["finished_at"] - values["started_at"]
                    ).total_seconds() * 1000
                ),
                0,
            )
        return ExecutionRecordSummary(
            id=f"{execution_type}:{values['execution_id']}",
            execution_type=execution_type,
            execution_id=values["execution_id"],
            project_id=values["project_id"],
            resource_id=values.get("resource_id"),
            resource_name=values.get("resource_name"),
            environment_id=values.get("environment_id"),
            scenario_run_id=scenario_run_id,
            status=values["status"],
            trigger_type=trigger_type,
            trigger_user_id=values["trigger_user_id"],
            duration_ms=duration_ms,
            error_message=values.get("error_message"),
            dataset_id=values.get("dataset_id"),
            dataset_name=values.get("dataset_name"),
            record_id=values.get("record_id"),
            record_name=values.get("record_name"),
            started_at=values.get("started_at"),
            finished_at=values.get("finished_at"),
            created_at=values["created_at"],
        )

    def list_records(
        self,
        *,
        project_id: int,
        current_user: User,
        execution_type: ExecutionType | None,
        status_filter: str | None,
        environment_id: int | None,
        trigger_user_id: int | None,
        started_from: datetime | None,
        started_to: datetime | None,
        keyword: str | None,
        page: int,
        page_size: int,
    ) -> ExecutionRecordPage:
        self._require_view(current_user, project_id)
        if started_from is not None and started_to is not None and started_from > started_to:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="started_from must be earlier than or equal to started_to",
            )
        rows, total = self.repository.list_records(
            project_id=project_id,
            execution_type=execution_type,
            status=status_filter,
            environment_id=environment_id,
            trigger_user_id=trigger_user_id,
            started_from=started_from,
            started_to=started_to,
            keyword=keyword,
            page=page,
            page_size=page_size,
        )
        return ExecutionRecordPage(
            items=[self._summary(row) for row in rows],
            total=total,
            page=page,
            page_size=page_size,
        )

    @staticmethod
    def _column_values(model: Any) -> dict[str, Any]:
        return {
            column.name: getattr(model, column.name)
            for column in model.__table__.columns
        }

    def get_detail(
        self,
        *,
        project_id: int,
        execution_type: ExecutionType,
        execution_id: int,
        current_user: User,
    ) -> ExecutionRecordDetail:
        self._require_view(current_user, project_id)
        loader = getattr(self, f"_get_{execution_type}_detail")
        result = loader(project_id=project_id, execution_id=execution_id)
        if result is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="execution record not found",
            )
        return result

    def _get_http_detail(self, *, project_id: int, execution_id: int):
        row = self.repository.get_http(project_id=project_id, execution_id=execution_id)
        if row is None:
            return None
        execution, resource_name = row
        summary = self._summary({
            "execution_type": "http",
            "execution_id": execution.id,
            "project_id": execution.project_id,
            "resource_id": execution.test_case_id,
            "resource_name": resource_name,
            "environment_id": execution.environment_id,
            "scenario_run_id": execution.scenario_run_id,
            "status": execution.status,
            "scenario_trigger": "scenario",
            "trigger_user_id": execution.executed_by_id,
            "duration_ms": execution.duration_ms,
            "error_message": execution.error_message,
            "started_at": execution.created_at,
            "finished_at": None,
            "created_at": execution.created_at,
        })
        detail = self._column_values(execution)
        return ExecutionRecordDetail(summary=summary, detail=detail)

    def _get_websocket_detail(self, *, project_id: int, execution_id: int):
        row = self.repository.get_websocket(project_id=project_id, execution_id=execution_id)
        if row is None:
            return None
        execution, resource_name = row
        summary = self._summary({
            "execution_type": "websocket",
            "execution_id": execution.id,
            "project_id": execution.project_id,
            "resource_id": execution.websocket_test_case_id,
            "resource_name": resource_name,
            "environment_id": execution.environment_id,
            "scenario_run_id": execution.scenario_run_id,
            "status": execution.status,
            "scenario_trigger": "scenario",
            "trigger_user_id": execution.executed_by_id,
            "duration_ms": execution.duration_ms,
            "error_message": execution.error_message,
            "started_at": execution.created_at,
            "finished_at": None,
            "created_at": execution.created_at,
        })
        detail = self._column_values(execution)
        return ExecutionRecordDetail(summary=summary, detail=detail)

    def _get_scenario_detail(self, *, project_id: int, execution_id: int):
        row = self.repository.get_scenario(project_id=project_id, execution_id=execution_id)
        if row is None:
            return None
        execution, resource_name = row
        summary = self._summary({
            "execution_type": "scenario",
            "execution_id": execution.id,
            "project_id": execution.project_id,
            "resource_id": execution.scenario_id,
            "resource_name": resource_name,
            "environment_id": execution.environment_id,
            "scenario_run_id": None,
            "status": execution.status,
            "scenario_trigger": execution.trigger_type,
            "trigger_user_id": execution.triggered_by_id,
            "duration_ms": execution.duration_ms,
            "error_message": None,
            "dataset_id": execution.dataset_id,
            "dataset_name": execution.dataset_name,
            "record_id": execution.record_id,
            "record_name": execution.record_name,
            "started_at": execution.started_at,
            "finished_at": execution.finished_at,
            "created_at": execution.created_at,
        })
        detail = self._column_values(execution)
        detail["events"] = [
            self._column_values(event)
            for event in self.repository.list_scenario_events(execution.id)
        ]
        return ExecutionRecordDetail(summary=summary, detail=detail)

    def _get_flow_detail(self, *, project_id: int, execution_id: int):
        row = self.repository.get_flow(project_id=project_id, execution_id=execution_id)
        if row is None:
            return None
        execution, resource_name = row
        duration_ms = None
        if execution.started_at is not None and execution.finished_at is not None:
            duration_ms = max(
                int((execution.finished_at - execution.started_at).total_seconds() * 1000),
                0,
            )
        summary = self._summary({
            "execution_type": "flow",
            "execution_id": execution.id,
            "project_id": execution.project_id,
            "resource_id": execution.flow_id,
            "resource_name": resource_name,
            "environment_id": execution.environment_id,
            "scenario_run_id": None,
            "status": execution.status,
            "scenario_trigger": execution.trigger_type,
            "trigger_user_id": execution.trigger_user_id,
            "duration_ms": duration_ms,
            "error_message": None,
            "started_at": execution.started_at,
            "finished_at": execution.finished_at,
            "created_at": execution.created_at,
        })
        detail = self._column_values(execution)
        detail["node_executions"] = [
            self._column_values(node)
            for node in self.repository.list_flow_nodes(execution.id)
        ]
        return ExecutionRecordDetail(summary=summary, detail=detail)
