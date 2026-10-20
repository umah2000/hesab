"""license

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-19 18:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mssql

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "license",
        sa.Column("license_id", mssql.UNIQUEIDENTIFIER(), nullable=False),
        sa.Column("text", sa.UnicodeText(), nullable=False),
        sa.Column("status", sa.String(length=8), nullable=False),
        sa.Column("installed_by", mssql.UNIQUEIDENTIFIER(), nullable=True),
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
        sa.CheckConstraint("status IN ('active','replaced')", name=op.f("ck_license_status")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_license")),
        sa.UniqueConstraint("license_id", name=op.f("uq_license_license_id")),
    )


def downgrade() -> None:
    op.drop_table("license")
