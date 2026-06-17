"""create defect tables

Revision ID: 0018_defects
Revises: 0017_step_retry
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0018_defects"
down_revision: str | Sequence[str] | None = "0017_step_retry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "defects",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("assignee", sa.String(128), nullable=True),
        sa.Column("bug_type", sa.String(32), nullable=False),
        sa.Column("urgency", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("content_html", sa.Text(), nullable=False),
        sa.Column("reporter_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["reporter_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_defects_id", "defects", ["id"])
    op.create_index("ix_defects_project_id", "defects", ["project_id"])
    op.create_index(
        "ix_defects_project_status_updated",
        "defects",
        ["project_id", "status", "updated_at"],
    )
    op.create_index(
        "ix_defects_project_urgency_updated",
        "defects",
        ["project_id", "urgency", "updated_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_defects_project_urgency_updated", table_name="defects")
    op.drop_index("ix_defects_project_status_updated", table_name="defects")
    op.drop_index("ix_defects_project_id", table_name="defects")
    op.drop_index("ix_defects_id", table_name="defects")
    op.drop_table("defects")
