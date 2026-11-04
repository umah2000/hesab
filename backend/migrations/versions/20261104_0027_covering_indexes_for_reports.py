"""covering indexes for reports and the ledger (ADR-0031)

Each one was measured on the volume database (14k items, 64k invoices, 425k stock
movements, 325k voucher lines) before and after; see docs/testing/volume-test.md.

- sales_invoice (status, document_date): dashboard and period sales reports seek the
  final invoices of a period instead of scanning every invoice.
- sales_payment (invoice_id) INCLUDE (method, amount): the dashboard's payment mix read
  every payment row through key lookups (188k reads per run).
- voucher_line (account_id, voucher_id) / (detail_account_id) INCLUDE the amounts: the
  ledger and trial balance no longer look up each line.
- stock_ledger (warehouse_id, document_date) INCLUDE quantities and values: stock movement.
- sales_invoice_line (invoice_id) INCLUDE the measures: the lines of a period's invoices
  are sought instead of scanning every line (a busy day's dashboard 643 -> 192 ms).

The three widened indexes are rebuilt in place (DROP_EXISTING), so the table is never
without them. Cost on writes was measured with 16 registers at full speed: within noise
(3.66 vs 3.77 invoices/s without/with the new indexes, 3.77 with the line index too).

Revision ID: 0027
Revises: 0026
Create Date: 2026-11-04 18:30:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX ix_sales_invoice_status_date ON sales_invoice (status, document_date) "
        "INCLUDE (kind, branch_id, cash_register_id, created_by, customer_id, shift_id)"
    )
    op.execute(
        "CREATE INDEX ix_stock_ledger_wh_date ON stock_ledger (warehouse_id, document_date) "
        "INCLUDE (item_id, qty_in, qty_out, value_in, value_out)"
    )
    op.execute(
        "CREATE INDEX ix_sales_invoice_line_measures ON sales_invoice_line (invoice_id) "
        "INCLUDE (item_id, base_qty, promotion_discount, manual_discount, revenue, tax, "
        "line_total, cost_total)"
    )
    op.execute(
        "CREATE INDEX ix_sales_payment_invoice ON sales_payment (invoice_id) "
        "INCLUDE (method, amount) WITH (DROP_EXISTING = ON)"
    )
    op.execute(
        "CREATE INDEX ix_voucher_line_account ON voucher_line (account_id, voucher_id) "
        "INCLUDE (detail_account_id, debit, credit) WITH (DROP_EXISTING = ON)"
    )
    op.execute(
        "CREATE INDEX ix_voucher_line_detail ON voucher_line (detail_account_id) "
        "INCLUDE (voucher_id, account_id, debit, credit) WITH (DROP_EXISTING = ON)"
    )


def downgrade() -> None:
    op.execute(
        "CREATE INDEX ix_voucher_line_detail ON voucher_line (detail_account_id) "
        "WITH (DROP_EXISTING = ON)"
    )
    op.execute(
        "CREATE INDEX ix_voucher_line_account ON voucher_line (account_id, voucher_id) "
        "WITH (DROP_EXISTING = ON)"
    )
    op.execute(
        "CREATE INDEX ix_sales_payment_invoice ON sales_payment (invoice_id) "
        "WITH (DROP_EXISTING = ON)"
    )
    op.drop_index("ix_sales_invoice_line_measures", table_name="sales_invoice_line")
    op.drop_index("ix_stock_ledger_wh_date", table_name="stock_ledger")
    op.drop_index("ix_sales_invoice_status_date", table_name="sales_invoice")
