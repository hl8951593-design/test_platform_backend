"""add agent reconcile foundation

Revision ID: 0022_agent_reconcile_foundation
Revises: 0021_agent_runtime_foundation
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0022_agent_reconcile_foundation"
down_revision: str | Sequence[str] | None = "0021_agent_runtime_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ai_agent_runs",
        sa.Column("migration_block_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "ai_agent_runs",
        sa.Column("blocking_tool_call_ids_json", sa.JSON(), nullable=True),
    )
    op.add_column(
        "ai_agent_tool_calls",
        sa.Column("backend_request_schema_hash", sa.String(64), nullable=True),
    )
    op.add_column(
        "ai_agent_tool_calls",
        sa.Column("backend_output_schema_hash", sa.String(64), nullable=True),
    )
    op.add_column(
        "ai_agent_tool_calls",
        sa.Column("reconcile_contract_version", sa.String(64), nullable=True),
    )
    op.add_column(
        "ai_agent_tool_calls",
        sa.Column("result_adapter_version", sa.String(64), nullable=True),
    )

    op.create_table(
        "ai_agent_migration_blocks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("block_id", sa.String(64), nullable=False),
        sa.Column("run_id", sa.String(64), nullable=False),
        sa.Column("tool_call_id", sa.String(64), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("block_type", sa.String(64), nullable=False),
        sa.Column("reason", sa.String(128), nullable=False),
        sa.Column("backend_name", sa.String(128), nullable=True),
        sa.Column("backend_operation", sa.String(128), nullable=True),
        sa.Column("backend_contract_version", sa.String(64), nullable=True),
        sa.Column("required_migration_type", sa.String(64), nullable=True),
        sa.Column("details_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("block_id", name="uq_agent_migration_blocks_block_id"),
    )
    op.create_index("ix_ai_agent_migration_blocks_id", "ai_agent_migration_blocks", ["id"])
    op.create_index(
        "idx_agent_migration_blocks_run_status",
        "ai_agent_migration_blocks",
        ["run_id", "status", "created_at"],
    )
    op.create_index(
        "idx_agent_migration_blocks_tool_call",
        "ai_agent_migration_blocks",
        ["tool_call_id"],
    )

    connection = op.get_bind()
    contracts = sa.table(
        "ai_agent_backend_contracts",
        sa.column("backend_name", sa.String),
        sa.column("backend_operation", sa.String),
        sa.column("backend_contract_version", sa.String),
        sa.column("request_schema_hash", sa.String),
        sa.column("output_schema_hash", sa.String),
        sa.column("reconcile_contract_version", sa.String),
        sa.column("result_adapter_version", sa.String),
    )
    calls = sa.table(
        "ai_agent_tool_calls",
        sa.column("backend_name", sa.String),
        sa.column("backend_operation", sa.String),
        sa.column("backend_contract_version", sa.String),
        sa.column("backend_request_schema_hash", sa.String),
        sa.column("backend_output_schema_hash", sa.String),
        sa.column("reconcile_contract_version", sa.String),
        sa.column("result_adapter_version", sa.String),
    )
    rows = connection.execute(sa.select(contracts)).mappings().all()
    for row in rows:
        connection.execute(
            calls.update()
            .where(
                calls.c.backend_name == row["backend_name"],
                calls.c.backend_operation == row["backend_operation"],
                calls.c.backend_contract_version == row["backend_contract_version"],
            )
            .values(
                backend_request_schema_hash=row["request_schema_hash"],
                backend_output_schema_hash=row["output_schema_hash"],
                reconcile_contract_version=row["reconcile_contract_version"],
                result_adapter_version=row["result_adapter_version"],
            )
        )


def downgrade() -> None:
    op.drop_table("ai_agent_migration_blocks")
    op.drop_column("ai_agent_tool_calls", "result_adapter_version")
    op.drop_column("ai_agent_tool_calls", "reconcile_contract_version")
    op.drop_column("ai_agent_tool_calls", "backend_output_schema_hash")
    op.drop_column("ai_agent_tool_calls", "backend_request_schema_hash")
    op.drop_column("ai_agent_runs", "blocking_tool_call_ids_json")
    op.drop_column("ai_agent_runs", "migration_block_count")
