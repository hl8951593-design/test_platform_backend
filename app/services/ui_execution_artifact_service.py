from __future__ import annotations

import secrets
from datetime import timedelta
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.desktop_device_security import utc_now_naive, utc_rfc3339
from app.models.execution_diagnostic import ExecutionPayloadArtifact
from app.models.ui_execution_artifact import ExecutionArtifactUploadSession
from app.models.user import User
from app.repositories.ui_execution_artifact_repository import (
    UiExecutionArtifactRepository,
)
from app.schemas.ui_execution_artifact import (
    UiArtifactFinalizeRequest,
    UiArtifactPresignRequest,
)
from app.services.desktop_device_service import DesktopDevicePrincipal
from app.services.object_storage_service import ObjectStorageService
from app.services.permission_service import PermissionService
from app.services.ui_execution_runtime_service import UiExecutionRuntimeService


class UiExecutionArtifactService:
    def __init__(
        self,
        db: Session,
        *,
        storage: ObjectStorageService | None = None,
    ) -> None:
        self.db = db
        self.repository = UiExecutionArtifactRepository(db)
        self.runtime = UiExecutionRuntimeService(db)
        self.permission_service = PermissionService(db)
        self.storage = storage or ObjectStorageService()

    def presign(
        self,
        *,
        execution_public_id: str,
        payload: UiArtifactPresignRequest,
        principal: DesktopDevicePrincipal,
    ) -> dict[str, Any]:
        execution = self.runtime._locked_execution(execution_public_id)
        self.runtime._require_device_binding(execution=execution, principal=principal)
        self.runtime._require_active_lease(
            execution,
            payload=payload,
            principal=principal,
        )
        self._validate_descriptor(execution, payload)
        request_hash = self.runtime._hash_json(
            payload.model_dump(
                mode="json",
                exclude={"lease_id", "lease_version"},
            )
        )
        existing = self.repository.get_session_by_request(
            execution_id=execution.id,
            device_id=principal.device.id,
            client_request_id=payload.client_request_id,
        )
        if existing is not None:
            return self._replay_presign(existing, request_hash=request_hash)

        now = utc_now_naive()
        artifact_ref = f"ui_art_{secrets.token_urlsafe(18)}"
        upload_id = f"ui_upload_{secrets.token_urlsafe(18)}"
        object_key = (
            f"{settings.UI_ARTIFACT_OBJECT_PREFIX.strip('/')}/"
            f"{execution.project_id}/{execution.public_id}/{artifact_ref}"
        )
        session = ExecutionArtifactUploadSession(
            upload_id=upload_id,
            artifact_ref=artifact_ref,
            project_id=execution.project_id,
            ui_execution_id=execution.id,
            created_by_device_id=principal.device.id,
            client_request_id=payload.client_request_id,
            request_hash=request_hash,
            step_id=payload.step_id,
            section=payload.section,
            object_key=object_key,
            content_type=payload.content_type,
            original_filename=payload.original_filename,
            expected_size_bytes=payload.size_bytes,
            expected_sha256=payload.sha256,
            status="pending",
            expires_at=now
            + timedelta(seconds=settings.UI_ARTIFACT_UPLOAD_EXPIRE_SECONDS),
        )
        response = self._presign_response(session, idempotent_replay=False)
        locked_execution_id = execution.id
        try:
            self.repository.add_session(session)
            execution.delivery_status = "uploading"
            self.runtime._project_execution(execution)
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            existing = self.repository.get_session_by_request(
                execution_id=locked_execution_id,
                device_id=principal.device.id,
                client_request_id=payload.client_request_id,
            )
            if existing is None:
                self.runtime._raise(
                    status.HTTP_409_CONFLICT,
                    "artifact_upload_conflict",
                )
            return self._replay_presign(existing, request_hash=request_hash)
        return response

    def finalize(
        self,
        *,
        execution_public_id: str,
        payload: UiArtifactFinalizeRequest,
        principal: DesktopDevicePrincipal,
    ) -> dict[str, Any]:
        execution = self.runtime._locked_execution(execution_public_id)
        self.runtime._require_device_binding(execution=execution, principal=principal)
        self.runtime._require_active_lease(
            execution,
            payload=payload,
            principal=principal,
        )
        upload = self.repository.get_session_for_update(payload.upload_id)
        if (
            upload is None
            or upload.ui_execution_id != execution.id
            or upload.artifact_ref != payload.artifact_ref
        ):
            self.runtime._raise(status.HTTP_404_NOT_FOUND, "artifact_upload_not_found")
        if upload.created_by_device_id != principal.device.id:
            self.runtime._raise(status.HTTP_403_FORBIDDEN, "lease_device_mismatch")
        artifact = self.repository.get_artifact(
            execution_id=execution.id,
            artifact_ref=upload.artifact_ref,
        )
        if upload.status == "finalized":
            if artifact is None:
                self.runtime._raise(
                    status.HTTP_409_CONFLICT,
                    "artifact_finalize_inconsistent",
                )
            return self._serialize_artifact(artifact, idempotent_replay=True)
        now = utc_now_naive()
        if upload.status != "pending" or upload.expires_at <= now:
            self.runtime._raise(status.HTTP_409_CONFLICT, "artifact_upload_expired")

        remote = self.storage.head(
            bucket=settings.MINIO_BUCKET,
            object_key=upload.object_key,
        )
        actual_content_type = str(remote.get("content_type") or "").split(";", 1)[0].lower()
        actual_sha256 = str((remote.get("metadata") or {}).get("sha256") or "").lower()
        if (
            int(remote.get("size_bytes") or 0) != upload.expected_size_bytes
            or actual_content_type != upload.content_type
            or actual_sha256 != upload.expected_sha256
        ):
            self.runtime._raise(
                status.HTTP_409_CONFLICT,
                "artifact_metadata_mismatch",
                expected_size_bytes=upload.expected_size_bytes,
                actual_size_bytes=int(remote.get("size_bytes") or 0),
            )

        artifact = ExecutionPayloadArtifact(
            artifact_ref=upload.artifact_ref,
            project_id=execution.project_id,
            execution_type="ui",
            execution_id=execution.id,
            step_id=upload.step_id,
            section=upload.section,
            storage_backend="minio",
            storage_locator=upload.object_key,
            content_type=upload.content_type,
            encoding="binary",
            content=None,
            raw_size_bytes=upload.expected_size_bytes,
            stored_size_bytes=upload.expected_size_bytes,
            sha256=upload.expected_sha256,
            redaction_version="desktop-redacted-v1",
            retention_tier="standard",
            metadata_json={
                "original_filename": upload.original_filename,
                "etag": remote.get("etag"),
                "upload_id": upload.upload_id,
                "captured_by_device_id": principal.device.public_id,
            },
        )
        self.repository.add_artifact(artifact)
        upload.status = "finalized"
        upload.finalized_at = now
        self.db.flush()
        execution.delivery_status = (
            "uploading"
            if self.repository.count_pending_sessions(execution.id, now) > 0
            else "complete"
        )
        self.runtime._project_execution(execution)
        self.db.commit()
        self.db.refresh(artifact)
        return self._serialize_artifact(artifact, idempotent_replay=False)

    def list_artifacts(
        self,
        *,
        execution_public_id: str,
        current_user: User,
    ) -> dict[str, Any]:
        execution = self.runtime.repository.get_by_public_id(execution_public_id)
        if execution is None:
            self.runtime._raise(status.HTTP_404_NOT_FOUND, "ui_execution_not_found")
        self.runtime._require_report_view(current_user, execution.project_id)
        items = self.repository.list_artifacts(execution.id)
        return {
            "items": [
                self._serialize_artifact(item, idempotent_replay=False)
                for item in items
            ],
            "total": len(items),
            "delivery_status": execution.delivery_status,
        }

    def get_download_url(
        self,
        *,
        execution_public_id: str,
        artifact_ref: str,
        current_user: User,
    ) -> dict[str, Any]:
        execution = self.runtime.repository.get_by_public_id(execution_public_id)
        if execution is None:
            self.runtime._raise(status.HTTP_404_NOT_FOUND, "ui_execution_not_found")
        self.runtime._require_report_view(current_user, execution.project_id)
        artifact = self.repository.get_artifact(
            execution_id=execution.id,
            artifact_ref=artifact_ref,
        )
        if artifact is None or artifact.storage_backend != "minio":
            self.runtime._raise(status.HTTP_404_NOT_FOUND, "ui_execution_artifact_not_found")
        return {
            "artifact_ref": artifact.artifact_ref,
            "url": self.storage.presigned_get_url(
                bucket=settings.MINIO_BUCKET,
                object_key=artifact.storage_locator,
                expires_in=settings.UI_ARTIFACT_DOWNLOAD_EXPIRE_SECONDS,
            ),
            "expires_in": settings.UI_ARTIFACT_DOWNLOAD_EXPIRE_SECONDS,
        }

    def delete_artifact(
        self,
        *,
        execution_public_id: str,
        artifact_ref: str,
        current_user: User,
    ) -> None:
        execution = self.runtime.repository.get_by_public_id(execution_public_id)
        if execution is None:
            self.runtime._raise(status.HTTP_404_NOT_FOUND, "ui_execution_not_found")
        self.permission_service.require_project_creator_or_admin(
            current_user,
            execution.project_id,
        )
        artifact = self.repository.get_artifact(
            execution_id=execution.id,
            artifact_ref=artifact_ref,
        )
        if artifact is None:
            self.runtime._raise(status.HTTP_404_NOT_FOUND, "ui_execution_artifact_not_found")
        if artifact.storage_backend == "minio":
            self.storage.delete(
                bucket=settings.MINIO_BUCKET,
                object_key=artifact.storage_locator,
            )
        self.repository.delete_artifact(artifact)
        self.db.commit()

    def cleanup_expired_uploads(self) -> int:
        now = utc_now_naive()
        sessions = self.repository.list_expired_pending(
            now=now,
            limit=settings.UI_ARTIFACT_CLEANUP_BATCH_SIZE,
        )
        cleaned = 0
        for upload in sessions:
            try:
                self.storage.delete(
                    bucket=settings.MINIO_BUCKET,
                    object_key=upload.object_key,
                )
            except HTTPException:
                continue
            upload.status = "expired"
            cleaned += 1
        if cleaned:
            self.db.commit()
        return cleaned

    def _validate_descriptor(self, execution, payload: UiArtifactPresignRequest) -> None:
        if payload.size_bytes > settings.UI_ARTIFACT_MAX_BYTES:
            self.runtime._raise(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                "desktop_payload_too_large",
            )
        if payload.content_type not in set(settings.UI_ARTIFACT_ALLOWED_CONTENT_TYPES):
            self.runtime._raise(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "artifact_content_type_not_allowed",
            )
        if (
            payload.step_id is not None
            and self.runtime._snapshot_step(execution, payload.step_id) is None
        ):
            self.runtime._raise(status.HTTP_404_NOT_FOUND, "ui_execution_step_not_found")

    def _replay_presign(
        self,
        upload: ExecutionArtifactUploadSession,
        *,
        request_hash: str,
    ) -> dict[str, Any]:
        if upload.request_hash != request_hash:
            self.runtime._raise(
                status.HTTP_409_CONFLICT,
                "client_request_id_payload_conflict",
            )
        if upload.status != "pending" or upload.expires_at <= utc_now_naive():
            self.runtime._raise(status.HTTP_409_CONFLICT, "artifact_upload_expired")
        return self._presign_response(upload, idempotent_replay=True)

    def _presign_response(
        self,
        upload: ExecutionArtifactUploadSession,
        *,
        idempotent_replay: bool,
    ) -> dict[str, Any]:
        now = utc_now_naive()
        expires_in = max(
            1,
            min(
                settings.UI_ARTIFACT_UPLOAD_EXPIRE_SECONDS,
                int((upload.expires_at - now).total_seconds()),
            ),
        )
        url, required_headers = self.storage.presigned_put_url(
            bucket=settings.MINIO_BUCKET,
            object_key=upload.object_key,
            content_type=upload.content_type,
            sha256=upload.expected_sha256,
            expires_in=expires_in,
        )
        return {
            "artifact_ref": upload.artifact_ref,
            "upload_id": upload.upload_id,
            "url": url,
            "method": "PUT",
            "required_headers": required_headers,
            "expires_at": utc_rfc3339(upload.expires_at),
            "max_size_bytes": upload.expected_size_bytes,
            "idempotent_replay": idempotent_replay,
        }

    @staticmethod
    def _serialize_artifact(
        artifact: ExecutionPayloadArtifact,
        *,
        idempotent_replay: bool,
    ) -> dict[str, Any]:
        metadata = artifact.metadata_json or {}
        return {
            "artifact_ref": artifact.artifact_ref,
            "step_id": artifact.step_id,
            "section": artifact.section,
            "content_type": artifact.content_type,
            "size_bytes": artifact.raw_size_bytes,
            "sha256": artifact.sha256,
            "original_filename": metadata.get("original_filename"),
            "etag": metadata.get("etag"),
            "created_at": utc_rfc3339(artifact.created_at),
            "idempotent_replay": idempotent_replay,
        }
