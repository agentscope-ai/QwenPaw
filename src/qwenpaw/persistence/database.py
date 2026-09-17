# -*- coding: utf-8 -*-
"""Lazy SQLAlchemy async engine, transaction boundary and safe health probe."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .mode import StorageMode
from .settings import (
    DatabaseConfigurationError,
    DatabaseSettings,
    load_database_settings,
)


@dataclass(frozen=True, slots=True)
class DatabaseHealth:
    connected: bool
    schema_version: str | None
    storage_mode: StorageMode
    error_code: str | None


class DatabaseUnavailableError(RuntimeError):
    """Raised when database-only code is reached outside postgres mode."""


_engine: AsyncEngine | None = None
_engine_dsn: str | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _get_engine(settings: DatabaseSettings) -> AsyncEngine:
    global _engine, _engine_dsn, _session_factory

    if settings.dsn is None:
        raise DatabaseUnavailableError("PostgreSQL storage is not configured")
    if _engine is None:
        _engine = create_async_engine(
            settings.dsn,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
            pool_timeout=10,
            connect_args={"timeout": 10},
            hide_parameters=True,
        )
        _engine_dsn = settings.dsn
        _session_factory = async_sessionmaker(
            _engine,
            expire_on_commit=False,
        )
    elif _engine_dsn != settings.dsn:
        raise DatabaseConfigurationError(
            "database_url_changed",
            StorageMode.POSTGRES,
        )
    return _engine


def _get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory

    settings = load_database_settings()
    _get_engine(settings)
    if _session_factory is None:  # pragma: no cover - guarded by _get_engine
        raise DatabaseUnavailableError(
            "PostgreSQL session factory is unavailable"
        )
    return _session_factory


@asynccontextmanager
async def database_session() -> AsyncIterator[AsyncSession]:
    """Provide one AsyncSession and commit/rollback at the context boundary."""
    from ..platform_ops.maintenance import operation

    async with operation():
        factory = _get_session_factory()
        async with factory.begin() as session:
            yield session


async def set_request_user(session: AsyncSession, user_id: UUID) -> None:
    """在当前事务内设置 RLS 使用的可信用户身份。"""
    await session.execute(
        text("SELECT set_config('qwenpaw.user_id', :user_id, true)"),
        {"user_id": str(user_id)},
    )


async def check_database() -> DatabaseHealth:
    """Return a stable health result without propagating connection details."""
    try:
        settings = load_database_settings()
    except DatabaseConfigurationError as exc:
        return DatabaseHealth(
            connected=False,
            schema_version=None,
            storage_mode=exc.storage_mode,
            error_code=exc.error_code,
        )

    if StorageMode(settings.storage_mode) is StorageMode.LEGACY:
        return DatabaseHealth(
            connected=False,
            schema_version=None,
            storage_mode=StorageMode.LEGACY,
            error_code=None,
        )

    try:
        engine = _get_engine(settings)
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except (
        Exception
    ):  # noqa: BLE001 - external driver errors must be sanitized
        return DatabaseHealth(
            connected=False,
            schema_version=None,
            storage_mode=StorageMode.POSTGRES,
            error_code="connection_failed",
        )

    return DatabaseHealth(
        connected=True,
        schema_version=None,
        storage_mode=StorageMode.POSTGRES,
        error_code=None,
    )
