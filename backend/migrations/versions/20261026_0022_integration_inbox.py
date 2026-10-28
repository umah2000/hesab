"""weighbridge platform integration: received documents and events (ADR-0025)

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-26 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mssql

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _times() -> list[sa.Column]:
    return [
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
    ]


def upgrade() -> None:
    op.create_table(
        "integration_document",
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("source_kind", sa.String(length=24), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("number", sa.Unicode(length=32), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=True),
        sa.Column("counterparty_code", sa.Unicode(length=48), nullable=True),
        sa.Column("counterparty_name", sa.Unicode(length=200), nullable=True),
        sa.Column("document_date", sa.Date(), nullable=True),
        sa.Column("total", sa.Numeric(precision=19, scale=4), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("problem", sa.Unicode(length=500), nullable=True),
        sa.Column("payload", sa.UnicodeText(), nullable=True),
        sa.Column("voucher_id", mssql.UNIQUEIDENTIFIER(), nullable=True),
        sa.Column("reversal_voucher_id", mssql.UNIQUEIDENTIFIER(), nullable=True),
        sa.Column("void_reason", sa.Unicode(length=500), nullable=True),
        *_times(),
        sa.Column(
            "row_version", mssql.ROWVERSION(), server_default=sa.FetchedValue(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('posted','held','voided','reversed')",
            name=op.f("ck_integration_document_status"),
        ),
        sa.ForeignKeyConstraint(
            ["voucher_id"], ["voucher.id"], name=op.f("fk_integration_document_voucher_id_voucher")
        ),
        sa.ForeignKeyConstraint(
            ["reversal_voucher_id"],
            ["voucher.id"],
            name=op.f("fk_integration_document_reversal_voucher_id_voucher"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_integration_document")),
        sa.UniqueConstraint(
            "source",
            "source_kind",
            "source_id",
            name=op.f("uq_integration_document_source_source_kind_source_id"),
        ),
    )
    op.create_index(
        "ix_integration_document_status", "integration_document", ["status", "created_at"]
    )
    op.create_table(
        "integration_event",
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("document_id", mssql.UNIQUEIDENTIFIER(), nullable=True),
        sa.Column("result", sa.String(length=16), nullable=False),
        sa.Column("message", sa.Unicode(length=500), nullable=True),
        *_times(),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["integration_document.id"],
            name=op.f("fk_integration_event_document_id_integration_document"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_integration_event")),
        sa.UniqueConstraint(
            "source", "event_id", name=op.f("uq_integration_event_source_event_id")
        ),
    )
    op.create_index("ix_integration_event_received", "integration_event", ["created_at"])

    # New permission for existing installs (system roles keep custom edits on sync).
    op.execute(
        """
        IF NOT EXISTS (SELECT 1 FROM permission WHERE code = 'accounting.integration.manage')
            INSERT INTO permission (code, group_name, label)
            VALUES ('accounting.integration.manage', N'حسابداری',
                    N'رسیدگی به اسناد رسیده از سامانه باسکول');
        INSERT INTO role_permission (role_id, permission_code)
        SELECT r.id, 'accounting.integration.manage' FROM role r
        WHERE r.code = 'ACC' AND r.is_system = 1
          AND NOT EXISTS (SELECT 1 FROM role_permission rp
                          WHERE rp.role_id = r.id
                            AND rp.permission_code = 'accounting.integration.manage');
        """
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM role_permission WHERE permission_code = 'accounting.integration.manage'"
    )
    op.execute("DELETE FROM permission WHERE code = 'accounting.integration.manage'")
    op.drop_index("ix_integration_event_received", table_name="integration_event")
    op.drop_table("integration_event")
    op.drop_index("ix_integration_document_status", table_name="integration_document")
    op.drop_table("integration_document")
