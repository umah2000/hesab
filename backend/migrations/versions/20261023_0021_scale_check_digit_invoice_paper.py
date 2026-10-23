"""scale labels without check digit; default invoice paper

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-23 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # False: the scale prints 12 digits without the EAN-13 check digit (the shop's
    # scale, 1405/08/02). Existing rules keep the check digit.
    op.add_column(
        "scale_barcode_rule",
        sa.Column("check_digit", sa.Boolean(), server_default=sa.true(), nullable=False),
    )
    # Where invoices are printed by default: the 80 mm roll, or A5 / A4 paper.
    op.add_column(
        "organization",
        sa.Column("invoice_paper", sa.String(length=8), server_default="thermal", nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_organization_invoice_paper"),
        "organization",
        "invoice_paper IN ('thermal','a5','a4')",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_organization_invoice_paper"), "organization", type_="check")
    op.drop_column("organization", "invoice_paper", mssql_drop_default=True)
    op.drop_column("scale_barcode_rule", "check_digit", mssql_drop_default=True)
