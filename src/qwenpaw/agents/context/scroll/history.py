"""Durable, file-backed conversation history shared across sessions."""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from ..types import LogEntry

_SCHEMA_VERSION = "2"
_BUSY_TIMEOUT_MS = 5000

# Columns of conversation_history, in INSERT order (minus the autoincrement seq).
_INSERT_COLUMNS = (
    "session_id", "agent_id", "step_index", "msg_index",
    "kind", "role", "name", "content",
    "tool_call_id", "tool_input", "tool_state", "headline", "blocks",
    "metadata", "created_at",
)


class HistoryStore:
    """Owns the *read-write* connection to the ``conversation_history`` file.

    Every event the agent appends is write-through-persisted here with full
    structure (blocks, tool args, state) so a later session can retrieve it.
    The model reaches the same file *read-only* through its ``MemorySpace``
    (ATTACHed ``hist`` schema), so this writer and those readers coexist under
    WAL. The file is never dropped; ``close()`` only closes this connection.
    """

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path).expanduser()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self.quarantined_to: Path | None = None
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
                    step_index   INTEGER,
                    msg_index    INTEGER,
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
                    created_at   TEXT
                )
                """,
            )
            # Migrate pre-v2 DBs: CREATE TABLE IF NOT EXISTS won't add the
            # column to an already-existing table, so ALTER it in once.
            cols = {
                r["name"]
                for r in self._conn.execute(
                    "PRAGMA table_info(conversation_history)",
                )
            }
            if "agent_id" not in cols:
                self._conn.execute(
                    "ALTER TABLE conversation_history ADD COLUMN agent_id TEXT",
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
                "CREATE TABLE IF NOT EXISTS _meta "
                "(key TEXT PRIMARY KEY, value TEXT)",
            )
            self._conn.execute(
                "INSERT OR IGNORE INTO _meta (key, value) "
                "VALUES ('schema_version', ?)",
                (_SCHEMA_VERSION,),
            )
            self._init_fts()

    def _init_fts(self) -> None:
        """Create the FTS5 full-text index over ``content``, if available.

        External-content FTS5 indexes without duplicating the text; it is kept
        in sync by ``append``/``update_entry``. On a pre-existing DB it is
        back-filled once via 'rebuild'. Porter stemming on top of unicode61
        casefolding so "tanks" matches "tank". Degrades silently to a LIKE
        scan (see ``MemorySpace.search``) when this SQLite build lacks FTS5.
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
        except sqlite3.OperationalError:
            self._fts = False

    # --- write path ----------------------------------------------------

    def append(
        self,
        *,
        session_id: str,
        entry: LogEntry,
        agent_id: str | None = None,
    ) -> int:
        """Write-through one event. Returns the assigned ``seq`` (watermark)."""
        row = (
            session_id,
            agent_id,
            entry.step_index,
            entry.msg_index,
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
        )
        placeholders = ", ".join("?" for _ in _INSERT_COLUMNS)
        with self._conn:
            cur = self._conn.execute(
                f"INSERT INTO conversation_history "
                f"({', '.join(_INSERT_COLUMNS)}) VALUES ({placeholders})",
                row,
            )
            seq = int(cur.lastrowid)
            if self._fts:
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
    ) -> None:
        """Refresh an already-appended row in place (keeping FTS in sync).

        Used when one logical turn is *extended* after first write: AgentScope
        accumulates a whole reply into a single assistant Msg, so the durable
        row must end up with every cell's blocks and any later-emitted
        headline. ``seq`` is unchanged.
        """
        with self._conn:
            old_content = None
            if self._fts:
                r = self._conn.execute(
                    "SELECT content FROM conversation_history WHERE seq = ?",
                    (seq,),
                ).fetchone()
                old_content = r["content"] if r else None
            self._conn.execute(
                "UPDATE conversation_history SET content = ?, headline = ?, "
                "blocks = ? WHERE seq = ?",
                (content, headline, _to_json(blocks), seq),
            )
            if self._fts:
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

    def close(self) -> None:
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
