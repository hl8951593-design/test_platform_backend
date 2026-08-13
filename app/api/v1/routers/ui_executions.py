from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, get_db
from app.api.v1.desktop_deps import get_current_desktop_device
from app.core.desktop_device_security import utc_now_naive, utc_rfc3339
from app.core.response import success
from app.models.user import User
from app.schemas.ui_execution import (
    UiExecutionClaimRequest,
    UiExecutionCommandAckRequest,
    UiExecutionCommandCreateRequest,
    UiExecutionCompleteRequest,
    UiExecutionEventBatchRequest,
    UiExecutionLeaseRequest,
    UiExecutionPatchRequestCreateRequest,
    UiExecutionRuntimePatchRequest,
    UiExecutionSource,
    UiExecutionStatus,
    UiLocalRunImportRequest,
)
from app.services.desktop_control_hub import desktop_control_hub
from app.services.desktop_device_service import DesktopDevicePrincipal
from app.services.ui_execution_runtime_service import UiExecutionRuntimeService
from app.services.ui_execution_artifact_service import UiExecutionArtifactService
from app.services.ui_local_run_import_service import UiLocalRunImportService
from app.schemas.ui_execution_artifact import (
    UiArtifactFinalizeRequest,
    UiArtifactPresignRequest,
)


router = APIRouter()


def _schedule_command_notification(
    *,
    background_tasks: BackgroundTasks,
    device_id: str | None,
    execution_id: str,
    command_id: str,
    idempotent_replay: bool,
) -> None:
    if device_id is None or idempotent_replay:
        return
    background_tasks.add_task(
        desktop_control_hub.notify_device,
        device_id,
        {
            "schema_version": "desktop-control-v1",
            "type": "command.available",
            "message_id": f"msg_{uuid.uuid4().hex}",
            "device_id": device_id,
            "execution_id": execution_id,
            "command_id": command_id,
            "server_time": utc_rfc3339(utc_now_naive()),
            "authoritative_transport": "rest",
        },
    )


