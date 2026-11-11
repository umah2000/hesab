"""Document numbers lock only their own counter (ADR-0031): a sale's counter and the
voucher counter never hold range locks on their neighbours, which deadlocked a sale
against a shift close."""

from __future__ import annotations

import pytest
from flask import Flask
from sqlalchemy import text

from app.core.db import new_session
from app.core.numbering import next_number
from tests.test_sales import Pos, pos  # noqa: F401 - fixture

pytestmark = pytest.mark.db


def test_next_number_locks_only_its_own_counter(app: Flask, pos: Pos) -> None:  # noqa: F811
    with app.app_context():
        s = new_session()
        try:
            fy, branch = s.execute(
                text(
                    "SELECT TOP 1 fiscal_year_id, branch_id FROM number_sequence "
                    "WHERE doc_type = 'sales' AND branch_id IS NOT NULL"
                )
            ).one()
            s.rollback()
            for doc_type, b in (("sales", branch), ("voucher", None)):
                first = next_number(s, doc_type, fy, b)
                assert next_number(s, doc_type, fy, b) == first + 1
                modes = {
                    m
                    for (m,) in s.execute(
                        text(
                            "SELECT request_mode FROM sys.dm_tran_locks "
                            "WHERE request_session_id = @@SPID AND resource_type = 'KEY'"
                        )
                    )
                }
                assert not any(m.startswith("Range") for m in modes), (doc_type, modes)
                s.rollback()
        finally:
            s.close()
