from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, get_db
from app.api.v1.desktop_deps import get_current_desktop_device
from app.core.desktop_device_security import utc_now_naive
from app.core.response import success
from app.models.user import User
from app.schemas.desktop_device import (
    DesktopDeviceHeartbeatRequest,
    DesktopDeviceProjectBindingUpdateRequest,
    DesktopDeviceRefreshRequest,
    DesktopDeviceRegisterRequest,
    DesktopDeviceUpdateRequest,
)
from app.services.desktop_control_hub import desktop_control_hub
from app.services.desktop_device_service import (
    DesktopDevicePrincipal,
    DesktopDeviceService,
)


router = APIRouter()
control_router = APIRouter()


@router.get("/runtime-policy", summary="Get TestAuto Desktop runtime policy")
def get_runtime_policy(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    del current_user
    return success(data=DesktopDeviceService(db).get_runtime_policy())


@router.post(
    "/devices/register",
    status_code=status.HTTP_201_CREATED,
    summary="Register or re-register a TestAuto Desktop installation",
)
def register_device(
    payload: DesktopDeviceRegisterRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = DesktopDeviceService(db).register_device(
        payload=payload,
        current_user=current_user,
    )
    return success(data=result, message="desktop_device_registered")


@router.post("/devices/token/refresh", summary="Rotate Desktop device credential")
def refresh_device_token(
    payload: DesktopDeviceRefreshRequest,
    db: Session = Depends(get_db),
):
    credential = DesktopDeviceService(db).refresh_device_credential(
        payload.refresh_token
    )
    return success(data=credential, message="desktop_device_token_refreshed")


@router.get("/devices", summary="List current user's or project's Desktop devices")
def list_devices(
    project_id: int | None = Query(default=None, gt=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    devices = DesktopDeviceService(db).list_devices(
        current_user=current_user,
        project_id=project_id,
    )
    return success(data=devices)


@router.get("/devices/{device_id}", summary="Get Desktop device details")
def get_device(
    device_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    device = DesktopDeviceService(db).get_device(
        device_public_id=device_id,
        current_user=current_user,
    )
    return success(data=device)


@router.patch("/devices/{device_id}", summary="Update a Desktop device")
def update_device(
    device_id: str,
    payload: DesktopDeviceUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    device = DesktopDeviceService(db).update_device(
        device_public_id=device_id,
        payload=payload,
        current_user=current_user,
    )
    return success(data=device, message="desktop_device_updated")


@router.put(
    "/devices/{device_id}/projects/{project_id}",
    summary="Create or update a Desktop device project binding",
)
def bind_device_project(
    device_id: str,
    project_id: int,
    payload: DesktopDeviceProjectBindingUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    device = DesktopDeviceService(db).bind_project(
        device_public_id=device_id,
        project_id=project_id,
        payload=payload,
        current_user=current_user,
    )
    return success(data=device, message="desktop_device_project_binding_updated")


@router.post("/devices/{device_id}/heartbeat", summary="Report Desktop device heartbeat")
def heartbeat(
    device_id: str,
    payload: DesktopDeviceHeartbeatRequest,
    principal: DesktopDevicePrincipal = Depends(get_current_desktop_device),
    db: Session = Depends(get_db),
):
    if principal.device.public_id != device_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="desktop_device_token_device_mismatch",
        )
    result = DesktopDeviceService(db).heartbeat(
        principal=principal,
        payload=payload,
    )
    return success(data=result)


@router.delete("/devices/{device_id}", summary="Revoke a Desktop device")
def revoke_device(
    device_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    DesktopDeviceService(db).revoke_device(
        device_public_id=device_id,
        current_user=current_user,
    )
    return success(message="desktop_device_revoked")


@control_router.websocket("/devices/{device_id}/control")
async def desktop_control_socket(
    websocket: WebSocket,
    device_id: str,
    db: Session = Depends(get_db),
) -> None:
    authorization = websocket.headers.get("authorization", "")
    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer" or not token:
        await websocket.close(code=4401, reason="desktop_device_access_token_required")
        return
    try:
        principal = DesktopDeviceService(db).authenticate_device_access_token(token)
    except HTTPException as exc:
        await websocket.close(code=4401, reason=str(exc.detail))
        return
    if principal.device.public_id != device_id:
        await websocket.close(code=4403, reason="desktop_device_token_device_mismatch")
        return

    await desktop_control_hub.connect(device_id, websocket)
    try:
        await websocket.send_json(_control_message("control.ready", device_id=device_id))
        while True:
            try:
                incoming = await websocket.receive_json()
            except WebSocketDisconnect:
                break
            except Exception:
                await websocket.send_json(
                    _control_message(
                        "control.error",
                        device_id=device_id,
                        error="invalid_json_message",
                    )
                )
                continue
            await _handle_control_message(
                websocket=websocket,
                device_id=device_id,
                incoming=incoming,
            )
    finally:
        desktop_control_hub.disconnect(device_id, websocket)


async def _handle_control_message(
    *,
    websocket: WebSocket,
    device_id: str,
    incoming: Any,
) -> None:
    if not isinstance(incoming, dict):
        await websocket.send_json(
            _control_message(
                "control.error",
                device_id=device_id,
                error="message_must_be_object",
            )
        )
        return
    message_type = incoming.get("type")
    request_message_id = incoming.get("message_id")
    if message_type == "control.ping":
        await websocket.send_json(
            _control_message(
                "control.pong",
                device_id=device_id,
                reply_to=request_message_id,
            )
        )
        return
    if message_type == "control.resync":
        await websocket.send_json(
            _control_message(
                "control.resync_required",
                device_id=device_id,
                reply_to=request_message_id,
                authoritative_transport="rest",
            )
        )
        return
    await websocket.send_json(
        _control_message(
            "control.error",
            device_id=device_id,
            reply_to=request_message_id,
            error="unsupported_message_type",
        )
    )


def _control_message(
    message_type: str,
    *,
    device_id: str,
    **payload: Any,
) -> dict[str, Any]:
    return {
        "schema_version": "desktop-control-v1",
        "type": message_type,
        "message_id": f"msg_{uuid.uuid4().hex}",
        "device_id": device_id,
        "server_time": f"{utc_now_naive().isoformat(timespec='milliseconds')}Z",
        **payload,
    }
