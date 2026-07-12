from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Index,
    Integer,
    JSON,
    LargeBinary,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


BIGINT_PK = BigInteger().with_variant(Integer, "sqlite")
BIGINT_VALUE = BigInteger().with_variant(Integer, "sqlite")


class ExecutionRecordIndex(Base):
    __tablename__ = "execution_record_index"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "execution_type",
            "execution_id",
            name="uq_execution_record_index_identity",
        ),
        Index(
            "ix_execution_record_index_project_started",
            "project_id",
            "started_at",
            "execution_type",
            "execution_id",
        ),
        Index(
            "ix_execution_record_index_project_status_started",
            "project_id",
            "status",
            "started_at",
            "execution_id",
        ),
        Index(
            "ix_execution_record_index_project_env_started",
            "project_id",
            "environment_id",
            "started_at",
            "execution_id",
        ),
        Index(
            "ix_execution_record_index_project_failure_started",
            "project_id",
            "failure_signature",
            "started_at",
            "execution_id",
        ),
    )

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(nullable=False)
    execution_type: Mapped[str] = mapped_column(String(32), nullable=False)
    execution_id: Mapped[int] = mapped_column(BIGINT_VALUE, nullable=False)
    object_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    resource_id: Mapped[int | None] = mapped_column(BIGINT_VALUE, nullable=True)
    resource_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    environment_id: Mapped[int | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(32), nullable=False)
    trigger_user_id: Mapped[int] = mapped_column(BIGINT_VALUE, nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(BIGINT_VALUE, nullable=True)
    total_steps: Mapped[int] = mapped_column(default=0, nullable=False)
    passed_steps: Mapped[int] = mapped_column(default=0, nullable=False)
    failed_steps: Mapped[int] = mapped_column(default=0, nullable=False)
    timeout_steps: Mapped[int] = mapped_column(default=0, nullable=False)
    skipped_steps: Mapped[int] = mapped_column(default=0, nullable=False)
    first_failed_step_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    failure_category: Mapped[str | None] = mapped_column(String(32), nullable=True)
    failure_signature: Mapped[str | None] = mapped_column(String(255), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    projection_version: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ExecutionStepDiagnostic(Base):
    __tablename__ = "execution_step_diagnostics"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "execution_type",
            "execution_id",
            "step_id",
            name="uq_execution_step_diagnostic_identity",
        ),
        Index(
            "ix_execution_step_project_execution_index",
            "project_id",
            "execution_type",
            "execution_id",
            "step_index",
        ),
        Index(
            "ix_execution_step_project_execution_status_index",
            "project_id",
            "execution_type",
            "execution_id",
            "status",
            "step_index",
        ),
        Index(
            "ix_execution_step_project_status_error_created",
            "project_id",
            "status",
            "error_code",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(nullable=False)
    execution_type: Mapped[str] = mapped_column(String(32), nullable=False)
    execution_id: Mapped[int] = mapped_column(BIGINT_VALUE, nullable=False)
    step_id: Mapped[str] = mapped_column(String(255), nullable=False)
    step_index: Mapped[int] = mapped_column(nullable=False)
    node_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    node_phase: Mapped[str | None] = mapped_column(String(32), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(BIGINT_VALUE, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(512), nullable=True)
    assertion_summary_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    response_summary_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    binding_summary_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    extraction_summary_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    retry_summary_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    detail_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    request_artifact_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    response_artifact_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    detail_artifact_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    projection_version: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ExecutionPayloadArtifact(Base):
    __tablename__ = "execution_payload_artifacts"
    __table_args__ = (
        UniqueConstraint("artifact_ref", name="uq_execution_payload_artifact_ref"),
        Index(
            "ix_execution_payload_artifact_project_execution_step",
            "project_id",
            "execution_type",
            "execution_id",
            "step_id",
        ),
        Index(
            "ix_execution_payload_artifact_project_created",
            "project_id",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    artifact_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    project_id: Mapped[int] = mapped_column(nullable=False)
    execution_type: Mapped[str] = mapped_column(String(32), nullable=False)
    execution_id: Mapped[int] = mapped_column(BIGINT_VALUE, nullable=False)
    step_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    section: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_backend: Mapped[str] = mapped_column(String(32), nullable=False)
    storage_locator: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    encoding: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    raw_size_bytes: Mapped[int] = mapped_column(BIGINT_VALUE, nullable=False)
    stored_size_bytes: Mapped[int] = mapped_column(BIGINT_VALUE, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    redaction_version: Mapped[str] = mapped_column(String(64), nullable=False)
    retention_tier: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )


class _ExecutionMetricMixin:
    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(nullable=False)
    environment_id: Mapped[int | None] = mapped_column(nullable=True)
    execution_type: Mapped[str] = mapped_column(String(32), nullable=False)
    time_bucket: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    failure_signature: Mapped[str | None] = mapped_column(String(255), nullable=True)
    execution_count: Mapped[int] = mapped_column(BIGINT_VALUE, nullable=False)
    duration_sum_ms: Mapped[int] = mapped_column(BIGINT_VALUE, nullable=False)
    duration_max_ms: Mapped[int] = mapped_column(BIGINT_VALUE, nullable=False)
    watermark: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ExecutionMetricHourly(_ExecutionMetricMixin, Base):
    __tablename__ = "execution_metrics_hourly"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "environment_id",
            "execution_type",
            "time_bucket",
            "status",
            "failure_signature",
            name="uq_execution_metric_hourly_dimensions",
        ),
        Index(
            "ix_execution_metric_hourly_project_bucket",
            "project_id",
            "time_bucket",
        ),
    )


class ExecutionMetricDaily(_ExecutionMetricMixin, Base):
    __tablename__ = "execution_metrics_daily"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "environment_id",
            "execution_type",
            "time_bucket",
            "status",
            "failure_signature",
            name="uq_execution_metric_daily_dimensions",
        ),
        Index(
            "ix_execution_metric_daily_project_bucket",
            "project_id",
            "time_bucket",
        ),
    )
