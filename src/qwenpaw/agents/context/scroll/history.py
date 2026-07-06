# -*- coding: utf-8 -*-
"""Durable, file-backed conversation history shared across sessions."""

from __future__ import annotations

import json
import logging
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..types import LogEntry

logger = logging.getLogger(__name__)

_BUSY_TIMEOUT_MS = 5000

# The recall tool's own turns — the model's ``ms.*`` Python source and its
# printed stdout/stderr — are written through to history like any turn, but
# they are the agent *reading* memory, not memory content. Keyword-indexing
# them lets a later ``ms.search`` match the agent's own past queries (and their
# tracebacks), drowning the real content: a self-pollution feedback loop. So
# these rows stay durable + recallable by ``seq``, but are kept OUT of the FTS
# index (and out of ``search`` — see ``MemorySpace``). Must match the recall
# tool name in ``repl.py``; the legacy "execute_python" name is kept so rows
# written before the rename stay excluded.
_RECALL_TOOL_NAMES = ("recall_history_python", "execute_python")

# Columns of conversation_history, in INSERT order (minus the
# autoincrement seq).
_INSERT_COLUMNS = (
    "session_id",
    "agent_id",
    "kind",
    "role",
    "name",
    "content",
    "tool_call_id",
    "tool_input",
    "tool_state",
    "headline",
    "blocks",
    "metadata",
    "created_at",
    "dedup_key",
)


