"""item images

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-22 13:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mssql

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "item_image",
        sa.Column("item_id", mssql.UNIQUEIDENTIFIER(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("large", sa.LargeBinary(), nullable=False),
        sa.Column("thumb", sa.LargeBinary(), nullable=False),
        sa.Column("id", mssql.UNIQUEIDENTIFIER(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("sysutcdatetime()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("sysutcdatetime()"),
            nullable=False,
        ),
        sa.Column("created_by", mssql.UNIQUEIDENTIFIER(), nullable=True),
        sa.Column("updated_by", mssql.UNIQUEIDENTIFIER(), nullable=True),
        sa.CheckConstraint("position >= 0", name=op.f("ck_item_image_position")),
        sa.ForeignKeyConstraint(["item_id"], ["item.id"], name=op.f("fk_item_image_item_id_item")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_item_image")),
        sa.UniqueConstraint("item_id", "sha256", name=op.f("uq_item_image_item_id_sha256")),
    )
    op.create_index(op.f("ix_item_image_item_id"), "item_image", ["item_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_item_image_item_id"), table_name="item_image")
    op.drop_table("item_image")
