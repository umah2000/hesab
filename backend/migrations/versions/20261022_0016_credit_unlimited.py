"""unlimited credit for a customer

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-22 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "detail_account",
        sa.Column("credit_unlimited", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_detail_account_credit_unlimited"),
        "detail_account",
        "credit_unlimited = 0 OR (credit_limit IS NULL AND kind = 'person')",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_detail_account_credit_unlimited"), "detail_account", type_="check")
    op.drop_column("detail_account", "credit_unlimited", mssql_drop_default=True)
