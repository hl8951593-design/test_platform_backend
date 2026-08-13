from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from datetime import timedelta

import jwt
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.desktop_device_security import (
    create_device_access_token,
    decode_device_access_token,
    hash_installation_id,
    issue_device_refresh_token,
    parse_device_refresh_token,
    rotate_device_refresh_token,
    utc_now_naive,
    verify_refresh_secret,
)
from app.models.desktop_device import (
    DesktopDevice,
    DesktopDeviceCredential,
    DesktopDeviceProjectBinding,
)
from app.models.user import User
from app.repositories.desktop_device_repository import DesktopDeviceRepository
from app.schemas.desktop_device import (
    DesktopDeviceCredentialRead,
    DesktopDeviceHeartbeatRead,
    DesktopDeviceHeartbeatRequest,
    DesktopDeviceProjectBindingRead,
    DesktopDeviceProjectBindingUpdateRequest,
    DesktopDeviceRead,
    DesktopDeviceRegisterRead,
    DesktopDeviceRegisterRequest,
    DesktopDeviceUpdateRequest,
    DesktopRuntimePolicyRead,
)
from app.services.desktop_presence_service import (
    DesktopPresenceService,
    desktop_presence_service,
)
from app.services.permission_service import PermissionService


@dataclass(frozen=True)
class DesktopDevicePrincipal:
    device: DesktopDevice
    credential: DesktopDeviceCredential
    owner: User