@router.post(
    "/import-local-run",
    status_code=status.HTTP_201_CREATED,
    summary="Import a completed local Desktop run",
)
def import_local_ui_run(
    payload: UiLocalRunImportRequest,
    project_id: int = Query(gt=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result, idempotent_replay = UiLocalRunImportService(db).import_run(
        project_id=project_id,
        payload=payload,
        current_user=current_user,
    )
    return success(
        data={**result, "idempotent_replay": idempotent_replay},
        message="ui_local_run_imported",
    )


@router.get("", summary="List UI executions and queue facets")
def list_ui_executions(
    project_id: int = Query(gt=0),
    execution_status: UiExecutionStatus | None = Query(default=None, alias="status"),
    delivery_status: str | None = Query(default=None, max_length=32),
    attention_only: bool = Query(default=False),
    assigned_device_id: str | None = Query(default=None, max_length=64),
    environment_id: int | None = Query(default=None, gt=0),
    source: UiExecutionSource | None = Query(default=None),
    keyword: str | None = Query(default=None, max_length=128),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return success(
        data=UiExecutionRuntimeService(db).list_executions(
            project_id=project_id,
            current_user=current_user,
            execution_status=execution_status,
            delivery_status=delivery_status,
            attention_only=attention_only,
            assigned_device_id=assigned_device_id,
            environment_id=environment_id,
            source=source,
            keyword=keyword,
            page=page,
            page_size=page_size,
        )
    )


@router.get("/available", summary="List UI executions available to this Desktop")
def list_available_ui_executions(
    limit: int = Query(default=20, ge=1, le=200),
    principal: DesktopDevicePrincipal = Depends(get_current_desktop_device),
    db: Session = Depends(get_db),
):
    return success(
        data=UiExecutionRuntimeService(db).list_available_executions(
            principal=principal,
            limit=limit,
        )
    )


@router.get("/{execution_id}", summary="Get a UI execution detail")
def get_ui_execution(
    execution_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return success(
        data=UiExecutionRuntimeService(db).get_execution(
            execution_public_id=execution_id,
            current_user=current_user,
        )
    )


@router.post("/{execution_id}/claim", summary="Claim a queued UI execution")
def claim_ui_execution(
    execution_id: str,
    payload: UiExecutionClaimRequest,
    principal: DesktopDevicePrincipal = Depends(get_current_desktop_device),
    db: Session = Depends(get_db),
):
    return success(
        data=UiExecutionRuntimeService(db).claim(
            execution_public_id=execution_id,
            payload=payload,
            principal=principal,
        ),
        message="ui_execution_claimed",
    )


@router.post("/{execution_id}/lease/renew", summary="Renew a UI execution lease")
def renew_ui_execution_lease(
    execution_id: str,
    payload: UiExecutionLeaseRequest,
    principal: DesktopDevicePrincipal = Depends(get_current_desktop_device),
    db: Session = Depends(get_db),
):
    return success(
        data=UiExecutionRuntimeService(db).renew_lease(
            execution_public_id=execution_id,
            payload=payload,
            principal=principal,
        )
    )


@router.post("/{execution_id}/lease/release", summary="Release a UI execution lease")
def release_ui_execution_lease(
    execution_id: str,
    payload: UiExecutionLeaseRequest,
    principal: DesktopDevicePrincipal = Depends(get_current_desktop_device),
    db: Session = Depends(get_db),
):
    return success(
        data=UiExecutionRuntimeService(db).release_lease(
            execution_public_id=execution_id,
            payload=payload,
            principal=principal,
        )
    )


@router.post("/{execution_id}/events/batch", summary="Append ordered UI runtime events")
def append_ui_execution_events(
    execution_id: str,
    payload: UiExecutionEventBatchRequest,
    principal: DesktopDevicePrincipal = Depends(get_current_desktop_device),
    db: Session = Depends(get_db),
):
    return success(
        data=UiExecutionRuntimeService(db).append_events(
            execution_public_id=execution_id,
            payload=payload,
            principal=principal,
        )
    )


@router.get("/{execution_id}/events", summary="List ordered UI runtime events")
def list_ui_execution_events(
    execution_id: str,
    after_sequence: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return success(
        data=UiExecutionRuntimeService(db).list_events(
            execution_public_id=execution_id,
            current_user=current_user,
            after_sequence=after_sequence,
            limit=limit,
        )
    )


@router.get("/{execution_id}/events/stream", summary="Stream UI runtime events")
def stream_ui_execution_events(
    execution_id: str,
    last_event_id: int = Header(default=0, alias="Last-Event-ID", ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    UiExecutionRuntimeService(db).get_execution(
        execution_public_id=execution_id,
        current_user=current_user,
    )

    return StreamingResponse(
        UiExecutionRuntimeService.stream_events(
            execution_public_id=execution_id,
            last_event_id=last_event_id,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post(
    "/{execution_id}/patch-requests",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Request a current-run patch from the assigned Desktop",
)
def create_ui_execution_patch_request(
    execution_id: str,
    payload: UiExecutionPatchRequestCreateRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result, device_id, idempotent_replay = UiExecutionRuntimeService(
        db
    ).create_patch_request(
        execution_public_id=execution_id,
        payload=payload,
        current_user=current_user,
    )
    _schedule_command_notification(
        background_tasks=background_tasks,
        device_id=device_id,
        execution_id=execution_id,
        command_id=result["command_id"],
        idempotent_replay=idempotent_replay,
    )
    return success(data=result, message="ui_execution_patch_request_accepted")


@router.post(
    "/{execution_id}/patches",
    status_code=status.HTTP_201_CREATED,
    summary="Record a current-run runtime patch",
)
def create_ui_execution_patch(
    execution_id: str,
    payload: UiExecutionRuntimePatchRequest,
    principal: DesktopDevicePrincipal = Depends(get_current_desktop_device),
    db: Session = Depends(get_db),
):
    return success(
        data=UiExecutionRuntimeService(db).create_patch(
            execution_public_id=execution_id,
            payload=payload,
            principal=principal,
        ),
        message="ui_execution_patch_recorded",
    )


@router.post("/{execution_id}/complete", summary="Finalize a UI execution")
def complete_ui_execution(
    execution_id: str,
    payload: UiExecutionCompleteRequest,
    principal: DesktopDevicePrincipal = Depends(get_current_desktop_device),
    db: Session = Depends(get_db),
):
    return success(
        data=UiExecutionRuntimeService(db).complete(
            execution_public_id=execution_id,
            payload=payload,
            principal=principal,
        ),
        message="ui_execution_completed",
    )


@router.post(
    "/{execution_id}/commands",
    status_code=status.HTTP_201_CREATED,
    summary="Issue a control command to the assigned Desktop",
)
def create_ui_execution_command(
    execution_id: str,
    payload: UiExecutionCommandCreateRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result, device_id, idempotent_replay = UiExecutionRuntimeService(db).create_command(
        execution_public_id=execution_id,
        payload=payload,
        current_user=current_user,
    )
    _schedule_command_notification(
        background_tasks=background_tasks,
        device_id=device_id,
        execution_id=execution_id,
        command_id=result["command_id"],
        idempotent_replay=idempotent_replay,
    )
    return success(data=result, message="ui_execution_command_created")


@router.post(
    "/{execution_id}/commands/{command_id}/ack",
    summary="Acknowledge a UI execution command",
)
def acknowledge_ui_execution_command(
    execution_id: str,
    command_id: str,
    payload: UiExecutionCommandAckRequest,
    principal: DesktopDevicePrincipal = Depends(get_current_desktop_device),
    db: Session = Depends(get_db),
):
    return success(
        data=UiExecutionRuntimeService(db).acknowledge_command(
            execution_public_id=execution_id,
            command_public_id=command_id,
            payload=payload,
            principal=principal,
        )
    )


@router.post(
    "/{execution_id}/artifacts/presign",
    status_code=status.HTTP_201_CREATED,
    summary="Create a UI artifact upload session",
)
def presign_ui_execution_artifact(
    execution_id: str,
    payload: UiArtifactPresignRequest,
    principal: DesktopDevicePrincipal = Depends(get_current_desktop_device),
    db: Session = Depends(get_db),
):
    return success(
        data=UiExecutionArtifactService(db).presign(
            execution_public_id=execution_id,
            payload=payload,
            principal=principal,
        ),
        message="ui_execution_artifact_upload_created",
    )


@router.post(
    "/{execution_id}/artifacts/finalize",
    summary="Finalize a UI artifact upload",
)
def finalize_ui_execution_artifact(
    execution_id: str,
    payload: UiArtifactFinalizeRequest,
    principal: DesktopDevicePrincipal = Depends(get_current_desktop_device),
    db: Session = Depends(get_db),
):
    return success(
        data=UiExecutionArtifactService(db).finalize(
            execution_public_id=execution_id,
            payload=payload,
            principal=principal,
        ),
        message="ui_execution_artifact_finalized",
    )


@router.get("/{execution_id}/artifacts", summary="List UI execution artifacts")
def list_ui_execution_artifacts(
    execution_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return success(
        data=UiExecutionArtifactService(db).list_artifacts(
            execution_public_id=execution_id,
            current_user=current_user,
        )
    )


@router.get(
    "/{execution_id}/artifacts/{artifact_ref}/url",
    summary="Get a temporary UI artifact download URL",
)
def get_ui_execution_artifact_url(
    execution_id: str,
    artifact_ref: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return success(
        data=UiExecutionArtifactService(db).get_download_url(
            execution_public_id=execution_id,
            artifact_ref=artifact_ref,
            current_user=current_user,
        )
    )


@router.delete(
    "/{execution_id}/artifacts/{artifact_ref}",
    summary="Delete a UI execution artifact",
)
def delete_ui_execution_artifact(
    execution_id: str,
    artifact_ref: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    UiExecutionArtifactService(db).delete_artifact(
        execution_public_id=execution_id,
        artifact_ref=artifact_ref,
        current_user=current_user,
    )
    return success(message="ui_execution_artifact_deleted")
