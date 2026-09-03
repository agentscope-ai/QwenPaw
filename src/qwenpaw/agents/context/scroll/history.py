# -*- coding: utf-8 -*-
"""Durable, file-backed conversation history shared across sessions."""

from __future__ import annotations

import json
import logging
import sqlite3
import sys
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..types import LogEntry
from .memoryspace import MemorySpace

logger = logging.getLogger(__name__)

_BUSY_TIMEOUT_MS = 5000
_UNSET = object()

# Read-endpoint expansion budget: how far a single page is allowed to walk
# backward past its own ``limit`` to reach a complete user turn boundary
# before giving up and returning a truncated page. Mirrors the "唯一允许回
# 合跨页切分的场景" rule in the pagination design doc.
DEFAULT_MAX_EXPANSION_ROWS = 600

# The recall tool's own turns — the model's ``ms.*`` Python source and its
# printed stdout/stderr — are written through to history like any turn, but
# they are the agent *reading* memory, not memory content. Keyword-indexing
# them lets a later ``ms.search`` match the agent's own past queries (and their
# tracebacks), drowning the real content: a self-pollution feedback loop. So
# these rows stay durable + recallable by ``seq``, but are kept OUT of the FTS
# index (and out of ``search`` — see ``MemorySpace``). Must match the recall
# tool names in ``repl.py`` and ``recall_tool.py``.
_RECALL_TOOL_NAMES = (
    "recall_history_python",
    "recall_history",
)

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
        # Serializes the single connection across threads: ``compress`` writes
        # from a worker thread (``asyncio.to_thread``, to spare the event loop)
        # while ``on_save`` writes on the loop thread. Both share this
        # connection, so every access takes ``self._lock``.
        self._lock = threading.Lock()
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
        # check_same_thread=False: used from both loop and worker threads;
        # ``self._lock`` provides the serialization SQLite would get from
        # same-thread affinity.
        self._conn = sqlite3.connect(
            str(self._path),
            check_same_thread=False,
        )
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
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS ch_created_at "
                "ON conversation_history(created_at)",
            )
            # Idempotency net: a second append of the same logical event, such
            # as a resume re-persisting its restored window, collides here and
            # is dropped by ON CONFLICT rather than duplicating a row. NULL
            # dedup_key never conflicts, so un-keyed rows are simply never
            # deduped.
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

    @staticmethod
    def _insert_row(
        session_id: str,
        agent_id: str | None,
        entry: LogEntry,
        dedup_key: str | None,
    ) -> tuple:
        """Build the SQLite row shared by single and batched appends."""
        return (
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
        row = self._insert_row(session_id, agent_id, entry, dedup_key)
        placeholders = ", ".join("?" for _ in _INSERT_COLUMNS)
        with self._lock, self._conn:
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

    def append_many(
        self,
        *,
        session_id: str,
        entries: Sequence[tuple[LogEntry, str | None]],
        agent_id: str | None = None,
    ) -> int:
        """Append a group of events in one transaction.

        Returns the number of newly inserted rows. Duplicate keys remain
        no-ops and only newly inserted rows are added to FTS, matching
        :meth:`append`. This is intended for backfills where committing every
        individual row would turn SQLite fsync latency into startup latency.
        """
        if not entries:
            return 0

        placeholders = ", ".join("?" for _ in _INSERT_COLUMNS)
        sql = (
            f"INSERT INTO conversation_history "
            f"({', '.join(_INSERT_COLUMNS)}) VALUES ({placeholders}) "
            f"ON CONFLICT(session_id, dedup_key) DO NOTHING"
        )
        inserted = 0
        with self._lock, self._conn:
            for entry, dedup_key in entries:
                row = self._insert_row(
                    session_id,
                    agent_id,
                    entry,
                    dedup_key,
                )
                cur = self._conn.execute(sql, row)
                if cur.rowcount == 0:
                    continue
                inserted += 1
                seq = int(cur.lastrowid or 0)
                if self._fts and entry.name not in _RECALL_TOOL_NAMES:
                    self._conn.execute(
                        "INSERT INTO conversation_history_fts(rowid, content) "
                        "VALUES (?, ?)",
                        (seq, entry.content or ""),
                    )
        return inserted

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
        metadata: Any = _UNSET,
    ) -> None:
        """Refresh an already-appended row in place (keeping FTS in sync).

        Used when one logical turn is *extended* after first write: AgentScope
        accumulates a whole reply into a single assistant Msg, so the durable
        row must end up with every cell's blocks and any later-emitted
        headline. The scalar ``tool_call_id``/``name``/``tool_state``/
        ``tool_input`` and message ``metadata`` are refreshed too, so a turn
        that grows a *later* tool call doesn't leave them frozen at their
        first-write values. ``seq`` is unchanged. Omitting ``metadata`` keeps
        the stored value unchanged for backwards-compatible direct callers.
        """
        # Recall-tool rows are never FTS-indexed (see ``_RECALL_TOOL_NAMES``),
        # so don't touch the index for them on update either.
        fts_sync = self._fts and name not in _RECALL_TOOL_NAMES
        with self._lock, self._conn:
            old_content = None
            if fts_sync:
                r = self._conn.execute(
                    "SELECT content FROM conversation_history WHERE seq = ?",
                    (seq,),
                ).fetchone()
                old_content = r["content"] if r else None
            # Keep every column name below as a hard-coded literal. Only
            # values are parameterized; never add caller-controlled names.
            assignments = [
                "content = ?",
                "headline = ?",
                "blocks = ?",
                "tool_call_id = ?",
                "name = ?",
                "tool_state = ?",
                "tool_input = ?",
            ]
            values: list[Any] = [
                content,
                headline,
                _to_json(blocks),
                tool_call_id,
                name,
                tool_state,
                _to_json(tool_input),
            ]
            if metadata is not _UNSET:
                assignments.append("metadata = ?")
                # The history schema canonically represents empty metadata
                # as SQL NULL, matching the initial insert path.
                values.append(_to_json(metadata or None))
            values.append(seq)
            self._conn.execute(
                "UPDATE conversation_history SET "
                + ", ".join(assignments)
                + " WHERE seq = ?",
                values,
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
        with self._lock:
            cur = self._conn.execute(
                "SELECT COUNT(*) AS n FROM conversation_history "
                "WHERE session_id = ?",
                (session_id,),
            )
            return int(cur.fetchone()["n"])

    def claim_session(self, session_id: str, agent_id: str | None) -> int:
        """Assign legacy unowned rows in a canonical session to an agent."""
        if not session_id or not agent_id:
            return 0
        with self._lock, self._conn:
            cur = self._conn.execute(
                "UPDATE conversation_history SET agent_id = ? "
                "WHERE session_id = ? AND agent_id IS NULL",
                (agent_id, session_id),
            )
            return int(cur.rowcount)

    def reconcile_session_rows(
        self,
        source_ids: set[str],
        target_id: str,
        dedup_keys: set[str],
        *,
        agent_id: str | None = None,
    ) -> tuple[int, int, int]:
        """Move rows proven to come from one file into its canonical session.

        ``source_ids`` alone is not sufficient provenance because synthetic
        IDs can collide across channel directories. Restricting the operation
        to dedup keys recomputed from the source file prevents unrelated rows
        from being swept into ``target_id``.

        Returns ``(moved, deduplicated, claimed)``. Non-conflicting rows retain
        their original ``seq``; source duplicates are removed in favor of the
        existing canonical row so the unique dedup contract remains valid.
        """
        sources = sorted(
            source_id
            for source_id in source_ids
            if source_id and source_id != target_id
        )
        keys = sorted(str(key) for key in dedup_keys if key)
        if not sources or not target_id or not keys:
            return (0, 0, self.claim_session(target_id, agent_id))

        moved = 0
        deduplicated = 0
        claimed = 0
        with self._lock, self._conn:
            for source_id in sources:
                for start in range(0, len(keys), 400):
                    chunk = keys[slice(start, start + 400)]
                    placeholders = ", ".join("?" for _ in chunk)
                    ownership = ""
                    params: list[Any] = [source_id, *chunk]
                    if agent_id:
                        ownership = " AND (agent_id = ? OR agent_id IS NULL)"
                        params.append(agent_id)
                    rows = self._conn.execute(
                        "SELECT seq, dedup_key, content "
                        "FROM conversation_history "
                        "WHERE session_id = ? AND dedup_key IN ("
                        + placeholders
                        + ")"
                        + ownership,
                        params,
                    ).fetchall()
                    if not rows:
                        continue

                    row_keys = [str(row["dedup_key"]) for row in rows]
                    target_placeholders = ", ".join("?" for _ in row_keys)
                    existing = self._conn.execute(
                        "SELECT dedup_key FROM conversation_history "
                        "WHERE session_id = ? AND dedup_key IN ("
                        + target_placeholders
                        + ")",
                        [target_id, *row_keys],
                    ).fetchall()
                    existing_keys = {str(row["dedup_key"]) for row in existing}
                    duplicates = [
                        row
                        for row in rows
                        if str(row["dedup_key"]) in existing_keys
                    ]
                    movable = [
                        row
                        for row in rows
                        if str(row["dedup_key"]) not in existing_keys
                    ]

                    if self._fts:
                        for row in duplicates:
                            self._conn.execute(
                                "INSERT INTO conversation_history_fts"
                                "(conversation_history_fts, rowid, content) "
                                "VALUES('delete', ?, ?)",
                                (row["seq"], row["content"] or ""),
                            )
                    if duplicates:
                        self._conn.executemany(
                            "DELETE FROM conversation_history WHERE seq = ?",
                            [(row["seq"],) for row in duplicates],
                        )
                        deduplicated += len(duplicates)

                    if movable:
                        seqs = [int(row["seq"]) for row in movable]
                        seq_placeholders = ", ".join("?" for _ in seqs)
                        cur = self._conn.execute(
                            "UPDATE conversation_history "
                            "SET session_id = ?, "
                            "agent_id = COALESCE(agent_id, ?) "
                            "WHERE seq IN (" + seq_placeholders + ")",
                            [target_id, agent_id, *seqs],
                        )
                        moved += int(cur.rowcount)

            if agent_id:
                cur = self._conn.execute(
                    "UPDATE conversation_history SET agent_id = ? "
                    "WHERE session_id = ? AND agent_id IS NULL",
                    (agent_id, target_id),
                )
                claimed = int(cur.rowcount)
        return (moved, deduplicated, claimed)

    def existing_seqs(self, seqs: set[int]) -> set[int]:
        """Return the subset of globally addressed history rows that exist."""
        if not seqs:
            return set()
        ordered = sorted(int(seq) for seq in seqs)
        placeholders = ", ".join("?" for _ in ordered)
        with self._lock:
            rows = self._conn.execute(
                "SELECT seq FROM conversation_history WHERE seq IN ("
                + placeholders
                + ")",
                ordered,
            ).fetchall()
        return {int(row["seq"]) for row in rows}

    def contents_by_seqs(self, seqs: set[int]) -> dict[int, str | None]:
        """Return exact persisted content for globally addressed rows.

        Summary evidence uses this after live tool results have been folded.
        Querying exact primary keys, instead of a broad ``lo..hi`` range,
        prevents interleaved rows from another agent or session entering the
        evidence. Chunking also keeps the query below SQLite parameter limits
        for unusually tool-heavy histories.
        """
        if not seqs:
            return {}
        ordered = sorted(int(seq) for seq in seqs)
        found: dict[int, str | None] = {}
        with self._lock:
            for start in range(0, len(ordered), 500):
                chunk = ordered[start : start + 500]
                placeholders = ", ".join("?" for _ in chunk)
                rows = self._conn.execute(
                    "SELECT seq, content FROM conversation_history "
                    f"WHERE seq IN ({placeholders})",
                    chunk,
                ).fetchall()
                found.update(
                    {int(row["seq"]): row["content"] for row in rows},
                )
        return found

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
        with self._lock, self._conn:
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
        with self._lock, self._conn:
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
        with self._lock:
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
        with self._lock:
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


# ---------------------------------------------------------------------------
# Stateless read-only page queries for the HTTP pagination endpoint.
#
# These are deliberately free functions, not ``HistoryStore`` methods: the
# endpoint opens its own short-lived ``mode=ro`` connection per request
# (never the live agent's read-write ``HistoryStore._conn``) so a slow or
# stuck page query can never contend with write-through persistence. The
# connection must be created, queried and closed inside one
# ``asyncio.to_thread`` call — see ``read_history_page``.
# ---------------------------------------------------------------------------


class HistoryUnavailable(Exception):
    """The history db can't be read (missing file, corruption, query error).

    Callers map this to ``history_status="degraded"`` — never to "no more
    history" — so a broken store doesn't masquerade as a clean end of scroll.
    """


@dataclass
class HistoryPageResult:
    """One page of raw db rows plus the bookkeeping to request the next."""

    rows: list[sqlite3.Row]  # ascending seq order (oldest -> newest)
    next_cursor: int | None  # smallest seq in ``rows``; None if rows is empty
    has_more: bool
    truncated: bool


def open_readonly_connection(db_path: str | Path) -> sqlite3.Connection:
    """Open a standalone ``mode=ro`` connection to an existing history db.

    Raises :class:`HistoryUnavailable` if the file is missing or SQLite can't
    open/read it (corruption, mid-write torn WAL, etc.) — the caller decides
    what "unavailable" means for its response (degraded vs unavailable).
    """
    path = Path(db_path)
    if not path.exists():
        raise HistoryUnavailable(f"history db not found: {path}")
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        conn.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
        # Cheap read to fail fast on a corrupt/torn file rather than on the
        # caller's first real query.
        conn.execute("SELECT 1 FROM conversation_history LIMIT 1")
    except sqlite3.Error as exc:
        raise HistoryUnavailable(f"history db unreadable: {exc}") from exc
    return conn


def find_seq_by_dedup_key(
    conn: sqlite3.Connection,
    session_id: str,
    dedup_key: str,
) -> int | None:
    """Resolve a live Msg's ``id`` (= db ``dedup_key``) to its durable ``seq``.

    This is the first-screen "anchor" query (design doc §2.1 step 4): the
    earliest real user Msg still visible in the live session JSON window
    tells the endpoint where to resume once the user scrolls up into
    ``history.db``.
    """
    row = conn.execute(
        "SELECT seq FROM conversation_history "
        "WHERE session_id = ? AND dedup_key = ?",
        (session_id, dedup_key),
    ).fetchone()
    return int(row["seq"]) if row else None


def min_seq_for_session(
    conn: sqlite3.Connection,
    session_id: str,
) -> int | None:
    """Smallest surviving ``seq`` for a session, or ``None`` if it has no rows.

    Used to tell "reached the true start" (``complete``) apart from "the true
    start was purged by an old retention policy" (``expired``) — see the
    design doc's expired-detection algorithm.
    """
    row = conn.execute(
        "SELECT MIN(seq) AS seq FROM conversation_history "
        "WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    return int(row["seq"]) if row and row["seq"] is not None else None


def fetch_tool_results_by_call_ids(
    conn: sqlite3.Connection,
    session_id: str,
    call_ids: Sequence[str],
) -> dict[str, sqlite3.Row]:
    """Look up ``tool_result`` rows anywhere in the session by call id.

    Used to tell "this call's result is just on a different page" apart from
    "no result row exists anywhere in history" — the latter is what actually
    drives the expired/pending tool-result placeholder in
    ``history_rows_to_messages``. Not scoped to a seq range on purpose.
    """
    ids = [c for c in dict.fromkeys(call_ids) if c]
    if not ids:
        return {}
    found: dict[str, sqlite3.Row] = {}
    for start in range(0, len(ids), 400):
        chunk = ids[start : start + 400]
        placeholders = ", ".join("?" for _ in chunk)
        rows = conn.execute(
            "SELECT * FROM conversation_history "
            f"WHERE session_id = ? AND kind = 'tool_result' "
            f"AND tool_call_id IN ({placeholders})",
            (session_id, *chunk),
        ).fetchall()
        for row in rows:
            found[row["tool_call_id"]] = row
    return found


def has_rows_before(
    conn: sqlite3.Connection,
    session_id: str,
    seq: int,
) -> bool:
    """Whether any row for ``session_id`` still exists with ``seq < seq``."""
    row = conn.execute(
        "SELECT 1 FROM conversation_history "
        "WHERE session_id = ? AND seq < ? LIMIT 1",
        (session_id, seq),
    ).fetchone()
    return row is not None


def _turn_start_seq_at_or_before(
    conn: sqlite3.Connection,
    session_id: str,
    seq: int,
) -> int | None:
    """Max seq of a real user turn boundary with ``seq <= seq`` in-session.

    Reuses ``MemorySpace._real_user_conditions`` — the same role/synthetic-tag
    test the recall REPL uses to find turn boundaries — so the HTTP read path
    and the model's own recall queries agree on what counts as a turn start.
    """
    conditions, params = MemorySpace._real_user_conditions()
    sql = (
        "SELECT MAX(seq) AS seq FROM conversation_history "
        "WHERE session_id = ? AND "
        + " AND ".join(conditions)
        + " AND seq <= ?"
    )
    row = conn.execute(sql, (session_id, *params, seq)).fetchone()
    return int(row["seq"]) if row and row["seq"] is not None else None


def read_history_page(
    db_path: str | Path,
    session_id: str,
    *,
    before_seq: int,
    limit: int,
    max_expansion_rows: int = DEFAULT_MAX_EXPANSION_ROWS,
) -> HistoryPageResult:
    """Load one turn-aligned page strictly older than ``before_seq``.

    Opens its own read-only connection, runs the whole query (including any
    boundary expansion), and closes it before returning — the caller wraps
    this single call in ``asyncio.to_thread``. Raises ``HistoryUnavailable``
    on any db-level failure; never returns a partial/corrupt result silently.
    """
    conn = open_readonly_connection(db_path)
    try:
        return _read_history_page(
            conn,
            session_id,
            before_seq=before_seq,
            limit=max(1, limit),
            max_expansion_rows=max(limit, max_expansion_rows),
        )
    except sqlite3.Error as exc:
        raise HistoryUnavailable(f"history page query failed: {exc}") from exc
    finally:
        conn.close()


def _read_history_page(
    conn: sqlite3.Connection,
    session_id: str,
    *,
    before_seq: int,
    limit: int,
    max_expansion_rows: int,
) -> HistoryPageResult:
    seed = conn.execute(
        "SELECT seq FROM conversation_history "
        "WHERE session_id = ? AND seq < ? ORDER BY seq DESC LIMIT ?",
        (session_id, before_seq, limit),
    ).fetchall()
    if not seed:
        return HistoryPageResult(
            rows=[],
            next_cursor=None,
            has_more=False,
            truncated=False,
        )

    oldest_seed_seq = int(seed[-1]["seq"])
    boundary_seq = _turn_start_seq_at_or_before(
        conn,
        session_id,
        oldest_seed_seq,
    )
    if boundary_seq is None:
        # No real user row at or before the oldest candidate in this session
        # at all (legacy/imported data with no turn markers). Fall back to
        # the oldest row we actually found rather than expanding forever.
        boundary_seq = oldest_seed_seq

    span = before_seq - boundary_seq
    truncated = False
    if span > max_expansion_rows:
        # Pathological single turn far exceeding the budget: stop expanding,
        # return the most recent ``max_expansion_rows`` rows below the
        # cursor and let the caller mark the page truncated. The next page
        # picks up exactly where this one stopped (no gap, no duplication).
        boundary_seq = before_seq - max_expansion_rows
        truncated = True

    rows_desc = conn.execute(
        "SELECT * FROM conversation_history "
        "WHERE session_id = ? AND seq >= ? AND seq < ? "
        "ORDER BY seq DESC",
        (session_id, boundary_seq, before_seq),
    ).fetchall()
    if not rows_desc:
        return HistoryPageResult(
            rows=[],
            next_cursor=None,
            has_more=False,
            truncated=False,
        )

    ascending = list(reversed(rows_desc))
    next_cursor = int(ascending[0]["seq"])
    has_more = has_rows_before(conn, session_id, next_cursor)
    return HistoryPageResult(
        rows=ascending,
        next_cursor=next_cursor,
        has_more=has_more,
        truncated=truncated,
    )
