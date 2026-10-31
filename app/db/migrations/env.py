"""Alembic environment for the ConceptTrail `concepttrail` schema.

- Database URL: validated application settings (root `.env`, overridden by the
  `DATABASE_URL` process environment variable). Never read from alembic.ini, never
  logged; only host, port and database name are reported.
- Metadata: `app.db.session.Base.metadata` with the 26 mappings from `app.db.models`.
- Version table: `public.alembic_version` (see `app/db/migration_settings.py`).
- Reflection is limited to the `concepttrail` schema, so pgvector objects and Alembic's
  own table in `public` are never compared with the application metadata.

Read app/db/migrations/README.md before running any command against a real database.
"""

from __future__ import annotations

import logging
from logging.config import fileConfig

from alembic import context
from alembic.migration import MigrationContext
from alembic.operations import ops
from sqlalchemy import create_engine, pool
from sqlalchemy.engine import make_url

from app.core.config import ConfigurationError, load_settings
from app.db import models  # noqa: F401  (registers the 26 mapped tables)
from app.db.migration_settings import context_options
from app.db.session import DB_SCHEMA, Base

config = context.config

# Callers (for example the test suite) can set attributes["configure_logger"] = False
# to keep their own logging configuration.
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

logger = logging.getLogger("alembic.env")
target_metadata = Base.metadata


def _settings_url() -> tuple[str, int]:
    settings = load_settings()
    if settings.db_schema != DB_SCHEMA:
        raise ConfigurationError(
            f"DB_SCHEMA must be '{DB_SCHEMA}' to match app/db/models.py and the migrations"
        )
    return settings.database_url.get_secret_value(), settings.db_connect_timeout_seconds


def _skip_empty_autogenerate(
    context_: MigrationContext, revision: object, directives: list[ops.MigrationScript]
) -> None:
    """Do not write a revision file when autogenerate finds no schema changes."""
    if getattr(config.cmd_opts, "autogenerate", False) and directives:
        script = directives[0]
        if isinstance(script, ops.MigrationScript) and script.upgrade_ops.is_empty():
            directives[:] = []
            logger.info("No schema changes detected; no revision file written.")


def run_migrations_offline() -> None:
    """Emit SQL to stdout (`--sql`). The URL selects the dialect only; nothing connects."""
    url, _ = _settings_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        **context_options(),
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    url, connect_timeout = _settings_url()
    target = make_url(url)
    logger.info("Target database: %s:%s/%s", target.host, target.port or 5432, target.database)
    engine = create_engine(
        url,
        poolclass=pool.NullPool,
        hide_parameters=True,
        connect_args={
            "application_name": "concepttrail-alembic",
            "connect_timeout": connect_timeout,
        },
    )
    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                process_revision_directives=_skip_empty_autogenerate,
                **context_options(),
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
