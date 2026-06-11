"""harden test plan execution

Revision ID: 0013_plan_hardening
Revises: 0012_test_plans
"""

from collections.abc import Sequence

from alembic import context, op
import sqlalchemy as sa

from app.core.sensitive_data import (
    decrypt_sensitive,
    encrypt_sensitive,
    protect_secret_text,
    reveal_secret_text,
)


revision: str = "0013_plan_hardening"
down_revision: str | Sequence[str] | None = "0012_test_plans"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("test_plan_runs", sa.Column("request_hash", sa.String(64), nullable=True))
    op.add_column("test_plan_runs", sa.Column("claimed_at", sa.DateTime(), nullable=True))
    op.add_column("test_plan_runs", sa.Column("heartbeat_at", sa.DateTime(), nullable=True))
    op.add_column("test_plan_runs", sa.Column("error_message", sa.Text(), nullable=True))
    op.add_column("test_plan_runs", sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("test_plan_runs", sa.Column("deleted_at", sa.DateTime(), nullable=True))

    op.add_column("test_scenario_runs", sa.Column("plan_run_id", sa.Integer(), nullable=True))
    op.add_column("test_scenario_runs", sa.Column("request_hash", sa.String(64), nullable=True))
    op.create_foreign_key(
        "fk_test_scenario_runs_plan_run_id", "test_scenario_runs", "test_plan_runs", ["plan_run_id"], ["id"]
    )
    op.create_index("ix_test_scenario_runs_plan_run_id", "test_scenario_runs", ["plan_run_id"])

    op.add_column("test_case_executions", sa.Column("scenario_run_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_test_case_executions_scenario_run_id",
        "test_case_executions",
        "test_scenario_runs",
        ["scenario_run_id"],
        ["id"],
    )
    op.create_index("ix_test_case_executions_scenario_run_id", "test_case_executions", ["scenario_run_id"])

    op.add_column("websocket_test_case_executions", sa.Column("scenario_run_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_websocket_executions_scenario_run_id",
        "websocket_test_case_executions",
        "test_scenario_runs",
        ["scenario_run_id"],
        ["id"],
    )
    op.create_index(
        "ix_websocket_test_case_executions_scenario_run_id",
        "websocket_test_case_executions",
        ["scenario_run_id"],
    )

    op.create_table(
        "test_plan_webhook_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("event", sa.String(128), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("body_hash", sa.String(64), nullable=False),
        sa.Column("run_ids", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("received_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id", "event", "idempotency_key",
            name="uq_test_plan_webhook_event_idempotency",
        ),
    )
    op.create_index("ix_test_plan_webhook_events_id", "test_plan_webhook_events", ["id"])
    op.create_index("ix_test_plan_webhook_events_project_id", "test_plan_webhook_events", ["project_id"])
    op.create_index(
        "ix_test_plan_webhook_events_project_received",
        "test_plan_webhook_events",
        ["project_id", "received_at"],
    )

    if not context.is_offline_mode():
        _transform_existing_data(encrypt=True)


def downgrade() -> None:
    if not context.is_offline_mode():
        _transform_existing_data(encrypt=False)

    op.drop_table("test_plan_webhook_events")
    op.drop_index("ix_websocket_test_case_executions_scenario_run_id", table_name="websocket_test_case_executions")
    op.drop_constraint(
        "fk_websocket_executions_scenario_run_id", "websocket_test_case_executions", type_="foreignkey"
    )
    op.drop_column("websocket_test_case_executions", "scenario_run_id")
    op.drop_index("ix_test_case_executions_scenario_run_id", table_name="test_case_executions")
    op.drop_constraint("fk_test_case_executions_scenario_run_id", "test_case_executions", type_="foreignkey")
    op.drop_column("test_case_executions", "scenario_run_id")
    op.drop_index("ix_test_scenario_runs_plan_run_id", table_name="test_scenario_runs")
    op.drop_constraint("fk_test_scenario_runs_plan_run_id", "test_scenario_runs", type_="foreignkey")
    op.drop_column("test_scenario_runs", "request_hash")
    op.drop_column("test_scenario_runs", "plan_run_id")
    op.drop_column("test_plan_runs", "deleted_at")
    op.drop_column("test_plan_runs", "is_deleted")
    op.drop_column("test_plan_runs", "error_message")
    op.drop_column("test_plan_runs", "heartbeat_at")
    op.drop_column("test_plan_runs", "claimed_at")
    op.drop_column("test_plan_runs", "request_hash")


def _transform_existing_data(*, encrypt: bool) -> None:
    bind = op.get_bind()
    scenario_versions = sa.table(
        "test_scenario_versions",
        sa.column("id", sa.Integer()),
        sa.column("definition", sa.JSON()),
    )
    for row in bind.execute(sa.select(scenario_versions.c.id, scenario_versions.c.definition)).mappings():
        bind.execute(
            sa.update(scenario_versions)
            .where(scenario_versions.c.id == row["id"])
            .values(definition=(
                encrypt_sensitive(row["definition"])
                if encrypt
                else decrypt_sensitive(row["definition"])
            ))
        )

    environment_variables = sa.table(
        "project_environment_variables",
        sa.column("id", sa.Integer()),
        sa.column("value", sa.Text()),
        sa.column("is_secret", sa.Boolean()),
    )
    for row in bind.execute(sa.select(
        environment_variables.c.id,
        environment_variables.c.value,
    ).where(environment_variables.c.is_secret.is_(True))).mappings():
        bind.execute(
            sa.update(environment_variables)
            .where(environment_variables.c.id == row["id"])
            .values(value=(
                protect_secret_text(row["value"])
                if encrypt
                else reveal_secret_text(row["value"])
            ))
        )
