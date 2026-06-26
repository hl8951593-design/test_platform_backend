"""add agent migration resolution fields

Revision ID: 0025_agent_migration_resolution
Revises: 0024_agent_loop_evidence_foundation
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0025_agent_migration_resolution"
down_revision: str | Sequence[str] | None = "0024_agent_loop_evidence_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ai_agent_migration_blocks", sa.Column("resolution_summary_json", sa.JSON(), nullable=True))
    op.add_column("ai_agent_migration_blocks", sa.Column("resolved_by", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_agent_migration_blocks_resolved_by_users",
        "ai_agent_migration_blocks",
        "users",
        ["resolved_by"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_agent_migration_blocks_resolved_by_users", "ai_agent_migration_blocks", type_="foreignkey")
    op.drop_column("ai_agent_migration_blocks", "resolved_by")
    op.drop_column("ai_agent_migration_blocks", "resolution_summary_json")
