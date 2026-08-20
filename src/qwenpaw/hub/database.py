# -*- coding: utf-8 -*-
"""Stable SQLite schema and extension storage for QwenPaw Hub."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SCHEMA_GENERATION = "hub-v1"
_JSON_DEFAULT = '{"schema_version":1}'


def utc_now() -> str:
    """Return one sortable UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()


def connect_hub_database(database_path: Path) -> sqlite3.Connection:
    """Open a consistently configured Hub database connection."""
    connection = sqlite3.connect(database_path, timeout=5)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def initialize_hub_database(database_path: Path) -> None:
    """Create and validate the unpublished Hub schema generation."""
    database_path.parent.mkdir(parents=True, exist_ok=True)
    with connect_hub_database(database_path) as connection:
        connection.execute("PRAGMA journal_mode = WAL")
        existing = _existing_hub_tables(connection)
        if existing and not _is_current_generation(connection):
            raise RuntimeError(
                "Unsupported pre-release Hub database schema. Back up and "
                "recreate control.db for this PR build.",
            )
        _validate_existing_columns(connection)
        connection.executescript(_SCHEMA_SQL)
        connection.execute(
            "INSERT OR IGNORE INTO hub_schema(key, value) VALUES (?, ?)",
            ("schema_generation", _SCHEMA_GENERATION),
        )
        connection.execute(
            "INSERT OR IGNORE INTO hub_settings("
            "key, value_json, schema_version, revision, updated_at) "
            "VALUES (?, ?, 1, 1, ?)",
            ("registration_enabled", "false", utc_now()),
        )
        connection.execute(
            "INSERT OR IGNORE INTO hub_settings("
            "key, value_json, schema_version, revision, updated_at) "
            "VALUES (?, ?, 1, 1, ?)",
            ("registration_default_role", '"user"', utc_now()),
        )
        _validate_schema(connection)


def ensure_tenant(
    connection: sqlite3.Connection,
    tenant_id: str,
    *,
    tenant_type: str = "external",
    display_name: str | None = None,
) -> None:
    """Register a tenant identity without changing an existing tenant."""
    now = utc_now()
    connection.execute(
        "INSERT OR IGNORE INTO hub_tenants("
        "tenant_id, tenant_type, display_name, status, profile_json, "
        "config_json, metadata_json, revision, created_at, updated_at) "
        "VALUES (?, ?, ?, 'active', ?, ?, ?, 1, ?, ?)",
        (
            tenant_id,
            tenant_type,
            display_name,
            _JSON_DEFAULT,
            _JSON_DEFAULT,
            _JSON_DEFAULT,
            now,
            now,
        ),
    )


def _existing_hub_tables(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND "
        "(name LIKE 'hub_%' OR name IN "
        "('runtimes', 'tenant_credentials', 'schema_meta'))",
    ).fetchall()
    return {str(row["name"]) for row in rows}


def _is_current_generation(connection: sqlite3.Connection) -> bool:
    tables = _existing_hub_tables(connection)
    if "hub_schema" not in tables:
        return False
    row = connection.execute(
        "SELECT value FROM hub_schema WHERE key = 'schema_generation'",
    ).fetchone()
    return row is not None and str(row["value"]) == _SCHEMA_GENERATION


def _validate_existing_columns(connection: sqlite3.Connection) -> None:
    tables = _existing_hub_tables(connection)
    for table, required in _REQUIRED_COLUMNS.items():
        if table not in tables:
            continue
        actual = _table_columns(connection, table)
        missing = required - actual
        if missing:
            raise RuntimeError(
                f"Invalid Hub table {table}; missing columns: "
                f"{', '.join(sorted(missing))}",
            )


def _validate_schema(connection: sqlite3.Connection) -> None:
    tables = _existing_hub_tables(connection)
    missing_tables = set(_REQUIRED_COLUMNS) - tables
    if missing_tables:
        raise RuntimeError(
            f"Invalid Hub schema; missing tables: "
            f"{', '.join(sorted(missing_tables))}",
        )
    _validate_existing_columns(connection)


