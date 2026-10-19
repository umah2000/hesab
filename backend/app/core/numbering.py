"""Gap-free document numbers per (doc type, fiscal year, branch) — ADR-0005.

The counter row is locked for the rest of the caller's transaction, so two
concurrent finalisations serialise and a rolled-back one gives its number back.
"""

from __future__ import annotations

import uuid

from sqlalchemy import BigInteger, Index, String, insert, text
from sqlalchemy.dialects.mssql import UNIQUEIDENTIFIER
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.core.db import Base


class NumberSequence(Base):
    __tablename__ = "number_sequence"
    __table_args__ = (
        # branch_id NULL = organisation-wide counter (e.g. accounting vouchers).
        Index(
            "uq_number_sequence_key",
            "doc_type",
            "fiscal_year_id",
            "branch_id",
            unique=True,
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4)
    doc_type: Mapped[str] = mapped_column(String(32))
    fiscal_year_id: Mapped[uuid.UUID] = mapped_column(UNIQUEIDENTIFIER)
    branch_id: Mapped[uuid.UUID | None] = mapped_column(UNIQUEIDENTIFIER)
    next_value: Mapped[int] = mapped_column(BigInteger)


# Equality on every key column (no "OR" on the nullable branch), so SQL Server seeks the
# unique index and locks only that key — no key-range locks held for the transaction.
_WHERE = "doc_type = :doc_type AND fiscal_year_id = :fy AND branch_id {}"
_NEXT_WHERE = "n.doc_type = :doc_type AND n.fiscal_year_id = :fy AND n.branch_id {}"
_NEXT_SQL = (
    # INDEX hint (FROM clause): on a small table the optimizer prefers a scan, and a scan
    # under HOLDLOCK range-locks every row it passes — two finalisations then deadlocked.
    "UPDATE n SET next_value = n.next_value + 1 OUTPUT deleted.next_value "
    "FROM number_sequence n WITH (UPDLOCK, HOLDLOCK, INDEX(uq_number_sequence_key)) WHERE "
)
_EXISTS_SQL = "SELECT 1 FROM number_sequence WHERE "


def _where(branch_id: uuid.UUID | None) -> str:
    return _WHERE.format("IS NULL" if branch_id is None else "= :branch")


# Counters are created ahead of time (new fiscal year, new branch, seed-defaults), outside
# any sale, so registers only ever UPDATE an existing row. Creating a first counter inside
# concurrent business transactions deadlocked on key-range locks.
ORG_COUNTERS = ("voucher",)
BRANCH_COUNTERS = (
    "stock",
    "sales",
    "sales_return",
    "purchase",
    "purchase_return",
    "purchase_order",
    "sales_order",
)


def ensure_counters(
    s: Session, fiscal_year_ids: list[uuid.UUID], branch_ids: list[uuid.UUID]
) -> None:
    keys: list[tuple[str, uuid.UUID, uuid.UUID | None]] = [
        (d, fy, None) for fy in fiscal_year_ids for d in ORG_COUNTERS
    ] + [(d, fy, b) for fy in fiscal_year_ids for b in branch_ids for d in BRANCH_COUNTERS]
    for doc_type, fy, branch in keys:
        params = {"doc_type": doc_type, "fy": fy, "branch": branch}
        if s.execute(text(_EXISTS_SQL + _where(branch)), params).first() is None:
            s.execute(
                insert(NumberSequence).values(
                    id=uuid.uuid4(),
                    doc_type=doc_type,
                    fiscal_year_id=fy,
                    branch_id=branch,
                    next_value=1,
                )
            )


def _ensure_counter(s: Session, params: dict[str, object]) -> None:
    """Fallback for a counter that was not created ahead of time (savepoint, in-transaction)."""
    if s.execute(text(_EXISTS_SQL + _where(params["branch"])), params).first() is not None:  # type: ignore[arg-type]
        return
    try:
        with s.begin_nested():
            s.execute(
                insert(NumberSequence).values(
                    id=uuid.uuid4(),
                    doc_type=params["doc_type"],
                    fiscal_year_id=params["fy"],
                    branch_id=params["branch"],
                    next_value=1,
                )
            )
    except IntegrityError:
        pass  # a concurrent transaction created it first


def next_number(
    s: Session, doc_type: str, fiscal_year_id: uuid.UUID, branch_id: uuid.UUID | None = None
) -> int:
    params: dict[str, object] = {"doc_type": doc_type, "fy": fiscal_year_id, "branch": branch_id}
    _ensure_counter(s, params)
    tail = _NEXT_WHERE.format("IS NULL" if branch_id is None else "= :branch")
    value = s.execute(text(_NEXT_SQL + tail), params).scalar()
    if value is None:
        raise RuntimeError("document number counter is missing")
    return int(value)
