from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class VisualFlow(Base):
    __tablename__ = "visual_flows"
    __table_args__ = (Index("ix_visual_flows_project_updated", "project_id", "updated_at"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    current_version: Mapped[int] = mapped_column(default=1, nullable=False)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    updated_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    versions = relationship("VisualFlowVersion", back_populates="flow", cascade="all, delete-orphan")


class VisualFlowVersion(Base):
    __tablename__ = "visual_flow_versions"
    __table_args__ = (
        UniqueConstraint("flow_id", "version", name="uq_visual_flow_versions_flow_version"),
        Index("ix_visual_flow_versions_flow_version", "flow_id", "version"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    flow_id: Mapped[int] = mapped_column(ForeignKey("visual_flows.id"), index=True, nullable=False)
    version: Mapped[int] = mapped_column(nullable=False)
    definition: Mapped[dict] = mapped_column(JSON, nullable=False)
    definition_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    flow = relationship("VisualFlow", back_populates="versions")


class VisualFlowExecution(Base):
    __tablename__ = "visual_flow_executions"
    __table_args__ = (
        UniqueConstraint("project_id", "idempotency_key", name="uq_visual_flow_executions_idempotency"),
        Index("ix_visual_flow_executions_project_created", "project_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    flow_id: Mapped[int | None] = mapped_column(ForeignKey("visual_flows.id"), index=True, nullable=True)
    flow_version_id: Mapped[int | None] = mapped_column(ForeignKey("visual_flow_versions.id"), nullable=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True, nullable=False)
    environment_id: Mapped[int | None] = mapped_column(ForeignKey("project_environments.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(32), default="manual", nullable=False)
    trigger_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    context_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class VisualFlowNodeExecution(Base):
    __tablename__ = "visual_flow_node_executions"
    __table_args__ = (
        UniqueConstraint("execution_id", "node_id", name="uq_visual_flow_node_executions_node"),
        Index("ix_visual_flow_node_executions_execution", "execution_id", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    execution_id: Mapped[int] = mapped_column(ForeignKey("visual_flow_executions.id"), index=True, nullable=False)
    node_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    attempt: Mapped[int] = mapped_column(default=1, nullable=False)
    request_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    output_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
