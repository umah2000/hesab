from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.dialects import mssql

import app.models  # noqa: F401  (registers all tables)
from app.core.config import get_settings
from app.core.db import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _compare_type(ctx, inspected_col, metadata_col, inspected_type, metadata_type):  # type: ignore[no-untyped-def]
    # SQL Server reflects ROWVERSION as its legacy synonym TIMESTAMP.
    if isinstance(metadata_type, mssql.ROWVERSION) and isinstance(inspected_type, mssql.TIMESTAMP):
        return False
    return None  # default comparison


def _url() -> str:
    override = config.attributes.get("database_url")
    return override or get_settings().database_url.get_secret_value()


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_url())
    with engine.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata, compare_type=_compare_type
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
