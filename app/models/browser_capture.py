from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class BrowserCapture(Base):
    __tablename__ = "browser_captures"
    __table_args__ = (Index("ix_browser_captures_project_updated", "project_id", "updated_at"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True, nullable=False)
    environment_id: Mapped[int] = mapped_column(ForeignKey("project_environments.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="capturing", nullable=False)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    entries = relationship("BrowserCaptureEntry", back_populates="capture", cascade="all, delete-orphan")


class BrowserCaptureEntry(Base):
    __tablename__ = "browser_capture_entries"
    __table_args__ = (
        UniqueConstraint("capture_id", "client_entry_id", name="uq_browser_capture_entries_client"),
        Index("ix_browser_capture_entries_capture_status", "capture_id", "status"),
        Index("ix_browser_capture_entries_project_created", "project_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    capture_id: Mapped[int] = mapped_column(ForeignKey("browser_captures.id"), index=True, nullable=False)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True, nullable=False)
    client_entry_id: Mapped[str] = mapped_column(String(64), nullable=False)
    protocol: Mapped[str] = mapped_column(String(16), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    method: Mapped[str] = mapped_column(String(16), nullable=False)
    path: Mapped[str] = mapped_column(String(1024), nullable=False)
    source_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    request_data: Mapped[dict] = mapped_column(JSON, nullable=False)
    response_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    draft_data: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="captured", nullable=False)
    ai_analysis: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    import_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    capture = relationship("BrowserCapture", back_populates="entries")