def _table_columns(
    connection: sqlite3.Connection,
    table: str,
) -> set[str]:
    rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
    return {str(row["name"]) for row in rows}


class HubExtensionStore:
    """Store namespaced, non-secret extensions outside core tables."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        initialize_hub_database(database_path)

    def put(
        self,
        *,
        resource_type: str,
        resource_id: str,
        namespace: str,
        key: str,
        value: dict[str, Any],
        schema_version: int = 1,
    ) -> int:
        """Create or replace one versioned extension document."""
        if not all((resource_type, resource_id, namespace, key)):
            raise ValueError("Extension identity fields are required.")
        if schema_version < 1:
            raise ValueError("schema_version must be positive.")
        now = utc_now()
        value_json = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
        )
        with connect_hub_database(self.database_path) as connection:
            connection.execute(
                "INSERT INTO hub_resource_extensions("
                "resource_type, resource_id, namespace, extension_key, "
                "value_json, schema_version, revision, created_at, "
                "updated_at) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?) "
                "ON CONFLICT(resource_type, resource_id, namespace, "
                "extension_key) DO UPDATE SET "
                "value_json = excluded.value_json, "
                "schema_version = excluded.schema_version, "
                "revision = hub_resource_extensions.revision + 1, "
                "updated_at = excluded.updated_at",
                (
                    resource_type,
                    resource_id,
                    namespace,
                    key,
                    value_json,
                    schema_version,
                    now,
                    now,
                ),
            )
            row = connection.execute(
                "SELECT revision FROM hub_resource_extensions WHERE "
                "resource_type = ? AND resource_id = ? AND namespace = ? "
                "AND extension_key = ?",
                (resource_type, resource_id, namespace, key),
            ).fetchone()
        return int(row["revision"])

    def get(
        self,
        *,
        resource_type: str,
        resource_id: str,
        namespace: str,
        key: str,
    ) -> dict[str, Any] | None:
        """Return one extension document and its format metadata."""
        with connect_hub_database(self.database_path) as connection:
            row = connection.execute(
                "SELECT value_json, schema_version, revision, updated_at "
                "FROM hub_resource_extensions WHERE resource_type = ? "
                "AND resource_id = ? AND namespace = ? "
                "AND extension_key = ?",
                (resource_type, resource_id, namespace, key),
            ).fetchone()
        if row is None:
            return None
        return {
            "value": json.loads(str(row["value_json"])),
            "schema_version": int(row["schema_version"]),
            "revision": int(row["revision"]),
            "updated_at": str(row["updated_at"]),
        }


_SCHEMA_SQL = f"""
CREATE TABLE IF NOT EXISTS hub_schema (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS hub_tenants (
    tenant_id TEXT PRIMARY KEY,
    tenant_type TEXT NOT NULL,
    display_name TEXT,
    status TEXT NOT NULL,
    profile_json TEXT NOT NULL CHECK(json_valid(profile_json)),
    config_json TEXT NOT NULL CHECK(json_valid(config_json)),
    metadata_json TEXT NOT NULL CHECK(json_valid(metadata_json)),
    revision INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT
);

CREATE TABLE IF NOT EXISTS hub_users (
    user_id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    password_salt TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('admin', 'user')),
    disabled INTEGER NOT NULL DEFAULT 0,
    token_version INTEGER NOT NULL DEFAULT 1,
    profile_json TEXT NOT NULL CHECK(json_valid(profile_json)),
    preferences_json TEXT NOT NULL CHECK(json_valid(preferences_json)),
    metadata_json TEXT NOT NULL CHECK(json_valid(metadata_json)),
    revision INTEGER NOT NULL DEFAULT 1,
    last_login_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT
);

CREATE TABLE IF NOT EXISTS runtimes (
    runtime_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    runtime_type TEXT NOT NULL,
    provisioner TEXT NOT NULL,
    desired_state TEXT NOT NULL,
    observed_state TEXT NOT NULL,
    endpoint_json TEXT NOT NULL CHECK(json_valid(endpoint_json)),
    storage_json TEXT NOT NULL CHECK(json_valid(storage_json)),
    config_json TEXT NOT NULL CHECK(json_valid(config_json)),
    status_json TEXT NOT NULL CHECK(json_valid(status_json)),
    metadata_json TEXT NOT NULL CHECK(json_valid(metadata_json)),
    revision INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    deleted_at TEXT
);

