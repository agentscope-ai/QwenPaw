# -*- coding: utf-8 -*-
"""SQLite registry for QwenPaw Hub runtime metadata."""

from __future__ import annotations

import builtins
import json
import sqlite3
from pathlib import Path
from typing import Any

from .database import (
    connect_hub_database,
    ensure_tenant,
    initialize_hub_database,
    utc_now,
)
from .models import RuntimeRecord, RuntimeStartPolicy, RuntimeState


class RuntimeRegistry:
    """Persist runtime ownership, locations, and latest observed state."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        initialize_hub_database(database_path)

    def _connect(self) -> sqlite3.Connection:
        return connect_hub_database(self.database_path)

    def create(self, record: RuntimeRecord) -> RuntimeRecord:
        """Insert a new runtime record."""
        now = utc_now()
        stored = RuntimeRecord(
            **{
                **record.__dict__,
                "created_at": record.created_at or now,
                "updated_at": now,
            },
        )
        with self._connect() as connection:
            ensure_tenant(connection, stored.tenant_id)
            connection.execute(
                """
                INSERT INTO runtimes(
                    runtime_id, tenant_id, owner_user_id, runtime_type,
                    provisioner, desired_state, observed_state,
                    endpoint_json, storage_json, config_json, status_json,
                    metadata_json, revision, created_at, updated_at,
                    observed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._values(stored),
            )
        return stored

    def save(self, record: RuntimeRecord) -> RuntimeRecord:
        """Persist the latest observed state for an existing runtime."""
        now = utc_now()
        stored = RuntimeRecord(
            **{
                **record.__dict__,
                "updated_at": now,
                "observed_at": now,
                "revision": record.revision + 1,
            },
        )
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE runtimes SET
                    tenant_id = ?, owner_user_id = ?, runtime_type = ?,
                    provisioner = ?, desired_state = ?, observed_state = ?,
                    endpoint_json = ?, storage_json = ?, config_json = ?,
                    status_json = ?, metadata_json = ?, revision = ?,
                    created_at = ?, updated_at = ?, observed_at = ?
                WHERE runtime_id = ? AND revision = ?
                    AND deleted_at IS NULL
                """,
                (
                    *self._values(stored)[1:],
                    stored.runtime_id,
                    record.revision,
                ),
            )
            if cursor.rowcount != 1:
                row = connection.execute(
                    "SELECT revision FROM runtimes WHERE runtime_id = ? "
                    "AND deleted_at IS NULL",
                    (stored.runtime_id,),
                ).fetchone()
                if row is None:
                    raise KeyError(stored.runtime_id)
                raise RuntimeError(
                    f"Runtime changed concurrently: {stored.runtime_id}",
                )
        return stored

    def get(self, runtime_id: str) -> RuntimeRecord | None:
        """Return one runtime or None when it does not exist."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM runtimes WHERE runtime_id = ? "
                "AND deleted_at IS NULL",
                (runtime_id,),
            ).fetchone()
        return self._from_row(row) if row is not None else None

    def list(self, owner_user_id: str | None = None) -> list[RuntimeRecord]:
        """Return runtimes in stable creation order."""
        with self._connect() as connection:
            if owner_user_id is None:
                rows = connection.execute(
                    "SELECT * FROM runtimes WHERE deleted_at IS NULL "
                    "ORDER BY created_at, runtime_id",
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM runtimes WHERE owner_user_id = ? "
                    "AND deleted_at IS NULL "
                    "ORDER BY created_at, runtime_id",
                    (owner_user_id,),
                ).fetchall()
        return [self._from_row(row) for row in rows]

    def list_page(
        self,
        *,
        page: int,
        page_size: int,
        owner_user_id: str | None = None,
        query: str | None = None,
        state: RuntimeState | None = None,
        provisioner: str | None = None,
        owner: str | None = None,
    ) -> tuple[builtins.list[RuntimeRecord], int]:
        """Return one filtered runtime page and the matching total."""
        clauses: list[str] = ["deleted_at IS NULL"]
        parameters: list[object] = []
        if owner_user_id is not None:
            clauses.append("owner_user_id = ?")
            parameters.append(owner_user_id)
        if query:
            clauses.append(
                "(runtime_id LIKE ? OR tenant_id LIKE ? "
                "OR owner_user_id LIKE ? OR "
                "json_extract(endpoint_json, '$.host') LIKE ? OR "
                "EXISTS (SELECT 1 FROM hub_users "
                "WHERE hub_users.user_id = runtimes.owner_user_id "
                "AND hub_users.deleted_at IS NULL "
                "AND hub_users.username LIKE ?))",
            )
            pattern = f"%{query}%"
            parameters.extend(
                [pattern, pattern, pattern, pattern, pattern],
            )
        if state is not None:
            clauses.append("observed_state = ?")
            parameters.append(state.value)
        if provisioner:
            clauses.append("provisioner = ?")
            parameters.append(provisioner)
        if owner:
            clauses.append(
                "(owner_user_id LIKE ? OR "
                "EXISTS (SELECT 1 FROM hub_users "
                "WHERE hub_users.user_id = runtimes.owner_user_id "
                "AND hub_users.deleted_at IS NULL "
                "AND hub_users.username LIKE ?))",
            )
            pattern = f"%{owner}%"
            parameters.extend([pattern, pattern])
        where = f" WHERE {' AND '.join(clauses)}"
        with self._connect() as connection:
            total_row = connection.execute(
                f"SELECT COUNT(*) AS count FROM runtimes{where}",
                parameters,
            ).fetchone()
            rows = connection.execute(
                f"SELECT * FROM runtimes{where} "
                "ORDER BY created_at DESC, runtime_id "
                "LIMIT ? OFFSET ?",
                (*parameters, page_size, (page - 1) * page_size),
            ).fetchall()
        return (
            [self._from_row(row) for row in rows],
            int(total_row["count"]),
        )

    def count_by_state(
        self,
        owner_user_id: str | None = None,
    ) -> dict[str, int]:
        """Return runtime totals grouped by persisted lifecycle state."""
        parameters: tuple[object, ...] = ()
        clauses = ["deleted_at IS NULL"]
        if owner_user_id is not None:
            clauses.append("owner_user_id = ?")
            parameters = (owner_user_id,)
        where = f" WHERE {' AND '.join(clauses)}"
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT observed_state, COUNT(*) AS count FROM runtimes"
                f"{where} GROUP BY observed_state",
                parameters,
            ).fetchall()
        counts = {state.value: 0 for state in RuntimeState}
        counts.update(
            {str(row["observed_state"]): int(row["count"]) for row in rows},
        )
        return counts

    def delete(self, runtime_id: str) -> None:
        """Remove registration without deleting runtime data."""
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM runtimes "
                "WHERE runtime_id = ? AND deleted_at IS NULL",
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
            record.runtime_type,
            record.provisioner,
            record.desired_state.value,
            record.state.value,
            json.dumps(
                {
                    "schema_version": 1,
                    "host": record.host,
                    "port": record.port,
                },
                sort_keys=True,
            ),
            json.dumps(
                {
                    "schema_version": 1,
                    "working_dir": str(record.working_dir),
                    "secret_dir": str(record.secret_dir),
                    "backup_dir": str(record.backup_dir),
                    "log_file": str(record.log_file),
                },
                sort_keys=True,
            ),
            json.dumps(
                {
                    "schema_version": 2,
                    "start_policy": record.start_policy.value,
                },
                sort_keys=True,
            ),
            json.dumps(
                {
                    "schema_version": 1,
                    "pid": record.pid,
                    "last_error": record.last_error,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            json.dumps(
                {
                    "schema_version": 1,
                    "values": record.metadata,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            record.revision,
            record.created_at,
            record.updated_at,
            record.observed_at or record.updated_at,
        )

    @staticmethod
    def _from_row(row: sqlite3.Row) -> RuntimeRecord:
        endpoint = json.loads(str(row["endpoint_json"]))
        storage = json.loads(str(row["storage_json"]))
        config = json.loads(str(row["config_json"]))
        status = json.loads(str(row["status_json"]))
        metadata = json.loads(str(row["metadata_json"]))
        return RuntimeRecord(
            runtime_id=str(row["runtime_id"]),
            tenant_id=str(row["tenant_id"]),
            owner_user_id=str(row["owner_user_id"]),
            runtime_type=str(row["runtime_type"]),
            provisioner=str(row["provisioner"]),
            host=str(endpoint["host"]),
            port=int(endpoint["port"]),
            desired_state=RuntimeState(str(row["desired_state"])),
            start_policy=RuntimeStartPolicy(
                str(config["start_policy"]),
            ),
            state=RuntimeState(str(row["observed_state"])),
            pid=(
                int(status["pid"]) if status.get("pid") is not None else None
            ),
            working_dir=Path(str(storage["working_dir"])),
            secret_dir=Path(str(storage["secret_dir"])),
            backup_dir=Path(str(storage["backup_dir"])),
            log_file=Path(str(storage["log_file"])),
            revision=int(row["revision"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            observed_at=str(row["observed_at"]),
            last_error=status.get("last_error"),
            metadata=dict(metadata.get("values", {})),
        )
