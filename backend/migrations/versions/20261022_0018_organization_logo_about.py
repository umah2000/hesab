"""organization logo and about

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-22 15:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNS = ("about", "phone", "address", "website", "logo", "logo_sha256")


def upgrade() -> None:
    op.add_column("organization", sa.Column("about", sa.Unicode(length=2000), nullable=True))
    op.add_column("organization", sa.Column("phone", sa.String(length=40), nullable=True))
    op.add_column("organization", sa.Column("address", sa.Unicode(length=300), nullable=True))
    op.add_column("organization", sa.Column("website", sa.String(length=200), nullable=True))
    op.add_column("organization", sa.Column("logo", sa.LargeBinary(), nullable=True))
    op.add_column("organization", sa.Column("logo_sha256", sa.String(length=64), nullable=True))


def downgrade() -> None:
    for name in reversed(COLUMNS):
        op.drop_column("organization", name)