class HistoryStore:
    """Owns the *read-write* connection to the ``conversation_history`` file.

    Every event the agent appends is write-through-persisted here with full
    structure (blocks, tool args, state) so a later session can retrieve it.
    The model reaches the same file *read-only* through its ``MemorySpace``
    (ATTACHed ``hist`` schema), so this writer and those readers coexist under
    WAL. The file is never dropped; ``close()`` only closes this connection.
    """

    # FTS5 is a property of the SQLite build, not of one DB — warn at most once
    # per process when it's missing, so a long-lived server doesn't log-spam.
    _fts_unavailable_warned = False

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path).expanduser()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self.quarantined_to: Path | None = None
        # Durability health: flipped True the first time a write-through fails
        # (disk/SQLite error). The durability promise no longer holds while
        # degraded; callers/monitoring can read this.
        self.degraded = False
        self.write_failures = 0
        # Flipped True by ``close()`` so callers can tell an intentional
        # teardown race from a real disk outage (see ``closed``).
        self._closed = False
        try:
            self._open_and_init()
        except sqlite3.DatabaseError as exc:
            # A corrupt / unreadable DB (truncated file, stale WAL trio, bad
            # page) would crash every task at startup. Quarantine the bad file
            # and recreate fresh, degrading "broken memory" to "lost history".
            self._quarantine(exc)
            self._open_and_init()

    def _open_and_init(self) -> None:
        self._conn = sqlite3.connect(str(self._path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
        # Probe for corruption that only surfaces on read.
        row = self._conn.execute("PRAGMA quick_check").fetchone()
        if not row or row[0] != "ok":
            raise sqlite3.DatabaseError(
                f"quick_check failed: {row[0] if row else None}",
            )
        self._init_schema()

    def _quarantine(self, exc: Exception) -> None:
        """Move the unreadable DB + its -wal/-shm aside with a timestamp."""
        try:
            self._conn.close()
        except (AttributeError, sqlite3.Error):
            pass
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        for suffix in ("", "-wal", "-shm"):
            src = Path(str(self._path) + suffix)
            if not src.exists():
                continue
            dest = Path(f"{self._path}.corrupt-{ts}{suffix}")
            try:
                src.rename(dest)
                if suffix == "":
                    self.quarantined_to = dest
            except OSError:
                try:
                    src.unlink()  # last resort so a fresh DB can be created
                except OSError:
                    pass
        print(
            f"[HistoryStore] {self._path} was unreadable ({exc}); quarantined "
            f"to {self.quarantined_to} and recreated a fresh store.",
            file=sys.stderr,
        )

    @property
    def path(self) -> Path:
        return self._path

    def _init_schema(self) -> None:
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS conversation_history (
                    seq          INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id   TEXT NOT NULL,
                    agent_id     TEXT,
                    kind         TEXT NOT NULL,
                    role         TEXT,
                    name         TEXT,
                    content      TEXT,
                    tool_call_id TEXT,
                    tool_input   TEXT,
                    tool_state   TEXT,
                    headline     TEXT,
                    blocks       TEXT,
                    metadata     TEXT,
                    created_at   TEXT,
                    dedup_key    TEXT
                )
                """,
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS ch_session "
                "ON conversation_history(session_id)",
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS ch_agent "
                "ON conversation_history(agent_id)",
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS ch_kind "
                "ON conversation_history(kind)",
            )
            # Idempotency net: a second append of the same logical event (a
            # resume re-persisting its restored window, or the cap middleware
            # racing the manager) collides here and is dropped by ON CONFLICT
            # rather than duplicating a row. NULL dedup_key never conflicts, so
            # un-keyed rows are simply never deduped.
            self._conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_dedup "
                "ON conversation_history(session_id, dedup_key)",
            )
            self._init_fts()

    def _init_fts(self) -> None:
        """Create the FTS5 full-text index over ``content``, if available.

        External-content FTS5 indexes without duplicating the text; it is kept
        in sync by ``append``/``update_entry``. On a pre-existing DB it is
        back-filled once via 'rebuild'. Porter stemming on top of unicode61
        casefolding so "tanks" matches "tank".

        Attempting the ``CREATE VIRTUAL TABLE`` is itself the availability
        probe: SQLite builds without the FTS5 module (some minimal
        container/distro builds) raise ``no such module: fts5`` here. We catch
        that, leave ``self._fts`` False so the write path skips FTS upkeep, and
        log one warning — search then degrades to a LIKE scan (see
        ``MemorySpace.search``). The store itself stays fully functional.
        """
        try:
            existed = self._conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='conversation_history_fts'",
            ).fetchone()
            self._conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS conversation_history_fts "
                "USING fts5(content, content='conversation_history', "
                "content_rowid='seq', tokenize='porter unicode61')",
            )
            if not existed:
                self._conn.execute(
                    "INSERT INTO conversation_history_fts"
                    "(conversation_history_fts) VALUES('rebuild')",
                )
            self._fts = True
        except sqlite3.OperationalError as exc:
            self._fts = False
            if not HistoryStore._fts_unavailable_warned:
                HistoryStore._fts_unavailable_warned = True
                logger.warning(
                    "SQLite has no FTS5 module (%s); scroll history keyword "
                    "search degrades to a slower LIKE scan. The history store "
                    "is otherwise fully functional. Use a SQLite build with "
                    "FTS5 to restore ranked full-text recall.",
                    exc,
                )

    # --- write path ----------------------------------------------------

    def append(
        self,
        *,
        session_id: str,
        entry: LogEntry,
        agent_id: str | None = None,
        dedup_key: str | None = None,
    ) -> int:
        """Write-through one event. Returns the assigned ``seq`` (watermark).

        ``dedup_key`` is the row's stable identity within the session (the
        source ``msg.id`` for a turn, the ``tool_call_id`` for a result). A
        second append carrying the same ``(session_id, dedup_key)`` is a no-op
        and returns the *existing* seq, so a resume that re-persists its
        restored window can re-link bookkeeping without duplicating rows. A
        ``None`` key is never deduped.
        """
        row = (
            session_id,
            agent_id,
            entry.kind,
            entry.role,
            entry.name,
            entry.content,
            entry.tool_call_id,
            _to_json(entry.tool_input),
            entry.tool_state,
            entry.headline,
            _to_json(entry.blocks),
            _to_json(entry.metadata or None),
            entry.created_at or datetime.now(timezone.utc).isoformat(),
            dedup_key,
        )
        placeholders = ", ".join("?" for _ in _INSERT_COLUMNS)
        with self._conn:
            cur = self._conn.execute(
                f"INSERT INTO conversation_history "
                f"({', '.join(_INSERT_COLUMNS)}) VALUES ({placeholders}) "
                f"ON CONFLICT(session_id, dedup_key) DO NOTHING",
                row,
            )
            if cur.rowcount == 0:
                # Conflict: this event is already durable. Return its seq so
                # the caller re-links to the existing row; no new row, no FTS
                # write.
                existing = self._conn.execute(
                    "SELECT seq FROM conversation_history "
                    "WHERE session_id = ? AND dedup_key = ?",
                    (session_id, dedup_key),
                ).fetchone()
                return int(existing["seq"]) if existing else 0
            seq = int(cur.lastrowid or 0)
            if self._fts and entry.name not in _RECALL_TOOL_NAMES:
                self._conn.execute(
                    "INSERT INTO conversation_history_fts(rowid, content) "
                    "VALUES (?, ?)",
                    (seq, entry.content or ""),
                )
            return seq

    def update_entry(
        self,
        seq: int,
        *,
        content: str | None,
        headline: str | None,
        blocks,
        tool_call_id: str | None = None,
        name: str | None = None,
        tool_state: str | None = None,
        tool_input: Any = None,
    ) -> None:
        """Refresh an already-appended row in place (keeping FTS in sync).

        Used when one logical turn is *extended* after first write: AgentScope
        accumulates a whole reply into a single assistant Msg, so the durable
        row must end up with every cell's blocks and any later-emitted
        headline. The scalar ``tool_call_id``/``name``/``tool_state``/
        ``tool_input`` are refreshed too, so a turn that grows a *later* tool
        call doesn't leave them frozen at their first-write values. ``seq`` is
        unchanged.
        """
        # Recall-tool rows are never FTS-indexed (see ``_RECALL_TOOL_NAMES``),
        # so don't touch the index for them on update either.
        fts_sync = self._fts and name not in _RECALL_TOOL_NAMES
        with self._conn:
            old_content = None
            if fts_sync:
                r = self._conn.execute(
                    "SELECT content FROM conversation_history WHERE seq = ?",
                    (seq,),
                ).fetchone()
                old_content = r["content"] if r else None
            self._conn.execute(
                "UPDATE conversation_history SET content = ?, headline = ?, "
                "blocks = ?, tool_call_id = ?, name = ?, tool_state = ?, "
                "tool_input = ? WHERE seq = ?",
                (
                    content,
                    headline,
                    _to_json(blocks),
                    tool_call_id,
                    name,
                    tool_state,
                    _to_json(tool_input),
                    seq,
                ),
            )
            if fts_sync:
                if old_content is not None:
                    self._conn.execute(
                        "INSERT INTO conversation_history_fts"
                        "(conversation_history_fts, rowid, content) "
                        "VALUES('delete', ?, ?)",
                        (seq, old_content),
                    )
                self._conn.execute(
                    "INSERT INTO conversation_history_fts(rowid, content) "
                    "VALUES (?, ?)",
                    (seq, content or ""),
                )

    # --- read path -----------------------------------------------------

    def count(self, session_id: str) -> int:
        cur = self._conn.execute(
            "SELECT COUNT(*) AS n FROM conversation_history "
            "WHERE session_id = ?",
            (session_id,),
        )
        return int(cur.fetchone()["n"])

    @staticmethod
    def _purge_where(
        before: str,
        kinds: tuple[str, ...] | None,
    ) -> tuple[str, list]:
        """Build the shared ``WHERE`` for purge/estimate so they can't drift.

        Always bounds by ``created_at < before`` (NULL ``created_at`` is never
        matched, so unstamped rows are retained). When ``kinds`` is given, also
        restricts to those row kinds (e.g. ``("tool_result",)`` to drop only
        tool output and keep the conversation). Values are bound, never
        interpolated.
        """
        clause = "created_at IS NOT NULL AND created_at < ?"
        params: list = [before]
        if kinds:
            placeholders = ", ".join("?" for _ in kinds)
            clause += f" AND kind IN ({placeholders})"
            params.extend(kinds)
        return clause, params

    def estimate_purge(
        self,
        *,
        before: str,
        kinds: tuple[str, ...] | None = None,
    ) -> dict:
        """How much ``purge(before=...)`` would remove — WITHOUT removing it.

        Returns ``{"rows": n, "content_bytes": b}`` where ``content_bytes`` is
        the summed length of the ``content`` column for the matched rows (the
        bulk of the on-disk weight; the FTS index roughly mirrors it, so true
        reclaim is larger). ``kinds`` narrows to specific row kinds (e.g.
        ``("tool_result",)`` to size only tool output). A dry-run estimate to
        show before an operator commits a purge, so they never delete blindly.
        """
        where, params = self._purge_where(before, kinds)
        with self._conn:
            row = self._conn.execute(
                "SELECT COUNT(*) AS rows, "
                "COALESCE(SUM(LENGTH(content)), 0) AS content_bytes "
                "FROM conversation_history WHERE " + where,
                params,
            ).fetchone()
        return {
            "rows": int(row["rows"]),
            "content_bytes": int(row["content_bytes"]),
        }

    def purge(
        self,
        *,
        before: str,
        dry_run: bool = False,
        kinds: tuple[str, ...] | None = None,
    ) -> int:
        """Delete history rows with ``created_at < before`` (ISO-8601).

        Returns the number of rows that match (and, unless ``dry_run``, were
        removed). With ``dry_run=True`` nothing is deleted — the count is
        computed and returned so a caller can preview the blast radius (pair
        with :meth:`estimate_purge` for the byte estimate). ``kinds`` narrows
        the delete to specific row kinds — e.g. ``("tool_result",)`` drops only
        tool output (the bulk of the bloat) while keeping the conversation
        turns. The FTS index is kept in sync (each purged row is removed from
        it first). Rows with a NULL/empty ``created_at`` are never matched, so
        they are retained. This is the retention/clear path — driven on
        startup and teardown by ``history_retention_days`` (default 30; set 0
        to keep history forever, which calls nothing here).

        Note: this DELETEs but does not ``VACUUM``, so freed pages are reused
        but the file does not shrink on disk until a separate vacuum.
        """
        where, params = self._purge_where(before, kinds)
        with self._conn:
            doomed = self._conn.execute(
                "SELECT seq, content FROM conversation_history WHERE " + where,
                params,
            ).fetchall()
            if not doomed:
                return 0
            if dry_run:
                return len(doomed)
            if self._fts:
                for row in doomed:
                    self._conn.execute(
                        "INSERT INTO conversation_history_fts"
                        "(conversation_history_fts, rowid, content) "
                        "VALUES('delete', ?, ?)",
                        (row["seq"], row["content"] or ""),
                    )
            self._conn.execute(
                "DELETE FROM conversation_history WHERE " + where,
                params,
            )
            return len(doomed)

    def vacuum(self) -> None:
        """Rebuild the database file to reclaim space freed by ``purge``.

        ``purge`` only DELETEs rows, so freed pages are reused but the file
        does not shrink on disk. VACUUM rewrites it compactly. It is O(db size)
        and briefly needs extra scratch space, so it is an explicit, separate
        step rather than run inline on the retention purge path.
        """
        # VACUUM cannot run inside an open transaction; sqlite3 in its default
        # isolation mode opens one implicitly on writes, so commit first.
        self._conn.commit()
        self._conn.execute("VACUUM")

    def note_write_failure(self, exc: BaseException) -> None:
        """Record a write-through failure — durability is now degraded.

        Logs prominently on the first failure (then counts the rest, to avoid
        log spam). Read ``degraded`` to gate any "fully durable" guarantees.
        """
        self.write_failures += 1
        if not self.degraded:
            self.degraded = True
            logger.error(
                "history write-through FAILED; durability degraded "
                "(further failures counted silently): %s",
                exc,
            )

    @property
    def closed(self) -> bool:
        """True once :meth:`close` has run — the connection is gone."""
        return self._closed

    def close(self) -> None:
        self._closed = True
        try:
            self._conn.close()
        except sqlite3.Error:
            pass

    def __repr__(self) -> str:
        return f"<HistoryStore path={self._path}>"


def _to_json(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, default=str)
