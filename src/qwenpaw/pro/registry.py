# -*- coding: utf-8 -*-
"""SQLite registry for QwenPaw Pro runtime metadata."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import RuntimeRecord, RuntimeState

_SCHEMA_VERSION = 1


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RuntimeRegistry:
    """Persist runtime ownership, locations, and latest observed state."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_meta ("
                "key TEXT PRIMARY KEY, value TEXT NOT NULL)",
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS runtimes (
                    runtime_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    owner_user_id TEXT NOT NULL,
                    driver TEXT NOT NULL,
                    host TEXT NOT NULL,
                    port INTEGER NOT NULL,
                    state TEXT NOT NULL,
                    pid INTEGER,
                    working_dir TEXT NOT NULL,
                    secret_dir TEXT NOT NULL,
                    backup_dir TEXT NOT NULL,
                    log_file TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_error TEXT,
                    metadata_json TEXT NOT NULL
                )
                """,
            )
            connection.execute(
                "INSERT OR REPLACE INTO schema_meta(key, value) "
                "VALUES ('schema_version', ?)",
                (str(_SCHEMA_VERSION),),
            )

    def create(self, record: RuntimeRecord) -> RuntimeRecord:
        """Insert a new runtime record."""
        now = _now()
        stored = RuntimeRecord(
            **{
                **record.__dict__,
                "created_at": record.created_at or now,
                "updated_at": now,
            },
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO runtimes(
                    runtime_id, tenant_id, owner_user_id, driver, host, port,
                    state, pid, working_dir, secret_dir, backup_dir, log_file,
                    created_at, updated_at, last_error, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._values(stored),
            )
        return stored

    def save(self, record: RuntimeRecord) -> RuntimeRecord:
        """Persist the latest observed state for an existing runtime."""
        stored = RuntimeRecord(
            **{
                **record.__dict__,
                "updated_at": _now(),
            },
        )
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE runtimes SET
                    tenant_id = ?, owner_user_id = ?, driver = ?, host = ?,
                    port = ?, state = ?, pid = ?, working_dir = ?,
                    secret_dir = ?, backup_dir = ?, log_file = ?,
                    created_at = ?, updated_at = ?, last_error = ?,
                    metadata_json = ?
                WHERE runtime_id = ?
                """,
                (*self._values(stored)[1:], stored.runtime_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(stored.runtime_id)
        return stored

    def get(self, runtime_id: str) -> RuntimeRecord | None:
        """Return one runtime or None when it does not exist."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM runtimes WHERE runtime_id = ?",
                (runtime_id,),
            ).fetchone()
        return self._from_row(row) if row is not None else None

    def list(self, owner_user_id: str | None = None) -> list[RuntimeRecord]:
        """Return runtimes in stable creation order."""
        with self._connect() as connection:
            if owner_user_id is None:
                rows = connection.execute(
                    "SELECT * FROM runtimes ORDER BY created_at, runtime_id",
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM runtimes WHERE owner_user_id = ? "
                    "ORDER BY created_at, runtime_id",
                    (owner_user_id,),
                ).fetchall()
        return [self._from_row(row) for row in rows]

    def delete(self, runtime_id: str) -> None:
        """Delete registration without deleting runtime data."""
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM runtimes WHERE runtime_id = ?",
                (runtime_id,),
            )
            if cursor.rowcount != 1:
                raise KeyError(runtime_id)

    @staticmethod
    def _values(record: RuntimeRecord) -> tuple[Any, ...]:
        return (
            record.runtime_id,
            record.tenant_id,
            record.owner_user_id,
            record.driver,
            record.host,
            record.port,
            record.state.value,
            record.pid,
            str(record.working_dir),
            str(record.secret_dir),
            str(record.backup_dir),
            str(record.log_file),
            record.created_at,
            record.updated_at,
            record.last_error,
            json.dumps(record.metadata, ensure_ascii=False, sort_keys=True),
        )

    @staticmethod
    def _from_row(row: sqlite3.Row) -> RuntimeRecord:
        return RuntimeRecord(
            runtime_id=str(row["runtime_id"]),
            tenant_id=str(row["tenant_id"]),
            owner_user_id=str(row["owner_user_id"]),
            driver=str(row["driver"]),
            host=str(row["host"]),
            port=int(row["port"]),
            state=RuntimeState(str(row["state"])),
            pid=int(row["pid"]) if row["pid"] is not None else None,
            working_dir=Path(str(row["working_dir"])),
            secret_dir=Path(str(row["secret_dir"])),
            backup_dir=Path(str(row["backup_dir"])),
            log_file=Path(str(row["log_file"])),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            last_error=(
                str(row["last_error"])
                if row["last_error"] is not None
                else None
            ),
            metadata=json.loads(str(row["metadata_json"])),
        )
