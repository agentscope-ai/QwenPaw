# -*- coding: utf-8 -*-
"""Durable, scoped SetupRequest lifecycle storage."""

from __future__ import annotations

import asyncio
import os
import sqlite3
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from pydantic_core import to_jsonable_python

from ..tasks.contracts import (
    TaskScope,
    TaskStoreError,
    canonical_json,
    content_digest,
)
from .contracts import SetupOpenAction, SetupRequest, SetupResult

_T = TypeVar("_T")
_SCHEMA_VERSION = 1
_TERMINAL = frozenset({"saved", "cancelled", "failed", "expired"})
_SCHEMA = (
    """CREATE TABLE setup_requests (
        request_id TEXT PRIMARY KEY,
        principal_id TEXT NOT NULL,
        workspace_id TEXT NOT NULL,
        app_id TEXT NOT NULL,
        idempotency_key TEXT NOT NULL,
        meaning_digest TEXT NOT NULL,
        request_json TEXT NOT NULL,
        open_action_json TEXT,
        result_digest TEXT,
        result_json TEXT,
        UNIQUE(principal_id, workspace_id, app_id, idempotency_key)
    )""",
    """CREATE INDEX setup_requests_scope ON setup_requests(
        principal_id, workspace_id, app_id, request_id
    )""",
    """CREATE TABLE setup_audit (
        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at REAL NOT NULL,
        principal_id TEXT NOT NULL,
        workspace_id TEXT NOT NULL,
        app_id TEXT NOT NULL,
        request_id TEXT NOT NULL,
        operation TEXT NOT NULL,
        outcome TEXT NOT NULL
    )""",
)


@dataclass(frozen=True)
class SetupRecord:
    """One persisted request with optional presentation and result receipts."""

    request: SetupRequest
    open_action: SetupOpenAction | None
    result: SetupResult | None


