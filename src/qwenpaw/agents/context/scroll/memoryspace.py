"""The model's SQLite working surface inside ``execute_python``.

Self-contained (stdlib only) so it can be imported by the sandboxed REPL
bootstrap without the rest of qwenpaw on the path.

``main`` is an in-memory database the model owns read/write — its scratch
space. The durable ``conversation_history`` file is ATTACHed **read-only** as
schema ``hist``: the model can ``SELECT ... FROM hist.conversation_history``
across sessions, but any write to ``hist.*`` is rejected by SQLite itself.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

_DEFAULT_ROW_CAP = 1000


def sanitize_suffix(session_id: str | None) -> str:
    """Turn a session id into a SQL-identifier-safe table suffix."""
    if not session_id:
        return "scratch"
    return re.sub(r"[^0-9A-Za-z_]", "_", session_id)


class MemorySpace:
    """The model's scratch space + read-only attach of durable history.

    Returned rows are capped (``row_cap``) so a runaway SELECT can't bomb the
    model's context; truncation is flagged with a trailing ``_truncated`` row.
    """

    def __init__(
        self,
        *,
        history_db_path: str | Path | None = None,
        session_id: str | None = None,
        task_id: str | None = None,
        row_cap: int = _DEFAULT_ROW_CAP,
        scratch_db_path: str | Path | None = None,
    ) -> None:
        # ``main`` is in-memory by default; a file path keeps derived scratch
        # tables across calls (the sandboxed REPL runs a fresh process per cell).
        main = (
            str(Path(scratch_db_path).expanduser())
            if scratch_db_path is not None
            else ":memory:"
        )
        self._conn = sqlite3.connect(main, uri=True)
        self._conn.row_factory = sqlite3.Row
        self._row_cap = row_cap
        self._session_id = session_id
        self._task_id = task_id
        self._session_suffix = sanitize_suffix(session_id)
        self._fts_ok: bool | None = None  # cached FTS5-availability check
        if history_db_path is not None:
            abs_path = Path(history_db_path).expanduser().resolve()
            self._conn.execute(
                "ATTACH DATABASE ? AS hist", (f"file:{abs_path}?mode=ro",),
            )

    @property
    def session_suffix(self) -> str:
        return self._session_suffix

    @property
    def session_id(self) -> str | None:
        """The current session id (this run only)."""
        return self._session_id

    @property
    def task_id(self) -> str | None:
        """The current task id — scopes ``hist`` across ALL runs of this task."""
        return self._task_id

    def sql_exec(self, sql: str, params: tuple | dict | None = None) -> int:
        """Run a non-SELECT statement. Returns rowcount or lastrowid.

        Use for CREATE TABLE / INSERT / UPDATE / DELETE in the scratch space.
        Parameters are bound, not interpolated. Writes targeting the read-only
        ``hist`` schema raise ``sqlite3.OperationalError``.
        """
        with self._conn:
            cur = self._conn.execute(sql, params or ())
            return int(cur.lastrowid or cur.rowcount or 0)

    def sql_query(self, sql: str, params: tuple | dict | None = None) -> list[dict]:
        """Run a SELECT (or any read query). Returns up to ``row_cap`` rows.

        Rows come back as plain dicts. On overflow, only the first ``row_cap``
        are returned plus a trailing ``_truncated`` marker.
        """
        cur = self._conn.execute(sql, params or ())
        rows: list[dict] = []
        for i, row in enumerate(cur):
            if i >= self._row_cap:
                rows.append({"_truncated": True, "_row_cap": self._row_cap})
                break
            rows.append({k: row[k] for k in row.keys()})
        return rows

    def search(
        self,
        query: str,
        *,
        scope: str = "session",
        kind: str | None = None,
        k: int = 10,
    ) -> list[dict]:
        """Full-text search over ``hist.conversation_history`` content (FTS5).

        Returns up to ``k`` rows ranked by relevance (bm25). ``scope`` limits to
        ``'session'`` (this run, default), ``'task'`` (all runs of this task),
        or ``'all'``. ``kind`` optionally filters. Falls back to a LIKE scan if
        this SQLite lacks FTS5.
        """
        if not self._fts_available():
            return self._search_like(query, scope, kind, int(k))
        # bm25 and the `tbl MATCH` syntax need the table NAME, not an alias.
        fts = "conversation_history_fts"
        where = [f"{fts} MATCH ?"]
        params: list = [query]
        if scope == "session" and self._session_id:
            where.append("ch.session_id = ?")
            params.append(self._session_id)
        elif scope == "task" and self._task_id:
            where.append("ch.task_id = ?")
            params.append(self._task_id)
        if kind:
            where.append("ch.kind = ?")
            params.append(kind)
        sql = (
            "SELECT ch.seq, ch.step_index, ch.kind, ch.role, ch.name, "
            "ch.headline, ch.content "
            f"FROM hist.{fts} JOIN hist.conversation_history ch "
            f"ON ch.seq = {fts}.rowid "
            "WHERE " + " AND ".join(where) + f" ORDER BY bm25({fts}) LIMIT ?"
        )
        params.append(int(k))
        return [
            {kk: r[kk] for kk in r.keys()}
            for r in self._conn.execute(sql, params)
        ]

    def _fts_available(self) -> bool:
        """True iff the read-only history DB has the FTS5 index table."""
        if self._fts_ok is None:
            try:
                row = self._conn.execute(
                    "SELECT 1 FROM hist.sqlite_master WHERE type='table' "
                    "AND name='conversation_history_fts'",
                ).fetchone()
                self._fts_ok = row is not None
            except sqlite3.OperationalError:
                self._fts_ok = False  # no hist attached at all
        return self._fts_ok

    def _search_like(self, query, scope, kind, k) -> list[dict]:
        """LIKE fallback when FTS5 is unavailable."""
        where = ["content LIKE ?"]
        params: list = [f"%{query}%"]
        if scope == "session" and self._session_id:
            where.append("session_id = ?")
            params.append(self._session_id)
        elif scope == "task" and self._task_id:
            where.append("task_id = ?")
            params.append(self._task_id)
        if kind:
            where.append("kind = ?")
            params.append(kind)
        sql = (
            "SELECT seq, step_index, kind, role, name, headline, content "
            "FROM hist.conversation_history "
            "WHERE " + " AND ".join(where) + " ORDER BY seq DESC LIMIT ?"
        )
        params.append(k)
        return [
            {kk: r[kk] for kk in r.keys()}
            for r in self._conn.execute(sql, params)
        ]

    def tables(self) -> list[str]:
        """Names of all scratch (``main``) tables defined so far."""
        cur = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name",
        )
        return [row["name"] for row in cur]

    def schema(self, table: str) -> list[dict]:
        """Column definitions for one scratch table."""
        cur = self._conn.execute(f"PRAGMA table_info({table})")
        return [
            {
                "name": row["name"],
                "type": row["type"],
                "notnull": bool(row["notnull"]),
                "pk": bool(row["pk"]),
            }
            for row in cur
        ]

    def digest(self) -> str:
        """A deterministic snapshot of the scratch space for working notes."""
        names = self.tables()
        if not names:
            return "scratch: (empty)"
        lines = [f"scratch (suffix _{self._session_suffix}):"]
        for name in names:
            cols = ", ".join(c["name"] for c in self.schema(name))
            try:
                n = self._conn.execute(
                    f'SELECT COUNT(*) AS n FROM "{name}"',
                ).fetchone()["n"]
            except sqlite3.Error:
                n = "?"
            lines.append(f"  - {name}({cols}) [{n} rows]")
        return "\n".join(lines)

    def close(self) -> None:
        try:
            self._conn.close()
        except sqlite3.Error:
            pass

    def __repr__(self) -> str:
        return f"<MemorySpace scratch={self.tables()}>"
