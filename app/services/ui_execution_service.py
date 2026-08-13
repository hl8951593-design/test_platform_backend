from __future__ import annotations

import hashlib
import json
import secrets
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.desktop_device_security import utc_rfc3339
from app.core.permissions import ProjectPermission
from app.models.ui_execution import UiExecution
from app.models.user import User
from app.repositories.execution_diagnostic_repository import (
    ExecutionDiagnosticRepository,
)
from app.repositories.project_repository import ProjectRepository
from app.repositories.ui_execution_repository import UiExecutionRepository
from app.repositories.ui_test_case_repository import UiTestCaseRepository
from app.schemas.ui_execution import UiExecutionAcceptedRead, UiExecutionCreateRequest
from app.services.permission_service import PermissionService


class UiExecutionService:
    def __init__(self, db: Session):
        self.db = db
        self.repository = UiExecutionRepository(db)
        self.case_repository = UiTestCaseRepository(db)
        self.project_repository = ProjectRepository(db)
        self.diagnostic_repository = ExecutionDiagnosticRepository(db)
        self.permission_service = PermissionService(db)

    def create_execution(
        self,
        *,
        project_id: int,
        case_public_id: str,
        payload: UiExecutionCreateRequest,
        current_user: User,
    ) -> tuple[UiExecutionAcceptedRead, str | None, bool]:
        self.permission_service.require_project_permission(
            current_user,
            project_id,
            ProjectPermission.EXECUTE_TEST.value,
        )
        request_hash = self._request_hash(
            project_id=project_id,
            case_public_id=case_public_id,
            payload=payload,
        )
        existing = self.repository.get_by_client_request(
            project_id=project_id,
            trigger_user_id=current_user.id,
            client_request_id=payload.client_request_id,
        )
        if existing is not None:
            return self._replay(existing, request_hash=request_hash), None, True

        ui_test_case = self.case_repository.get_by_public_id(
            case_public_id,
            project_id=project_id,
        )
        if ui_test_case is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="ui_test_case_not_found",
            )
        if ui_test_case.status != "active":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="ui_test_case_not_active",
            )
        version = self.case_repository.get_version(
            ui_test_case_id=ui_test_case.id,
            version_number=payload.version,
        )
        if version is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="ui_test_case_version_not_found",
            )
        environment = self.project_repository.get_environment_with_context(
            project_id=project_id,
            environment_id=payload.environment_id,
        )
        if environment is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="ui_execution_environment_not_found",
            )

        requested_device = None
        if payload.requested_device_id is not None:
            requested_device = self.repository.get_available_requested_device(
                device_public_id=payload.requested_device_id,
                project_id=project_id,
            )
            if requested_device is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="ui_execution_requested_device_unavailable",
                )

        now = datetime.now(UTC).replace(tzinfo=None)
        snapshot = self._case_snapshot(
            ui_test_case=ui_test_case,
            version=version,
            environment=environment,
        )
        execution = UiExecution(
            public_id=f"ui_exec_{secrets.token_urlsafe(18)}",
            project_id=project_id,
            environment_id=environment.id,
            ui_test_case_id=ui_test_case.id,
            ui_test_case_version_id=version.id,
            trigger_user_id=current_user.id,
            trigger_type="manual",
            source=payload.source,
            client_request_id=payload.client_request_id,
            request_hash=request_hash,
            requested_device_id=requested_device.id if requested_device else None,
            status="queued",
            delivery_status="pending",
            case_snapshot_json=snapshot,
            runtime_policy_json={
                "schema_version": "ui-runtime-policy-v1",
                **payload.runtime_options.model_dump(mode="json"),
            },
            required_secret_refs_json=list(version.required_secret_refs_json or []),
            total_steps=len(
                [
                    step
                    for step in (version.dsl_json or {}).get("steps", [])
                    if step.get("enabled", True)
                ]
            ),
            created_at=now,
            updated_at=now,
        )
        try:
            self.repository.add(execution)
            self.diagnostic_repository.upsert_execution_index(
                self._projection_values(execution, resource_name=ui_test_case.name)
            )
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            concurrent = self.repository.get_by_client_request(
                project_id=project_id,
                trigger_user_id=current_user.id,
                client_request_id=payload.client_request_id,
            )
            if concurrent is not None:
                return self._replay(concurrent, request_hash=request_hash), None, True
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="ui_execution_create_conflict",
            ) from exc
        self.db.refresh(execution)
        return (
            self._serialize_accepted(execution),
            requested_device.public_id if requested_device is not None else None,
            False,
        )

    @staticmethod
    def _request_hash(
        *,
        project_id: int,
        case_public_id: str,
        payload: UiExecutionCreateRequest,
    ) -> str:
        canonical = {
            "project_id": project_id,
            "case_id": case_public_id,
            **payload.model_dump(mode="json"),
        }
        encoded = json.dumps(
            canonical,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _replay(
        self,
        execution: UiExecution,
        *,
        request_hash: str,
    ) -> UiExecutionAcceptedRead:
        if execution.request_hash != request_hash:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="client_request_id_payload_conflict",
            )
        return self._serialize_accepted(execution)

    @staticmethod
    def _case_snapshot(*, ui_test_case, version, environment) -> dict[str, Any]:
        public_variables: dict[str, str] = {}
        required_secret_refs = set(version.required_secret_refs_json or [])
        secret_variable_names: list[str] = []
        for variable in environment.variables:
            if variable.is_secret:
                if variable.name in required_secret_refs:
                    secret_variable_names.append(variable.name)
            else:
                public_variables[variable.name] = variable.value
        return {
            "schema_version": "ui-execution-snapshot-v1",
            "case": {
                "case_id": ui_test_case.public_id,
                "name": ui_test_case.name,
                "version": version.version_number,
                "checksum": f"sha256:{version.checksum_sha256}",
                "dsl": version.dsl_json,
            },
            "environment": {
                "environment_id": environment.id,
                "name": environment.name,
                "base_url": environment.base_url,
                "variables": public_variables,
                "secret_variable_names": sorted(secret_variable_names),
            },
        }

    @staticmethod
    def _projection_values(
        execution: UiExecution,
        *,
        resource_name: str,
    ) -> dict[str, Any]:
        return {
            "project_id": execution.project_id,
            "execution_type": "ui",
            "execution_id": execution.id,
            "object_ref": execution.public_id,
            "resource_id": execution.ui_test_case_id,
            "resource_name": resource_name,
            "environment_id": execution.environment_id,
            "status": execution.status,
            "trigger_type": execution.trigger_type,
            "trigger_user_id": execution.trigger_user_id,
            "duration_ms": execution.duration_ms,
            "total_steps": execution.total_steps,
            "passed_steps": execution.passed_steps,
            "failed_steps": execution.failed_steps,
            "timeout_steps": 0,
            "skipped_steps": execution.skipped_steps,
            "first_failed_step_id": None,
            "failure_category": execution.error_category,
            "failure_signature": None,
            "started_at": execution.created_at,
            "finished_at": execution.finished_at,
            "source_updated_at": execution.updated_at,
            "projection_version": "ui-runtime-v1",
        }

    @staticmethod
    def _serialize_accepted(
        execution: UiExecution,
    ) -> UiExecutionAcceptedRead:
        return UiExecutionAcceptedRead(
            execution_id=execution.public_id,
            status="queued",
            delivery_status=execution.delivery_status,
            created_at=utc_rfc3339(execution.created_at),
        )
