from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


BIGINT_PK = BigInteger().with_variant(Integer, "sqlite")


class DesktopDevice(Base):
    __tablename__ = "desktop_devices"
    __table_args__ = (
        UniqueConstraint(
            "owner_id",
            "installation_id_hash",
            name="uq_desktop_devices_owner_installation",
        ),
        Index(
            "ix_desktop_devices_owner_status_updated",
            "owner_id",
            "registration_status",
            "updated_at",
            "id",
        ),
        Index(
            "ix_desktop_devices_last_heartbeat",
            "last_heartbeat_at",
            "id",
        ),
    )

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=False
    )
    installation_id_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    registration_status: Mapped[str] = mapped_column(
        String(32), default="active", nullable=False
    )
    accepting_jobs: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    concurrency_limit: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    desktop_version: Mapped[str] = mapped_column(String(64), nullable=False)
    os_name: Mapped[str] = mapped_column(String(64), nullable=False)
    os_version: Mapped[str] = mapped_column(String(128), nullable=False)
    architecture: Mapped[str] = mapped_column(String(32), nullable=False)
    supported_protocols_json: Mapped[dict] = mapped_column(
        JSON, default=dict, nullable=False
    )
    capabilities_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    runtime_state_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    device_public_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    registered_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    owner = relationship("User")
    credentials = relationship(
        "DesktopDeviceCredential",
        back_populates="device",
        cascade="all, delete-orphan",
    )
    project_bindings = relationship(
        "DesktopDeviceProjectBinding",
        back_populates="device",
        cascade="all, delete-orphan",
    )


class DesktopDeviceCredential(Base):
    __tablename__ = "desktop_device_credentials"
    __table_args__ = (
        Index(
            "ix_desktop_device_credentials_device_active",
            "device_id",
            "revoked_at",
            "expires_at",
            "id",
        ),
    )

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    credential_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    device_id: Mapped[int] = mapped_column(
        ForeignKey("desktop_devices.id", ondelete="CASCADE"), index=True, nullable=False
    )
    refresh_secret_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    device = relationship("DesktopDevice", back_populates="credentials")


class DesktopDeviceProjectBinding(Base):
    __tablename__ = "desktop_device_project_bindings"
    __table_args__ = (
        UniqueConstraint(
            "device_id",
            "project_id",
            name="uq_desktop_device_project_bindings_device_project",
        ),
        Index(
            "ix_desktop_device_project_bindings_project_available",
            "project_id",
            "enabled",
            "accepting_jobs",
            "device_id",
        ),
    )

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    device_id: Mapped[int] = mapped_column(
        ForeignKey("desktop_devices.id", ondelete="CASCADE"), index=True, nullable=False
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    accepting_jobs: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    concurrency_limit: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    device = relationship("DesktopDevice", back_populates="project_bindings")
    project = relationship("Project")
    created_by = relationship("User")