CREATE TABLE IF NOT EXISTS tenant_credentials (
    credential_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    scope TEXT NOT NULL,
    credential_name TEXT NOT NULL,
    encrypted_value TEXT NOT NULL,
    encryption_scheme TEXT NOT NULL,
    encryption_key_id TEXT NOT NULL,
    secret_type TEXT NOT NULL,
    metadata_json TEXT NOT NULL CHECK(json_valid(metadata_json)),
    revision INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (tenant_id, scope, credential_name)
);

CREATE TABLE IF NOT EXISTS hub_settings (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL CHECK(json_valid(value_json)),
    schema_version INTEGER NOT NULL DEFAULT 1,
    metadata_json TEXT NOT NULL DEFAULT '{_JSON_DEFAULT}'
        CHECK(json_valid(metadata_json)),
    revision INTEGER NOT NULL DEFAULT 1,
    updated_by_user_id TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS hub_audit_events (
    event_id TEXT PRIMARY KEY,
    actor_user_id TEXT NOT NULL,
    actor_username TEXT NOT NULL,
    action TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    outcome TEXT NOT NULL,
    request_id TEXT,
    correlation_id TEXT,
    remote_address TEXT,
    detail_json TEXT NOT NULL CHECK(json_valid(detail_json)),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS hub_resource_extensions (
    resource_type TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    namespace TEXT NOT NULL,
    extension_key TEXT NOT NULL,
    value_json TEXT NOT NULL CHECK(json_valid(value_json)),
    schema_version INTEGER NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (
        resource_type,
        resource_id,
        namespace,
        extension_key
    )
);

CREATE INDEX IF NOT EXISTS idx_tenants_type_status
ON hub_tenants(tenant_type, status);
CREATE INDEX IF NOT EXISTS idx_users_role_disabled
ON hub_users(role, disabled);
CREATE INDEX IF NOT EXISTS idx_runtimes_owner_created
ON runtimes(owner_user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_runtimes_tenant_created
ON runtimes(tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_runtimes_observed_state
ON runtimes(observed_state);
CREATE INDEX IF NOT EXISTS idx_runtimes_provisioner
ON runtimes(provisioner);
CREATE INDEX IF NOT EXISTS idx_credentials_tenant_updated
ON tenant_credentials(tenant_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_created
ON hub_audit_events(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_actor_created
ON hub_audit_events(actor_user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_resource_created
ON hub_audit_events(resource_type, resource_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_extensions_namespace
ON hub_resource_extensions(namespace, updated_at DESC);
"""

_REQUIRED_COLUMNS = {
    "hub_schema": {"key", "value"},
    "hub_tenants": {
        "tenant_id",
        "tenant_type",
        "profile_json",
        "config_json",
        "metadata_json",
        "revision",
        "deleted_at",
    },
    "hub_users": {
        "user_id",
        "profile_json",
        "preferences_json",
        "metadata_json",
        "revision",
        "deleted_at",
    },
    "runtimes": {
        "runtime_id",
        "desired_state",
        "observed_state",
        "endpoint_json",
        "storage_json",
        "config_json",
        "status_json",
        "metadata_json",
        "revision",
        "deleted_at",
    },
    "tenant_credentials": {
        "credential_id",
        "encryption_scheme",
        "encryption_key_id",
        "secret_type",
        "metadata_json",
        "revision",
    },
    "hub_settings": {
        "key",
        "value_json",
        "schema_version",
        "metadata_json",
        "revision",
    },
    "hub_audit_events": {
        "event_id",
        "request_id",
        "correlation_id",
        "remote_address",
        "detail_json",
    },
    "hub_resource_extensions": {
        "resource_type",
        "resource_id",
        "namespace",
        "extension_key",
        "value_json",
        "schema_version",
        "revision",
    },
}
