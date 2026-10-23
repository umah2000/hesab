"""Database engine, session handling and the declarative base."""

from __future__ import annotations

import uuid
from collections.abc import Collection, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, TypeVar

from flask import Flask, current_app
from sqlalchemy import DateTime, FetchedValue, MetaData, create_engine, event, func
from sqlalchemy.dialects.mssql import ROWVERSION, UNIQUEIDENTIFIER
from sqlalchemy.engine import Engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    ORMExecuteState,
    Session,
    declared_attr,
    mapped_column,
    sessionmaker,
)
from sqlalchemy.sql.selectable import Select

from app.core.config import Settings

# Deterministic constraint names keep Alembic migrations stable on SQL Server.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


@compiles(Select, "mssql")
def _mssql_row_lock(select: Select[Any], compiler: Any, **kw: Any) -> str:
    """``with_for_update()`` as a SQL Server table hint.

    SQLAlchemy's SQL Server dialect drops FOR UPDATE without a word, so without this
    every ``with_for_update`` (and ``Session.get(..., with_for_update=True)``) read the
    row without locking it. ``WITH (UPDLOCK, ROWLOCK)``: an update lock held to the end
    of the transaction, reading the latest committed row also under RCSI;
    ``skip_locked`` adds READPAST, ``nowait`` NOWAIT. Lock only by key (rule 22).
    """
    arg = select._for_update_arg
    if arg is not None:
        hint = ["HOLDLOCK" if arg.read else "UPDLOCK", "ROWLOCK"]
        if arg.skip_locked:
            hint.append("READPAST")
        if arg.nowait:
            hint.append("NOWAIT")
        for table in select.get_final_froms():
            select = select.with_hint(table, f"WITH ({', '.join(hint)})", "mssql")
    return str(compiler.visit_select(select, **kw))


@event.listens_for(Session, "do_orm_execute")
def _locked_reads_are_fresh(state: ORMExecuteState) -> None:
    """A locked read always refreshes the objects it returns.

    Without this, a row already in the session would keep the values read before the
    lock when another transaction changed it in between, and the lock would guard stale
    data. (A versioned row raises StaleDataError instead, answered as 409.)
    """
    stmt = state.statement
    if state.is_select and getattr(stmt, "_for_update_arg", None) is not None:
        state.update_execution_options(populate_existing=True)


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class EntityMixin:
    """Client-generatable UUID id + audit timestamps (ADR-0006)."""

    id: Mapped[uuid.UUID] = mapped_column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.sysutcdatetime(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.sysutcdatetime(),
        onupdate=utcnow,
        nullable=False,
    )


class ActorMixin:
    created_by: Mapped[uuid.UUID | None] = mapped_column(UNIQUEIDENTIFIER, nullable=True)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UNIQUEIDENTIFIER, nullable=True)


class VersionedMixin:
    """Optimistic concurrency via SQL Server ROWVERSION (ADR-0006).

    SQLAlchemy adds ``WHERE row_version = :old`` to every UPDATE and raises
    StaleDataError when another writer got there first.
    """

    row_version: Mapped[bytes] = mapped_column(
        ROWVERSION, nullable=False, server_default=FetchedValue(), server_onupdate=FetchedValue()
    )

    @declared_attr.directive
    def __mapper_args__(cls) -> dict[str, Any]:  # noqa: N805
        return {"version_id_col": cls.row_version, "version_id_generator": False}


def version_to_str(v: bytes) -> str:
    return v.hex()


def build_engine(settings: Settings) -> Engine:
    return create_engine(
        settings.database_url.get_secret_value(),
        pool_pre_ping=True,
        fast_executemany=True,
    )


def init_db(app: Flask, settings: Settings) -> None:
    engine = build_engine(settings)
    app.extensions["db_engine"] = engine
    app.extensions["db_sessionmaker"] = sessionmaker(bind=engine, expire_on_commit=False)


def new_session() -> Session:
    factory: sessionmaker[Session] = current_app.extensions["db_sessionmaker"]
    return factory()


@contextmanager
def unit_of_work() -> Iterator[Session]:
    """One transaction per business operation: commit on success, rollback on any error."""
    session = new_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# SQL Server accepts at most 2100 parameters per statement; an IN list over thousands of
# ids (a 5000-line opening stock, a year's sales by item) must be split.
IN_CHUNK = 1000
M = TypeVar("M")


def load_by_ids(s: Any, model: type[M], ids: Collection[uuid.UUID]) -> dict[uuid.UUID, M]:
    """``{id: row}`` for these ids, in chunks below the parameter limit."""
    from sqlalchemy import select

    out: dict[uuid.UUID, M] = {}
    pending = list(set(ids))
    col = model.id  # type: ignore[attr-defined]
    for i in range(0, len(pending), IN_CHUNK):
        for row in list(s.scalars(select(model).where(col.in_(pending[i : i + IN_CHUNK])))):
            out[row.id] = row
    return out


def load_columns_by_ids(
    s: Any, id_col: Any, cols: list[Any], ids: Collection[uuid.UUID]
) -> dict[uuid.UUID, Any]:
    """``{id: Row(*cols)}`` for these ids, chunked. Plain columns, so no relationship is
    loaded (whole ORM rows pulled every barcode and unit of 12k items in a report)."""
    from sqlalchemy import select

    out: dict[uuid.UUID, Any] = {}
    pending = list(set(ids))
    for i in range(0, len(pending), IN_CHUNK):
        q = select(id_col, *cols).where(id_col.in_(pending[i : i + IN_CHUNK]))
        for row in list(s.execute(q)):
            out[row[0]] = row
    return out
