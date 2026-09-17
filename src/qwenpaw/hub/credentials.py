# -*- coding: utf-8 -*-
"""Tenant-scoped encrypted credential vault for QwenPaw Hub."""

from __future__ import annotations

import os
import re
import secrets
import sqlite3
import uuid
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from .database import (
    connect_hub_database,
    ensure_tenant,
    initialize_hub_database,
    utc_now,
)

_CREDENTIAL_NAME_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")
_SYSTEM_TENANT_ID = "__qwenpaw_hub_system__"
_SYSTEM_SCOPE = "control"
_RUNTIME_CONTROL_NAMES = {
    "BASH_ENV",
    "COMSPEC",
    "CONDA_PREFIX",
    "ENV",
    "HOME",
    "PATH",
    "PATHEXT",
    "SHELLOPTS",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "TMPDIR",
    "VIRTUAL_ENV",
    "WINDIR",
}
_RUNTIME_CONTROL_PREFIXES = (
    "DYLD_",
    "LD_",
    "PYTHON",
    "QWENPAW_",
)


def runtime_credential_name_allowed(name: str) -> bool:
    """Return whether a tenant may project a credential into a runtime."""
    return name not in _RUNTIME_CONTROL_NAMES and not name.startswith(
        _RUNTIME_CONTROL_PREFIXES,
    )


class TenantCredentialVault:
    """Encrypt credentials and enforce tenant-qualified lookup keys."""

    def __init__(self, database_path: Path, key_path: Path) -> None:
        self.database_path = database_path
        self.key_path = key_path
        self._fernet = Fernet(self._load_or_create_key())
        self._cache: dict[tuple[str, str, str], str] = {}
        initialize_hub_database(database_path)

    def _connect(self) -> sqlite3.Connection:
        return connect_hub_database(self.database_path)

    def put(
        self,
        *,
        tenant_id: str,
        scope: str,
        name: str,
        value: str,
        trusted: bool = False,
    ) -> None:
        """Create or replace one credential inside an explicit tenant scope."""
        self._validate_scope(tenant_id, scope, name)
        if not trusted:
            self._validate_runtime_credential_name(name)
        if not value:
            raise ValueError("Credential value cannot be empty.")
        encrypted = self._fernet.encrypt(value.encode("utf-8")).decode("ascii")
        now = utc_now()
        with self._connect() as connection:
            ensure_tenant(connection, tenant_id)
            connection.execute(
                """
                INSERT INTO tenant_credentials(
                    credential_id, tenant_id, scope, credential_name,
                    encrypted_value, encryption_scheme, encryption_key_id,
                    secret_type, metadata_json, revision, created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, 'fernet-v1', 'local-vault',
                    'environment', '{"schema_version":1}', 1, ?, ?)
                ON CONFLICT(tenant_id, scope, credential_name) DO UPDATE SET
                    encrypted_value = excluded.encrypted_value,
                    encryption_scheme = excluded.encryption_scheme,
                    encryption_key_id = excluded.encryption_key_id,
                    revision = tenant_credentials.revision + 1,
                    updated_at = excluded.updated_at
                """,
                (
                    uuid.uuid4().hex,
                    tenant_id,
                    scope,
                    name,
                    encrypted,
                    now,
                    now,
                ),
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

    def list_metadata_page(
        self,
        *,
        tenant_id: str,
        page: int,
        page_size: int,
        query: str | None = None,
        scope: str | None = None,
    ) -> tuple[list[dict[str, str]], int]:
        """Return one filtered credential metadata page."""
        clauses = ["tenant_id = ?"]
        parameters: list[object] = [tenant_id]
        if query:
            clauses.append(
                "(credential_name LIKE ? OR scope LIKE ?)",
            )
            pattern = f"%{query}%"
            parameters.extend([pattern, pattern])
        if scope:
            clauses.append("scope = ?")
            parameters.append(scope)
        where = f" WHERE {' AND '.join(clauses)}"
        with self._connect() as connection:
            total_row = connection.execute(
                "SELECT COUNT(*) AS count FROM tenant_credentials" f"{where}",
                parameters,
            ).fetchone()
            rows = connection.execute(
                "SELECT scope, credential_name, created_at, updated_at "
                f"FROM tenant_credentials{where} "
                "ORDER BY updated_at DESC, scope, credential_name "
                "LIMIT ? OFFSET ?",
                (*parameters, page_size, (page - 1) * page_size),
            ).fetchall()
        items = [
            {
                "scope": str(row["scope"]),
                "name": str(row["credential_name"]),
                "created_at": str(row["created_at"]),
                "updated_at": str(row["updated_at"]),
            }
            for row in rows
        ]
        return items, int(total_row["count"])

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
        stored = self._resolve_scope(tenant_id, "tenant")
        stored.update(
            self._resolve_scope(tenant_id, f"runtime:{runtime_id}"),
        )
        return {
            name: value
            for name, value in stored.items()
            if runtime_credential_name_allowed(name)
        }

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
            trusted=True,
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
        try:
            self.delete(
                tenant_id=tenant_id,
                scope=f"runtime:{runtime_id}",
                name=name,
            )
        except KeyError:
            pass
        scope = self._runtime_control_scope(tenant_id, runtime_id)
        existing = self.get(
            tenant_id=_SYSTEM_TENANT_ID,
            scope=scope,
            name=name,
        )
        if existing is not None:
            return existing
        value = secrets.token_urlsafe(48)
        self.put(
            tenant_id=_SYSTEM_TENANT_ID,
            scope=scope,
            name=name,
            value=value,
            trusted=True,
        )
        return value

    def get_runtime_secret(
        self,
        *,
        tenant_id: str,
        runtime_id: str,
        name: str,
    ) -> str | None:
        """Read a server-owned runtime secret outside tenant scopes."""
        return self.get(
            tenant_id=_SYSTEM_TENANT_ID,
            scope=self._runtime_control_scope(tenant_id, runtime_id),
            name=name,
        )

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
    def _runtime_control_scope(tenant_id: str, runtime_id: str) -> str:
        return f"runtime-control:{tenant_id}:{runtime_id}"

    @staticmethod
    def _validate_scope(tenant_id: str, scope: str, name: str) -> None:
        if not tenant_id or not scope:
            raise ValueError("tenant_id and scope are required.")
        if not _CREDENTIAL_NAME_PATTERN.fullmatch(name):
            raise ValueError(
                "Credential name must be an uppercase environment "
                "variable name.",
            )

    @staticmethod
    def _validate_runtime_credential_name(name: str) -> None:
        if not runtime_credential_name_allowed(name):
            raise ValueError(
                f"Credential name is reserved by the runtime: {name}",
            )
