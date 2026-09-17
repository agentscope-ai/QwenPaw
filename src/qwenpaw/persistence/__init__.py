# -*- coding: utf-8 -*-
"""PostgreSQL persistence primitives introduced behind the legacy boundary."""

from .database import DatabaseHealth, check_database, database_session
from .mode import StorageMode
from .repository_provider import (
    ALL_CUTOVER_DOMAINS,
    CutoverDomain,
    CutoverPolicy,
    MigrationState,
    RepositoryProvider,
    RepositorySelectionError,
    load_cutover_policy,
    read_migration_state,
    validate_runtime_cutover,
)
from .settings import DatabaseConfigurationError, DatabaseSettings

__all__ = [
    "ALL_CUTOVER_DOMAINS",
    "CutoverDomain",
    "CutoverPolicy",
    "DatabaseConfigurationError",
    "DatabaseHealth",
    "DatabaseSettings",
    "MigrationState",
    "RepositoryProvider",
    "RepositorySelectionError",
    "StorageMode",
    "check_database",
    "database_session",
    "load_cutover_policy",
    "read_migration_state",
    "validate_runtime_cutover",
]
