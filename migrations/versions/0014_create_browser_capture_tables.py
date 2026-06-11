"""create browser capture tables

Revision ID: 0014_browser_captures
Revises: 0013_plan_hardening
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0014_browser_captures"
down_revision: str | Sequence[str] | None = "0013_plan_hardening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "browser_captures",
        sa.Column("id", sa.Integer(), nullable=False), sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("environment_id", sa.Integer(), nullable=False), sa.Column("name", sa.String(128), nullable=False),
        sa.Column("source_url", sa.String(1024), nullable=True), sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_by_id", sa.Integer(), nullable=False), sa.Column("is_deleted", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]), sa.ForeignKeyConstraint(["environment_id"], ["project_environments.id"]),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]), sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_browser_captures_id", "browser_captures", ["id"])
    op.create_index("ix_browser_captures_project_id", "browser_captures", ["project_id"])
    op.create_index("ix_browser_captures_project_updated", "browser_captures", ["project_id", "updated_at"])
    op.create_table(
        "browser_capture_entries",
        sa.Column("id", sa.Integer(), nullable=False), sa.Column("capture_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False), sa.Column("client_entry_id", sa.String(64), nullable=False),
        sa.Column("protocol", sa.String(16), nullable=False), sa.Column("fingerprint", sa.String(128), nullable=False),
        sa.Column("name", sa.String(256), nullable=False), sa.Column("method", sa.String(16), nullable=False),
        sa.Column("path", sa.String(1024), nullable=False), sa.Column("source_url", sa.String(2048), nullable=False),
        sa.Column("request_data", sa.JSON(), nullable=False), sa.Column("response_data", sa.JSON(), nullable=True),
        sa.Column("draft_data", sa.JSON(), nullable=False), sa.Column("status", sa.String(32), nullable=False),
        sa.Column("ai_analysis", sa.JSON(), nullable=True), sa.Column("import_result", sa.JSON(), nullable=True),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["capture_id"], ["browser_captures.id"]), sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("capture_id", "client_entry_id", name="uq_browser_capture_entries_client"),
    )
    op.create_index("ix_browser_capture_entries_id", "browser_capture_entries", ["id"])
    op.create_index("ix_browser_capture_entries_capture_id", "browser_capture_entries", ["capture_id"])
    op.create_index("ix_browser_capture_entries_project_id", "browser_capture_entries", ["project_id"])
    op.create_index("ix_browser_capture_entries_capture_status", "browser_capture_entries", ["capture_id", "status"])
    op.create_index("ix_browser_capture_entries_project_created", "browser_capture_entries", ["project_id", "created_at"])


def downgrade() -> None:
    op.drop_table("browser_capture_entries")
    op.drop_table("browser_captures")
