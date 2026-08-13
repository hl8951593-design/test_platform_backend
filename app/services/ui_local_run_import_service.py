from __future__ import annotations

import secrets
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.permissions import ProjectPermission
from app.models.ui_execution import UiExecution, UiStepExecution
from app.models.user import User
from app.repositories.desktop_device_repository import DesktopDeviceRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.ui_execution_repository import UiExecutionRepository
from app.repositories.ui_test_case_repository import UiTestCaseRepository
from app.schemas.ui_execution import UiLocalRunImportRequest
from app.services.permission_service import PermissionService
from app.services.ui_execution_runtime_service import UiExecutionRuntimeService
from app.services.ui_execution_service import UiExecutionService


class UiLocalRunImportService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repository = UiExecutionRepository(db)
        self.case_repository = UiTestCaseRepository(db)
        self.project_repository = ProjectRepository(db)
        self.device_repository = DesktopDeviceRepository(db)
        self.permission_service = PermissionService(db)
        self.runtime = UiExecutionRuntimeService(db)

    def import_run(
        self,
        *,
        project_id: int,
        payload: UiLocalRunImportRequest,
        current_user: User,
    ) -> tuple[dict[str, Any], bool]:
        self.permission_service.require_project_permission(
            current_user,
            project_id,
            ProjectPermission.EXECUTE_TEST.value,
        )
        request_hash = self.runtime._hash_json(
            {"project_id": project_id, **payload.model_dump(mode="json")}
        )
        existing = self.repository.get_by_client_request(
            project_id=project_id,
            trigger_user_id=current_user.id,
            client_request_id=payload.client_request_id,
        )
        if existing is not None:
            return self._replay(existing, request_hash=request_hash), True

        ui_test_case = self.case_repository.get_by_public_id(
            payload.case_id,
            project_id=project_id,
        )
        if ui_test_case is None:
            self.runtime._raise(status.HTTP_404_NOT_FOUND, "ui_test_case_not_found")
        version = self.case_repository.get_version(
            ui_test_case_id=ui_test_case.id,
            version_number=payload.version,
        )
        if version is None:
            self.runtime._raise(
                status.HTTP_404_NOT_FOUND,
                "ui_test_case_version_not_found",
            )
        environment = self.project_repository.get_environment_with_context(
            project_id=project_id,
            environment_id=payload.environment_id,
        )
        if environment is None:
            self.runtime._raise(
                status.HTTP_404_NOT_FOUND,
                "ui_execution_environment_not_found",
            )
        assigned_device = self._resolve_device(
            project_id=project_id,
            device_public_id=payload.device_id,
            current_user=current_user,
        )
        snapshot = UiExecutionService._case_snapshot(
            ui_test_case=ui_test_case,
            version=version,
            environment=environment,
        )
        enabled_steps = [
            item
            for item in (version.dsl_json or {}).get("steps", [])
            if item.get("enabled", True)
        ]
        if payload.summary.total_steps != len(enabled_steps):
            self.runtime._raise(status.HTTP_409_CONFLICT, "execution_summary_conflict")
        descriptors = {
            str(item.get("id")): (index, item)
            for index, item in enumerate(enabled_steps)
        }
        latest: dict[str, Any] = {}
        for item in payload.steps:
            if item.step_id not in descriptors:
                self.runtime._raise(
                    status.HTTP_404_NOT_FOUND,
                    "ui_execution_step_not_found",
                )
            current = latest.get(item.step_id)
            if current is None or item.attempt > current.attempt:
                latest[item.step_id] = item
        counts = {
            "passed": sum(item.status == "passed" for item in latest.values()),
            "failed": sum(item.status in {"failed", "timeout"} for item in latest.values()),
            "skipped": sum(item.status == "skipped" for item in latest.values()),
        }
        if (
            counts["passed"] != payload.summary.passed_steps
            or counts["failed"] != payload.summary.failed_steps
            or counts["skipped"] != payload.summary.skipped_steps
        ):
            self.runtime._raise(status.HTTP_409_CONFLICT, "execution_summary_conflict")

        primary = payload.primary_error
        execution = UiExecution(
            public_id=f"ui_exec_{secrets.token_urlsafe(18)}",
            project_id=project_id,
            environment_id=environment.id,
            ui_test_case_id=ui_test_case.id,
            ui_test_case_version_id=version.id,
            trigger_user_id=current_user.id,
            trigger_type="local_import",
            source="local_import",
            client_request_id=payload.client_request_id,
            request_hash=request_hash,
            assigned_device_id=assigned_device.id if assigned_device is not None else None,
            status=payload.status,
            delivery_status="complete",
            case_snapshot_json=snapshot,
            runtime_policy_json={"schema_version": "ui-runtime-policy-v1"},
            required_secret_refs_json=list(version.required_secret_refs_json or []),
            current_step=len(latest),
            total_steps=payload.summary.total_steps,
            passed_steps=payload.summary.passed_steps,
            failed_steps=payload.summary.failed_steps,
            skipped_steps=payload.summary.skipped_steps,
            assisted=payload.summary.assisted or payload.status == "assisted",
            duration_ms=payload.summary.duration_ms,
            error_category=primary.category if primary is not None else None,
            error_message=primary.message if primary is not None else None,
            started_at=self.runtime._naive_utc(payload.started_at),
            finished_at=self.runtime._naive_utc(payload.finished_at),
        )
        try:
            self.repository.add(execution)
            for item in payload.steps:
                index, descriptor = descriptors[item.step_id]
                step = UiStepExecution(
                    ui_execution_id=execution.id,
                    step_id=item.step_id,
                    attempt=item.attempt,
                    step_index=index,
                    name=str(descriptor.get("name") or item.step_id)[:200],
                    kind=str(descriptor.get("kind") or "action")[:32],
                    operation=str(descriptor.get("operation") or "unknown")[:32],
                    status=item.status,
                    started_at=self.runtime._naive_utc(item.started_at),
                    finished_at=self.runtime._naive_utc(item.finished_at),
                    duration_ms=item.duration_ms,
                    error_code=item.error_code,
                    error_message=item.error_message,
                    result_summary_json=item.result,
                )
                self.repository.add_step(step)
                self.runtime._project_step(execution, step)
            self.runtime._project_execution(execution)
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            concurrent = self.repository.get_by_client_request(
                project_id=project_id,
                trigger_user_id=current_user.id,
                client_request_id=payload.client_request_id,
            )
            if concurrent is not None:
                return self._replay(concurrent, request_hash=request_hash), True
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"error": "ui_local_run_import_conflict"},
            ) from exc
        self.db.refresh(execution)
        return self.runtime._serialize_detail(
            self.repository.get_detail_by_public_id(execution.public_id)
        ), False

    def _resolve_device(
        self,
        *,
        project_id: int,
        device_public_id: str | None,
        current_user: User,
    ):
        if device_public_id is None:
            return None
        device = self.device_repository.get_by_public_id(device_public_id)
        if (
            device is None
            or device.owner_id != current_user.id
            or device.registration_status != "active"
        ):
            self.runtime._raise(status.HTTP_404_NOT_FOUND, "desktop_device_not_found")
        binding = self.repository.get_project_binding(
            device_id=device.id,
            project_id=project_id,
        )
        if binding is None or not binding.enabled:
            self.runtime._raise(status.HTTP_403_FORBIDDEN, "device_project_not_bound")
        return device

    def _replay(self, execution: UiExecution, *, request_hash: str) -> dict[str, Any]:
        if execution.source != "local_import" or execution.request_hash != request_hash:
            self.runtime._raise(
                status.HTTP_409_CONFLICT,
                "client_request_id_payload_conflict",
            )
        detail = self.repository.get_detail_by_public_id(execution.public_id)
        return self.runtime._serialize_detail(detail)
