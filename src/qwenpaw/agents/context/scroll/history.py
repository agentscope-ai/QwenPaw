# -*- coding: utf-8 -*-
"""Durable, file-backed conversation history shared across sessions."""

from __future__ import annotations

import json
import logging
import random
import sqlite3
import sys
import threading
import time
from collections.abc import Sequence
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..types import LogEntry

logger = logging.getLogger(__name__)

_BUSY_TIMEOUT_MS = 250
_WRITE_RETRY_DEADLINE_S = 2.0
_WRITE_RETRY_MIN_S = 0.020
_WRITE_RETRY_MAX_S = 0.150
_CHECKPOINT_EVERY_N_WRITES = 50
_SCHEMA_VERSION = 1
_REQUIRED_COLUMNS = {"seq", "session_id", "kind"}

# SQLite extended result codes keep the primary result code in the low byte.
# Only these errors prove that the file itself is corrupt/unreadable. Busy,
# readonly, I/O, disk-full, and permission errors must NEVER quarantine a DB.
_CORRUPTION_CODES = {
    sqlite3.SQLITE_CORRUPT,
    sqlite3.SQLITE_NOTADB,
}
_CONTENTION_CODES = {
    sqlite3.SQLITE_BUSY,
    sqlite3.SQLITE_LOCKED,
}

_OPTIONAL_COLUMNS = {
    "agent_id": "TEXT",
    "role": "TEXT",
    "name": "TEXT",
    "content": "TEXT",
    "tool_call_id": "TEXT",
    "tool_input": "TEXT",
    "tool_state": "TEXT",
    "headline": "TEXT",
    "blocks": "TEXT",
    "metadata": "TEXT",
    "created_at": "TEXT",
    "dedup_key": "TEXT",
}

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


class HistorySchemaError(sqlite3.DatabaseError):
    """The DB is valid SQLite, but its schema cannot be opened safely."""


class HistoryCorruptionError(sqlite3.DatabaseError):
    """An integrity check proved that the SQLite file is corrupt."""


def _is_corruption_error(exc: BaseException) -> bool:
    """Whether *exc* proves on-disk SQLite corruption.

    Python exposes SQLite's primary/extended result code on exceptions raised
    by the driver. The message fallback covers wrapped errors and older Python
    builds, but is deliberately narrow: lock/contention and general I/O errors
    are operational failures, not evidence that the database should be moved.
    """
    if isinstance(exc, HistoryCorruptionError):
        return True
    code = getattr(exc, "sqlite_errorcode", None)
    if isinstance(code, int) and (code & 0xFF) in _CORRUPTION_CODES:
        return True
    message = str(exc).lower()
    return any(
        marker in message
        for marker in (
            "database disk image is malformed",
            "file is not a database",
            "file is encrypted or is not a database",
        )
    )


def _is_contention_error(exc: BaseException) -> bool:
    """Whether *exc* is transient SQLite writer/schema contention."""
    code = getattr(exc, "sqlite_errorcode", None)
    if isinstance(code, int) and (code & 0xFF) in _CONTENTION_CODES:
        return True
    message = str(exc).lower()
    return "locked" in message or "busy" in message


def _retry_contention(operation):
    """Run *operation* with a bounded randomized SQLite contention retry."""
    deadline = time.monotonic() + _WRITE_RETRY_DEADLINE_S
    while True:
        try:
            return operation()
        except sqlite3.OperationalError as exc:
            now = time.monotonic()
            if not _is_contention_error(exc) or now >= deadline:
                raise
            delay = min(
                random.uniform(_WRITE_RETRY_MIN_S, _WRITE_RETRY_MAX_S),
                max(0.0, deadline - now),
            )
            if delay:
                time.sleep(delay)


