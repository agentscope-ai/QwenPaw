# -*- coding: utf-8 -*-
"""Tenant-scoped encrypted credential vault for QwenPaw Pro."""

from __future__ import annotations

import os
import re
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

_CREDENTIAL_NAME_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")
_SYSTEM_TENANT_ID = "__qwenpaw_pro_system__"
_SYSTEM_SCOPE = "control"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TenantCredentialVault:
    """Encrypt credentials and enforce tenant-qualified lookup keys."""

    def __init__(self, database_path: Path, key_path: Path) -> None:
        self.database_path = database_path
        self.key_path = key_path
        self._fernet = Fernet(self._load_or_create_key())
        self._cache: dict[tuple[str, str, str], str] = {}
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS tenant_credentials (
                    tenant_id TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    credential_name TEXT NOT NULL,
                    encrypted_value TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, scope, credential_name)
                )
                """,
            )

    def put(
        self,
        *,
        tenant_id: str,
        scope: str,
        name: str,
        value: str,
    ) -> None:
        """Create or replace one credential inside an explicit tenant scope."""
        self._validate_scope(tenant_id, scope, name)
        if not value:
            raise ValueError("Credential value cannot be empty.")
        encrypted = self._fernet.encrypt(value.encode("utf-8")).decode("ascii")
        now = _now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO tenant_credentials(
                    tenant_id, scope, credential_name, encrypted_value,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(tenant_id, scope, credential_name) DO UPDATE SET
                    encrypted_value = excluded.encrypted_value,
                    updated_at = excluded.updated_at
                """,
                (tenant_id, scope, name, encrypted, now, now),
            )
        self._cache[(tenant_id, scope, name)] = value

    def get(self, *, tenant_id: str, scope: str, name: str) -> str | None:
        """Resolve only the exact tenant-qualified credential key."""
        self._validate_scope(tenant_id, scope, name)
        cache_key = (tenant_id, scope, name)
        if cache_key in self._cache:
            return self._cache[cache_key]
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT encrypted_value FROM tenant_credentials
                WHERE tenant_id = ? AND scope = ? AND credential_name = ?
                """,
                cache_key,
            ).fetchone()
        if row is None:
            return None
        try:
            value = self._fernet.decrypt(
                str(row["encrypted_value"]).encode("ascii"),
            ).decode("utf-8")
        except InvalidToken as exc:
            raise RuntimeError(
                f"Credential cannot be decrypted: {tenant_id}/{scope}/{name}",
            ) from exc
        self._cache[cache_key] = value
        return value

    def list_metadata(self, *, tenant_id: str) -> list[dict[str, str]]:
        """List credential names without returning secret values."""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT scope, credential_name, created_at, updated_at
                FROM tenant_credentials WHERE tenant_id = ?
                ORDER BY scope, credential_name
                """,
                (tenant_id,),
            ).fetchall()
        return [
            {
                "scope": str(row["scope"]),
                "name": str(row["credential_name"]),
                "created_at": str(row["created_at"]),
                "updated_at": str(row["updated_at"]),
            }
            for row in rows
        ]

    def delete(self, *, tenant_id: str, scope: str, name: str) -> None:
        """Delete one exact tenant-qualified credential."""
        self._validate_scope(tenant_id, scope, name)
        cache_key = (tenant_id, scope, name)
        with self._connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM tenant_credentials
                WHERE tenant_id = ? AND scope = ? AND credential_name = ?
                """,
                cache_key,
            )
            if cursor.rowcount != 1:
                raise KeyError(cache_key)
        self._cache.pop(cache_key, None)

    def resolve_environment(
        self,
        *,
        tenant_id: str,
        runtime_id: str,
    ) -> dict[str, str]:
        """Resolve tenant credentials with runtime-specific overrides."""
        resolved = self._resolve_scope(tenant_id, "tenant")
        resolved.update(
            self._resolve_scope(tenant_id, f"runtime:{runtime_id}"),
        )
        return resolved

    def get_or_create_system_secret(self, name: str) -> str:
        """Store control-plane keys in the encrypted system tenant scope."""
        existing = self.get(
            tenant_id=_SYSTEM_TENANT_ID,
            scope=_SYSTEM_SCOPE,
            name=name,
        )
        if existing is not None:
            return existing
        value = Fernet.generate_key().decode("ascii")
        self.put(
            tenant_id=_SYSTEM_TENANT_ID,
            scope=_SYSTEM_SCOPE,
            name=name,
            value=value,
        )
        return value

    def get_or_create_runtime_secret(
        self,
        *,
        tenant_id: str,
        runtime_id: str,
        name: str,
    ) -> str:
        """Create a stable tenant-qualified runtime boundary secret."""
        scope = f"runtime:{runtime_id}"
        existing = self.get(
            tenant_id=tenant_id,
            scope=scope,
            name=name,
        )
        if existing is not None:
            return existing
        value = secrets.token_urlsafe(48)
        self.put(
            tenant_id=tenant_id,
            scope=scope,
            name=name,
            value=value,
        )
        return value

    def _resolve_scope(self, tenant_id: str, scope: str) -> dict[str, str]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT credential_name FROM tenant_credentials
                WHERE tenant_id = ? AND scope = ?
                ORDER BY credential_name
                """,
                (tenant_id, scope),
            ).fetchall()
        resolved: dict[str, str] = {}
        for row in rows:
            name = str(row["credential_name"])
            value = self.get(tenant_id=tenant_id, scope=scope, name=name)
            if value is not None:
                resolved[name] = value
        return resolved

    def _load_or_create_key(self) -> bytes:
        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        if self.key_path.is_file():
            return self.key_path.read_bytes().strip()
        key = Fernet.generate_key()
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        descriptor = os.open(self.key_path, flags, 0o600)
        try:
            os.write(descriptor, key)
        finally:
            os.close(descriptor)
        return key

    @staticmethod
    def _validate_scope(tenant_id: str, scope: str, name: str) -> None:
        if not tenant_id or not scope:
            raise ValueError("tenant_id and scope are required.")
        if not _CREDENTIAL_NAME_PATTERN.fullmatch(name):
            raise ValueError(
                "Credential name must be an uppercase environment "
                "variable name.",
            )
