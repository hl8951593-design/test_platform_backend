from __future__ import annotations

import hashlib
import json
import secrets
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException, status
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.desktop_device_security import utc_now_naive, utc_rfc3339
from app.core.permissions import ProjectPermission
from app.core.sensitive_data import redact_sensitive_data
from app.db.session import SessionLocal
from app.models.desktop_device import DesktopDeviceProjectBinding
from app.models.ui_execution import (
    UiExecution,
    UiExecutionCommand,
    UiExecutionEvent,
    UiRuntimePatch,
    UiStepExecution,
)
from app.models.user import User
from app.repositories.execution_diagnostic_repository import ExecutionDiagnosticRepository
from app.repositories.ui_execution_repository import UiExecutionRepository
from app.schemas.ui_execution import (
    UiExecutionClaimRequest,
    UiExecutionCommandAckRequest,
    UiExecutionCommandCreateRequest,
    UiExecutionCompleteRequest,
    UiExecutionEventBatchRequest,
    UiExecutionEventItem,
    UiExecutionLeaseRequest,
    UiExecutionPatchRequestCreateRequest,
    UiExecutionRuntimePatchRequest,
)
from app.schemas.ui_test_case import UiCaseStep
from app.services.desktop_device_service import DesktopDevicePrincipal, DesktopDeviceService
from app.services.permission_service import PermissionService


ACTIVE_STATUSES = {"claimed", "launching", "running", "paused", "waiting_user"}
TERMINAL_STATUSES = {"passed", "assisted", "failed", "cancelled", "lost"}
ASSISTED_EVENT_TYPES = {
    "execution.assisted",
    "step.retry",
    "step.skipped",
    "user.intervention",
}
EVENT_STATUS_TARGETS = {
    "execution.launching": "launching",
    "execution.running": "running",
    "execution.paused": "paused",
    "execution.waiting_user": "waiting_user",
}
ALLOWED_STATUS_TRANSITIONS = {
    "claimed": {"launching", "running"},
    "launching": {"running"},
    "running": {"paused", "waiting_user"},
    "paused": {"running"},
    "waiting_user": {"running"},
}
PATCH_FIELDS = {
    "locator": ("locator_by", "locator_value"),
    "input": ("input_value",),
    "timeout": ("timeout_ms",),
    "failure_policy": ("failure_policy",),
}