class DesktopDeviceService:
    def __init__(
        self,
        db: Session,
        *,
        presence_service: DesktopPresenceService | None = None,
    ) -> None:
        self.db = db
        self.repository = DesktopDeviceRepository(db)
        self.permission_service = PermissionService(db)
        self.presence_service = presence_service or desktop_presence_service

    def get_runtime_policy(self) -> DesktopRuntimePolicyRead:
        return DesktopRuntimePolicyRead(
            min_desktop_version=settings.DESKTOP_MIN_VERSION,
            supported_dsl_versions=list(settings.DESKTOP_SUPPORTED_DSL_VERSIONS),
            supported_ipc_versions=list(settings.DESKTOP_SUPPORTED_IPC_VERSIONS),
            heartbeat_interval_seconds=settings.DESKTOP_HEARTBEAT_INTERVAL_SECONDS,
            offline_after_seconds=settings.DESKTOP_DEVICE_OFFLINE_AFTER_SECONDS,
            max_concurrency=settings.DESKTOP_MAX_CONCURRENCY,
        )

    def register_device(
        self,
        *,
        payload: DesktopDeviceRegisterRequest,
        current_user: User,
    ) -> DesktopDeviceRegisterRead:
        now = utc_now_naive()
        installation_hash = hash_installation_id(
            owner_id=current_user.id,
            installation_id=payload.installation_id,
        )
        device = self.repository.get_by_owner_installation_hash(
            owner_id=current_user.id,
            installation_id_hash=installation_hash,
        )
        if device is None:
            device = DesktopDevice(
                public_id=f"dev_{secrets.token_urlsafe(18)}",
                owner_id=current_user.id,
                installation_id_hash=installation_hash,
                name=payload.name,
                desktop_version=payload.desktop_version,
                os_name=payload.os_name,
                os_version=payload.os_version,
                architecture=payload.architecture,
                supported_protocols_json=payload.supported_protocols,
                capabilities_json=payload.capabilities,
                runtime_state_json={},
                device_public_key=payload.device_public_key,
                registered_at=now,
            )
            self.repository.add_device(device)
        else:
            device.name = payload.name
            device.desktop_version = payload.desktop_version
            device.os_name = payload.os_name
            device.os_version = payload.os_version
            device.architecture = payload.architecture
            device.supported_protocols_json = payload.supported_protocols
            device.capabilities_json = payload.capabilities
            device.device_public_key = payload.device_public_key
            device.registration_status = "active"
            device.revoked_at = None
            self.repository.revoke_active_credentials(device=device, revoked_at=now)

        issued = issue_device_refresh_token()
        expires_at = now + timedelta(
            days=settings.DESKTOP_DEVICE_REFRESH_TOKEN_EXPIRE_DAYS
        )
        credential = DesktopDeviceCredential(
            credential_id=issued.credential_id,
            device=device,
            refresh_secret_hash=issued.secret_hash,
            expires_at=expires_at,
        )
        self.repository.add_credential(credential)
        self.db.commit()
        self.db.refresh(device)

        return DesktopDeviceRegisterRead(
            device=self._serialize_device(device),
            credential=self._credential_read(
                device=device,
                credential=credential,
                refresh_token=issued.token,
            ),
        )

    def refresh_device_credential(self, refresh_token: str) -> DesktopDeviceCredentialRead:
        credentials_exception = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="desktop_device_refresh_token_invalid",
            headers={"WWW-Authenticate": "Bearer"},
        )
        try:
            credential_id, secret = parse_device_refresh_token(refresh_token)
        except ValueError as exc:
            raise credentials_exception from exc

        credential = self.repository.get_credential(credential_id)
        now = utc_now_naive()
        if (
            credential is None
            or credential.revoked_at is not None
            or credential.expires_at <= now
            or not verify_refresh_secret(
                secret=secret,
                expected_hash=credential.refresh_secret_hash,
            )
        ):
            raise credentials_exception

        device = credential.device
        owner = device.owner
        if (
            owner is None
            or not owner.is_active
            or device.registration_status != "active"
        ):
            raise credentials_exception

        rotated = rotate_device_refresh_token(credential.credential_id)
        rotated_expires_at = now + timedelta(
            days=settings.DESKTOP_DEVICE_REFRESH_TOKEN_EXPIRE_DAYS
        )
        if not self.repository.rotate_credential_secret(
            credential_id=credential.credential_id,
            expected_hash=credential.refresh_secret_hash,
            new_hash=rotated.secret_hash,
            used_at=now,
            expires_at=rotated_expires_at,
        ):
            self.db.rollback()
            raise credentials_exception
        self.db.commit()
        self.db.refresh(credential)
        return self._credential_read(
            device=device,
            credential=credential,
            refresh_token=rotated.token,
        )

    def list_devices(
        self,
        *,
        current_user: User,
        project_id: int | None = None,
    ) -> list[DesktopDeviceRead]:
        if project_id is None:
            devices = self.repository.list_for_owner(current_user.id)
        else:
            self.permission_service.require_project_access(current_user, project_id)
            devices = self.repository.list_for_project(project_id)
        return [self._serialize_device(device) for device in devices]

    def get_device(
        self,
        *,
        device_public_id: str,
        current_user: User,
    ) -> DesktopDeviceRead:
        device = self._get_manageable_device(device_public_id, current_user)
        return self._serialize_device(device)

    def update_device(
        self,
        *,
        device_public_id: str,
        payload: DesktopDeviceUpdateRequest,
        current_user: User,
    ) -> DesktopDeviceRead:
        device = self._get_manageable_device(device_public_id, current_user)
        if (
            payload.concurrency_limit is not None
            and payload.concurrency_limit > settings.DESKTOP_MAX_CONCURRENCY
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="desktop_device_concurrency_limit_exceeded",
            )
        changes = payload.model_dump(exclude_unset=True)
        for field_name, value in changes.items():
            setattr(device, field_name, value)
        self.db.commit()
        self.db.refresh(device)
        return self._serialize_device(device)

    def bind_project(
        self,
        *,
        device_public_id: str,
        project_id: int,
        payload: DesktopDeviceProjectBindingUpdateRequest,
        current_user: User,
    ) -> DesktopDeviceRead:
        if payload.concurrency_limit > settings.DESKTOP_MAX_CONCURRENCY:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="desktop_device_concurrency_limit_exceeded",
            )
        device = self._get_manageable_device(device_public_id, current_user)
        self.permission_service.require_project_access(current_user, project_id)
        binding = self.repository.get_project_binding(
            device_id=device.id,
            project_id=project_id,
        )
        if binding is None:
            binding = DesktopDeviceProjectBinding(
                device=device,
                project_id=project_id,
                enabled=payload.enabled,
                accepting_jobs=payload.accepting_jobs,
                concurrency_limit=payload.concurrency_limit,
                created_by_id=current_user.id,
            )
            self.repository.add_project_binding(binding)
        else:
            binding.enabled = payload.enabled
            binding.accepting_jobs = payload.accepting_jobs
            binding.concurrency_limit = payload.concurrency_limit
        self.db.commit()
        self.db.refresh(device)
        return self._serialize_device(device)

    def heartbeat(
        self,
        *,
        principal: DesktopDevicePrincipal,
        payload: DesktopDeviceHeartbeatRequest,
    ) -> DesktopDeviceHeartbeatRead:
        device = principal.device
        now = utc_now_naive()
        runtime_state = {
            "active_execution_ids": list(payload.active_execution_ids),
            "local_outbox_events": payload.local_outbox_events,
            "local_outbox_artifacts": payload.local_outbox_artifacts,
            "current_load": payload.current_load,
        }
        self.presence_service.mark_online(
            device_public_id=device.public_id,
            observed_at=now,
            runtime_state=runtime_state,
        )

        metadata_changed = any(
            (
                device.desktop_version != payload.desktop_version,
                device.supported_protocols_json != payload.supported_protocols,
                device.capabilities_json != payload.capabilities,
                device.runtime_state_json != runtime_state,
            )
        )
        persist_due = (
            device.last_heartbeat_at is None
            or now - device.last_heartbeat_at
            >= timedelta(seconds=settings.DESKTOP_HEARTBEAT_PERSIST_SECONDS)
        )
        if metadata_changed or persist_due:
            device.desktop_version = payload.desktop_version
            device.supported_protocols_json = payload.supported_protocols
            device.capabilities_json = payload.capabilities
            device.runtime_state_json = runtime_state
            device.last_heartbeat_at = now
            self.db.commit()

        compatible = self._version_at_least(
            payload.desktop_version,
            settings.DESKTOP_MIN_VERSION,
        )
        return DesktopDeviceHeartbeatRead(
            device_id=device.public_id,
            server_time=now,
            runtime_compatible=compatible,
            accepting_jobs=(
                device.registration_status == "active"
                and device.accepting_jobs
                and compatible
            ),
            heartbeat_interval_seconds=settings.DESKTOP_HEARTBEAT_INTERVAL_SECONDS,
        )

    def revoke_device(
        self,
        *,
        device_public_id: str,
        current_user: User,
    ) -> None:
        device = self._get_manageable_device(device_public_id, current_user)
        now = utc_now_naive()
        device.registration_status = "revoked"
        device.accepting_jobs = False
        device.revoked_at = now
        self.repository.revoke_active_credentials(device=device, revoked_at=now)
        self.db.commit()
        self.presence_service.forget(device.public_id)

    def authenticate_device_access_token(self, token: str) -> DesktopDevicePrincipal:
        credentials_exception = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="desktop_device_access_token_invalid",
            headers={"WWW-Authenticate": "Bearer"},
        )
        try:
            payload = decode_device_access_token(token)
            device_public_id = str(payload["sub"])
            credential_id = str(payload["credential_id"])
            owner_id = int(payload["owner_id"])
        except (jwt.InvalidTokenError, KeyError, TypeError, ValueError) as exc:
            raise credentials_exception from exc

        credential = self.repository.get_credential(credential_id)
        now = utc_now_naive()
        if credential is None:
            raise credentials_exception
        device = credential.device
        if (
            credential.revoked_at is not None
            or credential.expires_at <= now
            or device.public_id != device_public_id
            or device.owner_id != owner_id
            or device.registration_status != "active"
        ):
            raise credentials_exception
        owner = device.owner
        if owner is None or not owner.is_active:
            raise credentials_exception
        return DesktopDevicePrincipal(
            device=device,
            credential=credential,
            owner=owner,
        )

    def _get_manageable_device(
        self,
        device_public_id: str,
        current_user: User,
    ) -> DesktopDevice:
        device = self.repository.get_by_public_id(
            device_public_id,
            with_bindings=True,
        )
        if device is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="desktop_device_not_found",
            )
        if device.owner_id != current_user.id and not current_user.is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="desktop_device_access_denied",
            )
        return device

    def _serialize_device(self, device: DesktopDevice) -> DesktopDeviceRead:
        online = False
        if device.registration_status == "active":
            redis_online = self.presence_service.is_online(device.public_id)
            if redis_online is not None:
                online = redis_online
            elif device.last_heartbeat_at is not None:
                online = utc_now_naive() - device.last_heartbeat_at < timedelta(
                    seconds=settings.DESKTOP_DEVICE_OFFLINE_AFTER_SECONDS
                )
        return DesktopDeviceRead(
            device_id=device.public_id,
            owner_id=device.owner_id,
            name=device.name,
            registration_status=device.registration_status,
            online=online,
            accepting_jobs=device.accepting_jobs,
            concurrency_limit=device.concurrency_limit,
            desktop_version=device.desktop_version,
            os_name=device.os_name,
            os_version=device.os_version,
            architecture=device.architecture,
            supported_protocols=device.supported_protocols_json or {},
            capabilities=device.capabilities_json or {},
            runtime_state=device.runtime_state_json or {},
            last_heartbeat_at=device.last_heartbeat_at,
            registered_at=device.registered_at,
            revoked_at=device.revoked_at,
            project_bindings=[
                DesktopDeviceProjectBindingRead(
                    project_id=binding.project_id,
                    enabled=binding.enabled,
                    accepting_jobs=binding.accepting_jobs,
                    concurrency_limit=binding.concurrency_limit,
                    created_at=binding.created_at,
                    updated_at=binding.updated_at,
                )
                for binding in sorted(
                    device.project_bindings,
                    key=lambda item: item.project_id,
                )
            ],
        )

    @staticmethod
    def _credential_read(
        *,
        device: DesktopDevice,
        credential: DesktopDeviceCredential,
        refresh_token: str,
    ) -> DesktopDeviceCredentialRead:
        return DesktopDeviceCredentialRead(
            access_token=create_device_access_token(
                device_public_id=device.public_id,
                owner_id=device.owner_id,
                credential_id=credential.credential_id,
            ),
            refresh_token=refresh_token,
            access_expires_in=(
                settings.DESKTOP_DEVICE_ACCESS_TOKEN_EXPIRE_MINUTES * 60
            ),
            refresh_expires_at=credential.expires_at,
        )

    @staticmethod
    def _version_at_least(current: str, minimum: str) -> bool:
        def normalize(value: str) -> tuple[int, ...]:
            numbers = [int(part) for part in re.findall(r"\d+", value)]
            return tuple((numbers + [0, 0, 0])[:3])

        return normalize(current) >= normalize(minimum)
