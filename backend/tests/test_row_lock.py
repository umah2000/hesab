"""Row locks on SQL Server (app.core.db): FOR UPDATE becomes a hint, locked reads are fresh."""

from __future__ import annotations

import uuid

import pytest
from flask import Flask
from sqlalchemy import select
from sqlalchemy.dialects.mssql import pyodbc

from app.core.db import new_session, unit_of_work
from app.modules.organization.models import Branch, CashRegister
from app.modules.sales.models import TerminalTransaction
from tests.conftest import Seed


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


def test_lock_options() -> None:
    q = select(CashRegister.id)
    assert "WITH (UPDLOCK, ROWLOCK, READPAST)" in sql(q.with_for_update(skip_locked=True))
    assert "WITH (UPDLOCK, ROWLOCK, NOWAIT)" in sql(q.with_for_update(nowait=True))
    assert "WITH (HOLDLOCK, ROWLOCK)" in sql(q.with_for_update(read=True))


def test_a_locked_read_sees_the_latest_row(app: Flask, seed: Seed) -> None:
    """A row already in the session is refreshed by the locked read; a versioned row
    changed in between is a conflict (StaleDataError, answered 409), never stale."""
    from sqlalchemy.orm.exc import StaleDataError

    from app.core.db import utcnow
    from app.modules.iam.models import MobileSession

    with app.app_context():
        with unit_of_work() as s:
            m = MobileSession(user_id=seed.admin_id, last_seen_at=utcnow(), expires_at=utcnow())
            s.add(m)
            s.flush()
            mid = m.id
        a = new_session()
        try:
            mine = a.get(MobileSession, mid)
            branch = a.get(Branch, seed.branch_a)
            assert mine is not None and branch is not None and mine.revoked_at is None
            with unit_of_work() as b:
                other = b.get(MobileSession, mid)
                assert other is not None
                other.revoked_at, other.revoke_reason = utcnow(), "logout"
                ob = b.get(Branch, seed.branch_a)
                assert ob is not None
                ob.address = "تغییر هم‌زمان"
            locked = a.get(MobileSession, mid, with_for_update=True)
            assert locked is mine and locked.revoked_at is not None
            assert locked.revoke_reason == "logout"
            with pytest.raises(StaleDataError):
                a.get(Branch, seed.branch_a, with_for_update=True)
        finally:
            a.rollback()
            a.close()
