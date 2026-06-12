# -*- coding: utf-8 -*-
"""AuditLog — Audit records for each assert_and_audit call.

Storage: single-file SQLite (~/.qwenpaw/audit.db), global singleton.
- record() writes immediately, no in-memory buffer
- query() supports filtering by workspace / agent / tool / decision / time range, with pagination
- purge() deletes expired records and VACUUMs to reclaim space
- Auto-cleanup: when total records reach 100k, deletes the oldest 10k
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

from ..constant import WORKING_DIR

from .policy import GovernanceDecision, ToolCallSpec

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS audit_events (
    ts            TEXT NOT NULL,
    workspace_dir TEXT NOT NULL,
    agent_id      TEXT NOT NULL,
    session_id    TEXT NOT NULL,
    tool_name     TEXT NOT NULL,
    target        TEXT NOT NULL,
    decision      TEXT NOT NULL,
    reason        TEXT NOT NULL DEFAULT '',
    extra         TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_events(ts);
CREATE INDEX IF NOT EXISTS idx_audit_workspace ON audit_events(workspace_dir);
CREATE INDEX IF NOT EXISTS idx_audit_agent ON audit_events(agent_id);
CREATE INDEX IF NOT EXISTS idx_audit_tool ON audit_events(tool_name);
"""


@dataclass
class AuditEvent:
    """A single audit record.

    Records 5W: who (agent_id), what (tool_name + target),
    when (ts), outcome (decision), why (reason).
    """
    ts: str                          # ISO 8601 UTC
    workspace_dir: str
    agent_id: str
    session_id: str
    tool_name: str
    target: str
    decision: str                    # "allow" | "deny" | "ask" | "sandbox_fallback"
    reason: str = ""                 # Additional explanation (e.g. violation cause)
    extra: dict = field(default_factory=dict)


def _event_from_row(row: sqlite3.Row) -> AuditEvent:
    """Construct an AuditEvent from a SQLite row."""
    return AuditEvent(
        ts=row["ts"],
        workspace_dir=row["workspace_dir"],
        agent_id=row["agent_id"],
        session_id=row["session_id"],
        tool_name=row["tool_name"],
        target=row["target"],
        decision=row["decision"],
        reason=row["reason"],
        extra=json.loads(row["extra"]),
    )


class AuditLog:
    """Append-only audit log, SQLite-backed, global singleton.

    Shared by multiple ResourceGovernor instances; each assert_and_audit
    call invokes record() which writes to the database immediately.
    """

    MAX_RECORDS = 100_000       # Threshold to trigger auto-cleanup
    PURGE_COUNT = 10_000        # Number of records to delete per cleanup
    _CHECK_INTERVAL = 1_000     # Check if cleanup is needed every N records

    _instance: Optional[AuditLog] = None

    @classmethod
    def get_instance(cls) -> AuditLog:
        """Get the global singleton, initializing on first call."""
        if cls._instance is None:
            db_path = WORKING_DIR / "governance" / "audit.db"
            cls._instance = cls._create(db_path)
        return cls._instance

    @classmethod
    def _create(cls, db_path: Path) -> AuditLog:
        """Internal factory method: create instance and initialize database."""
        obj = object.__new__(cls)
        obj._db_path = db_path
        obj._db_path.parent.mkdir(parents=True, exist_ok=True)
        obj._conn = sqlite3.connect(
            str(obj._db_path), check_same_thread=False
        )
        obj._conn.row_factory = sqlite3.Row
        obj._conn.execute("PRAGMA journal_mode=WAL")
        obj._conn.executescript(_SCHEMA)
        obj._conn.commit()
        obj._insert_count = 0
        return obj

    def close(self) -> None:
        """Close the database connection and reset the singleton."""
        if self._conn:
            self._conn.close()
            self._conn = None
        AuditLog._instance = None

    def record(self, workspace_dir: str, tc_spec: ToolCallSpec,
               decision: GovernanceDecision) -> None:
        """Record a policy decision, writing to SQLite immediately.

        Args:
            workspace_dir: Workspace path this event belongs to
            tc_spec: ToolCallSpec instance
            decision: GovernanceDecision instance (action + reason)
        """
        self._conn.execute(
            "INSERT INTO audit_events "
            "(ts, workspace_dir, agent_id, session_id, tool_name, target, decision, reason, extra) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                datetime.now(timezone.utc).isoformat(),
                workspace_dir,
                tc_spec.agent_id,
                tc_spec.session_id,
                tc_spec.tool_name,
                tc_spec.target,
                str(decision.action.value),
                decision.reason,
                "{}",
            ),
        )
        self._conn.commit()

        # Auto-cleanup check
        self._insert_count += 1
        if self._insert_count >= self._CHECK_INTERVAL:
            self._insert_count = 0
            if self.count >= self.MAX_RECORDS:
                self._auto_purge()

    def query(
        self,
        workspace_dir: Optional[str] = None,
        agent_id: Optional[str] = None,
        tool_name: Optional[str] = None,
        decision: Optional[str] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Tuple[List[AuditEvent], int]:
        """Query audit events with pagination.

        Args:
            workspace_dir: Filter by workspace
            agent_id: Filter by agent
            tool_name: Filter by tool name
            decision: Filter by decision result
            since: Start time (ISO 8601), inclusive
            until: End time (ISO 8601), inclusive
            limit: Page size
            offset: Offset (for pagination)

        Returns:
            (events, total) — event list and total count of matching records
        """
        clauses: list[str] = []
        params: list = []

        if workspace_dir:
            clauses.append("workspace_dir = ?")
            params.append(workspace_dir)
        if agent_id:
            clauses.append("agent_id = ?")
            params.append(agent_id)
        if tool_name:
            clauses.append("tool_name = ?")
            params.append(tool_name)
        if decision:
            clauses.append("decision = ?")
            params.append(decision)
        if since:
            clauses.append("ts >= ?")
            params.append(since)
        if until:
            clauses.append("ts <= ?")
            params.append(until)

        where = " WHERE " + " AND ".join(clauses) if clauses else ""

        # Total count
        count_sql = f"SELECT COUNT(*) FROM audit_events{where}"
        total = self._conn.execute(count_sql, params).fetchone()[0]

        # Paginated query
        data_sql = f"SELECT * FROM audit_events{where} ORDER BY ts DESC LIMIT ? OFFSET ?"
        data_params = params + [limit, offset]
        rows = self._conn.execute(data_sql, data_params).fetchall()

        return [_event_from_row(r) for r in rows], total

    def purge(self, before: str) -> int:
        """Delete records before the specified time and VACUUM to reclaim space.

        Args:
            before: Cutoff time (ISO 8601), exclusive

        Returns:
            Number of deleted records
        """
        cursor = self._conn.execute(
            "DELETE FROM audit_events WHERE ts < ?", (before,)
        )
        self._conn.commit()
        deleted = cursor.rowcount
        if deleted > 0:
            self._conn.execute("VACUUM")
        return deleted

    @property
    def count(self) -> int:
        """Total number of records."""
        return self._conn.execute(
            "SELECT COUNT(*) FROM audit_events"
        ).fetchone()[0]

    def _auto_purge(self) -> None:
        """Delete the oldest PURGE_COUNT records and VACUUM."""
        row = self._conn.execute(
            "SELECT rowid FROM audit_events ORDER BY rowid ASC LIMIT 1 OFFSET ?",
            (self.PURGE_COUNT,),
        ).fetchone()
        if row:
            self._conn.execute(
                "DELETE FROM audit_events WHERE rowid <= ?", (row["rowid"],)
            )
            self._conn.commit()
            self._conn.execute("VACUUM")
