"""create media objects

Revision ID: 0019_media_objects
Revises: 0018_defects
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0019_media_objects"
down_revision: str | Sequence[str] | None = "0018_defects"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "media_objects",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("defect_id", sa.Integer(), nullable=True),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("bucket", sa.String(128), nullable=False),
        sa.Column("object_key", sa.String(512), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("etag", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["defect_id"], ["defects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("object_key"),
    )
    op.create_index("ix_media_objects_id", "media_objects", ["id"])
    op.create_index("ix_media_objects_project_id", "media_objects", ["project_id"])
    op.create_index("ix_media_objects_defect_id", "media_objects", ["defect_id"])
    op.create_index("ix_media_objects_owner_id", "media_objects", ["owner_id"])
    op.create_index("ix_media_objects_project_defect", "media_objects", ["project_id", "defect_id"])
    op.create_index("ix_media_objects_owner_created", "media_objects", ["owner_id", "created_at"])


def downgrade() -> None:
    op.drop_table("media_objects")
