# -*- coding: utf-8 -*-
"""Lightweight operational telemetry for QwenPaw Hub."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psutil


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class HubOperationsStore:
    """Persist audit events and collect inexpensive host metrics."""

    def __init__(self, database_path: Path, data_root: Path) -> None:
        self.database_path = database_path
        self.data_root = data_root
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
                CREATE TABLE IF NOT EXISTS hub_audit_events (
                    event_id TEXT PRIMARY KEY,
                    actor_user_id TEXT NOT NULL,
                    actor_username TEXT NOT NULL,
                    action TEXT NOT NULL,
                    resource_type TEXT NOT NULL,
                    resource_id TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    detail_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """,
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_hub_audit_created "
                "ON hub_audit_events(created_at DESC)",
            )

    def record(
        self,
        *,
        actor_user_id: str,
        actor_username: str,
        action: str,
        resource_type: str,
        resource_id: str,
        outcome: str = "success",
        detail: dict[str, Any] | None = None,
    ) -> None:
        """Append one sanitized Hub management event."""
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO hub_audit_events(
                    event_id, actor_user_id, actor_username, action,
                    resource_type, resource_id, outcome, detail_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid.uuid4().hex,
                    actor_user_id,
                    actor_username,
                    action,
                    resource_type,
                    resource_id,
                    outcome,
                    json.dumps(
                        detail or {},
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    _now(),
                ),
            )

    def list_events(
        self,
        *,
        page: int,
        page_size: int,
        query: str | None = None,
        action: str | None = None,
        outcome: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """Return one filtered audit page without secret data."""
        clauses: list[str] = []
        parameters: list[object] = []
        if query:
            clauses.append(
                "(actor_username LIKE ? OR resource_id LIKE ?)",
            )
            pattern = f"%{query}%"
            parameters.extend([pattern, pattern])
        if action:
            clauses.append("action = ?")
            parameters.append(action)
        if outcome:
            clauses.append("outcome = ?")
            parameters.append(outcome)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as connection:
            total_row = connection.execute(
                "SELECT COUNT(*) AS count FROM hub_audit_events" f"{where}",
                parameters,
            ).fetchone()
            rows = connection.execute(
                "SELECT * FROM hub_audit_events"
                f"{where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (*parameters, page_size, (page - 1) * page_size),
            ).fetchall()
        return [self._event_from_row(row) for row in rows], int(
            total_row["count"],
        )

    def host_metrics(self) -> dict[str, float]:
        """Collect portable host utilization percentages."""
        return {
            "cpu_percent": round(float(psutil.cpu_percent()), 1),
            "memory_percent": round(
                float(psutil.virtual_memory().percent),
                1,
            ),
            "disk_percent": round(
                float(psutil.disk_usage(self.data_root).percent),
                1,
            ),
        }

    @staticmethod
    def _event_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "event_id": str(row["event_id"]),
            "actor_user_id": str(row["actor_user_id"]),
            "actor_username": str(row["actor_username"]),
            "action": str(row["action"]),
            "resource_type": str(row["resource_type"]),
            "resource_id": str(row["resource_id"]),
            "outcome": str(row["outcome"]),
            "detail": json.loads(str(row["detail_json"])),
            "created_at": str(row["created_at"]),
        }
