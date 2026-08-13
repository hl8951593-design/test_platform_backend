from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, get_db
from app.core.desktop_device_security import utc_now_naive
from app.core.response import success
from app.models.user import User
from app.repositories.desktop_device_repository import DesktopDeviceRepository
from app.schemas.ui_execution import UiExecutionCreateRequest
from app.schemas.ui_test_case import (
    UiCaseStatus,
    UiTestCaseCreateRequest,
    UiTestCaseUpdateRequest,
    UiTestCaseValidateRequest,
    UiTestCaseVersionCreateRequest,
)
from app.services.desktop_control_hub import desktop_control_hub
from app.services.ui_execution_service import UiExecutionService
from app.services.ui_test_case_service import UiTestCaseService


router = APIRouter()


def _execution_available_message(*, device_id: str, execution_id: str) -> dict:
    return {
        "schema_version": "desktop-control-v1",
        "type": "execution.available",
        "message_id": f"msg_{uuid.uuid4().hex}",
        "device_id": device_id,
        "execution_id": execution_id,
        "server_time": f"{utc_now_naive().isoformat(timespec='milliseconds')}Z",
        "authoritative_transport": "rest",
    }


def _execution_notification_targets(
    db: Session,
    *,
    project_id: int,
    requested_device_id: str | None,
) -> list[str]:
    if requested_device_id is not None:
        return [requested_device_id]
    targets: list[str] = []
    for device in DesktopDeviceRepository(db).list_job_notification_targets(project_id):
        protocols = device.supported_protocols_json or {}
        if "ui-case-v1" not in (protocols.get("dsl") or []):
            continue
        if "desktop-ipc-v1" not in (protocols.get("ipc") or []):
            continue
        targets.append(device.public_id)
    return targets


@router.post("/validate", summary="Validate and normalize an unsaved UI case")
def validate_ui_test_case(
    payload: UiTestCaseValidateRequest,
    project_id: int = Query(gt=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = UiTestCaseService(db).validate_unsaved(
        project_id=project_id,
        default_environment_id=payload.default_environment_id,
        dsl=payload.dsl,
        current_user=current_user,
    )
    return success(data=result)


@router.get("", summary="List UI test cases")
def list_ui_test_cases(
    project_id: int = Query(gt=0),
    keyword: str | None = Query(default=None, max_length=128),
    case_status: UiCaseStatus | None = Query(default=None, alias="status"),
    environment_id: int | None = Query(default=None, gt=0),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = UiTestCaseService(db).list_cases(
        project_id=project_id,
        keyword=keyword,
        case_status=case_status,
        environment_id=environment_id,
        page=page,
        page_size=page_size,
        current_user=current_user,
    )
    return success(data=result)


@router.post("", status_code=status.HTTP_201_CREATED, summary="Create a UI test case")
def create_ui_test_case(
    payload: UiTestCaseCreateRequest,
    project_id: int = Query(gt=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = UiTestCaseService(db).create_case(
        project_id=project_id,
        payload=payload,
        current_user=current_user,
    )
    return success(data=result, message="ui_test_case_created")


@router.get("/{case_id}", summary="Get a UI test case")
def get_ui_test_case(
    case_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return success(
        data=UiTestCaseService(db).get_case(
            case_public_id=case_id,
            current_user=current_user,
        )
    )


@router.patch("/{case_id}", summary="Update UI test case metadata")
def update_ui_test_case(
    case_id: str,
    payload: UiTestCaseUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = UiTestCaseService(db).update_case(
        case_public_id=case_id,
        payload=payload,
        current_user=current_user,
    )
    return success(data=result, message="ui_test_case_updated")


@router.delete("/{case_id}", summary="Soft-delete a UI test case")
def delete_ui_test_case(
    case_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    UiTestCaseService(db).delete_case(
        case_public_id=case_id,
        current_user=current_user,
    )
    return success(message="ui_test_case_deleted")


@router.get("/{case_id}/versions", summary="List immutable UI case versions")
def list_ui_test_case_versions(
    case_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return success(
        data=UiTestCaseService(db).list_versions(
            case_public_id=case_id,
            current_user=current_user,
        )
    )


@router.post(
    "/{case_id}/versions",
    status_code=status.HTTP_201_CREATED,
    summary="Append an immutable UI case version",
)
def create_ui_test_case_version(
    case_id: str,
    payload: UiTestCaseVersionCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = UiTestCaseService(db).create_version(
        case_public_id=case_id,
        payload=payload,
        current_user=current_user,
    )
    return success(data=result, message="ui_test_case_version_created")


@router.get("/{case_id}/versions/{version}", summary="Get an immutable UI case version")
def get_ui_test_case_version(
    case_id: str,
    version: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return success(
        data=UiTestCaseService(db).get_version(
            case_public_id=case_id,
            version_number=version,
            current_user=current_user,
        )
    )


@router.post(
    "/{case_id}/execute",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Create an asynchronous UI execution",
)
def execute_ui_test_case(
    case_id: str,
    payload: UiExecutionCreateRequest,
    background_tasks: BackgroundTasks,
    project_id: int = Query(gt=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result, requested_device_id, idempotent_replay = UiExecutionService(db).create_execution(
        project_id=project_id,
        case_public_id=case_id,
        payload=payload,
        current_user=current_user,
    )
    if not idempotent_replay:
        for device_id in _execution_notification_targets(
            db,
            project_id=project_id,
            requested_device_id=requested_device_id,
        ):
            background_tasks.add_task(
                desktop_control_hub.notify_device,
                device_id,
                _execution_available_message(
                    device_id=device_id,
                    execution_id=result.execution_id,
                ),
            )
    return success(data=result, message="UI execution accepted")
