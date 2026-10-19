"""encrypted backup copies

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-19 17:10:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_backup_log_kind"), "backup_log", type_="check")
    op.create_check_constraint(
        op.f("ck_backup_log_kind"), "backup_log", "kind IN ('backup','restore_test','copy')"
    )


def downgrade() -> None:
    op.execute("DELETE FROM backup_log WHERE kind = 'copy'")
    op.drop_constraint(op.f("ck_backup_log_kind"), "backup_log", type_="check")
    op.create_check_constraint(
        op.f("ck_backup_log_kind"), "backup_log", "kind IN ('backup','restore_test')"
    )
