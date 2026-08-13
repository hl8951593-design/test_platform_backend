from __future__ import annotations

from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session, joinedload, selectinload

from app.models.desktop_device import (
    DesktopDevice,
    DesktopDeviceCredential,
    DesktopDeviceProjectBinding,
)


class DesktopDeviceRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_public_id(
        self,
        device_public_id: str,
        *,
        with_bindings: bool = False,
    ) -> DesktopDevice | None:
        statement = select(DesktopDevice).where(
            DesktopDevice.public_id == device_public_id
        )
        if with_bindings:
            statement = statement.options(selectinload(DesktopDevice.project_bindings))
        return self.db.scalar(statement)

    def get_by_owner_installation_hash(
        self,
        *,
        owner_id: int,
        installation_id_hash: str,
    ) -> DesktopDevice | None:
        statement = (
            select(DesktopDevice)
            .options(selectinload(DesktopDevice.project_bindings))
            .where(
                DesktopDevice.owner_id == owner_id,
                DesktopDevice.installation_id_hash == installation_id_hash,
            )
        )
        return self.db.scalar(statement.with_for_update())

    def list_for_owner(self, owner_id: int) -> list[DesktopDevice]:
        statement = (
            select(DesktopDevice)
            .options(selectinload(DesktopDevice.project_bindings))
            .where(DesktopDevice.owner_id == owner_id)
            .order_by(DesktopDevice.updated_at.desc(), DesktopDevice.id.desc())
        )
        return list(self.db.scalars(statement).unique().all())

    def list_for_project(self, project_id: int) -> list[DesktopDevice]:
        statement = (
            select(DesktopDevice)
            .join(DesktopDeviceProjectBinding)
            .options(selectinload(DesktopDevice.project_bindings))
            .where(
                DesktopDeviceProjectBinding.project_id == project_id,
                DesktopDeviceProjectBinding.enabled.is_(True),
                DesktopDevice.registration_status == "active",
            )
            .order_by(DesktopDevice.updated_at.desc(), DesktopDevice.id.desc())
        )
        return list(self.db.scalars(statement).unique().all())

    def list_job_notification_targets(self, project_id: int) -> list[DesktopDevice]:
        """Return active project-bound devices worth nudging to recover the REST queue."""
        statement = (
            select(DesktopDevice)
            .join(DesktopDeviceProjectBinding)
            .where(
                DesktopDeviceProjectBinding.project_id == project_id,
                DesktopDeviceProjectBinding.enabled.is_(True),
                DesktopDeviceProjectBinding.accepting_jobs.is_(True),
                DesktopDevice.registration_status == "active",
                DesktopDevice.accepting_jobs.is_(True),
            )
            .order_by(DesktopDevice.id.asc())
        )
        return list(self.db.scalars(statement).unique().all())

    def add_device(self, device: DesktopDevice) -> DesktopDevice:
        self.db.add(device)
        self.db.flush()
        return device

    def get_credential(self, credential_id: str) -> DesktopDeviceCredential | None:
        statement = (
            select(DesktopDeviceCredential)
            .options(
                joinedload(DesktopDeviceCredential.device).joinedload(
                    DesktopDevice.owner
                )
            )
            .where(DesktopDeviceCredential.credential_id == credential_id)
        )
        return self.db.scalar(statement)

    def add_credential(
        self,
        credential: DesktopDeviceCredential,
    ) -> DesktopDeviceCredential:
        self.db.add(credential)
        self.db.flush()
        return credential

    def rotate_credential_secret(
        self,
        *,
        credential_id: str,
        expected_hash: str,
        new_hash: str,
        used_at: datetime,
        expires_at: datetime,
    ) -> bool:
        result = self.db.execute(
            update(DesktopDeviceCredential)
            .where(
                DesktopDeviceCredential.credential_id == credential_id,
                DesktopDeviceCredential.refresh_secret_hash == expected_hash,
                DesktopDeviceCredential.revoked_at.is_(None),
                DesktopDeviceCredential.expires_at > used_at,
            )
            .values(
                refresh_secret_hash=new_hash,
                last_used_at=used_at,
                expires_at=expires_at,
            )
        )
        return result.rowcount == 1

    def revoke_active_credentials(
        self,
        *,
        device: DesktopDevice,
        revoked_at: datetime,
    ) -> None:
        for credential in device.credentials:
            if credential.revoked_at is None:
                credential.revoked_at = revoked_at

    def get_project_binding(
        self,
        *,
        device_id: int,
        project_id: int,
    ) -> DesktopDeviceProjectBinding | None:
        statement = select(DesktopDeviceProjectBinding).where(
            DesktopDeviceProjectBinding.device_id == device_id,
            DesktopDeviceProjectBinding.project_id == project_id,
        )
        return self.db.scalar(statement)

    def add_project_binding(
        self,
        binding: DesktopDeviceProjectBinding,
    ) -> DesktopDeviceProjectBinding:
        self.db.add(binding)
        self.db.flush()
        return binding
