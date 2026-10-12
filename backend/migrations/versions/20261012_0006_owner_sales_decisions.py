"""owner sales decisions: VAT-exclusive shelf prices, no cashier discount

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-12

Owner decisions (1405/07/20): shelf prices exclude VAT, and cashiers give no manual
discount (only promotions); a supervisor can still approve one on the register.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("UPDATE organization SET prices_include_vat = 0, cashier_discount_limit = 0")
    op.execute(
        "DELETE rp FROM role_permission rp JOIN role r ON r.id = rp.role_id "
        "WHERE r.code = 'CSH' AND r.is_system = 1 AND rp.permission_code = 'sales.invoice.discount'"
    )


def downgrade() -> None:
    op.execute("UPDATE organization SET prices_include_vat = 1, cashier_discount_limit = 5")
    op.execute(
        "INSERT INTO role_permission (role_id, permission_code) "
        "SELECT r.id, 'sales.invoice.discount' FROM role r "
        "WHERE r.code = 'CSH' AND r.is_system = 1 AND NOT EXISTS (SELECT 1 FROM role_permission rp "
        "WHERE rp.role_id = r.id AND rp.permission_code = 'sales.invoice.discount')"
    )
