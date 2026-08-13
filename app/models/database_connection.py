from datetime import datetime

from sqlalchemy import (
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


class ProjectDatabaseConnection(Base):
    __tablename__ = "project_database_connections"
    __table_args__ = (
        UniqueConstraint(
            "environment_id",
            "connection_key",
            name="uq_project_database_connections_environment_key",
        ),
        Index(
            "ix_project_database_connections_project_environment_active",
            "project_id",
            "environment_id",
            "is_deleted",
            "is_enabled",
            "id",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id"), index=True, nullable=False
    )
    environment_id: Mapped[int] = mapped_column(
        ForeignKey("project_environments.id"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    connection_key: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    database_name: Mapped[str] = mapped_column(String(128), nullable=False)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    password_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    options_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    allow_writes: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    connect_timeout_ms: Mapped[int] = mapped_column(
        Integer, default=5000, nullable=False
    )
    statement_timeout_ms: Mapped[int] = mapped_column(
        Integer, default=10000, nullable=False
    )
    max_rows: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_by_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    project = relationship("Project")
    environment = relationship("ProjectEnvironment")
    created_by = relationship("User")


class DatabaseActionExecution(Base):
    __tablename__ = "database_action_executions"
    __table_args__ = (
        Index(
            "ix_database_action_executions_project_created",
            "project_id",
            "created_at",
            "id",
        ),
        Index(
            "ix_database_action_executions_scenario_step",
            "scenario_run_id",
            "step_id",
            "id",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id"), index=True, nullable=False
    )
    environment_id: Mapped[int] = mapped_column(
        ForeignKey("project_environments.id"), index=True, nullable=False
    )
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("project_database_connections.id"), index=True, nullable=False
    )
    scenario_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("test_scenario_runs.id"), index=True, nullable=True
    )
    step_id: Mapped[str] = mapped_column(String(128), nullable=False)
    action_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    statement_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    result_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    assertion_results: Mapped[list | None] = mapped_column(JSON, nullable=True)
    attempt_history: Mapped[list | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    triggered_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    connection = relationship("ProjectDatabaseConnection")
    triggered_by = relationship("User")
