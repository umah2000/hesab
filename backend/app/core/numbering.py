"""Gap-free document numbers per (doc type, fiscal year, branch) — ADR-0005.

The counter row is locked for the rest of the caller's transaction, so two
concurrent finalisations serialise and a rolled-back one gives its number back.
"""

from __future__ import annotations

import uuid

from sqlalchemy import BigInteger, Index, String, text
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


_NEXT = text(
    """
    UPDATE number_sequence WITH (UPDLOCK, HOLDLOCK)
    SET next_value = next_value + 1
    OUTPUT deleted.next_value
    WHERE doc_type = :doc_type AND fiscal_year_id = :fy
      AND ((:branch IS NULL AND branch_id IS NULL) OR branch_id = :branch)
    """
)


def next_number(
    s: Session, doc_type: str, fiscal_year_id: uuid.UUID, branch_id: uuid.UUID | None = None
) -> int:
    params = {"doc_type": doc_type, "fy": fiscal_year_id, "branch": branch_id}
    for _ in range(2):
        value = s.execute(_NEXT, params).scalar()
        if value is not None:
            return int(value)
        try:
            with s.begin_nested():
                s.add(
                    NumberSequence(
                        doc_type=doc_type,
                        fiscal_year_id=fiscal_year_id,
                        branch_id=branch_id,
                        next_value=2,
                    )
                )
            return 1
        except IntegrityError:
            continue  # a concurrent transaction created the counter first; use it
    raise RuntimeError("could not allocate document number")
