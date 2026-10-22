"""card terminals: several card readers, chosen at payment

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-22 19:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mssql

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "card_terminal",
        sa.Column("name", sa.Unicode(length=100), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("host", sa.String(length=64), nullable=True),
        sa.Column("port", sa.Integer(), nullable=True),
        sa.Column("terminal_no", sa.String(length=16), nullable=True),
        sa.Column("branch_id", mssql.UNIQUEIDENTIFIER(), nullable=False),
        sa.Column("cash_register_id", mssql.UNIQUEIDENTIFIER(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("note", sa.Unicode(length=300), nullable=True),
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
        sa.Column(
            "row_version", mssql.ROWVERSION(), server_default=sa.FetchedValue(), nullable=False
        ),
        sa.CheckConstraint(
            "port IS NULL OR (port BETWEEN 1 AND 65535)", name=op.f("ck_card_terminal_port")
        ),
        sa.CheckConstraint("provider IN ('sep','mock')", name=op.f("ck_card_terminal_provider")),
        sa.ForeignKeyConstraint(
            ["branch_id"], ["branch.id"], name=op.f("fk_card_terminal_branch_id_branch")
        ),
        sa.ForeignKeyConstraint(
            ["cash_register_id"],
            ["cash_register.id"],
            name=op.f("fk_card_terminal_cash_register_id_cash_register"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_card_terminal")),
        sa.UniqueConstraint("name", name=op.f("uq_card_terminal_name")),
    )
    op.add_column(
        "terminal_transaction",
        sa.Column("terminal_id", mssql.UNIQUEIDENTIFIER(), nullable=True),
    )
    op.create_foreign_key(
        op.f("fk_terminal_transaction_terminal_id_card_terminal"),
        "terminal_transaction",
        "card_terminal",
        ["terminal_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_terminal_transaction_terminal_id_card_terminal"),
        "terminal_transaction",
        type_="foreignkey",
    )
    op.drop_column("terminal_transaction", "terminal_id")
    op.drop_table("card_terminal")
