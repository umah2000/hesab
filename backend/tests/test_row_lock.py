"""SQLAlchemy's SQL Server dialect drops FOR UPDATE; app.core.db turns it into a hint."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.dialects.mssql import pyodbc

import app.core.db  # noqa: F401  (registers the compile hook)
from app.modules.organization.models import CashRegister
from app.modules.sales.models import TerminalTransaction


def sql(stmt: object) -> str:
    return str(stmt.compile(dialect=pyodbc.dialect()))  # type: ignore[attr-defined]


def test_with_for_update_locks_the_row_on_sql_server() -> None:
    locked = select(CashRegister.id).where(CashRegister.id == uuid.uuid4()).with_for_update()
    assert "FROM cash_register WITH (UPDLOCK, ROWLOCK)" in sql(locked)
    # What Session.get(..., with_for_update=True) builds.
    stmt = select(TerminalTransaction)
    stmt._for_update_arg = locked._for_update_arg
    assert "FROM terminal_transaction WITH (UPDLOCK, ROWLOCK)" in sql(stmt)
    assert "UPDLOCK" not in sql(select(CashRegister.id))
