"""SQLAlchemy 2.x declarative base, engine, session factory and request-scoped session.

Importing this module never connects to PostgreSQL; the engine is built on first use.
Nothing here creates, alters or drops tables: `Base.metadata.create_all()` and
`drop_all()` must never be called against the ConceptTrail database. Schema changes
go through reviewed Alembic migrations only.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import datetime
from decimal import Decimal
from functools import lru_cache

from sqlalchemy import BOOLEAN, INTEGER, NUMERIC, Engine, MetaData, String, create_engine
from sqlalchemy.dialects.postgresql import DOUBLE_PRECISION, TIMESTAMP, UUID
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import ConfigurationError, Settings, get_settings

DB_SCHEMA = "concepttrail"

# Reproduces PostgreSQL's default constraint names so ORM metadata matches the live
# database exactly. The only non-default name (`fk_note_approved_by`) is set explicitly
# in models.py; `idx_*` index names are always explicit.
NAMING_CONVENTION = {
    "pk": "%(table_name)s_pkey",
    "fk": "%(table_name)s_%(column_0_name)s_fkey",
    "uq": "%(table_name)s_%(column_0_name)s_key",
}

READ_ONLY_OPTIONS = "-c default_transaction_read_only=on"


class Base(DeclarativeBase):
    metadata = MetaData(schema=DB_SCHEMA, naming_convention=NAMING_CONVENTION)

    # Live column types: VARCHAR without length, NUMERIC without precision,
    # TIMESTAMPTZ, UUID and DOUBLE PRECISION. TEXT, SMALLINT, JSONB and VECTOR
    # columns declare their type explicitly in models.py.
    type_annotation_map = {
        str: String(),
        int: INTEGER(),
        bool: BOOLEAN(),
        float: DOUBLE_PRECISION(),
        Decimal: NUMERIC(),
        datetime: TIMESTAMP(timezone=True),
        uuid.UUID: UUID(as_uuid=True),
    }


def create_db_engine(settings: Settings | None = None, *, read_only: bool = False) -> Engine:
    """Build an engine from `DATABASE_URL` without opening a connection.

    `read_only=True` makes PostgreSQL reject every write in every transaction on the
    engine's connections; use it for introspection and schema comparison.
    """
    settings = settings or get_settings()
    if settings.db_schema != DB_SCHEMA:
        raise ConfigurationError(
            f"DB_SCHEMA must be '{DB_SCHEMA}' to match the ORM mappings in app/db/models.py"
        )
    connect_args: dict[str, object] = {
        "connect_timeout": settings.db_connect_timeout_seconds,
        "application_name": "concepttrail-readonly" if read_only else "concepttrail",
    }
    if read_only:
        connect_args["options"] = READ_ONLY_OPTIONS
    return create_engine(
        settings.database_url.get_secret_value(),
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout_seconds,
        # Keep bound values (answers, identifiers) out of exception text and logs.
        hide_parameters=True,
        connect_args=connect_args,
    )


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    return create_db_engine(get_settings())


@lru_cache(maxsize=1)
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """Request-scoped session dependency.

    Does not commit: the service that owns a unit of work calls `session.commit()`
    explicitly. An exception raised while the session is in use rolls back the open
    transaction; the session is always closed, which returns its connection to the pool.
    """
    session = get_sessionmaker()()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def dispose_engine() -> None:
    """Close pooled connections and reset the cached engine and session factory."""
    if get_engine.cache_info().currsize:
        get_engine().dispose()
    get_sessionmaker.cache_clear()
    get_engine.cache_clear()