class SetupStore:
    """Persist setup state without raw action inputs or credentials."""

    def __init__(self, path: Path):
        self.path = Path(path)

    @classmethod
    async def open(cls, path: Path) -> SetupStore:
        store = cls(path)
        await asyncio.to_thread(store._initialize)
        return store

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path,
            timeout=10,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA synchronous = FULL")
        return connection

    def _initialize(self) -> None:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        flags = os.O_CREAT | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(self.path, flags, 0o600)
        os.close(descriptor)
        connection = self._connect()
        try:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("BEGIN IMMEDIATE")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version == 0:
                for statement in _SCHEMA:
                    connection.execute(statement)
                connection.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
            elif version != _SCHEMA_VERSION:
                raise TaskStoreError("unsupported_setup_store_version")
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    async def _run(
        self,
        operation: Callable[[sqlite3.Connection], _T],
        *,
        write: bool = False,
    ) -> _T:
        def transaction() -> _T:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
                result = operation(connection)
                connection.commit()
                return result
            except BaseException:
                connection.rollback()
                raise
            finally:
                connection.close()

        return await asyncio.to_thread(transaction)

    @staticmethod
    def _row(row: sqlite3.Row) -> SetupRecord:
        return SetupRecord(
            SetupRequest.model_validate_json(row["request_json"]),
            SetupOpenAction.model_validate_json(row["open_action_json"])
            if row["open_action_json"]
            else None,
            SetupResult.model_validate_json(row["result_json"])
            if row["result_json"]
            else None,
        )

    @staticmethod
    def _get(
        connection: sqlite3.Connection,
        scope: TaskScope,
        request_id: str,
    ) -> SetupRecord:
        row = connection.execute(
            """SELECT * FROM setup_requests WHERE request_id = ?
            AND principal_id = ? AND workspace_id = ? AND app_id = ?""",
            (
                request_id,
                scope.principal_id,
                scope.workspace_id,
                scope.app_id,
            ),
        ).fetchone()
        if row is None:
            raise TaskStoreError("setup_request_not_found")
        return SetupStore._row(row)

    @staticmethod
    def _audit(
        connection: sqlite3.Connection,
        scope: TaskScope,
        request_id: str,
        operation: str,
        outcome: str,
    ) -> None:
        connection.execute(
            """INSERT INTO setup_audit(
                created_at, principal_id, workspace_id, app_id,
                request_id, operation, outcome
            ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                time.time(),
                scope.principal_id,
                scope.workspace_id,
                scope.app_id,
                request_id,
                operation,
                outcome,
            ),
        )

    @staticmethod
    def _expire(
        connection: sqlite3.Connection,
        scope: TaskScope,
        record: SetupRecord,
    ) -> SetupRecord:
        request = record.request
        if request.state in _TERMINAL or request.expires_at > time.time():
            return record
        request = request.model_copy(
            update={"state": "expired", "updated_at": time.time()},
        )
        connection.execute(
            "UPDATE setup_requests SET request_json = ? WHERE request_id = ?",
            (request.model_dump_json(), request.request_id),
        )
        SetupStore._audit(
            connection,
            scope,
            request.request_id,
            "expire",
            "expired",
        )
        return SetupRecord(request, record.open_action, record.result)

    async def create(
        self,
        scope: TaskScope,
        *,
        idempotency_key: str,
        values: dict,
        meaning_context: dict | None = None,
    ) -> tuple[SetupRecord, bool]:
        """Create one Host-ID request or return its exact idempotent replay."""
        stable_values = {
            key: value for key, value in values.items() if key != "expires_at"
        }
        meaning = to_jsonable_python(
            {
                "scope": scope.model_dump(mode="json"),
                "context": meaning_context or {},
                **stable_values,
            },
        )
        digest = content_digest(meaning)

        def transaction(connection: sqlite3.Connection):
            row = connection.execute(
                """SELECT * FROM setup_requests
                WHERE principal_id = ? AND workspace_id = ? AND app_id = ?
                AND idempotency_key = ?""",
                (
                    scope.principal_id,
                    scope.workspace_id,
                    scope.app_id,
                    idempotency_key,
                ),
            ).fetchone()
            if row is not None:
                if row["meaning_digest"] != digest:
                    raise TaskStoreError("setup_idempotency_conflict")
                return self._expire(connection, scope, self._row(row)), True
            now = time.time()
            request = SetupRequest(
                request_id="setup_" + uuid.uuid4().hex,
                scope=scope,
                created_at=now,
                updated_at=now,
                **values,
            )
            connection.execute(
                """INSERT INTO setup_requests(
                    request_id, principal_id, workspace_id, app_id,
                    idempotency_key, meaning_digest, request_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    request.request_id,
                    scope.principal_id,
                    scope.workspace_id,
                    scope.app_id,
                    idempotency_key,
                    digest,
                    request.model_dump_json(),
                ),
            )
            self._audit(
                connection,
                scope,
                request.request_id,
                "create",
                "requested",
            )
            return SetupRecord(request, None, None), False

        canonical_json(meaning)
        return await self._run(transaction, write=True)

    async def get(self, scope: TaskScope, request_id: str) -> SetupRecord:
        def transaction(connection: sqlite3.Connection):
            return self._expire(
                connection,
                scope,
                self._get(connection, scope, request_id),
            )

        return await self._run(transaction, write=True)

    async def backend_scope(
        self,
        principal_id: str,
        app_id: str,
        request_id: str,
    ) -> TaskScope:
        """Resolve scope for a trusted App backend without browser claims."""

        def transaction(connection: sqlite3.Connection):
            row = connection.execute(
                """SELECT workspace_id FROM setup_requests
                WHERE request_id = ? AND principal_id = ? AND app_id = ?""",
                (request_id, principal_id, app_id),
            ).fetchone()
            if row is None:
                raise TaskStoreError("setup_request_not_found")
            return TaskScope(
                principal_id=principal_id,
                workspace_id=row["workspace_id"],
                app_id=app_id,
            )

        return await self._run(transaction)

    async def opened(
        self,
        scope: TaskScope,
        request_id: str,
        action: SetupOpenAction,
    ) -> SetupRecord:
        def transaction(connection: sqlite3.Connection):
            record = self._expire(
                connection,
                scope,
                self._get(connection, scope, request_id),
            )
            request = record.request
            if request.state in _TERMINAL:
                raise TaskStoreError("setup_request_closed")
            if record.open_action is not None:
                return record
            if request.state != "requested":
                raise TaskStoreError("setup_request_closed")
            if (
                action.request_id != request_id
                or action.app_id != scope.app_id
            ):
                raise TaskStoreError("invalid_setup_open_action")
            if (
                action.entry_id != request.entry_id
                or action.presentation != request.presentation
            ):
                raise TaskStoreError("invalid_setup_open_action")
            request = request.model_copy(
                update={"state": "opened", "updated_at": time.time()},
            )
            connection.execute(
                """UPDATE setup_requests
                SET request_json = ?, open_action_json = ?
                WHERE request_id = ?""",
                (
                    request.model_dump_json(),
                    action.model_dump_json(),
                    request_id,
                ),
            )
            self._audit(
                connection,
                scope,
                request_id,
                "open",
                "opened",
            )
            return SetupRecord(request, action, None)

        return await self._run(transaction, write=True)

    async def waiting_external(
        self,
        scope: TaskScope,
        request_id: str,
    ) -> SetupRecord:
        def transaction(connection: sqlite3.Connection):
            record = self._expire(
                connection,
                scope,
                self._get(connection, scope, request_id),
            )
            request = record.request
            if request.state == "waiting_external":
                return record
            if request.state != "opened":
                raise TaskStoreError("setup_request_closed")
            request = request.model_copy(
                update={
                    "state": "waiting_external",
                    "updated_at": time.time(),
                },
            )
            connection.execute(
                """UPDATE setup_requests SET request_json = ?
                WHERE request_id = ?""",
                (request.model_dump_json(), request_id),
            )
            self._audit(
                connection,
                scope,
                request_id,
                "wait_external",
                "waiting_external",
            )
            return SetupRecord(request, record.open_action, None)

        return await self._run(transaction, write=True)

    async def complete(
        self,
        scope: TaskScope,
        result: SetupResult,
    ) -> SetupRecord:
        digest = content_digest(result.model_dump(mode="json"))

        def transaction(connection: sqlite3.Connection):
            record = self._expire(
                connection,
                scope,
                self._get(connection, scope, result.request_id),
            )
            request = record.request
            row = connection.execute(
                """SELECT result_digest FROM setup_requests
                WHERE request_id = ?""",
                (result.request_id,),
            ).fetchone()
            if record.result is not None:
                if row["result_digest"] == digest:
                    return record
                if request.state in {"cancelled", "expired"}:
                    raise TaskStoreError("setup_request_closed")
                raise TaskStoreError("setup_result_conflict")
            if request.state not in {"opened", "waiting_external"}:
                raise TaskStoreError("setup_request_closed")
            if not set(result.changed_requirement_ids).issubset(
                request.requirement_ids,
            ):
                raise TaskStoreError("setup_result_scope_mismatch")
            if not set(result.config_revisions).issubset(
                request.requirement_ids,
            ):
                raise TaskStoreError("setup_result_scope_mismatch")
            request = request.model_copy(
                update={"state": result.outcome, "updated_at": time.time()},
            )
            connection.execute(
                """UPDATE setup_requests SET request_json = ?,
                result_digest = ?, result_json = ? WHERE request_id = ?""",
                (
                    request.model_dump_json(),
                    digest,
                    result.model_dump_json(),
                    result.request_id,
                ),
            )
            self._audit(
                connection,
                scope,
                result.request_id,
                "complete",
                result.outcome,
            )
            return SetupRecord(request, record.open_action, result)

        return await self._run(transaction, write=True)

    async def cancel(
        self,
        scope: TaskScope,
        request_id: str,
    ) -> SetupRecord:
        def transaction(connection: sqlite3.Connection):
            record = self._expire(
                connection,
                scope,
                self._get(connection, scope, request_id),
            )
            if record.request.state == "cancelled":
                return record
            if record.request.state in _TERMINAL:
                raise TaskStoreError("setup_request_closed")
            result = SetupResult(
                request_id=request_id,
                result_id="setup_result_" + uuid.uuid4().hex,
                outcome="cancelled",
            )
            request = record.request.model_copy(
                update={"state": "cancelled", "updated_at": time.time()},
            )
            digest = content_digest(result.model_dump(mode="json"))
            connection.execute(
                """UPDATE setup_requests SET request_json = ?,
                result_digest = ?, result_json = ? WHERE request_id = ?""",
                (
                    request.model_dump_json(),
                    digest,
                    result.model_dump_json(),
                    request_id,
                ),
            )
            self._audit(
                connection,
                scope,
                request_id,
                "cancel",
                "cancelled",
            )
            return SetupRecord(request, record.open_action, result)

        return await self._run(transaction, write=True)
