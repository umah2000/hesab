"""Database engine, session handling and the declarative base."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from flask import Flask, current_app
from sqlalchemy import DateTime, MetaData, create_engine, func
from sqlalchemy.dialects.mssql import UNIQUEIDENTIFIER
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.core.config import Settings

# Deterministic constraint names keep Alembic migrations stable on SQL Server.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


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
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )


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


@contextmanager
def unit_of_work() -> Iterator[Session]:
    """One transaction per business operation: commit on success, rollback on any error."""
    factory: sessionmaker[Session] = current_app.extensions["db_sessionmaker"]
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