@contextmanager
def _immediate_transaction(
    conn: sqlite3.Connection,
    *,
    on_commit=None,
):
    """Run a short write transaction with bounded, jittered lock retries.

    ``BEGIN IMMEDIATE`` surfaces the only-writer collision before any
    statement mutates state. Retrying that boundary is therefore safe and
    avoids SQLite's deterministic lock-wait convoy across gateway/CLI/worker
    processes. Non-contention errors are never retried.
    """
    _retry_contention(lambda: conn.execute("BEGIN IMMEDIATE"))
    try:
        yield
    except BaseException:
        if conn.in_transaction:
            conn.rollback()
        raise
    conn.commit()
    if on_commit is not None:
        on_commit()


def _validate_history_connection(conn: sqlite3.Connection) -> int:
    """Validate integrity and the minimum compatible history schema."""
    row = conn.execute("PRAGMA quick_check").fetchone()
    result = str(row[0]) if row else "no result"
    if result != "ok":
        raise HistoryCorruptionError(f"quick_check failed: {result}")

    version_row = conn.execute("PRAGMA user_version").fetchone()
    version = int(version_row[0] if version_row else 0)
    if version > _SCHEMA_VERSION:
        raise HistorySchemaError(
            f"history schema version {version} is newer than supported "
            f"version {_SCHEMA_VERSION}",
        )

    columns = {
        str(column[1])
        for column in conn.execute(
            "PRAGMA table_info(conversation_history)",
        ).fetchall()
    }
    missing_required = _REQUIRED_COLUMNS - columns
    if missing_required:
        raise HistorySchemaError(
            "history schema is missing required column(s): "
            + ", ".join(sorted(missing_required)),
        )
    return version


