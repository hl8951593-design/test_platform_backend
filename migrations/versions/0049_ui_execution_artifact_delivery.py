"""add UI execution artifact delivery

Revision ID: 0049_ui_execution_artifact_delivery
Revises: 0048_ui_execution_runtime
Create Date: 2026-07-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0049_ui_execution_artifact_delivery"
down_revision: str | Sequence[str] | None = "0048_ui_execution_runtime"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "execution_artifact_upload_sessions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("upload_id", sa.String(length=64), nullable=False),
        sa.Column("artifact_ref", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("ui_execution_id", sa.BigInteger(), nullable=False),
        sa.Column("created_by_device_id", sa.BigInteger(), nullable=False),
        sa.Column("client_request_id", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("step_id", sa.String(length=128), nullable=True),
        sa.Column("section", sa.String(length=64), nullable=False),
        sa.Column("object_key", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("expected_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("expected_sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("finalized_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["ui_execution_id"], ["ui_executions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["created_by_device_id"], ["desktop_devices.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "upload_id", name="uq_execution_artifact_upload_session_upload"
        ),
        sa.UniqueConstraint(
            "artifact_ref", name="uq_execution_artifact_upload_session_artifact"
        ),
        sa.UniqueConstraint(
            "ui_execution_id",
            "created_by_device_id",
            "client_request_id",
            name="uq_execution_artifact_upload_session_request",
        ),
    )
    op.create_index(
        "ix_execution_artifact_upload_session_status_expires",
        "execution_artifact_upload_sessions",
        ["status", "expires_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_execution_artifact_upload_session_execution_created",
        "execution_artifact_upload_sessions",
        ["ui_execution_id", "created_at", "id"],
        unique=False,
    )
    op.add_column(
        "execution_payload_artifacts",
        sa.Column("metadata_json", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("execution_payload_artifacts", "metadata_json")
    op.drop_index(
        "ix_execution_artifact_upload_session_execution_created",
        table_name="execution_artifact_upload_sessions",
    )
    op.drop_index(
        "ix_execution_artifact_upload_session_status_expires",
        table_name="execution_artifact_upload_sessions",
    )
    op.drop_table("execution_artifact_upload_sessions")
