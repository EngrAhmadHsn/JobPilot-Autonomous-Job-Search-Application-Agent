"""Alembic migration environment for the Agentic Job Application Agent.

The database URL is never stored in ``alembic.ini``. It is resolved here, for
both online and offline modes, as::

    ALEMBIC_DATABASE_URL (env var override, used by tests/CI/one-off targets)
    -> settings.database_url (src.config.settings, from DATABASE_URL / .env)

Migration policy (per workstream — see docs/implementation/01-data-foundation.md):
each later workstream adds its *own* revision(s) instead of one big-bang schema,
so reviews stay small and rollback is per feature:

- WS-04: candidate_profiles, job_matches
- WS-05: tailored_resumes
- WS-06: approval_requests, audit_events
- WS-07: applications, application_events

The initial revision (this directory, "initial schema") covers exactly the
tables the current models define: ``jobs`` (src.db.jobs) and
``application_evidence`` (src.db.evidence). Model modules must be imported
below so autogenerate sees every table registered on ``Base.metadata``.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from src.config.settings import get_settings

# Import model modules so they register on Base.metadata before autogenerate.
# New model modules added by later workstreams must be imported here too.
from src.auth.tokens import AccessTokenDB  # noqa: F401  (registers the model)
from src.db import (  # noqa: F401
    applications,
    approval,
    audit,
    evidence,
    jobs,
    matches,
    profiles,
    tailored,
    users,
)
from src.db.base import Base
from src.db.session import ensure_sqlite_parent_dir

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# disable_existing_loggers=False: the default (True) permanently disables
# every logger created before an in-process alembic call, which breaks
# logging for the rest of the process (e.g. the test suite running alembic
# then asserting on application log records).
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# Model metadata used by 'autogenerate'.
target_metadata = Base.metadata


def _database_url() -> str:
    """Resolve the target database URL (env override first, then settings)."""
    override = os.getenv("ALEMBIC_DATABASE_URL")
    if override:
        return override
    return get_settings().database_url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    Configures the context with just a URL and not an Engine, so no DBAPI
    driver is required. Calls to context.execute() emit the given string to
    the script output.
    """
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    Creates an Engine from the resolved URL and associates a connection
    with the context.
    """
    url = _database_url()
    # SQLite creates files but not parent directories (e.g. ./data for the
    # default sqlite:///./data/app.db); make sure the target dir exists.
    ensure_sqlite_parent_dir(url)
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = url
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
