# -*- coding: utf-8 -*-
"""Fail-closed database settings without exposing connection credentials."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError

from ..constant import EnvVarLoader
from .mode import StorageMode


class DatabaseConfigurationError(RuntimeError):
    """A stable, credential-free database configuration failure."""

    def __init__(self, error_code: str, storage_mode: StorageMode) -> None:
        self.error_code = error_code
        self.storage_mode = storage_mode
        super().__init__(f"Database configuration is invalid ({error_code})")


@dataclass(frozen=True, slots=True)
class DatabaseSettings:
    """Resolved storage settings.

    The DSN is deliberately excluded from ``repr``.
    """

    multi_user_enabled: bool
    storage_mode: StorageMode
    dsn: str | None = field(repr=False)
    safe_database_target: str | None


def _normalize_postgres_url(raw_dsn: str) -> tuple[str, str]:
    try:
        url = make_url(raw_dsn)
    except ArgumentError as exc:
        raise DatabaseConfigurationError(
            "invalid_database_url",
            StorageMode.POSTGRES,
        ) from exc

    if url.get_backend_name() != "postgresql":
        raise DatabaseConfigurationError(
            "unsupported_database_driver",
            StorageMode.POSTGRES,
        )

    async_url: URL = url.set(drivername="postgresql+asyncpg")
    host = async_url.host or "localhost"
    port = f":{async_url.port}" if async_url.port is not None else ""
    database = f"/{async_url.database}" if async_url.database else ""
    return (
        async_url.render_as_string(hide_password=False),
        f"{host}{port}{database}",
    )


def load_database_settings() -> DatabaseSettings:
    """Resolve legacy/postgres mode and reject unsafe multi-user fallbacks."""
    multi_user_enabled = EnvVarLoader.get_bool(
        "QWENPAW_MULTI_USER_ENABLED", False
    )
    default_mode = "postgres" if multi_user_enabled else "legacy"
    raw_mode = EnvVarLoader.get_str("QWENPAW_STORAGE_MODE", default_mode)
    storage_mode = raw_mode.strip().lower()
    try:
        typed_mode = StorageMode(storage_mode)
    except ValueError as exc:
        raise DatabaseConfigurationError(
            "invalid_storage_mode",
            StorageMode.LEGACY,
        ) from exc
    raw_dsn = EnvVarLoader.get_str("QWENPAW_DATABASE_URL", "").strip()

    if multi_user_enabled and typed_mode is not StorageMode.POSTGRES:
        raise DatabaseConfigurationError(
            "postgres_storage_required",
            typed_mode,
        )
    if typed_mode is StorageMode.POSTGRES and not raw_dsn:
        raise DatabaseConfigurationError("database_url_required", typed_mode)
    if typed_mode is StorageMode.LEGACY:
        return DatabaseSettings(
            multi_user_enabled=multi_user_enabled,
            storage_mode=typed_mode,
            dsn=None,
            safe_database_target=None,
        )

    dsn, safe_target = _normalize_postgres_url(raw_dsn)
    return DatabaseSettings(
        multi_user_enabled=multi_user_enabled,
        storage_mode=typed_mode,
        dsn=dsn,
        safe_database_target=safe_target,
    )
