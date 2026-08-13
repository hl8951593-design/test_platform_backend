"""Add TestAuto Desktop device control-plane tables.

Revision ID: 0046_desktop_devices
Revises: 0045_database_test_actions
Create Date: 2026-07-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0046_desktop_devices"
down_revision: str | Sequence[str] | None = "0045_database_test_actions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "desktop_devices",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.String(length=64), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("installation_id_hash", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column(
            "registration_status",
            sa.String(length=32),
            nullable=False,
            server_default="active",
        ),
        sa.Column("accepting_jobs", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("concurrency_limit", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("desktop_version", sa.String(length=64), nullable=False),
        sa.Column("os_name", sa.String(length=64), nullable=False),
        sa.Column("os_version", sa.String(length=128), nullable=False),
        sa.Column("architecture", sa.String(length=32), nullable=False),
        sa.Column("supported_protocols_json", sa.JSON(), nullable=False),
        sa.Column("capabilities_json", sa.JSON(), nullable=False),
        sa.Column("runtime_state_json", sa.JSON(), nullable=False),
        sa.Column("device_public_key", sa.Text(), nullable=True),
        sa.Column("last_heartbeat_at", sa.DateTime(), nullable=True),
        sa.Column(
            "registered_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "owner_id",
            "installation_id_hash",
            name="uq_desktop_devices_owner_installation",
        ),
    )
    op.create_index("ix_desktop_devices_public_id", "desktop_devices", ["public_id"], unique=True)
    op.create_index("ix_desktop_devices_owner_id", "desktop_devices", ["owner_id"])
    op.create_index(
        "ix_desktop_devices_owner_status_updated",
        "desktop_devices",
        ["owner_id", "registration_status", "updated_at", "id"],
    )
    op.create_index(
        "ix_desktop_devices_last_heartbeat",
        "desktop_devices",
        ["last_heartbeat_at", "id"],
    )

    op.create_table(
        "desktop_device_credentials",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("credential_id", sa.String(length=64), nullable=False),
        sa.Column("device_id", sa.BigInteger(), nullable=False),
        sa.Column("refresh_secret_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["device_id"], ["desktop_devices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_desktop_device_credentials_credential_id",
        "desktop_device_credentials",
        ["credential_id"],
        unique=True,
    )
    op.create_index(
        "ix_desktop_device_credentials_device_id",
        "desktop_device_credentials",
        ["device_id"],
    )
    op.create_index(
        "ix_desktop_device_credentials_device_active",
        "desktop_device_credentials",
        ["device_id", "revoked_at", "expires_at", "id"],
    )

    op.create_table(
        "desktop_device_project_bindings",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("device_id", sa.BigInteger(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("accepting_jobs", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("concurrency_limit", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["device_id"], ["desktop_devices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "device_id",
            "project_id",
            name="uq_desktop_device_project_bindings_device_project",
        ),
    )
    op.create_index(
        "ix_desktop_device_project_bindings_device_id",
        "desktop_device_project_bindings",
        ["device_id"],
    )
    op.create_index(
        "ix_desktop_device_project_bindings_project_id",
        "desktop_device_project_bindings",
        ["project_id"],
    )
    op.create_index(
        "ix_desktop_device_project_bindings_project_available",
        "desktop_device_project_bindings",
        ["project_id", "enabled", "accepting_jobs", "device_id"],
    )


def downgrade() -> None:
    op.drop_table("desktop_device_project_bindings")
    op.drop_table("desktop_device_credentials")
    op.drop_table("desktop_devices")
