"""add UI execution runtime foundation

Revision ID: 0048_ui_execution_runtime
Revises: 0047_ui_test_cases
Create Date: 2026-07-16
"""

from alembic import op
import sqlalchemy as sa


revision = "0048_ui_execution_runtime"
down_revision = "0047_ui_test_cases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ui_executions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("environment_id", sa.Integer(), nullable=True),
        sa.Column("ui_test_case_id", sa.BigInteger(), nullable=False),
        sa.Column("ui_test_case_version_id", sa.BigInteger(), nullable=False),
        sa.Column("trigger_user_id", sa.Integer(), nullable=False),
        sa.Column("trigger_type", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("client_request_id", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("requested_device_id", sa.BigInteger(), nullable=True),
        sa.Column("assigned_device_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("delivery_status", sa.String(length=32), nullable=False),
        sa.Column("attention_reason", sa.String(length=128), nullable=True),
        sa.Column("case_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("runtime_policy_json", sa.JSON(), nullable=False),
        sa.Column("required_secret_refs_json", sa.JSON(), nullable=False),
        sa.Column("lease_id", sa.String(length=64), nullable=True),
        sa.Column("lease_version", sa.Integer(), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("claimed_at", sa.DateTime(), nullable=True),
        sa.Column("last_renewed_at", sa.DateTime(), nullable=True),
        sa.Column("current_step", sa.Integer(), nullable=False),
        sa.Column("total_steps", sa.Integer(), nullable=False),
        sa.Column("passed_steps", sa.Integer(), nullable=False),
        sa.Column("failed_steps", sa.Integer(), nullable=False),
        sa.Column("skipped_steps", sa.Integer(), nullable=False),
        sa.Column("assisted", sa.Boolean(), nullable=False),
        sa.Column("duration_ms", sa.BigInteger(), nullable=True),
        sa.Column("error_category", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("last_client_sequence", sa.BigInteger(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
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
            ["environment_id"], ["project_environments.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["ui_test_case_id"], ["ui_test_cases.id"]),
        sa.ForeignKeyConstraint(
            ["ui_test_case_version_id"], ["ui_test_case_versions.id"]
        ),
        sa.ForeignKeyConstraint(["trigger_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["requested_device_id"], ["desktop_devices.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["assigned_device_id"], ["desktop_devices.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "trigger_user_id",
            "client_request_id",
            name="uq_ui_executions_project_user_request",
        ),
    )
    op.create_index("ix_ui_executions_public_id", "ui_executions", ["public_id"], unique=True)
    op.create_index("ix_ui_executions_project_id", "ui_executions", ["project_id"])
    op.create_index("ix_ui_executions_environment_id", "ui_executions", ["environment_id"])
    op.create_index("ix_ui_executions_ui_test_case_id", "ui_executions", ["ui_test_case_id"])
    op.create_index(
        "ix_ui_executions_ui_test_case_version_id",
        "ui_executions",
        ["ui_test_case_version_id"],
    )
    op.create_index("ix_ui_executions_trigger_user_id", "ui_executions", ["trigger_user_id"])
    op.create_index(
        "ix_ui_executions_requested_device_id", "ui_executions", ["requested_device_id"]
    )
    op.create_index(
        "ix_ui_executions_assigned_device_id", "ui_executions", ["assigned_device_id"]
    )
    op.create_index(
        "ix_ui_executions_project_environment_status_created",
        "ui_executions",
        ["project_id", "environment_id", "status", "created_at", "id"],
    )
    op.create_index(
        "ix_ui_executions_assigned_device_status_updated",
        "ui_executions",
        ["assigned_device_id", "status", "updated_at", "id"],
    )
    op.create_index(
        "ix_ui_executions_status_lease_expires",
        "ui_executions",
        ["status", "lease_expires_at", "id"],
    )
    op.create_index(
        "ix_ui_executions_case_version_created",
        "ui_executions",
        ["ui_test_case_id", "ui_test_case_version_id", "created_at", "id"],
    )

    op.create_table(
        "ui_step_executions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("ui_execution_id", sa.BigInteger(), nullable=False),
        sa.Column("step_id", sa.String(length=128), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("step_index", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("operation", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("duration_ms", sa.BigInteger(), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("result_summary_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["ui_execution_id"], ["ui_executions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "ui_execution_id",
            "step_id",
            "attempt",
            name="uq_ui_step_executions_execution_step_attempt",
        ),
    )
    op.create_index(
        "ix_ui_step_executions_ui_execution_id",
        "ui_step_executions",
        ["ui_execution_id"],
    )
    op.create_index(
        "ix_ui_step_executions_execution_step_index",
        "ui_step_executions",
        ["ui_execution_id", "step_index", "attempt"],
    )

    op.create_table(
        "ui_execution_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("ui_execution_id", sa.BigInteger(), nullable=False),
        sa.Column("client_event_id", sa.String(length=128), nullable=False),
        sa.Column("client_sequence", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("step_id", sa.String(length=128), nullable=True),
        sa.Column("level", sa.String(length=16), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column(
            "received_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["ui_execution_id"], ["ui_executions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "ui_execution_id",
            "client_event_id",
            name="uq_ui_execution_events_execution_event",
        ),
        sa.UniqueConstraint(
            "ui_execution_id",
            "client_sequence",
            name="uq_ui_execution_events_execution_sequence",
        ),
    )
    op.create_index("ix_ui_execution_events_project_id", "ui_execution_events", ["project_id"])
    op.create_index(
        "ix_ui_execution_events_ui_execution_id", "ui_execution_events", ["ui_execution_id"]
    )
    op.create_index(
        "ix_ui_execution_events_execution_sequence",
        "ui_execution_events",
        ["ui_execution_id", "client_sequence"],
    )
    op.create_index(
        "ix_ui_execution_events_project_received",
        "ui_execution_events",
        ["project_id", "received_at", "id"],
    )

    op.create_table(
        "ui_runtime_patches",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("ui_execution_id", sa.BigInteger(), nullable=False),
        sa.Column("step_id", sa.String(length=128), nullable=True),
        sa.Column("patch_type", sa.String(length=32), nullable=False),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("before_json", sa.JSON(), nullable=False),
        sa.Column("after_json", sa.JSON(), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("actor_device_id", sa.BigInteger(), nullable=True),
        sa.Column("reason", sa.String(length=512), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["ui_execution_id"], ["ui_executions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["actor_device_id"], ["desktop_devices.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ui_runtime_patches_ui_execution_id", "ui_runtime_patches", ["ui_execution_id"]
    )
    op.create_index(
        "ix_ui_runtime_patches_execution_created",
        "ui_runtime_patches",
        ["ui_execution_id", "created_at", "id"],
    )

    op.create_table(
        "ui_execution_commands",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.String(length=64), nullable=False),
        sa.Column("ui_execution_id", sa.BigInteger(), nullable=False),
        sa.Column("command_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("issued_by_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["ui_execution_id"], ["ui_executions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["issued_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ui_execution_commands_public_id",
        "ui_execution_commands",
        ["public_id"],
        unique=True,
    )
    op.create_index(
        "ix_ui_execution_commands_ui_execution_id",
        "ui_execution_commands",
        ["ui_execution_id"],
    )
    op.create_index(
        "ix_ui_execution_commands_execution_status_created",
        "ui_execution_commands",
        ["ui_execution_id", "status", "created_at", "id"],
    )


def downgrade() -> None:
    op.drop_table("ui_execution_commands")
    op.drop_table("ui_runtime_patches")
    op.drop_table("ui_execution_events")
    op.drop_table("ui_step_executions")
    op.drop_table("ui_executions")
