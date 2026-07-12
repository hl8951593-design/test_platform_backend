"""Add execution diagnostic read models.

Revision ID: 0041_execution_diagnostic_read_models
Revises: 0040_agent_capability_plans
Create Date: 2026-07-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0041_execution_diagnostic_read_models"
down_revision: str | Sequence[str] | None = "0040_agent_capability_plans"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "execution_record_index",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("execution_type", sa.String(length=32), nullable=False),
        sa.Column("execution_id", sa.BigInteger(), nullable=False),
        sa.Column("object_ref", sa.String(length=255), nullable=False),
        sa.Column("resource_id", sa.BigInteger(), nullable=True),
        sa.Column("resource_name", sa.String(length=255), nullable=True),
        sa.Column("environment_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("trigger_type", sa.String(length=32), nullable=False),
        sa.Column("trigger_user_id", sa.BigInteger(), nullable=False),
        sa.Column("duration_ms", sa.BigInteger(), nullable=True),
        sa.Column("total_steps", sa.Integer(), nullable=False),
        sa.Column("passed_steps", sa.Integer(), nullable=False),
        sa.Column("failed_steps", sa.Integer(), nullable=False),
        sa.Column("timeout_steps", sa.Integer(), nullable=False),
        sa.Column("skipped_steps", sa.Integer(), nullable=False),
        sa.Column("first_failed_step_id", sa.String(length=255), nullable=True),
        sa.Column("failure_category", sa.String(length=32), nullable=True),
        sa.Column("failure_signature", sa.String(length=255), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("source_updated_at", sa.DateTime(), nullable=True),
        sa.Column("projection_version", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "execution_type",
            "execution_id",
            name="uq_execution_record_index_identity",
        ),
    )
    op.create_index(
        "ix_execution_record_index_project_started",
        "execution_record_index",
        ["project_id", "started_at", "execution_type", "execution_id"],
        unique=False,
    )
    op.create_index(
        "ix_execution_record_index_project_status_started",
        "execution_record_index",
        ["project_id", "status", "started_at", "execution_id"],
        unique=False,
    )
    op.create_index(
        "ix_execution_record_index_project_env_started",
        "execution_record_index",
        ["project_id", "environment_id", "started_at", "execution_id"],
        unique=False,
    )
    op.create_index(
        "ix_execution_record_index_project_failure_started",
        "execution_record_index",
        ["project_id", "failure_signature", "started_at", "execution_id"],
        unique=False,
    )

    op.create_table(
        "execution_step_diagnostics",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("execution_type", sa.String(length=32), nullable=False),
        sa.Column("execution_id", sa.BigInteger(), nullable=False),
        sa.Column("step_id", sa.String(length=255), nullable=False),
        sa.Column("step_index", sa.Integer(), nullable=False),
        sa.Column("node_id", sa.String(length=255), nullable=True),
        sa.Column("node_phase", sa.String(length=32), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("duration_ms", sa.BigInteger(), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.String(length=512), nullable=True),
        sa.Column("assertion_summary_json", sa.JSON(), nullable=False),
        sa.Column("response_summary_json", sa.JSON(), nullable=False),
        sa.Column("binding_summary_json", sa.JSON(), nullable=False),
        sa.Column("extraction_summary_json", sa.JSON(), nullable=False),
        sa.Column("retry_summary_json", sa.JSON(), nullable=False),
        sa.Column("detail_json", sa.JSON(), nullable=False),
        sa.Column("request_artifact_ref", sa.String(length=255), nullable=True),
        sa.Column("response_artifact_ref", sa.String(length=255), nullable=True),
        sa.Column("detail_artifact_ref", sa.String(length=255), nullable=True),
        sa.Column("projection_version", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "execution_type",
            "execution_id",
            "step_id",
            name="uq_execution_step_diagnostic_identity",
        ),
    )
    op.create_index(
        "ix_execution_step_project_execution_index",
        "execution_step_diagnostics",
        ["project_id", "execution_type", "execution_id", "step_index"],
        unique=False,
    )
    op.create_index(
        "ix_execution_step_project_execution_status_index",
        "execution_step_diagnostics",
        ["project_id", "execution_type", "execution_id", "status", "step_index"],
        unique=False,
    )
    op.create_index(
        "ix_execution_step_project_status_error_created",
        "execution_step_diagnostics",
        ["project_id", "status", "error_code", "created_at"],
        unique=False,
    )

    op.create_table(
        "execution_payload_artifacts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("artifact_ref", sa.String(length=255), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("execution_type", sa.String(length=32), nullable=False),
        sa.Column("execution_id", sa.BigInteger(), nullable=False),
        sa.Column("step_id", sa.String(length=255), nullable=True),
        sa.Column("section", sa.String(length=64), nullable=False),
        sa.Column("storage_backend", sa.String(length=32), nullable=False),
        sa.Column("storage_locator", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("encoding", sa.String(length=32), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=True),
        sa.Column("raw_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("stored_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("redaction_version", sa.String(length=64), nullable=False),
        sa.Column("retention_tier", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("artifact_ref", name="uq_execution_payload_artifact_ref"),
    )
    op.create_index(
        "ix_execution_payload_artifact_project_execution_step",
        "execution_payload_artifacts",
        ["project_id", "execution_type", "execution_id", "step_id"],
        unique=False,
    )
    op.create_index(
        "ix_execution_payload_artifact_project_created",
        "execution_payload_artifacts",
        ["project_id", "created_at"],
        unique=False,
    )

    _create_metric_table(
        "execution_metrics_hourly",
        "uq_execution_metric_hourly_dimensions",
        "ix_execution_metric_hourly_project_bucket",
    )
    _create_metric_table(
        "execution_metrics_daily",
        "uq_execution_metric_daily_dimensions",
        "ix_execution_metric_daily_project_bucket",
    )


def downgrade() -> None:
    op.drop_table("execution_metrics_daily")
    op.drop_table("execution_metrics_hourly")
    op.drop_table("execution_payload_artifacts")
    op.drop_table("execution_step_diagnostics")
    op.drop_table("execution_record_index")


def _create_metric_table(table_name: str, constraint_name: str, index_name: str) -> None:
    op.create_table(
        table_name,
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("environment_id", sa.Integer(), nullable=True),
        sa.Column("execution_type", sa.String(length=32), nullable=False),
        sa.Column("time_bucket", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=True),
        sa.Column("failure_signature", sa.String(length=255), nullable=True),
        sa.Column("execution_count", sa.BigInteger(), nullable=False),
        sa.Column("duration_sum_ms", sa.BigInteger(), nullable=False),
        sa.Column("duration_max_ms", sa.BigInteger(), nullable=False),
        sa.Column("watermark", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "environment_id",
            "execution_type",
            "time_bucket",
            "status",
            "failure_signature",
            name=constraint_name,
        ),
    )
    op.create_index(
        index_name,
        table_name,
        ["project_id", "time_bucket"],
        unique=False,
    )
