# -*- coding: utf-8 -*-
"""Durable task facts and delivery intents; no executor or Chat scheduling.

Each operation owns a short SQLite transaction on a worker thread. The store
does not replace app.task_tracker, whose state describes active Chat runs.
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Callable, TypeVar

from .contracts import (
    TERMINAL_STATUSES,
    WAITING_STATUSES,
    ActionDescriptor,
    ExecutorEvent,
    ExecutorRunRef,
    RecoveryState,
    TaskDelivery,
    TaskEvent,
    TaskHandle,
    TaskOrigin,
    TaskScope,
    TaskStoreError,
    TaskSubmission,
    canonical_json,
    content_digest,
)

_T = TypeVar("_T")
_SCHEMA_VERSION = 2
_AUDIT_SCHEMA = """CREATE TABLE task_audit (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at REAL NOT NULL,
    principal_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    app_id TEXT NOT NULL,
    action_id TEXT NOT NULL,
    operation TEXT NOT NULL,
    outcome TEXT NOT NULL,
    request_id TEXT,
    task_id TEXT
)"""
_SCHEMA = (
    """CREATE TABLE tasks (
        task_id TEXT PRIMARY KEY,
        principal_id TEXT NOT NULL,
        workspace_id TEXT NOT NULL,
        app_id TEXT NOT NULL,
        request_id TEXT NOT NULL,
        request_digest TEXT NOT NULL,
        submission_json TEXT NOT NULL,
        UNIQUE(principal_id, workspace_id, app_id, request_id)
    )""",
    """CREATE TABLE executor_runs (
        executor_id TEXT NOT NULL,
        session_id TEXT NOT NULL,
        run_id TEXT NOT NULL,
        task_id TEXT NOT NULL UNIQUE REFERENCES tasks(task_id),
        PRIMARY KEY(executor_id, session_id, run_id)
    )""",
    """CREATE TABLE task_events (
        task_id TEXT NOT NULL REFERENCES tasks(task_id),
        sequence INTEGER NOT NULL,
        event_json TEXT NOT NULL,
        executor_sequence INTEGER,
        executor_digest TEXT,
        PRIMARY KEY(task_id, sequence),
        UNIQUE(task_id, executor_sequence)
    )""",
    """CREATE TABLE task_deliveries (
        task_id TEXT NOT NULL,
        event_sequence INTEGER NOT NULL,
        kind TEXT NOT NULL,
        target_ref TEXT NOT NULL,
        acknowledged INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY(task_id, event_sequence, kind),
        FOREIGN KEY(task_id, event_sequence)
            REFERENCES task_events(task_id, sequence)
    )""",
)


class TaskStore:
    """Open explicitly with ``await TaskStore.open(host_owned_path)``.

    Every task access matches principal, workspace and App. The caller must
    derive that scope from trusted Host context and separately authorize the
    registered action. This is persistence, not a public dispatch endpoint.
    """

    def __init__(self, path: Path):
        self.path = path

    @classmethod
    async def open(cls, path: Path) -> TaskStore:
        store = cls(Path(path))
        await asyncio.to_thread(store._initialize)
        return store

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path,
            timeout=10,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA synchronous = FULL")
        return connection

    def _initialize(self) -> None:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        # Create with private permissions before SQLite creates its journal.
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
            if version in (0, 1):
                connection.execute(_AUDIT_SCHEMA)
                connection.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
            elif version != _SCHEMA_VERSION:
                raise TaskStoreError("unsupported_store_version")
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
    def _get(
        connection: sqlite3.Connection,
        scope: TaskScope,
        task_id: str,
    ) -> TaskSubmission:
        row = connection.execute(
            """SELECT submission_json FROM tasks WHERE task_id = ?
            AND principal_id = ? AND workspace_id = ? AND app_id = ?""",
            (task_id, scope.principal_id, scope.workspace_id, scope.app_id),
        ).fetchone()
        if row is None:
            # Missing and inaccessible IDs deliberately have the same result.
            raise TaskStoreError("task_not_found")
        return TaskSubmission.model_validate_json(row["submission_json"])

    @staticmethod
    def _event(
        connection: sqlite3.Connection,
        submission: TaskSubmission,
        kind: str,
        payload: dict,
        *,
        wake: bool = False,
        source: ExecutorEvent | None = None,
    ) -> TaskSubmission:
        handle = submission.handle.model_copy(
            update={
                "event_sequence": submission.handle.event_sequence + 1,
                "updated_at": time.time(),
            },
        )
        submission = submission.model_copy(update={"handle": handle})
        event = TaskEvent(
            task_id=handle.task_id,
            sequence=handle.event_sequence,
            kind=kind,
            status=handle.status,
            payload=payload,
            created_at=handle.updated_at,
        )
        connection.execute(
            "UPDATE tasks SET submission_json = ? WHERE task_id = ?",
            (submission.model_dump_json(), handle.task_id),
        )
        connection.execute(
            "INSERT INTO task_events VALUES (?, ?, ?, ?, ?)",
            (
                handle.task_id,
                event.sequence,
                event.model_dump_json(),
                source.sequence if source is not None else None,
                (
                    content_digest(source.model_dump(mode="json"))
                    if source is not None
                    else None
                ),
            ),
        )
        origin = handle.origin
        target = (
            origin.return_session_ref
            if origin.engagement == "delegated"
            else origin.app_session_ref
        )
        kinds = ["update"]
        if wake and origin.engagement == "delegated":
            kinds.append("continuation")
        for delivery_kind in kinds:
            connection.execute(
                """INSERT INTO task_deliveries
                (task_id, event_sequence, kind, target_ref)
                VALUES (?, ?, ?, ?)""",
                (handle.task_id, event.sequence, delivery_kind, target),
            )
        return submission

    async def create(
        self,
        scope: TaskScope,
        action: ActionDescriptor,
        *,
        request_id: str,
        inputs: dict,
        origin: TaskOrigin,
    ) -> TaskSubmission:
        """Allocate identities once, before any external submission.

        Retries of a scoped request return its original task. Different
        inputs, descriptor or origin under the same identity are conflicts.
        """
        if not request_id or len(request_id) > 256:
            raise ValueError("request_id must contain 1 to 256 characters")
        # Snapshot nested mutable JSON before handing it to a worker thread.
        action = ActionDescriptor.model_validate_json(action.model_dump_json())
        if action.app_id != scope.app_id:
            raise TaskStoreError("action_scope_mismatch")
        if origin.engagement not in action.engagements:
            raise TaskStoreError("unsupported_engagement")
        action.validate_inputs(inputs)
        # Round-trip into a private object so callers cannot mutate in flight.
        inputs = json.loads(canonical_json(inputs))
        digest = content_digest(
            {
                "action": action.descriptor_digest,
                "inputs": inputs,
                "origin": origin.model_dump(mode="json"),
            },
        )

        def operation(connection: sqlite3.Connection) -> TaskSubmission:
            row = connection.execute(
                """SELECT request_digest, submission_json FROM tasks
                WHERE principal_id = ? AND workspace_id = ? AND app_id = ?
                AND request_id = ?""",
                (
                    scope.principal_id,
                    scope.workspace_id,
                    scope.app_id,
                    request_id,
                ),
            ).fetchone()
            if row is not None:
                if row["request_digest"] != digest:
                    raise TaskStoreError("request_conflict")
                return TaskSubmission.model_validate_json(
                    row["submission_json"],
                )
            now = time.time()
            handle = TaskHandle(
                task_id=str(uuid.uuid4()),
                submission_id=str(uuid.uuid4()),
                scope=scope,
                action_id=action.action_id,
                descriptor_digest=action.descriptor_digest,
                origin=origin,
                created_at=now,
                updated_at=now,
            )
            submission = TaskSubmission(
                handle=handle,
                action=action,
                inputs=inputs,
            )
            connection.execute(
                "INSERT INTO tasks VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    handle.task_id,
                    scope.principal_id,
                    scope.workspace_id,
                    scope.app_id,
                    request_id,
                    digest,
                    submission.model_dump_json(),
                ),
            )
            return self._event(connection, submission, "created", {})

        return await self._run(operation, write=True)

    async def get(self, scope: TaskScope, task_id: str) -> TaskSubmission:
        return await self._run(
            lambda connection: self._get(connection, scope, task_id),
        )

    async def find_request(
        self,
        scope: TaskScope,
        request_id: str,
    ) -> TaskSubmission | None:
        def operation(connection):
            row = connection.execute(
                """SELECT submission_json FROM tasks WHERE principal_id = ?
                AND workspace_id = ? AND app_id = ? AND request_id = ?""",
                (
                    scope.principal_id,
                    scope.workspace_id,
                    scope.app_id,
                    request_id,
                ),
            ).fetchone()
            return (
                TaskSubmission.model_validate_json(row["submission_json"])
                if row
                else None
            )

        return await self._run(operation)

    async def recoverable(
        self,
        *,
        after: str = "",
        limit: int = 100,
    ) -> list[TaskSubmission]:
        """Host lifecycle scan, never exposed as an unscoped HTTP listing."""
        if not 1 <= limit <= 1000:
            raise ValueError("invalid recovery page size")

        def operation(connection):
            rows = connection.execute(
                """SELECT submission_json FROM tasks WHERE task_id > ?
                AND json_extract(submission_json, '$.handle.status')
                NOT IN ('succeeded', 'failed', 'cancelled', 'interrupted')
                ORDER BY task_id LIMIT ?""",
                (after, limit),
            ).fetchall()
            return [TaskSubmission.model_validate_json(row[0]) for row in rows]

        return await self._run(operation)

    async def audit(
        self,
        scope: TaskScope,
        action_id: str,
        operation: str,
        outcome: str,
        *,
        request_id: str | None = None,
        task_id: str | None = None,
    ) -> None:
        """Persist decisions without prompts, credentials or output."""
        await self._run(
            lambda connection: connection.execute(
                """INSERT INTO task_audit
                (created_at, principal_id, workspace_id, app_id, action_id,
                 operation, outcome, request_id, task_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    time.time(),
                    scope.principal_id,
                    scope.workspace_id,
                    scope.app_id,
                    action_id,
                    operation,
                    outcome,
                    request_id,
                    task_id,
                ),
            ).rowcount,
            write=True,
        )

    async def begin_submission(self, scope: TaskScope, task_id: str) -> bool:
        """Persist the send intent. Only the first dispatcher wins.

        A crash after this commit is an uncertain outcome. Recovery must
        query the executor by submission_id, not allocate another identity.
        """

        def operation(connection: sqlite3.Connection) -> bool:
            submission = self._get(connection, scope, task_id)
            handle = submission.handle
            if (
                handle.submission_state != "prepared"
                or handle.status in TERMINAL_STATUSES
            ):
                return False
            handle = handle.model_copy(
                update={"submission_state": "in_flight"},
            )
            self._event(
                connection,
                submission.model_copy(update={"handle": handle}),
                "submission",
                {"state": "in_flight"},
            )
            return True

        return await self._run(operation, write=True)

    async def record_accepted(
        self,
        scope: TaskScope,
        task_id: str,
        run_ref: ExecutorRunRef,
    ) -> TaskSubmission:
        """Bind the original run, even after a lost acceptance response."""

        def operation(connection: sqlite3.Connection) -> TaskSubmission:
            submission = self._get(connection, scope, task_id)
            handle = submission.handle
            if handle.executor_run_ref is not None:
                if handle.executor_run_ref != run_ref:
                    raise TaskStoreError("run_conflict")
                # Reconcile with the same mapping, never replace it.
                if (
                    handle.recovery_state == "none"
                    or handle.status in TERMINAL_STATUSES
                ):
                    return submission
            elif handle.submission_state != "in_flight":
                raise TaskStoreError("submission_not_started")
            try:
                connection.execute(
                    "INSERT OR IGNORE INTO executor_runs VALUES (?, ?, ?, ?)",
                    (
                        run_ref.executor_id,
                        run_ref.session_id,
                        run_ref.run_id,
                        task_id,
                    ),
                )
                owner = connection.execute(
                    """SELECT task_id FROM executor_runs
                    WHERE executor_id = ? AND session_id = ? AND run_id = ?""",
                    (run_ref.executor_id, run_ref.session_id, run_ref.run_id),
                ).fetchone()
                if owner is None or owner["task_id"] != task_id:
                    raise TaskStoreError("run_conflict")
            except sqlite3.IntegrityError as exc:
                raise TaskStoreError("run_conflict") from exc
            handle = handle.model_copy(
                update={
                    "submission_state": "accepted",
                    "executor_run_ref": run_ref,
                    "recovery_state": "none",
                    "recovery_reason": None,
                },
            )
            return self._event(
                connection,
                submission.model_copy(update={"handle": handle}),
                "submission",
                {"state": "accepted", "run_ref": run_ref.model_dump()},
            )

        return await self._run(operation, write=True)

    async def mark_recovery(
        self,
        scope: TaskScope,
        task_id: str,
        *,
        state: RecoveryState,
        reason: str,
    ) -> TaskSubmission:
        """Record EOF/unknown outcomes without inventing a terminal status."""
        if state not in {"reconciling", "unresolved"} or not reason:
            raise ValueError("recovery requires a pending state and reason")

        def operation(connection: sqlite3.Connection) -> TaskSubmission:
            submission = self._get(connection, scope, task_id)
            handle = submission.handle
            if handle.status in TERMINAL_STATUSES:
                return submission
            if (
                handle.recovery_state == state
                and handle.recovery_reason == reason
            ):
                return submission
            handle = handle.model_copy(
                update={"recovery_state": state, "recovery_reason": reason},
            )
            return self._event(
                connection,
                submission.model_copy(update={"handle": handle}),
                "recovery",
                {"state": state, "reason": reason},
            )

        return await self._run(operation, write=True)

    async def apply_event(
        self,
        scope: TaskScope,
        task_id: str,
        event: ExecutorEvent,
    ) -> TaskSubmission:
        """Commit result, status, sequences, cursor and outbox atomically."""
        event = ExecutorEvent.model_validate_json(
            canonical_json(event.model_dump(mode="json")),
        )
        digest = content_digest(event.model_dump(mode="json"))

        def operation(connection: sqlite3.Connection) -> TaskSubmission:
            submission = self._get(connection, scope, task_id)
            handle = submission.handle
            if event.run_ref != handle.executor_run_ref:
                raise TaskStoreError("run_conflict")
            previous = connection.execute(
                """SELECT executor_digest FROM task_events
                WHERE task_id = ? AND executor_sequence = ?""",
                (task_id, event.sequence),
            ).fetchone()
            if previous is not None:
                if previous["executor_digest"] != digest:
                    raise TaskStoreError("event_conflict")
                return submission
            if handle.status in TERMINAL_STATUSES:
                raise TaskStoreError("task_terminal")
            if (
                handle.executor_sequence is not None
                and event.sequence <= handle.executor_sequence
            ):
                raise TaskStoreError("event_out_of_order")
            status = event.status or handle.status
            if status == "pending" and handle.status != "pending":
                raise TaskStoreError("invalid_transition")
            result = (
                event.text_result
                if event.text_result is not None
                else handle.text_result
            )
            if status == "succeeded" and result is None:
                raise TaskStoreError("result_required")
            wake = (
                status != handle.status
                and status in TERMINAL_STATUSES | WAITING_STATUSES
            )
            handle = handle.model_copy(
                update={
                    "status": status,
                    "text_result": result,
                    "replay_cursor": event.cursor,
                    "executor_sequence": event.sequence,
                    "recovery_state": "none",
                    "recovery_reason": None,
                },
            )
            return self._event(
                connection,
                submission.model_copy(update={"handle": handle}),
                "executor",
                event.model_dump(mode="json"),
                wake=wake,
                source=event,
            )

        return await self._run(operation, write=True)

    async def events(
        self,
        scope: TaskScope,
        task_id: str,
        *,
        after: int = 0,
        limit: int = 100,
    ) -> list[TaskEvent]:
        if after < 0 or not 1 <= limit <= 1000:
            raise ValueError("invalid event page")

        def operation(connection: sqlite3.Connection) -> list[TaskEvent]:
            self._get(connection, scope, task_id)
            rows = connection.execute(
                """SELECT event_json FROM task_events WHERE task_id = ?
                AND sequence > ? ORDER BY sequence LIMIT ?""",
                (task_id, after, limit),
            ).fetchall()
            return [
                TaskEvent.model_validate_json(row["event_json"])
                for row in rows
            ]

        return await self._run(operation)

    async def pending_deliveries(
        self,
        scope: TaskScope,
        task_id: str,
        *,
        limit: int = 100,
    ) -> list[TaskDelivery]:
        if not 1 <= limit <= 1000:
            raise ValueError("invalid delivery page")

        def operation(connection: sqlite3.Connection) -> list[TaskDelivery]:
            self._get(connection, scope, task_id)
            rows = connection.execute(
                """SELECT task_id, event_sequence, kind, target_ref
                FROM task_deliveries WHERE task_id = ? AND acknowledged = 0
                ORDER BY event_sequence, kind LIMIT ?""",
                (task_id, limit),
            ).fetchall()
            return [TaskDelivery.model_validate(dict(row)) for row in rows]

        return await self._run(operation)

    async def acknowledge(
        self,
        scope: TaskScope,
        delivery: TaskDelivery,
    ) -> None:
        """Acknowledge after the target durably records this event identity.

        This is a delivery receipt, not an exactly-once LLM/tool execution
        guarantee. A future worker must fence its own output commits.
        """

        def operation(connection: sqlite3.Connection) -> None:
            self._get(connection, scope, delivery.task_id)
            cursor = connection.execute(
                """UPDATE task_deliveries SET acknowledged = 1
                WHERE task_id = ? AND event_sequence = ? AND kind = ?
                AND target_ref = ?""",
                (
                    delivery.task_id,
                    delivery.event_sequence,
                    delivery.kind,
                    delivery.target_ref,
                ),
            )
            if cursor.rowcount != 1:
                raise TaskStoreError("delivery_not_found")

        await self._run(operation, write=True)
