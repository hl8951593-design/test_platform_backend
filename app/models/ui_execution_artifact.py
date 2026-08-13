from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


BIGINT_PK = BigInteger().with_variant(Integer, "sqlite")
BIGINT_VALUE = BigInteger().with_variant(Integer, "sqlite")


class ExecutionArtifactUploadSession(Base):
    __tablename__ = "execution_artifact_upload_sessions"
    __table_args__ = (
        UniqueConstraint("upload_id", name="uq_execution_artifact_upload_session_upload"),
        UniqueConstraint("artifact_ref", name="uq_execution_artifact_upload_session_artifact"),
        UniqueConstraint(
            "ui_execution_id",
            "created_by_device_id",
            "client_request_id",
            name="uq_execution_artifact_upload_session_request",
        ),
        Index(
            "ix_execution_artifact_upload_session_status_expires",
            "status",
            "expires_at",
            "id",
        ),
        Index(
            "ix_execution_artifact_upload_session_execution_created",
            "ui_execution_id",
            "created_at",
            "id",
        ),
    )

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    upload_id: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    ui_execution_id: Mapped[int] = mapped_column(
        BIGINT_VALUE,
        ForeignKey("ui_executions.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_by_device_id: Mapped[int] = mapped_column(
        BIGINT_VALUE,
        ForeignKey("desktop_devices.id", ondelete="RESTRICT"),
        nullable=False,
    )
    client_request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    step_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    section: Mapped[str] = mapped_column(String(64), nullable=False)
    object_key: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    expected_size_bytes: Mapped[int] = mapped_column(BIGINT_VALUE, nullable=False)
    expected_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    execution = relationship("UiExecution")
    device = relationship("DesktopDevice")
