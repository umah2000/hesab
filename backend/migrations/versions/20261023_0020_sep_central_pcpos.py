"""SEP central PC-POS: provider sep_central and the provider's id of each attempt

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-23 09:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CK = "ck_card_terminal_provider"


def upgrade() -> None:
    op.drop_constraint(op.f(CK), "card_terminal", type_="check")
    op.create_check_constraint(
        op.f(CK), "card_terminal", "provider IN ('sep','sep_central','mock')"
    )
    # The id the provider issued for the attempt (SEP: Identifier), kept before anything
    # is sent so an unanswered attempt can always be inquired.
    op.add_column(
        "terminal_transaction", sa.Column("provider_ref", sa.String(length=64), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("terminal_transaction", "provider_ref")
    # Kept as plain SEP readers (no driver in that version), so past attempts keep theirs.
    op.execute("UPDATE card_terminal SET provider = 'sep' WHERE provider = 'sep_central'")
    op.drop_constraint(op.f(CK), "card_terminal", type_="check")
    op.create_check_constraint(op.f(CK), "card_terminal", "provider IN ('sep','mock')")