def validate_history_database(db_path: str | Path) -> int:
    """Read-only integrity and compatibility check for an existing store.

    Returns the on-disk ``PRAGMA user_version``. Version ``0`` remains valid
    for pre-versioned stores and is migrated on the next runtime open.
    """
    path = Path(db_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    conn = sqlite3.connect(
        path.as_uri() + "?mode=ro",
        uri=True,
        timeout=_BUSY_TIMEOUT_MS / 1000,
    )
    try:
        conn.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
        return _validate_history_connection(conn)
    finally:
        conn.close()


def backup_history_database(
    source: str | Path,
    destination: str | Path,
) -> Path:
    """Create a verified online snapshot without mutating the source store."""
    source_path = Path(source).expanduser().resolve()
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    target = Path(destination).expanduser()
    if target.resolve() == source_path:
        raise ValueError(
            "history backup destination must differ from source",
        )
    if target.exists():
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(
        source_path.as_uri() + "?mode=ro",
        uri=True,
        timeout=_BUSY_TIMEOUT_MS / 1000,
    )
    snapshot: sqlite3.Connection | None = None
    try:
        conn.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
        snapshot = sqlite3.connect(str(target))
        conn.backup(snapshot)
        _validate_history_connection(snapshot)
        return target
    finally:
        if snapshot is not None:
            snapshot.close()
        conn.close()


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
        self._writes_since_checkpoint = 0
        # Flipped True by ``close()`` so callers can tell an intentional
        # teardown race from a real disk outage (see ``closed``).
        self._closed = False
        try:
            self._open_and_init()
        except sqlite3.DatabaseError as exc:
            # Only proven corruption is recoverable by moving the file aside.
            # A broad DatabaseError also includes busy/locked, readonly, I/O,
            # disk-full, and unsupported-schema failures; quarantining any of
            # those could move a healthy live database out from other writers.
            if not _is_corruption_error(exc):
                self._close_connection()
                raise
            self._quarantine(exc)
            self._open_and_init()

    def _open_and_init(self) -> None:
        # check_same_thread=False: used from both loop and worker threads;
        # ``self._lock`` provides the serialization SQLite would get from
        # same-thread affinity.
        self._conn = sqlite3.connect(
            str(self._path),
            check_same_thread=False,
            timeout=_BUSY_TIMEOUT_MS / 1000,
        )
        self._conn.row_factory = sqlite3.Row
        # Set the wait policy before journal_mode: switching/confirming WAL can
        # itself need a lock when several processes start at once.
        self._conn.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
        _retry_contention(
            lambda: self._conn.execute("PRAGMA journal_mode=WAL"),
        )
        # Probe for corruption that only surfaces on read.
        row = self._conn.execute("PRAGMA quick_check").fetchone()
        if not row or row[0] != "ok":
            raise HistoryCorruptionError(
                f"quick_check failed: {row[0] if row else None}",
            )
        self._init_schema()

    def _close_connection(self) -> None:
        try:
            self._conn.close()
        except (AttributeError, sqlite3.Error):
            pass

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

    @staticmethod
    def _schema_columns(conn: sqlite3.Connection) -> set[str]:
        return {
            str(row["name"])
            for row in conn.execute(
                "PRAGMA table_info(conversation_history)",
            ).fetchall()
        }

    def _migrate_schema(self) -> None:
        """Apply bounded, idempotent upgrades to the current schema version."""
        version_row = self._conn.execute("PRAGMA user_version").fetchone()
        version = int(version_row[0] if version_row else 0)
        if version > _SCHEMA_VERSION:
            raise HistorySchemaError(
                f"history schema version {version} is newer than supported "
                f"version {_SCHEMA_VERSION}",
            )

        columns = self._schema_columns(self._conn)
        missing_required = _REQUIRED_COLUMNS - columns
        if missing_required:
            raise HistorySchemaError(
                "history schema is missing required column(s): "
                + ", ".join(sorted(missing_required)),
            )
        for name, ddl in _OPTIONAL_COLUMNS.items():
            if name not in columns:
                self._conn.execute(
                    f"ALTER TABLE conversation_history "
                    f"ADD COLUMN {name} {ddl}",
                )

    @property
    def path(self) -> Path:
        return self._path

    def _init_schema(self) -> None:
        with self._lock, _immediate_transaction(self._conn):
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
            self._migrate_schema()
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
            # Publish the version only after every table/index/FTS migration in
            # this transaction has succeeded.
            self._conn.execute(f"PRAGMA user_version={_SCHEMA_VERSION}")

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
            if "no such module: fts5" not in str(exc).lower():
                raise
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
        with self._lock, _immediate_transaction(
            self._conn,
            on_commit=self._checkpoint_after_write,
        ):
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
        with self._lock, _immediate_transaction(
            self._conn,
            on_commit=self._checkpoint_after_write,
        ):
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
        with self._lock, _immediate_transaction(
            self._conn,
            on_commit=self._checkpoint_after_write,
        ):
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
        with self._lock:
            cur = self._conn.execute(
                "SELECT COUNT(*) AS n FROM conversation_history "
                "WHERE session_id = ?",
                (session_id,),
            )
            return int(cur.fetchone()["n"])

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
        with self._lock:
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
        with self._lock, _immediate_transaction(
            self._conn,
            on_commit=self._checkpoint_after_write,
        ):
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

    def _checkpoint_after_write(self) -> None:
        """Bound WAL growth without blocking a concurrent writer."""
        self._writes_since_checkpoint += 1
        if self._writes_since_checkpoint < _CHECKPOINT_EVERY_N_WRITES:
            return
        self._writes_since_checkpoint = 0
        try:
            self._conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
        except sqlite3.Error as exc:
            # The data commit already succeeded. Checkpoint failure affects
            # only WAL compaction and must not turn it into a false write
            # failure or trigger a duplicate retry.
            logger.debug("history passive WAL checkpoint skipped: %s", exc)

    @property
    def closed(self) -> bool:
        """True once :meth:`close` has run — the connection is gone."""
        return self._closed

    def close(self) -> None:
        self._closed = True
        with self._lock:
            try:
                self._conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
            except sqlite3.Error:
                pass
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
