# -*- coding: utf-8 -*-
"""Alembic environment for one explicitly selected PostgreSQL schema."""

from __future__ import annotations

import asyncio
import os
import re
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

_SAFE_SCHEMA = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


def _target_schema() -> str:
    schema = (
        str(
            config.attributes.get("target_schema")
            or os.environ.get("QWENPAW_DATABASE_SCHEMA", "qwenpaw")
        )
        .strip()
        .lower()
    )
    if not _SAFE_SCHEMA.fullmatch(schema):
        raise RuntimeError("invalid_database_schema")
    return schema


def _quote_identifier(identifier: str) -> str:
    if not _SAFE_SCHEMA.fullmatch(identifier):
        raise RuntimeError("invalid_database_schema")
    return f'"{identifier}"'


def _reject_unversioned_nonempty_schema(
    connection: Connection,
    schema: str,
) -> None:
    tables = set(
        connection.execute(
            text(
                "SELECT tablename FROM pg_tables " "WHERE schemaname = :schema"
            ),
            {"schema": schema},
        ).scalars()
    )
    if tables and "alembic_version" not in tables:
        raise RuntimeError("nonempty_unversioned_schema")


def _run_migrations(connection: Connection) -> None:
    schema = _target_schema()
    _reject_unversioned_nonempty_schema(connection, schema)
    connection.execute(text(f"SET search_path TO {_quote_identifier(schema)}"))
    # The preflight SELECT and SET start SQLAlchemy's implicit transaction.
    # Commit it so Alembic owns and commits the migration transaction.
    connection.commit()
    context.configure(
        connection=connection,
        target_metadata=None,
        version_table_schema=schema,
        include_schemas=True,
        compare_type=True,
        transaction_per_migration=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def _run_async_migrations() -> None:
    section = config.get_section(config.config_ini_section, {})
    connectable = async_engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    try:
        async with connectable.connect() as connection:
            await connection.run_sync(_run_migrations)
    finally:
        await connectable.dispose()


def run_migrations_offline() -> None:
    schema = _target_schema()
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=None,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table_schema=schema,
        include_schemas=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    asyncio.run(_run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
