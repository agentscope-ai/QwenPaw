# -*- coding: utf-8 -*-
"""Validated storage settings without persisted database credentials."""

from __future__ import annotations

import os
import re
from pathlib import Path
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

_IDENTIFIER = re.compile(f"[a-z][a-z0-9_]*")


class PostgreSQLConfig(BaseModel):
    """Connection settings for one application-owned namespace."""

    model_config = ConfigDict(extra=f"forbid")
    dsn_env: str = f"QWENPAW_POSTGRES_DSN"
    schema_name: str = Field(default=f"qwenpaw", alias=f"schema")
    table_prefix: str = f""
    pool_min_size: int = Field(default=1, ge=0, le=100)
    pool_max_size: int = Field(default=10, ge=1, le=100)
    connect_timeout_seconds: float = Field(default=5, gt=0, le=300)
    acquire_timeout_seconds: float = Field(default=5, gt=0, le=300)
    statement_timeout_seconds: float = Field(default=15, gt=0, le=3600)

    @field_validator(f"schema_name", f"table_prefix")
    @classmethod
    def validate_identifier(cls, value: str, info) -> str:
        """Keep generated identifiers bounded and independent of SQL."""
        prefix = info.field_name == f"table_prefix"
        if prefix and not value:
            return value
        maximum = 16 if prefix else 40
        if len(value) > maximum or _IDENTIFIER.fullmatch(value) is None:
            raise ValueError(f"Invalid PostgreSQL {info.field_name}")
        return value

    @field_validator(f"pool_max_size")
    @classmethod
    def validate_pool_size(cls, value: int, info) -> int:
        """Reject a minimum larger than the pool capacity."""
        if value < info.data.get(f"pool_min_size", 1):
            raise ValueError(f"pool_max_size must be >= pool_min_size")
        return value

    def connection_string(self) -> str:
        """Resolve credentials only when opening a connection."""
        value = os.environ.get(self.dsn_env)
        if not value:
            raise ValueError(f"Missing database environment: {self.dsn_env}")
        return value


class SQLiteConfig(BaseModel):
    """Local authoritative state location, relative to the runtime root."""

    model_config = ConfigDict(extra=f"forbid")
    data_dir: str = f"state"
    busy_timeout_seconds: float = Field(default=5, gt=0, le=300)

    def database_path(self, root: Path) -> Path:
        """Resolve paths without platform-specific separators."""
        directory = Path(self.data_dir).expanduser()
        if not directory.is_absolute():
            directory = root / directory
        return directory / f"state.db"


class StorageBackend(StrEnum):
    """Supported database engines."""

    SQLITE = f"sqlite"
    POSTGRESQL = f"postgresql"


class StorageConfig(BaseModel):
    """Select a backend; activation is separate from editing settings."""

    model_config = ConfigDict(extra=f"forbid")
    backend: StorageBackend = StorageBackend.SQLITE
    deployment_id: str = f""
    postgresql: PostgreSQLConfig = Field(default_factory=PostgreSQLConfig)
    sqlite: SQLiteConfig = Field(default_factory=SQLiteConfig)
