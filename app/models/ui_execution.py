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
BIGINT_VALUE = BigInteger().with_variant(Integer, "sqlite")


class UiExecution(Base):
    __tablename__ = "ui_executions"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "trigger_user_id",
            "client_request_id",
            name="uq_ui_executions_project_user_request",
        ),
        Index(
            "ix_ui_executions_project_environment_status_created",
            "project_id",
            "environment_id",
            "status",
            "created_at",
            "id",
        ),
        Index(
            "ix_ui_executions_assigned_device_status_updated",
            "assigned_device_id",
            "status",
            "updated_at",
            "id",
        ),
        Index(
            "ix_ui_executions_status_lease_expires",
            "status",
            "lease_expires_at",
            "id",
        ),
        Index(
            "ix_ui_executions_case_version_created",
            "ui_test_case_id",
            "ui_test_case_version_id",
            "created_at",
            "id",
        ),
    )

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    environment_id: Mapped[int | None] = mapped_column(
        ForeignKey("project_environments.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    ui_test_case_id: Mapped[int] = mapped_column(
        ForeignKey("ui_test_cases.id"), index=True, nullable=False
    )
    ui_test_case_version_id: Mapped[int] = mapped_column(
        ForeignKey("ui_test_case_versions.id"), index=True, nullable=False
    )
    trigger_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=False
    )
    trigger_type: Mapped[str] = mapped_column(String(32), default="manual", nullable=False)
    source: Mapped[str] = mapped_column(String(32), default="platform_task", nullable=False)
    client_request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    requested_device_id: Mapped[int | None] = mapped_column(
        ForeignKey("desktop_devices.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    assigned_device_id: Mapped[int | None] = mapped_column(
        ForeignKey("desktop_devices.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False)
    delivery_status: Mapped[str] = mapped_column(
        String(32), default="pending", nullable=False
    )
    attention_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
    case_snapshot_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    runtime_policy_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    required_secret_refs_json: Mapped[list] = mapped_column(
        JSON, default=list, nullable=False
    )
    lease_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_renewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    current_step: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_steps: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    passed_steps: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_steps: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    skipped_steps: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    assisted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(BIGINT_VALUE, nullable=True)
    error_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_client_sequence: Mapped[int] = mapped_column(BIGINT_VALUE, default=0, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    project = relationship("Project")
    environment = relationship("ProjectEnvironment")
    ui_test_case = relationship("UiTestCase")
    ui_test_case_version = relationship("UiTestCaseVersion")
    trigger_user = relationship("User")
    requested_device = relationship("DesktopDevice", foreign_keys=[requested_device_id])
    assigned_device = relationship("DesktopDevice", foreign_keys=[assigned_device_id])
    step_executions = relationship(
        "UiStepExecution", back_populates="execution", cascade="all, delete-orphan"
    )
    events = relationship(
        "UiExecutionEvent", back_populates="execution", cascade="all, delete-orphan"
    )
    runtime_patches = relationship(
        "UiRuntimePatch", back_populates="execution", cascade="all, delete-orphan"
    )
    commands = relationship(
        "UiExecutionCommand", back_populates="execution", cascade="all, delete-orphan"
    )


class UiStepExecution(Base):
    __tablename__ = "ui_step_executions"
    __table_args__ = (
        UniqueConstraint(
            "ui_execution_id",
            "step_id",
            "attempt",
            name="uq_ui_step_executions_execution_step_attempt",
        ),
        Index(
            "ix_ui_step_executions_execution_step_index",
            "ui_execution_id",
            "step_index",
            "attempt",
        ),
    )

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    ui_execution_id: Mapped[int] = mapped_column(
        ForeignKey("ui_executions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    step_id: Mapped[str] = mapped_column(String(128), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    step_index: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(BIGINT_VALUE, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_summary_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    execution = relationship("UiExecution", back_populates="step_executions")


class UiExecutionEvent(Base):
    __tablename__ = "ui_execution_events"
    __table_args__ = (
        UniqueConstraint(
            "ui_execution_id",
            "client_event_id",
            name="uq_ui_execution_events_execution_event",
        ),
        UniqueConstraint(
            "ui_execution_id",
            "client_sequence",
            name="uq_ui_execution_events_execution_sequence",
        ),
        Index(
            "ix_ui_execution_events_execution_sequence",
            "ui_execution_id",
            "client_sequence",
        ),
        Index(
            "ix_ui_execution_events_project_received",
            "project_id",
            "received_at",
            "id",
        ),
    )

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    ui_execution_id: Mapped[int] = mapped_column(
        ForeignKey("ui_executions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    client_event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    client_sequence: Mapped[int] = mapped_column(BIGINT_VALUE, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    step_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    level: Mapped[str] = mapped_column(String(16), default="info", nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    execution = relationship("UiExecution", back_populates="events")


class UiRuntimePatch(Base):
    __tablename__ = "ui_runtime_patches"
    __table_args__ = (
        UniqueConstraint(
            "request_command_id",
            name="uq_ui_runtime_patches_request_command",
        ),
        Index(
            "ix_ui_runtime_patches_execution_created",
            "ui_execution_id",
            "created_at",
            "id",
        ),
    )

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    ui_execution_id: Mapped[int] = mapped_column(
        ForeignKey("ui_executions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    request_command_id: Mapped[int | None] = mapped_column(
        ForeignKey("ui_execution_commands.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    step_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    patch_type: Mapped[str] = mapped_column(String(32), nullable=False)
    scope: Mapped[str] = mapped_column(String(32), default="current_run", nullable=False)
    before_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    after_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    actor_device_id: Mapped[int | None] = mapped_column(
        ForeignKey("desktop_devices.id", ondelete="SET NULL"), nullable=True
    )
    reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    execution = relationship("UiExecution", back_populates="runtime_patches")
    request_command = relationship(
        "UiExecutionCommand",
        foreign_keys=[request_command_id],
    )


class UiExecutionCommand(Base):
    __tablename__ = "ui_execution_commands"
    __table_args__ = (
        Index(
            "ix_ui_execution_commands_execution_status_created",
            "ui_execution_id",
            "status",
            "created_at",
            "id",
        ),
    )

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    ui_execution_id: Mapped[int] = mapped_column(
        ForeignKey("ui_executions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    command_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    issued_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    execution = relationship("UiExecution", back_populates="commands")
