# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Leased continuation jobs sharing the task/outbox transaction."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from typing import Callable

from .contracts import (
    TaskOrigin,
    TaskScope,
    TaskStoreError,
    TaskSubmission,
    canonical_json,
    content_digest,
)

_SCHEMA = """CREATE TABLE IF NOT EXISTS task_continuations (
    task_id TEXT NOT NULL,
    event_sequence INTEGER NOT NULL,
    principal_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    target_ref TEXT NOT NULL,
    summary_json TEXT NOT NULL,
    created_at REAL NOT NULL,
    lease_token TEXT,
    lease_until REAL NOT NULL DEFAULT 0,
    retry_at REAL NOT NULL DEFAULT 0,
    attempts INTEGER NOT NULL DEFAULT 0,
    generation_attempts INTEGER NOT NULL DEFAULT 0,
    prepared_json TEXT,
    committed_at REAL,
    abandoned_at REAL,
    last_error TEXT,
    PRIMARY KEY(task_id, event_sequence),
    FOREIGN KEY(task_id, event_sequence)
        REFERENCES task_events(task_id, sequence)
)"""


def enqueue(connection, handle, *, sequence=None, status=None, text=None):
    """Called within the transaction that records a delegated transition."""
    result = handle.text_result if text is None else text
    summary = {
        "app_id": handle.scope.app_id,
        "action_id": handle.action_id,
        "task_id": handle.task_id,
        "status": status or handle.status,
        "text_result": result[:16000] if result else result,
        "text_truncated": bool(result and len(result) > 16000),
    }
    connection.execute(
        """INSERT OR IGNORE INTO task_continuations
        (task_id, event_sequence, principal_id, workspace_id, target_ref,
         summary_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            handle.task_id,
            sequence or handle.event_sequence,
            handle.scope.principal_id,
            handle.scope.workspace_id,
            handle.origin.return_session_ref,
            canonical_json(summary),
            handle.updated_at,
        ),
    )


def migrate(connection):
    connection.execute(_SCHEMA)
    connection.execute(
        """CREATE INDEX IF NOT EXISTS task_continuations_pending
        ON task_continuations(committed_at, retry_at, lease_until)""",
    )
    rows = connection.execute(
        """SELECT t.submission_json, d.event_sequence, e.event_json
        FROM task_deliveries d JOIN tasks t USING (task_id)
        JOIN task_events e ON e.task_id = d.task_id
          AND e.sequence = d.event_sequence
        WHERE d.kind = 'continuation' AND d.acknowledged = 0""",
    ).fetchall()
    for row in rows:
        handle = TaskSubmission.model_validate_json(
            row["submission_json"],
        ).handle
        event = json.loads(row["event_json"])
        # Old outboxes did not snapshot the inherited text. Never pair a
        # later terminal result with an earlier waiting event during migration.
        text = event["payload"].get("text_result")
        if text is None and event["status"] != handle.status:
            text = ""
        enqueue(
            connection,
            handle,
            sequence=row["event_sequence"],
            status=event["status"],
            text=text,
        )


@dataclass(frozen=True)
class ContinuationClaim:
    task_id: str
    event_sequence: int
    token: str
    scope: TaskScope
    origin: TaskOrigin
    summary: dict
    prepared: dict | None

    @property
    def run_id(self):
        return "pawapp_" + content_digest(
            [
                self.scope.model_dump(),
                self.task_id,
                self.event_sequence,
                self.origin.return_session_ref,
            ],
        )


class ContinuationQueue:
    """Host queue. Token and expiry fence writes and destination commits.

    Session persistence happens while the SQLite write lock fences other
    workers. The session embeds its own receipt before outbox acknowledgment,
    so a crash between the two stores is recoverable without another append.
    """

    def __init__(self, store, *, lease_seconds=60.0, clock=time.time):
        if lease_seconds <= 0:
            raise ValueError("lease must be positive")
        self.store = store
        self.lease_seconds = lease_seconds
        self.clock = clock

    async def claim(self):
        def operation(connection):
            now = self.clock()
            row = connection.execute(
                """SELECT j.*, t.submission_json FROM task_continuations j
                JOIN tasks t USING(task_id)
                WHERE j.committed_at IS NULL AND j.abandoned_at IS NULL
                  AND j.retry_at <= ?
                  AND j.lease_until <= ?
                  AND NOT EXISTS (
                    SELECT 1 FROM task_continuations earlier
                    WHERE earlier.committed_at IS NULL
                      AND earlier.abandoned_at IS NULL
                      AND earlier.principal_id = j.principal_id
                      AND earlier.workspace_id = j.workspace_id
                      AND earlier.target_ref = j.target_ref
                      AND (
                        earlier.lease_until > ? OR
                        (earlier.created_at, earlier.task_id,
                         earlier.event_sequence) <
                        (j.created_at, j.task_id, j.event_sequence)
                      )
                  )
                ORDER BY j.created_at, j.task_id, j.event_sequence LIMIT 1""",
                (now, now, now),
            ).fetchone()
            if row is None:
                return None
            token = uuid.uuid4().hex
            connection.execute(
                """UPDATE task_continuations SET lease_token = ?,
                lease_until = ?, attempts = attempts + 1
                WHERE task_id = ? AND event_sequence = ?""",
                (
                    token,
                    now + self.lease_seconds,
                    row["task_id"],
                    row["event_sequence"],
                ),
            )
            handle = TaskSubmission.model_validate_json(
                row["submission_json"],
            ).handle
            return ContinuationClaim(
                row["task_id"],
                row["event_sequence"],
                token,
                handle.scope,
                handle.origin,
                json.loads(row["summary_json"]),
                json.loads(row["prepared_json"])
                if row["prepared_json"]
                else None,
            )

        return await self.store._run(operation, write=True)

    def _owned(self, connection, claim):
        row = connection.execute(
            """SELECT * FROM task_continuations WHERE task_id = ?
            AND event_sequence = ? AND lease_token = ? AND lease_until > ?
            AND committed_at IS NULL""",
            (claim.task_id, claim.event_sequence, claim.token, self.clock()),
        ).fetchone()
        if row is None:
            raise TaskStoreError("continuation_lease_lost")
        return row

    async def renew(self, claim):
        def operation(connection):
            self._owned(connection, claim)
            connection.execute(
                """UPDATE task_continuations SET lease_until = ?
                WHERE task_id = ? AND event_sequence = ?""",
                (
                    self.clock() + self.lease_seconds,
                    claim.task_id,
                    claim.event_sequence,
                ),
            )

        await self.store._run(operation, write=True)

    async def prepare(self, claim, prepared):
        encoded = canonical_json(prepared)

        def operation(connection):
            row = self._owned(connection, claim)
            if row["prepared_json"] not in (None, encoded):
                raise TaskStoreError("continuation_result_conflict")
            connection.execute(
                """UPDATE task_continuations SET prepared_json = ?
                WHERE task_id = ? AND event_sequence = ?""",
                (encoded, claim.task_id, claim.event_sequence),
            )

        await self.store._run(operation, write=True)

    async def begin_generation(self, claim):
        def operation(connection):
            row = self._owned(connection, claim)
            if row["generation_attempts"] >= 3:
                raise TaskStoreError("continuation_retry_exhausted")
            connection.execute(
                """UPDATE task_continuations
                SET generation_attempts = generation_attempts + 1
                WHERE task_id = ? AND event_sequence = ?""",
                (claim.task_id, claim.event_sequence),
            )

        await self.store._run(operation, write=True)

    async def release(self, claim, *, reason, delay=5.0):
        def operation(connection):
            # An expired worker must never release its successor's lease.
            connection.execute(
                """UPDATE task_continuations SET lease_token = NULL,
                lease_until = 0, retry_at = ?, last_error = ?, abandoned_at = ?
                WHERE task_id = ? AND event_sequence = ? AND lease_token = ?
                AND committed_at IS NULL""",
                (
                    self.clock() + delay,
                    reason,
                    self.clock()
                    if reason
                    in {
                        "continuation_retry_exhausted",
                        "continuation_cancelled",
                    }
                    else None,
                    claim.task_id,
                    claim.event_sequence,
                    claim.token,
                ),
            )

        await self.store._run(operation, write=True)

    async def commit(self, claim, destination: Callable[[dict], None]):
        def operation(connection):
            row = self._owned(connection, claim)
            if row["prepared_json"] is None:
                raise TaskStoreError("continuation_not_prepared")
            destination(json.loads(row["prepared_json"]))
            # The lock prevents another worker from claiming while the
            # destination write runs. Recheck expiry before accepting it.
            self._owned(connection, claim)
            connection.execute(
                """UPDATE task_continuations SET committed_at = ?,
                lease_token = NULL, lease_until = 0, last_error = NULL
                WHERE task_id = ? AND event_sequence = ?""",
                (self.clock(), claim.task_id, claim.event_sequence),
            )
            connection.execute(
                """UPDATE task_deliveries SET acknowledged = 1
                WHERE task_id = ? AND event_sequence = ?
                AND kind = 'continuation'""",
                (claim.task_id, claim.event_sequence),
            )

        await self.store._run(operation, write=True)