class UiExecutionRuntimeService:
    def __init__(self, db: Session):
        self.db = db
        self.repository = UiExecutionRepository(db)
        self.diagnostic_repository = ExecutionDiagnosticRepository(db)
        self.permission_service = PermissionService(db)

    def list_executions(
        self,
        *,
        project_id: int,
        current_user: User,
        execution_status: str | None,
        delivery_status: str | None,
        attention_only: bool,
        assigned_device_id: str | None,
        environment_id: int | None,
        source: str | None,
        keyword: str | None,
        page: int,
        page_size: int,
    ) -> dict[str, Any]:
        self._require_report_view(current_user, project_id)
        items, total, facets = self.repository.list_by_project(
            project_id=project_id,
            status=execution_status,
            delivery_status=delivery_status,
            attention_only=attention_only,
            assigned_device_public_id=assigned_device_id,
            environment_id=environment_id,
            source=source,
            keyword=keyword,
            page=page,
            page_size=page_size,
        )
        return {
            "items": [self._serialize_summary(item) for item in items],
            "facets": facets,
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    def list_available_executions(
        self,
        *,
        principal: DesktopDevicePrincipal,
        limit: int,
    ) -> dict[str, Any]:
        device = principal.device
        if not device.accepting_jobs or not self._runtime_compatible(principal):
            return {"items": [], "total": 0}

        active_count = self.repository.count_active_for_device(device.id)
        device_limit = min(
            device.concurrency_limit,
            settings.DESKTOP_MAX_CONCURRENCY,
        )
        if active_count >= device_limit:
            return {"items": [], "total": 0}

        items, total = self.repository.list_available_for_device(
            device_id=device.id,
            active_count=active_count,
            limit=limit,
        )
        return {
            "items": [
                {
                    **self._serialize_summary(item),
                    "expected_status": item.status,
                }
                for item in items
            ],
            "total": total,
        }

    def get_execution(
        self,
        *,
        execution_public_id: str,
        current_user: User,
    ) -> dict[str, Any]:
        execution = self.repository.get_detail_by_public_id(execution_public_id)
        if execution is None:
            self._raise(status.HTTP_404_NOT_FOUND, "ui_execution_not_found")
        self._require_report_view(current_user, execution.project_id)
        return self._serialize_detail(execution)

    def claim(
        self,
        *,
        execution_public_id: str,
        payload: UiExecutionClaimRequest,
        principal: DesktopDevicePrincipal,
    ) -> dict[str, Any]:
        if payload.device_id != principal.device.public_id:
            self._raise(status.HTTP_403_FORBIDDEN, "device_identity_mismatch")
        execution = self._locked_execution(execution_public_id)
        binding = self._require_device_binding(
            execution=execution,
            principal=principal,
            require_accepting=True,
        )
        now = utc_now_naive()

        if (
            execution.assigned_device_id == principal.device.id
            and execution.status in ACTIVE_STATUSES
            and execution.lease_id
            and execution.lease_expires_at
            and execution.lease_expires_at > now
        ):
            return self._claim_response(execution)
        if execution.status != payload.expected_status or execution.status not in {
            "queued",
            "assigned",
        }:
            self._raise(
                status.HTTP_409_CONFLICT,
                "execution_claim_conflict",
                current_status=execution.status,
            )
        if (
            execution.requested_device_id is not None
            and execution.requested_device_id != principal.device.id
        ):
            self._raise(status.HTTP_409_CONFLICT, "execution_claim_conflict")
        if (
            execution.assigned_device_id is not None
            and execution.assigned_device_id != principal.device.id
        ):
            self._raise(status.HTTP_409_CONFLICT, "execution_claim_conflict")
        if not self._runtime_compatible(
            principal,
            supported_dsl_versions=payload.supported_dsl_versions,
            supported_ipc_versions=payload.supported_ipc_versions,
        ):
            self._raise(status.HTTP_409_CONFLICT, "runtime_incompatible")
        concurrency_limit = min(
            principal.device.concurrency_limit,
            binding.concurrency_limit,
            settings.DESKTOP_MAX_CONCURRENCY,
        )
        if self.repository.count_active_for_device(principal.device.id) >= concurrency_limit:
            self._raise(status.HTTP_409_CONFLICT, "device_not_accepting_jobs")

        execution.assigned_device_id = principal.device.id
        execution.status = "claimed"
        execution.lease_id = f"lease_{secrets.token_urlsafe(18)}"
        execution.lease_version = max(execution.lease_version, 0) + 1
        execution.lease_expires_at = now + timedelta(
            seconds=settings.UI_EXECUTION_LEASE_SECONDS
        )
        execution.claimed_at = now
        execution.last_renewed_at = now
        execution.attention_reason = None
        self._project_execution(execution)
        self.db.commit()
        self.db.refresh(execution)
        return self._claim_response(execution)

    def renew_lease(
        self,
        *,
        execution_public_id: str,
        payload: UiExecutionLeaseRequest,
        principal: DesktopDevicePrincipal,
    ) -> dict[str, Any]:
        execution = self._locked_execution(execution_public_id)
        self._require_device_binding(execution=execution, principal=principal)
        now = utc_now_naive()
        self._require_assigned_device(execution, principal)
        if execution.status not in ACTIVE_STATUSES:
            self._raise(
                status.HTTP_409_CONFLICT,
                "execution_not_active",
                current_status=execution.status,
            )
        if execution.lease_id != payload.lease_id:
            self._raise(status.HTTP_409_CONFLICT, "lease_version_conflict")
        if execution.lease_expires_at is None or execution.lease_expires_at <= now:
            self._mark_lost(execution, now=now)
            self.db.commit()
            self._raise(status.HTTP_409_CONFLICT, "lease_expired")

        idempotent_replay = payload.lease_version + 1 == execution.lease_version
        if payload.lease_version != execution.lease_version and not idempotent_replay:
            self._raise(
                status.HTTP_409_CONFLICT,
                "lease_version_conflict",
                current_lease_version=execution.lease_version,
            )
        if not idempotent_replay:
            execution.lease_version += 1
            execution.lease_expires_at = now + timedelta(
                seconds=settings.UI_EXECUTION_LEASE_SECONDS
            )
            execution.last_renewed_at = now

        commands = self.repository.list_deliverable_commands(
            execution_id=execution.id,
            now=now,
        )
        for command in commands:
            if command.status == "pending":
                command.status = "delivered"
                command.delivered_at = now
        self.db.commit()
        return {
            "execution_id": execution.public_id,
            "status": execution.status,
            "lease": self._serialize_lease(execution),
            "last_client_sequence": execution.last_client_sequence,
            "commands": [self._serialize_command(command) for command in commands],
            "idempotent_replay": idempotent_replay,
        }

    def release_lease(
        self,
        *,
        execution_public_id: str,
        payload: UiExecutionLeaseRequest,
        principal: DesktopDevicePrincipal,
    ) -> dict[str, Any]:
        execution = self._locked_execution(execution_public_id)
        self._require_device_binding(execution=execution, principal=principal)
        if (
            execution.status == "queued"
            and execution.assigned_device_id is None
            and execution.lease_id == payload.lease_id
            and execution.lease_version == payload.lease_version + 1
        ):
            return {
                "execution_id": execution.public_id,
                "status": "queued",
                "lease_version": execution.lease_version,
                "idempotent_replay": True,
            }
        self._require_active_lease(execution, payload=payload, principal=principal)
        if execution.status not in {"claimed", "launching"}:
            self._raise(
                status.HTTP_409_CONFLICT,
                "lease_release_not_allowed",
                current_status=execution.status,
            )
        execution.status = "queued"
        execution.assigned_device_id = None
        execution.lease_version += 1
        execution.lease_expires_at = utc_now_naive()
        execution.claimed_at = None
        execution.last_renewed_at = None
        execution.attention_reason = None
        self._project_execution(execution)
        self.db.commit()
        return {
            "execution_id": execution.public_id,
            "status": execution.status,
            "lease_version": execution.lease_version,
            "idempotent_replay": False,
        }

    def append_events(
        self,
        *,
        execution_public_id: str,
        payload: UiExecutionEventBatchRequest,
        principal: DesktopDevicePrincipal,
    ) -> dict[str, Any]:
        if len(payload.events) > settings.UI_EXECUTION_EVENT_BATCH_MAX:
            self._raise(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "desktop_payload_too_large")
        batch_bytes = self._json_size(payload.model_dump(mode="json"))
        if batch_bytes > settings.UI_EXECUTION_EVENT_BATCH_MAX_BYTES:
            self._raise(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "desktop_payload_too_large")

        execution = self._locked_execution(execution_public_id)
        self._require_device_binding(execution=execution, principal=principal)
        self._require_active_lease(execution, payload=payload, principal=principal)
        accepted_count = 0
        duplicate_count = 0
        now = utc_now_naive()

        for item in payload.events:
            redacted_payload = redact_sensitive_data(item.payload)
            if self._json_size(redacted_payload) > settings.UI_EXECUTION_EVENT_MAX_BYTES:
                self._raise(
                    status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    "desktop_payload_too_large",
                    client_event_id=item.client_event_id,
                )
            occurred_at = self._naive_utc(item.occurred_at)
            if occurred_at > now + timedelta(minutes=5):
                self._raise(
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    "event_time_in_future",
                    client_event_id=item.client_event_id,
                )
            by_id, by_sequence = self.repository.get_event_by_identity(
                execution_id=execution.id,
                client_event_id=item.client_event_id,
                client_sequence=item.client_sequence,
            )
            if by_id is not None or by_sequence is not None:
                existing = by_id or by_sequence
                if by_id is not by_sequence or not self._same_event(
                    existing,
                    item=item,
                    payload=redacted_payload,
                    occurred_at=occurred_at,
                ):
                    self._raise(
                        status.HTTP_409_CONFLICT,
                        "event_sequence_conflict",
                        client_event_id=item.client_event_id,
                        client_sequence=item.client_sequence,
                    )
                duplicate_count += 1
                continue
            if item.client_sequence != execution.last_client_sequence + 1:
                self._raise(
                    status.HTTP_409_CONFLICT,
                    "event_sequence_conflict",
                    expected_sequence=execution.last_client_sequence + 1,
                    received_sequence=item.client_sequence,
                )

            event = UiExecutionEvent(
                project_id=execution.project_id,
                ui_execution_id=execution.id,
                client_event_id=item.client_event_id,
                client_sequence=item.client_sequence,
                event_type=item.event_type,
                step_id=item.step_id,
                level=item.level,
                payload_json=redacted_payload,
                occurred_at=occurred_at,
                received_at=now,
            )
            self.repository.add_event(event)
            execution.last_client_sequence = item.client_sequence
            self._apply_event(execution, item=item, payload=redacted_payload, occurred_at=occurred_at)
            accepted_count += 1

        self._sync_step_counts(execution)
        self._project_execution(execution)
        self.db.commit()
        return {
            "execution_id": execution.public_id,
            "accepted_through_sequence": execution.last_client_sequence,
            "accepted_count": accepted_count,
            "duplicate_count": duplicate_count,
            "server_execution_status": execution.status,
            "lease_expires_at": utc_rfc3339(execution.lease_expires_at),
        }

    def create_patch_request(
        self,
        *,
        execution_public_id: str,
        payload: UiExecutionPatchRequestCreateRequest,
        current_user: User,
    ) -> tuple[dict[str, Any], str | None, bool]:
        execution = self._locked_execution(execution_public_id)
        self.permission_service.require_project_permission(
            current_user,
            execution.project_id,
            ProjectPermission.EXECUTE_TEST.value,
        )
        command_public_id = self._command_public_id(
            project_id=execution.project_id,
            user_id=current_user.id,
            client_request_id=payload.client_request_id,
        )
        request_hash = self._hash_json(
            {
                "execution_id": execution.public_id,
                "command_type": "patch",
                **payload.model_dump(mode="json"),
            }
        )
        existing = self.repository.get_command_by_public_id(command_public_id)
        if existing is not None:
            if (
                existing.ui_execution_id != execution.id
                or existing.command_type != "patch"
                or (existing.payload_json or {}).get("request_hash") != request_hash
            ):
                self._raise(status.HTTP_409_CONFLICT, "client_request_id_payload_conflict")
            return self._serialize_command(existing), None, True

        self._validate_command_state(execution, "patch")
        now = utc_now_naive()
        if execution.lease_expires_at is None or execution.lease_expires_at <= now:
            self._mark_lost(execution, now=now)
            self.db.commit()
            self._raise(status.HTTP_409_CONFLICT, "lease_expired")
        if execution.assigned_device is None:
            self._raise(status.HTTP_409_CONFLICT, "execution_device_not_assigned")

        snapshot = self._snapshot_step(execution, payload.step_id)
        if snapshot is None:
            self._raise(status.HTTP_404_NOT_FOUND, "ui_execution_step_not_found")
        effective_step = self._effective_snapshot_step(
            execution=execution,
            step_id=payload.step_id,
            snapshot_step=snapshot["step"],
        )
        patch_fields = PATCH_FIELDS[payload.patch_type]
        expected_fields = set(patch_fields)
        if set(payload.after) != expected_fields or (
            payload.before is not None and set(payload.before) != expected_fields
        ):
            self._raise(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "patch_request_invalid",
                issues=[
                    {
                        "location": ["before", "after"],
                        "message": (
                            f"{payload.patch_type} patch requires exactly: "
                            f"{', '.join(patch_fields)}"
                        ),
                    }
                ],
            )
        current_before = {field: effective_step.get(field) for field in patch_fields}
        supplied_before = (
            redact_sensitive_data(payload.before) if payload.before is not None else None
        )
        if supplied_before is not None and supplied_before != current_before:
            self._raise(
                status.HTTP_409_CONFLICT,
                "patch_request_stale",
                current_before=current_before,
            )
        after = redact_sensitive_data(payload.after)
        if after == current_before:
            self._raise(status.HTTP_409_CONFLICT, "patch_request_noop")
        candidate_step = {**effective_step, **after}
        try:
            UiCaseStep.model_validate(candidate_step)
        except ValidationError as exc:
            self._raise(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "patch_request_invalid",
                issues=[
                    {
                        "location": [str(item) for item in issue.get("loc", ())],
                        "message": issue.get("msg", "invalid patch"),
                    }
                    for issue in exc.errors(include_url=False)
                ],
            )

        body = {
            "schema_version": "ui-runtime-patch-request-v1",
            "step_id": payload.step_id,
            "patch_type": payload.patch_type,
            "scope": "current_run",
            "before": current_before,
            "after": after,
            "reason": payload.reason,
        }
        if self._json_size(body) > settings.UI_EXECUTION_EVENT_MAX_BYTES:
            self._raise(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                "patch_request_too_large",
            )
        command = UiExecutionCommand(
            public_id=command_public_id,
            ui_execution_id=execution.id,
            command_type="patch",
            status="pending",
            payload_json={
                "request_hash": request_hash,
                "body": body,
            },
            issued_by_id=current_user.id,
            expires_at=now
            + timedelta(
                seconds=payload.expires_in_seconds
                or settings.UI_EXECUTION_COMMAND_TTL_SECONDS
            ),
        )
        locked_execution_id = execution.id
        try:
            self.repository.add_command(command)
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            existing = self.repository.get_command_by_public_id(command_public_id)
            if (
                existing is None
                or existing.ui_execution_id != locked_execution_id
                or existing.command_type != "patch"
                or (existing.payload_json or {}).get("request_hash") != request_hash
            ):
                self._raise(
                    status.HTTP_409_CONFLICT,
                    "client_request_id_payload_conflict",
                )
            return self._serialize_command(existing), None, True
        self.db.refresh(command)
        return self._serialize_command(command), execution.assigned_device.public_id, False

    def create_patch(
        self,
        *,
        execution_public_id: str,
        payload: UiExecutionRuntimePatchRequest,
        principal: DesktopDevicePrincipal,
    ) -> dict[str, Any]:
        execution = self._locked_execution(execution_public_id)
        self._require_device_binding(execution=execution, principal=principal)
        self._require_active_lease(execution, payload=payload, principal=principal)
        if self._snapshot_step(execution, payload.step_id) is None:
            self._raise(status.HTTP_404_NOT_FOUND, "ui_execution_step_not_found")
        before = redact_sensitive_data(payload.before)
        after = redact_sensitive_data(payload.after)
        if self._json_size({"before": before, "after": after}) > settings.UI_EXECUTION_EVENT_MAX_BYTES:
            self._raise(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "desktop_payload_too_large")

        request_command = None
        if payload.command_id is not None:
            request_command = self.repository.get_command(
                execution_id=execution.id,
                command_public_id=payload.command_id,
            )
            if request_command is None or request_command.command_type != "patch":
                self._raise(status.HTTP_404_NOT_FOUND, "ui_patch_request_not_found")
            if (
                request_command.status != "acknowledged"
                and request_command.expires_at is not None
                and request_command.expires_at <= utc_now_naive()
            ):
                request_command.status = "expired"
                self.db.commit()
                self._raise(status.HTTP_409_CONFLICT, "command_expired")
            if request_command.status not in {"delivered", "acknowledged"}:
                self._raise(
                    status.HTTP_409_CONFLICT,
                    "patch_request_not_delivered",
                    command_status=request_command.status,
                )
            expected_body = {
                "schema_version": "ui-runtime-patch-request-v1",
                "step_id": payload.step_id,
                "patch_type": payload.patch_type,
                "scope": payload.scope,
                "before": before,
                "after": after,
                "reason": payload.reason,
            }
            if (request_command.payload_json or {}).get("body") != expected_body:
                self._raise(status.HTTP_409_CONFLICT, "patch_request_payload_conflict")
            linked_patch = self.repository.get_patch_by_request_command(
                execution_id=execution.id,
                request_command_id=request_command.id,
            )
            if linked_patch is not None:
                if self._same_patch(
                    linked_patch,
                    step_id=payload.step_id,
                    patch_type=payload.patch_type,
                    scope=payload.scope,
                    before=before,
                    after=after,
                    reason=payload.reason,
                ):
                    return self._serialize_patch(linked_patch, idempotent_replay=True)
                self._raise(status.HTTP_409_CONFLICT, "patch_request_payload_conflict")

        for existing in self.repository.list_patches(execution.id):
            if (
                request_command is None
                and existing.request_command_id is None
                and existing.actor_device_id == principal.device.id
                and existing.step_id == payload.step_id
                and existing.patch_type == payload.patch_type
                and existing.scope == payload.scope
                and existing.before_json == before
                and existing.after_json == after
                and existing.reason == payload.reason
            ):
                return self._serialize_patch(existing, idempotent_replay=True)

        patch = UiRuntimePatch(
            ui_execution_id=execution.id,
            request_command_id=(request_command.id if request_command is not None else None),
            step_id=payload.step_id,
            patch_type=payload.patch_type,
            scope=payload.scope,
            before_json=before,
            after_json=after,
            actor_user_id=(
                request_command.issued_by_id
                if request_command is not None
                else principal.owner.id
            ),
            actor_device_id=principal.device.id,
            reason=payload.reason,
        )
        self.repository.add_patch(patch)
        execution.assisted = True
        self._project_execution(execution)
        self.db.commit()
        self.db.refresh(patch)
        return self._serialize_patch(patch, idempotent_replay=False)

    def complete(
        self,
        *,
        execution_public_id: str,
        payload: UiExecutionCompleteRequest,
        principal: DesktopDevicePrincipal,
    ) -> dict[str, Any]:
        execution = self._locked_execution(execution_public_id)
        self._require_device_binding(execution=execution, principal=principal)
        self._require_assigned_device(execution, principal)
        if execution.status in TERMINAL_STATUSES:
            if self._same_completion(execution, payload):
                return self._complete_response(execution, idempotent_replay=True)
            self._raise(status.HTTP_409_CONFLICT, "execution_complete_conflict")
        self._require_active_lease(execution, payload=payload, principal=principal)
        if payload.final_client_sequence != execution.last_client_sequence:
            self._raise(
                status.HTTP_409_CONFLICT,
                "event_sequence_conflict",
                accepted_through_sequence=execution.last_client_sequence,
            )
        if payload.summary.total_steps != execution.total_steps:
            self._raise(status.HTTP_409_CONFLICT, "execution_summary_conflict")
        if payload.status in {"passed", "assisted"} and payload.summary.failed_steps:
            self._raise(status.HTTP_409_CONFLICT, "execution_summary_conflict")
        if payload.status == "failed" and payload.primary_error is None:
            self._raise(status.HTTP_422_UNPROCESSABLE_CONTENT, "primary_error_required")
        assisted = execution.assisted or payload.summary.assisted or payload.status == "assisted"
        if payload.status == "passed" and assisted:
            self._raise(status.HTTP_409_CONFLICT, "assisted_status_required")

        now = utc_now_naive()
        execution.status = payload.status
        execution.assisted = assisted
        execution.total_steps = payload.summary.total_steps
        execution.passed_steps = payload.summary.passed_steps
        execution.failed_steps = payload.summary.failed_steps
        execution.skipped_steps = payload.summary.skipped_steps
        execution.duration_ms = payload.summary.duration_ms
        execution.finished_at = now
        execution.lease_expires_at = now
        if execution.delivery_status == "pending":
            execution.delivery_status = "complete"
            execution.attention_reason = None
        elif execution.delivery_status == "uploading":
            execution.delivery_status = "failed"
            execution.attention_reason = "artifact_delivery_failed"
        else:
            execution.attention_reason = None
        if payload.primary_error is not None:
            execution.error_category = payload.primary_error.category
            execution.error_message = payload.primary_error.message
        else:
            execution.error_category = None
            execution.error_message = None
        self._project_all_steps(execution)
        self._project_execution(execution)
        self.db.commit()
        return self._complete_response(execution, idempotent_replay=False)

    def list_events(
        self,
        *,
        execution_public_id: str,
        current_user: User,
        after_sequence: int,
        limit: int,
    ) -> dict[str, Any]:
        execution = self.repository.get_by_public_id(execution_public_id)
        if execution is None:
            self._raise(status.HTTP_404_NOT_FOUND, "ui_execution_not_found")
        self._require_report_view(current_user, execution.project_id)
        events = self.repository.list_events(
            execution_id=execution.id,
            after_sequence=after_sequence,
            limit=limit + 1,
        )
        has_more = len(events) > limit
        visible = events[:limit]
        return {
            "items": [self._serialize_event(item) for item in visible],
            "after_sequence": after_sequence,
            "returned": len(visible),
            "has_more": has_more,
            "next_sequence": visible[-1].client_sequence if visible else after_sequence,
        }

    @staticmethod
    def stream_events(
        *,
        execution_public_id: str,
        last_event_id: int,
        session_factory=SessionLocal,
    ):
        sequence = last_event_id
        heartbeat_at = time.monotonic()
        while True:
            with session_factory() as event_db:
                runtime = UiExecutionRuntimeService(event_db)
                execution = runtime.repository.get_by_public_id(execution_public_id)
                if execution is None:
                    return
                events = runtime.repository.list_events(
                    execution_id=execution.id,
                    after_sequence=sequence,
                    limit=500,
                )
                execution_status = execution.status
                last_sequence = execution.last_client_sequence

            for item in events:
                sequence = item.client_sequence
                payload = UiExecutionRuntimeService._serialize_event(item)
                yield (
                    f"id: {sequence}\n"
                    f"event: {item.event_type}\n"
                    f"data: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n\n"
                )
                heartbeat_at = time.monotonic()

            if execution_status in TERMINAL_STATUSES and sequence >= last_sequence:
                return
            if time.monotonic() - heartbeat_at >= settings.UI_EXECUTION_SSE_HEARTBEAT_SECONDS:
                yield (
                    "event: heartbeat\n"
                    f"data: {json.dumps({'status': execution_status}, separators=(',', ':'))}\n\n"
                )
                heartbeat_at = time.monotonic()
            time.sleep(settings.UI_EXECUTION_SSE_POLL_SECONDS)

    def create_command(
        self,
        *,
        execution_public_id: str,
        payload: UiExecutionCommandCreateRequest,
        current_user: User,
    ) -> tuple[dict[str, Any], str | None, bool]:
        execution = self._locked_execution(execution_public_id)
        self.permission_service.require_project_permission(
            current_user,
            execution.project_id,
            ProjectPermission.EXECUTE_TEST.value,
        )
        command_public_id = self._command_public_id(
            project_id=execution.project_id,
            user_id=current_user.id,
            client_request_id=payload.client_request_id,
        )
        request_hash = self._hash_json(
            {
                "execution_id": execution.public_id,
                **payload.model_dump(mode="json"),
            }
        )
        existing = self.repository.get_command_by_public_id(command_public_id)
        if existing is not None:
            if (
                existing.ui_execution_id != execution.id
                or (existing.payload_json or {}).get("request_hash") != request_hash
            ):
                self._raise(status.HTTP_409_CONFLICT, "client_request_id_payload_conflict")
            return self._serialize_command(existing), None, True

        self._validate_command_state(execution, payload.command_type)
        now = utc_now_naive()
        command = UiExecutionCommand(
            public_id=command_public_id,
            ui_execution_id=execution.id,
            command_type=payload.command_type,
            status="pending",
            payload_json={
                "request_hash": request_hash,
                "body": redact_sensitive_data(payload.payload),
            },
            issued_by_id=current_user.id,
            expires_at=now
            + timedelta(
                seconds=payload.expires_in_seconds
                or settings.UI_EXECUTION_COMMAND_TTL_SECONDS
            ),
        )
        notify_device_id = None
        if payload.command_type == "cancel" and execution.status in {"queued", "assigned"}:
            command.status = "acknowledged"
            command.delivered_at = now
            command.acknowledged_at = now
            execution.status = "cancelled"
            execution.finished_at = now
            execution.attention_reason = None
            self._project_execution(execution)
        else:
            if execution.assigned_device is None:
                self._raise(status.HTTP_409_CONFLICT, "execution_device_not_assigned")
            notify_device_id = execution.assigned_device.public_id
        locked_execution_id = execution.id
        try:
            self.repository.add_command(command)
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            existing = self.repository.get_command_by_public_id(command_public_id)
            if (
                existing is None
                or existing.ui_execution_id != locked_execution_id
                or (existing.payload_json or {}).get("request_hash") != request_hash
            ):
                self._raise(
                    status.HTTP_409_CONFLICT,
                    "client_request_id_payload_conflict",
                )
            return self._serialize_command(existing), None, True
        self.db.refresh(command)
        return self._serialize_command(command), notify_device_id, False

    def acknowledge_command(
        self,
        *,
        execution_public_id: str,
        command_public_id: str,
        payload: UiExecutionCommandAckRequest,
        principal: DesktopDevicePrincipal,
    ) -> dict[str, Any]:
        execution = self._locked_execution(execution_public_id)
        self._require_device_binding(execution=execution, principal=principal)
        self._require_active_lease(execution, payload=payload, principal=principal)
        command = self.repository.get_command(
            execution_id=execution.id,
            command_public_id=command_public_id,
        )
        if command is None:
            self._raise(status.HTTP_404_NOT_FOUND, "ui_execution_command_not_found")
        if command.status in {"acknowledged", "rejected"}:
            if command.status == payload.status:
                return self._serialize_command(command)
            self._raise(status.HTTP_409_CONFLICT, "command_ack_conflict")
        if command.status == "expired" or (
            command.expires_at is not None and command.expires_at <= utc_now_naive()
        ):
            command.status = "expired"
            self.db.commit()
            self._raise(status.HTTP_409_CONFLICT, "command_expired")
        if command.command_type == "patch" and payload.status == "acknowledged":
            applied_patch = self.repository.get_patch_by_request_command(
                execution_id=execution.id,
                request_command_id=command.id,
            )
            if applied_patch is None:
                self._raise(
                    status.HTTP_409_CONFLICT,
                    "patch_request_not_applied",
                    command_id=command.public_id,
                )
        now = utc_now_naive()
        command.status = payload.status
        command.acknowledged_at = now
        command.payload_json = {
            **(command.payload_json or {}),
            "ack": redact_sensitive_data(payload.detail),
        }
        self.db.commit()
        return self._serialize_command(command)

    def expire_stale_leases(self) -> int:
        now = utc_now_naive()
        executions = self.repository.list_expired_active(
            now=now,
            limit=settings.UI_EXECUTION_LEASE_SWEEP_BATCH_SIZE,
        )
        for execution in executions:
            self._mark_lost(execution, now=now)
        if executions:
            self.db.commit()
        return len(executions)

    def _apply_event(
        self,
        execution: UiExecution,
        *,
        item: UiExecutionEventItem,
        payload: dict[str, Any],
        occurred_at: datetime,
    ) -> None:
        target_status = EVENT_STATUS_TARGETS.get(item.event_type)
        if target_status and target_status != execution.status:
            allowed = ALLOWED_STATUS_TRANSITIONS.get(execution.status, set())
            if target_status not in allowed:
                self._raise(
                    status.HTTP_409_CONFLICT,
                    "execution_state_conflict",
                    current_status=execution.status,
                    target_status=target_status,
                )
            execution.status = target_status
            if target_status in {"launching", "running"} and execution.started_at is None:
                execution.started_at = occurred_at
            execution.attention_reason = (
                str(payload.get("reason") or payload.get("error") or "waiting_user")[:128]
                if target_status == "waiting_user"
                else None
            )
        if item.event_type in ASSISTED_EVENT_TYPES:
            execution.assisted = True
        if item.event_type in {"step.started", "step.finished", "step.skipped"}:
            self._apply_step_event(
                execution,
                item=item,
                payload=payload,
                occurred_at=occurred_at,
            )

    def _apply_step_event(
        self,
        execution: UiExecution,
        *,
        item: UiExecutionEventItem,
        payload: dict[str, Any],
        occurred_at: datetime,
    ) -> None:
        descriptor = self._snapshot_step(execution, str(item.step_id))
        if descriptor is None:
            self._raise(status.HTTP_404_NOT_FOUND, "ui_execution_step_not_found")
        attempt = self._safe_int(payload.get("attempt"), default=1, minimum=1, maximum=100)
        step = self.repository.get_step(
            execution_id=execution.id,
            step_id=str(item.step_id),
            attempt=attempt,
        )
        if step is None:
            step = UiStepExecution(
                ui_execution_id=execution.id,
                step_id=str(item.step_id),
                attempt=attempt,
                step_index=descriptor["step_index"],
                name=str(descriptor["step"].get("name") or item.step_id)[:200],
                kind=str(descriptor["step"].get("kind") or "action")[:32],
                operation=str(descriptor["step"].get("operation") or "unknown")[:32],
                status="pending",
            )
            self.repository.add_step(step)
        elif item.event_type == "step.started" and step.status != "pending":
            self._raise(status.HTTP_409_CONFLICT, "step_attempt_conflict")

        if item.event_type == "step.started":
            step.status = "running"
            step.started_at = occurred_at
        else:
            step_status = "skipped" if item.event_type == "step.skipped" else str(
                payload.get("status") or ""
            )
            if step_status not in {"passed", "failed", "skipped", "timeout"}:
                self._raise(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_step_status")
            step.status = step_status
            step.finished_at = occurred_at
            if step.started_at is None:
                step.started_at = occurred_at
            step.duration_ms = self._safe_int(
                payload.get("duration_ms"),
                default=max(int((step.finished_at - step.started_at).total_seconds() * 1000), 0),
                minimum=0,
                maximum=86_400_000,
            )
            step.error_code = self._bounded_optional(payload.get("error_code"), 128)
            step.error_message = self._bounded_optional(payload.get("error_message"), 4000)
            result = payload.get("result")
            step.result_summary_json = result if isinstance(result, dict) else {}
        execution.current_step = max(execution.current_step, descriptor["step_index"] + 1)
        self._project_step(execution, step)

    def _sync_step_counts(self, execution: UiExecution) -> None:
        latest: dict[str, UiStepExecution] = {}
        for step in self.repository.list_steps(execution.id):
            current = latest.get(step.step_id)
            if current is None or step.attempt > current.attempt:
                latest[step.step_id] = step
        execution.passed_steps = sum(step.status == "passed" for step in latest.values())
        execution.failed_steps = sum(
            step.status in {"failed", "timeout"} for step in latest.values()
        )
        execution.skipped_steps = sum(step.status == "skipped" for step in latest.values())

    def _project_all_steps(self, execution: UiExecution) -> None:
        for step in self.repository.list_steps(execution.id):
            self._project_step(execution, step)

    def _project_step(self, execution: UiExecution, step: UiStepExecution) -> None:
        result = step.result_summary_json or {}
        self.diagnostic_repository.upsert_step(
            {
                "project_id": execution.project_id,
                "execution_type": "ui",
                "execution_id": execution.id,
                "step_id": f"{step.step_id}:attempt:{step.attempt}",
                "step_index": step.step_index,
                "node_id": step.step_id,
                "node_phase": "ui_step",
                "name": step.name,
                "kind": step.kind,
                "status": step.status,
                "duration_ms": step.duration_ms,
                "error_code": step.error_code,
                "error_message": self._bounded_optional(step.error_message, 512),
                "assertion_summary_json": result.get("assertions", []),
                "response_summary_json": result,
                "binding_summary_json": [],
                "extraction_summary_json": [],
                "retry_summary_json": {"attempt": step.attempt},
                "detail_json": {
                    "operation": step.operation,
                    "started_at": utc_rfc3339(step.started_at),
                    "finished_at": utc_rfc3339(step.finished_at),
                },
                "projection_version": "ui-runtime-v1",
            }
        )

    def _project_execution(self, execution: UiExecution) -> None:
        case_name = (
            execution.ui_test_case.name
            if execution.ui_test_case is not None
            else str((execution.case_snapshot_json or {}).get("case", {}).get("name") or "UI execution")
        )
        self.diagnostic_repository.upsert_execution_index(
            {
                "project_id": execution.project_id,
                "execution_type": "ui",
                "execution_id": execution.id,
                "object_ref": execution.public_id,
                "resource_id": execution.ui_test_case_id,
                "resource_name": case_name,
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
                "started_at": execution.started_at or execution.created_at,
                "finished_at": execution.finished_at,
                "source_updated_at": utc_now_naive(),
                "projection_version": "ui-runtime-v1",
            }
        )

    def _mark_lost(self, execution: UiExecution, *, now: datetime) -> None:
        execution.status = "lost"
        execution.attention_reason = "lease_lost"
        execution.error_category = "lease_lost"
        execution.error_message = "Desktop lease expired before completion"
        execution.finished_at = now
        execution.lease_expires_at = now
        next_sequence = execution.last_client_sequence + 1
        self.repository.add_event(
            UiExecutionEvent(
                project_id=execution.project_id,
                ui_execution_id=execution.id,
                client_event_id=f"system_lease_lost_{secrets.token_urlsafe(12)}",
                client_sequence=next_sequence,
                event_type="lease.lost",
                level="error",
                payload_json={"error": "lease_expired"},
                occurred_at=now,
                received_at=now,
            )
        )
        execution.last_client_sequence = next_sequence
        self._project_execution(execution)

    def _locked_execution(self, execution_public_id: str) -> UiExecution:
        execution = self.repository.get_for_update(execution_public_id)
        if execution is None:
            self._raise(status.HTTP_404_NOT_FOUND, "ui_execution_not_found")
        return execution

    def _require_device_binding(
        self,
        *,
        execution: UiExecution,
        principal: DesktopDevicePrincipal,
        require_accepting: bool = False,
    ) -> DesktopDeviceProjectBinding:
        binding = self.repository.get_project_binding(
            device_id=principal.device.id,
            project_id=execution.project_id,
        )
        if binding is None or not binding.enabled:
            self._raise(status.HTTP_403_FORBIDDEN, "device_project_not_bound")
        if require_accepting and (
            not principal.device.accepting_jobs or not binding.accepting_jobs
        ):
            self._raise(status.HTTP_409_CONFLICT, "device_not_accepting_jobs")
        return binding

    @staticmethod
    def _runtime_compatible(
        principal: DesktopDevicePrincipal,
        *,
        supported_dsl_versions: list[str] | None = None,
        supported_ipc_versions: list[str] | None = None,
    ) -> bool:
        if supported_dsl_versions is not None and "ui-case-v1" not in supported_dsl_versions:
            return False
        if supported_ipc_versions is not None and "desktop-ipc-v1" not in supported_ipc_versions:
            return False
        stored_protocols = principal.device.supported_protocols_json or {}
        if "ui-case-v1" not in stored_protocols.get("dsl", ["ui-case-v1"]):
            return False
        if "desktop-ipc-v1" not in stored_protocols.get("ipc", ["desktop-ipc-v1"]):
            return False
        return DesktopDeviceService._version_at_least(
            principal.device.desktop_version,
            settings.DESKTOP_MIN_VERSION,
        )

    def _require_assigned_device(
        self,
        execution: UiExecution,
        principal: DesktopDevicePrincipal,
    ) -> None:
        if execution.assigned_device_id != principal.device.id:
            self._raise(status.HTTP_403_FORBIDDEN, "lease_device_mismatch")

    def _require_active_lease(
        self,
        execution: UiExecution,
        *,
        payload: UiExecutionLeaseRequest,
        principal: DesktopDevicePrincipal,
    ) -> None:
        self._require_assigned_device(execution, principal)
        if execution.status not in ACTIVE_STATUSES:
            self._raise(
                status.HTTP_409_CONFLICT,
                "execution_not_active",
                current_status=execution.status,
            )
        if execution.lease_id != payload.lease_id:
            self._raise(status.HTTP_409_CONFLICT, "lease_version_conflict")
        if execution.lease_version != payload.lease_version:
            self._raise(
                status.HTTP_409_CONFLICT,
                "lease_version_conflict",
                current_lease_version=execution.lease_version,
            )
        now = utc_now_naive()
        if execution.lease_expires_at is None or execution.lease_expires_at <= now:
            self._mark_lost(execution, now=now)
            self.db.commit()
            self._raise(status.HTTP_409_CONFLICT, "lease_expired")

    def _claim_response(self, execution: UiExecution) -> dict[str, Any]:
        snapshot = execution.case_snapshot_json or {}
        case = snapshot.get("case") or {}
        environment = snapshot.get("environment") or {}
        dsl = case.get("dsl") or {}
        return {
            "execution_id": execution.public_id,
            "internal_execution_id": execution.id,
            "status": execution.status,
            "last_client_sequence": execution.last_client_sequence,
            "lease": self._serialize_lease(execution),
            "snapshot": {
                "case_id": case.get("case_id"),
                "version": case.get("version"),
                "schema_version": dsl.get("schema_version", "ui-case-v1"),
                "checksum": case.get("checksum"),
                "dsl": dsl,
                "environment": {
                    "id": environment.get("environment_id"),
                    "name": environment.get("name"),
                    "base_url": environment.get("base_url"),
                    "variables": environment.get("variables", {}),
                },
                "required_secret_refs": execution.required_secret_refs_json or [],
                "runtime_policy": execution.runtime_policy_json or {},
            },
        }

    @staticmethod
    def _serialize_lease(execution: UiExecution) -> dict[str, Any]:
        return {
            "lease_id": execution.lease_id,
            "version": execution.lease_version,
            "expires_at": utc_rfc3339(execution.lease_expires_at),
            "renew_after_seconds": settings.UI_EXECUTION_LEASE_RENEW_AFTER_SECONDS,
        }

    def _serialize_summary(self, execution: UiExecution) -> dict[str, Any]:
        case_snapshot = (execution.case_snapshot_json or {}).get("case", {})
        return {
            "execution_id": execution.public_id,
            "project_id": execution.project_id,
            "project_name": execution.project.name if execution.project is not None else None,
            "case_id": (
                execution.ui_test_case.public_id if execution.ui_test_case is not None else None
            ),
            "case_name": (
                execution.ui_test_case.name
                if execution.ui_test_case is not None
                else case_snapshot.get("name")
            ),
            "case_version": case_snapshot.get("version"),
            "case_checksum": case_snapshot.get("checksum"),
            "environment_id": execution.environment_id,
            "environment_name": (
                execution.environment.name if execution.environment is not None else None
            ),
            "status": execution.status,
            "delivery_status": execution.delivery_status,
            "attention_reason": execution.attention_reason,
            "current_step": execution.current_step,
            "total_steps": execution.total_steps,
            "passed_steps": execution.passed_steps,
            "failed_steps": execution.failed_steps,
            "skipped_steps": execution.skipped_steps,
            "requested_device_id": (
                execution.requested_device.public_id
                if execution.requested_device is not None
                else None
            ),
            "assigned_device": (
                {
                    "device_id": execution.assigned_device.public_id,
                    "name": execution.assigned_device.name,
                }
                if execution.assigned_device is not None
                else None
            ),
            "source": execution.source,
            "assisted": execution.assisted,
            "duration_ms": execution.duration_ms,
            "created_at": utc_rfc3339(execution.created_at),
            "updated_at": utc_rfc3339(execution.updated_at),
        }

    def _serialize_detail(self, execution: UiExecution) -> dict[str, Any]:
        return {
            **self._serialize_summary(execution),
            "trigger_type": execution.trigger_type,
            "trigger_user_id": execution.trigger_user_id,
            "lease": {
                "version": execution.lease_version,
                "expires_at": utc_rfc3339(execution.lease_expires_at),
                "claimed_at": utc_rfc3339(execution.claimed_at),
                "last_renewed_at": utc_rfc3339(execution.last_renewed_at),
            },
            "started_at": utc_rfc3339(execution.started_at),
            "finished_at": utc_rfc3339(execution.finished_at),
            "last_client_sequence": execution.last_client_sequence,
            "error": (
                {
                    "category": execution.error_category,
                    "message": execution.error_message,
                }
                if execution.error_category or execution.error_message
                else None
            ),
            "steps": [
                self._serialize_step(item)
                for item in sorted(
                    execution.step_executions,
                    key=lambda row: (row.step_index, row.attempt, row.id),
                )
            ],
            "runtime_patches": [
                self._serialize_patch(item, idempotent_replay=False)
                for item in sorted(execution.runtime_patches, key=lambda row: row.id)
            ],
            "commands": [
                self._serialize_command(item)
                for item in sorted(execution.commands, key=lambda row: row.id)
            ],
        }

    @staticmethod
    def _serialize_step(step: UiStepExecution) -> dict[str, Any]:
        return {
            "step_id": step.step_id,
            "attempt": step.attempt,
            "step_index": step.step_index,
            "name": step.name,
            "kind": step.kind,
            "operation": step.operation,
            "status": step.status,
            "started_at": utc_rfc3339(step.started_at),
            "finished_at": utc_rfc3339(step.finished_at),
            "duration_ms": step.duration_ms,
            "error_code": step.error_code,
            "error_message": step.error_message,
            "result_summary": step.result_summary_json or {},
        }

    @staticmethod
    def _serialize_event(event: UiExecutionEvent) -> dict[str, Any]:
        return {
            "client_event_id": event.client_event_id,
            "client_sequence": event.client_sequence,
            "event_type": event.event_type,
            "step_id": event.step_id,
            "level": event.level,
            "payload": event.payload_json or {},
            "occurred_at": utc_rfc3339(event.occurred_at),
            "received_at": utc_rfc3339(event.received_at),
        }

    @staticmethod
    def _serialize_patch(
        patch: UiRuntimePatch,
        *,
        idempotent_replay: bool,
    ) -> dict[str, Any]:
        return {
            "patch_id": patch.id,
            "command_id": (
                patch.request_command.public_id
                if patch.request_command is not None
                else None
            ),
            "step_id": patch.step_id,
            "patch_type": patch.patch_type,
            "scope": patch.scope,
            "before": patch.before_json or {},
            "after": patch.after_json or {},
            "reason": patch.reason,
            "created_at": utc_rfc3339(patch.created_at),
            "idempotent_replay": idempotent_replay,
        }

    @staticmethod
    def _serialize_command(command: UiExecutionCommand) -> dict[str, Any]:
        payload = command.payload_json or {}
        return {
            "command_id": command.public_id,
            "command_type": command.command_type,
            "status": command.status,
            "payload": payload.get("body", {}),
            "ack": payload.get("ack"),
            "created_at": utc_rfc3339(command.created_at),
            "delivered_at": utc_rfc3339(command.delivered_at),
            "acknowledged_at": utc_rfc3339(command.acknowledged_at),
            "expires_at": utc_rfc3339(command.expires_at),
        }

    @staticmethod
    def _complete_response(execution: UiExecution, *, idempotent_replay: bool) -> dict[str, Any]:
        return {
            "execution_id": execution.public_id,
            "status": execution.status,
            "delivery_status": execution.delivery_status,
            "assisted": execution.assisted,
            "duration_ms": execution.duration_ms,
            "finished_at": utc_rfc3339(execution.finished_at),
            "idempotent_replay": idempotent_replay,
        }

    @staticmethod
    def _same_event(
        existing: UiExecutionEvent,
        *,
        item: UiExecutionEventItem,
        payload: dict[str, Any],
        occurred_at: datetime,
    ) -> bool:
        return all(
            (
                existing.client_event_id == item.client_event_id,
                existing.client_sequence == item.client_sequence,
                existing.event_type == item.event_type,
                existing.step_id == item.step_id,
                existing.level == item.level,
                existing.payload_json == payload,
                existing.occurred_at == occurred_at,
            )
        )

    @staticmethod
    def _same_completion(execution: UiExecution, payload: UiExecutionCompleteRequest) -> bool:
        primary = payload.primary_error
        return all(
            (
                execution.status == payload.status,
                execution.total_steps == payload.summary.total_steps,
                execution.passed_steps == payload.summary.passed_steps,
                execution.failed_steps == payload.summary.failed_steps,
                execution.skipped_steps == payload.summary.skipped_steps,
                execution.duration_ms == payload.summary.duration_ms,
                execution.error_category == (primary.category if primary else None),
                execution.error_message == (primary.message if primary else None),
            )
        )

    @staticmethod
    def _snapshot_step(execution: UiExecution, step_id: str) -> dict[str, Any] | None:
        steps = (
            (execution.case_snapshot_json or {})
            .get("case", {})
            .get("dsl", {})
            .get("steps", [])
        )
        for index, step in enumerate(steps):
            if str(step.get("id")) == step_id:
                return {"step_index": index, "step": step}
        return None

    def _effective_snapshot_step(
        self,
        *,
        execution: UiExecution,
        step_id: str,
        snapshot_step: dict[str, Any],
    ) -> dict[str, Any]:
        effective = dict(snapshot_step)
        for patch in self.repository.list_patches(execution.id):
            if patch.step_id != step_id or patch.patch_type not in PATCH_FIELDS:
                continue
            for field in PATCH_FIELDS[patch.patch_type]:
                if field in (patch.after_json or {}):
                    effective[field] = patch.after_json[field]
        return effective

    @staticmethod
    def _same_patch(
        patch: UiRuntimePatch,
        *,
        step_id: str,
        patch_type: str,
        scope: str,
        before: dict[str, Any],
        after: dict[str, Any],
        reason: str,
    ) -> bool:
        return all(
            (
                patch.step_id == step_id,
                patch.patch_type == patch_type,
                patch.scope == scope,
                patch.before_json == before,
                patch.after_json == after,
                patch.reason == reason,
            )
        )

    @staticmethod
    def _validate_command_state(execution: UiExecution, command_type: str) -> None:
        allowed = {
            "pause": {"running"},
            "resume": {"paused", "waiting_user"},
            "cancel": {"queued", "assigned", *ACTIVE_STATUSES},
            "patch": {"paused", "waiting_user"},
        }
        if execution.status not in allowed[command_type]:
            UiExecutionRuntimeService._raise(
                status.HTTP_409_CONFLICT,
                "command_state_conflict",
                current_status=execution.status,
                command_type=command_type,
            )

    def _require_report_view(self, current_user: User, project_id: int) -> None:
        self.permission_service.require_project_permission(
            current_user,
            project_id,
            ProjectPermission.VIEW_REPORT.value,
        )

    @staticmethod
    def _command_public_id(*, project_id: int, user_id: int, client_request_id: str) -> str:
        digest = hashlib.sha256(
            f"{project_id}:{user_id}:{client_request_id}".encode("utf-8")
        ).hexdigest()[:40]
        return f"ui_cmd_{digest}"

    @staticmethod
    def _hash_json(value: Any) -> str:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _json_size(value: Any) -> int:
        return len(
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        )

    @staticmethod
    def _naive_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value
        return value.astimezone(UTC).replace(tzinfo=None)

    @staticmethod
    def _bounded_optional(value: Any, maximum: int) -> str | None:
        if value is None:
            return None
        return str(value)[:maximum]

    @staticmethod
    def _safe_int(
        value: Any,
        *,
        default: int,
        minimum: int,
        maximum: int,
    ) -> int:
        if value is None:
            return default
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            UiExecutionRuntimeService._raise(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "invalid_numeric_event_field",
            )
        if parsed < minimum or parsed > maximum:
            UiExecutionRuntimeService._raise(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "invalid_numeric_event_field",
            )
        return parsed

    @staticmethod
    def _raise(status_code: int, error: str, **detail: Any) -> None:
        raise HTTPException(
            status_code=status_code,
            detail={"error": error, **detail},
        )
