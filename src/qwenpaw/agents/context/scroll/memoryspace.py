# -*- coding: utf-8 -*-
"""The model's SQLite working surface inside ``recall_history_python``.

Self-contained (stdlib only) so the sandboxed REPL cell can import it by bare
module name, without the rest of qwenpaw on the path.

``main`` is an in-memory database the model owns read/write — its scratch
space. The durable ``conversation_history`` file is ATTACHed **read-only** as
schema ``hist``: the model can ``SELECT ... FROM hist.conversation_history``
across sessions, but any write to ``hist.*`` is rejected by SQLite itself.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import date
from pathlib import Path

_DEFAULT_ROW_CAP = 1000

# The recall tool's own turns (its ``ms.*`` source + printed output) are
# durable but must never surface as *search hits* — otherwise a query matches
# the agent's own earlier queries/tracebacks (self-pollution). New rows are
# already kept out of the FTS index (see ``history._RECALL_TOOL_NAMES``); this
# filter also hides any legacy rows indexed before that, and covers the LIKE
# fallback. Must match the recall tool name in ``repl.py``; the legacy
# "execute_python" name is kept so pre-rename rows stay excluded.
_RECALL_TOOL_NAMES = ("recall_history_python", "execute_python")
_RECALL_EXCL_PLACEHOLDERS = ", ".join("?" for _ in _RECALL_TOOL_NAMES)

_DATE_RE = re.compile(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})")

_FTS_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
# FTS5's boolean operators are UPPERCASE-only; we pass these through bare so a
# query like ``tank OR aquarium`` casts a wide net, while every other token is
# quoted as a literal phrase. A lowercase ``or`` stays a search term.
_FTS_OPERATORS = frozenset({"AND", "OR", "NOT"})


def fts_match_query(raw: str) -> str:
    """The ``plainto_tsquery()`` that SQLite FTS5 lacks.

    FTS5 ``MATCH`` takes a query grammar, not plain text, so raw queries like
    ``C++`` or ``foo-bar`` raise a syntax error. Extract word tokens and quote
    each as a phrase (doubling embedded quotes); bare uppercase ``AND``/``OR``/
    ``NOT`` pass through as boolean operators (so ``tank OR aquarium`` works),
    everything else is AND-combined implicitly — keeping a plain multi-word
    query's implicit-AND while neutralising punctuation operators. A malformed
    operator sequence just raises in ``MATCH`` and the caller degrades to LIKE.
    Returns ``""`` when there are no word tokens (caller falls back to LIKE).
    """
    toks = _FTS_TOKEN_RE.findall(raw)
    return " ".join(
        t if t in _FTS_OPERATORS else '"' + t.replace('"', '""') + '"'
        for t in toks
    )


def sanitize_suffix(session_id: str | None) -> str:
    """Turn a session id into a SQL-identifier-safe table suffix."""
    if not session_id:
        return "scratch"
    return re.sub(r"[^0-9A-Za-z_]", "_", session_id)


def parse_date(value: object) -> date:
    """Pull the first ``YYYY-MM-DD`` (or ``YYYY/MM/DD``) out of any string.

    Tolerant of trailing time / surrounding text, so a raw stored timestamp
    like ``'2024-03-01 09:15:00'`` parses cleanly.
    """
    m = _DATE_RE.search(str(value))
    if not m:
        raise ValueError(f"no YYYY-MM-DD date in {value!r}")
    y, mo, d = (int(g) for g in m.groups())
    return date(y, mo, d)


# Mutating actions denied against the read-only ``hist`` schema. DDL is
# covered transitively: DROP/ALTER/CREATE authorize as writes to
# ``hist.sqlite_master``.
_HIST_WRITE_ACTIONS = frozenset(
    {sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE},
)


def _authorize(  # noqa: ANN001  # pylint: disable=unused-argument
    action,
    arg1,
    arg2,
    db_name,
    trigger,
):
    """SQLite authorizer for the model-facing recall connection.

    The durable history is mounted read-only as ``hist``; the model owns the
    ``main`` scratch DB read/write. We forbid only what would let it escape
    that contract:

    * ``ATTACH``/``DETACH`` — blocks re-mounting ``hist`` read-write and
      mounting another workspace's store (the documented escapes).
    * ``INSERT``/``UPDATE``/``DELETE`` on ``hist`` — defense-in-depth over the
      read-only file handle (and these transitively block DDL on ``hist``).

    Everything else (scratch reads/writes, ``SELECT`` and read pragmas such as
    ``data_version`` on ``hist``, functions, transactions) is allowed.
    """
    if action in (sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH):
        return sqlite3.SQLITE_DENY
    if db_name == "hist" and action in _HIST_WRITE_ACTIONS:
        return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


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
        agent_id: str | None = None,
        row_cap: int = _DEFAULT_ROW_CAP,
        scratch_db_path: str | Path | None = None,
    ) -> None:
        # ``main`` is in-memory by default; a file path keeps derived scratch
        # tables across calls (the sandboxed REPL runs a fresh process per
        # cell).
        main = (
            str(Path(scratch_db_path).expanduser())
            if scratch_db_path is not None
            else ":memory:"
        )
        self._conn = sqlite3.connect(main, uri=True)
        self._conn.row_factory = sqlite3.Row
        self._row_cap = row_cap
        self._session_id = session_id
        self._agent_id = agent_id
        self._session_suffix = sanitize_suffix(session_id)
        self._fts_ok: bool | None = None  # cached FTS5-availability check
        if history_db_path is not None:
            abs_path = Path(history_db_path).expanduser().resolve()
            self._conn.execute(
                "ATTACH DATABASE ? AS hist",
                (f"file:{abs_path}?mode=ro",),
            )
        # Lock the connection down AFTER our own ATTACH: the model runs
        # arbitrary SQL through sql_query/sql_exec, so guard at the engine
        # level. An authorizer fires at prepare time and can't be evaded by
        # comments, casing, or stacked statements the way a string blocklist
        # can.
        self._conn.set_authorizer(_authorize)

    @property
    def session_suffix(self) -> str:
        return self._session_suffix

    @property
    def session_id(self) -> str | None:
        """The current session id (this conversation)."""
        return self._session_id

    @property
    def agent_id(self) -> str | None:
        """The current agent id — scopes recall to this agent across
        sessions."""
        return self._agent_id

    def sql_exec(self, sql: str, params: tuple | dict | None = None) -> int:
        """Run a non-SELECT statement. Returns rowcount or lastrowid.

        Use for CREATE TABLE / INSERT / UPDATE / DELETE in the scratch space.
        Parameters are bound, not interpolated. Writes targeting the read-only
        ``hist`` schema raise ``sqlite3.OperationalError``.
        """
        with self._conn:
            cur = self._conn.execute(sql, params or ())
            return int(cur.lastrowid or cur.rowcount or 0)

    def sql_query(
        self,
        sql: str,
        params: tuple | dict | None = None,
    ) -> list[dict]:
        """Run a SELECT (or any read query). Returns up to ``row_cap`` rows.

        An escape hatch for custom aggregation (counting/ranking mentions);
        for ordinary recall prefer :meth:`expand` / :meth:`search` /
        :meth:`recall_tool`. Rows come back as plain dicts; on overflow only
        the first ``row_cap`` are returned plus a trailing ``_truncated``
        marker. Bind values through ``params`` — never f-string them in.
        """
        return self._select(sql, params or ())

    def _select(self, sql: str, params: tuple | dict) -> list[dict]:
        """Execute a read query and return capped, dict-shaped rows."""
        cur = self._conn.execute(sql, params)
        rows: list[dict] = []
        for i, row in enumerate(cur):
            if i >= self._row_cap:
                rows.append({"_truncated": True, "_row_cap": self._row_cap})
                break
            rows.append({k: row[k] for k in row.keys()})
        return rows

    # -- intent-named recall over the read-only history -----------------------

    def expand(self, lo: int, hi: int) -> list[dict]:
        """Full durable turns in the seq span ``[lo, hi]``, oldest first.

        ``seq`` is a globally-unique address (one autoincrement across every
        session and agent), so a span needs no scope filter. This is the
        primary way to re-read the evicted turns the index points you at.
        """
        return self._select(
            "SELECT seq, kind, role, name, content, headline "
            "FROM hist.conversation_history "
            "WHERE seq BETWEEN ? AND ? ORDER BY seq",
            (int(lo), int(hi)),
        )

    def recall_tool(
        self,
        tool_call_id: str,
        *,
        all_agents: bool = False,
    ) -> list[dict]:
        """Re-read a tool call and its result by ``tool_call_id``.

        Scoped to this agent's history by default — tool-call ids are not
        globally unique, so widening risks cross-agent collisions; pass
        ``all_agents=True`` only when you mean to. Returns the matching rows
        oldest-first (typically the call turn followed by its result).
        """
        where = ["tool_call_id = ?"]
        params: list = [str(tool_call_id)]
        if not all_agents and self._agent_id:
            where.append("agent_id = ?")
            params.append(self._agent_id)
        return self._select(
            "SELECT seq, kind, role, name, tool_input, tool_state, content "
            "FROM hist.conversation_history "
            "WHERE " + " AND ".join(where) + " ORDER BY seq",
            tuple(params),
        )

    def sessions(
        self,
        *,
        all_agents: bool = False,
        limit: int = 50,
    ) -> list[dict]:
        """List the conversations recorded in durable history.

        Scoped to this agent's own sessions by default (e.g. the live chat
        plus any ``cron:<job-id>`` / ``main`` heartbeat sessions it has run);
        pass ``all_agents=True`` for every agent in the workspace. Each row is
        a ``session_id`` with its turn count and ``seq``/time span — use it to
        discover a session, then read it with :meth:`session`.
        """
        where: list[str] = []
        params: list = []
        if not all_agents and self._agent_id:
            where.append("agent_id = ?")
            params.append(self._agent_id)
        clause = ("WHERE " + " AND ".join(where) + " ") if where else ""
        params.append(int(limit))
        return self._select(
            "SELECT session_id, COUNT(*) AS turns, MIN(seq) AS first_seq, "
            "MAX(seq) AS last_seq, MAX(created_at) AS last_at "
            "FROM hist.conversation_history "
            f"{clause}GROUP BY session_id ORDER BY last_seq DESC LIMIT ?",
            tuple(params),
        )

    def session(
        self,
        session_id: str,
        *,
        all_agents: bool = False,
        limit: int = 200,
    ) -> list[dict]:
        """Read one conversation's turns oldest-first, by ``session_id``.

        The companion to :meth:`sessions` — e.g.
        ``ms.session("cron:nightly-report")`` reconstructs exactly what that
        scheduled job said and did. Scoped to this agent's history by default:
        session ids are not globally unique (``main``, ``local``,
        ``cron:<job>`` recur across agents in a shared workspace), so widening
        risks reading another agent's conversation. Pass ``all_agents=True``
        only when you mean to span every agent.
        """
        where = ["session_id = ?"]
        params: list = [str(session_id)]
        if not all_agents and self._agent_id:
            where.append("agent_id = ?")
            params.append(self._agent_id)
        params.append(int(limit))
        return self._select(
            "SELECT seq, kind, role, name, headline, content "
            "FROM hist.conversation_history "
            "WHERE " + " AND ".join(where) + " ORDER BY seq LIMIT ?",
            tuple(params),
        )

    def agents(self, *, limit: int = 50) -> list[dict]:
        """List every agent that has written history in this workspace.

        Always workspace-wide (a discovery/ops view), so it can surface other
        agents — each row is an ``agent_id`` with its session and turn counts.
        """
        return self._select(
            "SELECT agent_id, COUNT(DISTINCT session_id) AS sessions, "
            "COUNT(*) AS turns, MAX(created_at) AS last_at "
            "FROM hist.conversation_history "
            "GROUP BY agent_id ORDER BY last_at DESC LIMIT ?",
            (int(limit),),
        )

    def _scope_filters(
        self,
        all_agents: bool,
        session_id: str | None,
        agent_id: str | None,
    ) -> list[tuple[str, str]]:
        """Resolve the ``(column, value)`` lineage filters for a search.

        An explicit ``session_id`` and/or ``agent_id`` pin the search to that
        conversation / agent (AND-combined). With neither given, the default
        is this agent's own cross-session history; ``all_agents`` drops the
        filter to span every agent in the workspace.
        """
        if session_id is not None or agent_id is not None:
            pinned: list[tuple[str, str]] = []
            if session_id is not None:
                pinned.append(("session_id", session_id))
            if agent_id is not None:
                pinned.append(("agent_id", agent_id))
            return pinned
        if all_agents:
            return []
        if self._agent_id:
            return [("agent_id", self._agent_id)]
        return []

    def _active_turn_floor(self) -> int | None:
        """Seq of the current session's latest real user message, or None.

        Everything at or after it is the ACTIVE TURN — the request the agent
        is answering right now plus its in-progress reply, all still in the
        live window (folded tool results carry their own ``ms.expand``
        address). ``search`` excludes that span: without it, a second recall
        round top-k-matches the agent's OWN in-progress turn — the previous
        round's quoted findings and the request itself — and the echoes drown
        the real hits. ``expand`` / ``recall_tool`` / ``session`` stay
        unfiltered (verbatim replay is their point).
        """
        if not self._session_id:
            return None
        where = ["session_id = ?", "kind = 'context_msg'", "role = 'user'"]
        params: list = [self._session_id]
        if self._agent_id:
            where.append("agent_id = ?")
            params.append(self._agent_id)
        try:
            row = self._conn.execute(
                "SELECT MAX(seq) AS s FROM hist.conversation_history "
                "WHERE " + " AND ".join(where),
                tuple(params),
            ).fetchone()
        except sqlite3.OperationalError:
            return None  # no hist attached
        return row["s"] if row and row["s"] is not None else None

    def _active_turn_exclusion(
        self,
        prefix: str = "",
    ) -> tuple[str, list] | None:
        """``(clause, params)`` excluding the active turn from a search."""
        floor = self._active_turn_floor()
        if floor is None:
            return None
        conds = [f"{prefix}session_id = ?"]
        params: list = [self._session_id]
        if self._agent_id:
            conds.append(f"{prefix}agent_id = ?")
            params.append(self._agent_id)
        conds.append(f"{prefix}seq >= ?")
        params.append(floor)
        return "NOT (" + " AND ".join(conds) + ")", params

    def search(
        self,
        query: str,
        *,
        session_id: str | None = None,
        agent_id: str | None = None,
        all_agents: bool = False,
        kind: str | None = None,
        k: int = 10,
    ) -> list[dict]:
        """Full-text search over ``hist.conversation_history`` content
        (FTS5).

        Returns up to ``k`` rows ranked by relevance (bm25), each a dict with
        keys: ``seq``, ``session_id``, ``kind``, ``role``, ``name``,
        ``headline``, ``content`` (the FULL turn text — the answer is often
        buried late in a long, multi-topic turn, so don't judge from the head
        of it). By default searches this agent across
        all its sessions. Pass ``all_agents=True`` to span every agent, or pin
        a *specific* conversation / agent with ``session_id='cron:<job>'``
        and/or ``agent_id='<other>'`` (these AND-combine and take precedence).
        ``kind`` optionally filters by row kind. The query is plain text:
        punctuation is treated as word separators (so ``C++`` searches the
        term ``C``), not FTS5 operators. Falls back to a LIKE scan if this
        SQLite lacks FTS5 or the query has no word tokens.

        The agent's current ACTIVE TURN (the latest user request of this
        session and everything after it) never appears in the hits — it is
        already in the live window, and matching it would only echo the
        previous recall round back. Earlier evicted turns of this session
        remain searchable.
        """
        targets = self._scope_filters(all_agents, session_id, agent_id)
        # FTS5 MATCH takes a query grammar, not plain text. Sanitize first; an
        # all-punctuation query (no word tokens) has nothing to MATCH, so use
        # the LIKE scan instead — as we also do when FTS5 is unavailable.
        match = fts_match_query(query)
        if not self._fts_available() or not match:
            return self._search_like(query, targets, kind, int(k))
        # bm25 and the `tbl MATCH` syntax need the table NAME, not an alias.
        fts = "conversation_history_fts"
        # Exclude the recall tool's own turns (NULL-safe: keep un-named rows).
        where = [
            f"{fts} MATCH ?",
            f"(ch.name IS NULL OR ch.name NOT IN "
            f"({_RECALL_EXCL_PLACEHOLDERS}))",
        ]
        params: list = [match, *_RECALL_TOOL_NAMES]
        excl = self._active_turn_exclusion("ch.")
        if excl:
            where.append(excl[0])
            params.extend(excl[1])
        for col, val in targets:
            where.append(f"ch.{col} = ?")
            params.append(val)
        if kind:
            where.append("ch.kind = ?")
            params.append(kind)
        sql = (
            "SELECT ch.seq, ch.session_id, ch.kind, ch.role, "
            "ch.name, ch.headline, ch.content "
            f"FROM hist.{fts} JOIN hist.conversation_history ch "
            f"ON ch.seq = {fts}.rowid "
            "WHERE " + " AND ".join(where) + f" ORDER BY bm25({fts}) LIMIT ?"
        )
        params.append(int(k))
        try:
            return [
                {kk: r[kk] for kk in r.keys()}
                for r in self._conn.execute(sql, params)
            ]
        except sqlite3.OperationalError:
            # Backstop: any residual MATCH-grammar edge case the sanitizer
            # missed degrades to LIKE rather than crashing the recall call.
            return self._search_like(query, targets, kind, int(k))

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

    def _search_like(self, query, targets, kind, k) -> list[dict]:
        """LIKE fallback when FTS5 is unavailable.

        ``targets`` is the resolved ``(column, value)`` lineage filter list
        from :meth:`_scope_filters` (already accounts for scope vs explicit
        session_id/agent_id).
        """
        # Exclude the recall tool's own turns (NULL-safe: keep un-named rows).
        where = [
            "content LIKE ?",
            f"(name IS NULL OR name NOT IN ({_RECALL_EXCL_PLACEHOLDERS}))",
        ]
        params: list = [f"%{query}%", *_RECALL_TOOL_NAMES]
        excl = self._active_turn_exclusion()
        if excl:
            where.append(excl[0])
            params.extend(excl[1])
        for col, val in targets:
            where.append(f"{col} = ?")
            params.append(val)
        if kind:
            where.append("kind = ?")
            params.append(kind)
        sql = (
            "SELECT seq, session_id, kind, role, name, headline, content "
            "FROM hist.conversation_history "
            "WHERE " + " AND ".join(where) + " ORDER BY seq DESC LIMIT ?"
        )
        params.append(k)
        rows = [
            {kk: r[kk] for kk in r.keys()}
            for r in self._conn.execute(sql, params)
        ]
        # If this is the *FTS-unavailable* fallback (not just an
        # all-punctuation query on an FTS-capable build), tell the model its
        # search degraded:
        # LIKE is a literal substring scan with no ranking and no boolean/OR
        # grammar, so it must query one term at a time. The notice shares the
        # row schema so a ``r["content"]`` loop over results never breaks.
        if not self._fts_available():
            rows.insert(0, self._like_notice())
        return rows

    @staticmethod
    def _like_notice() -> dict:
        """A schema-compatible leading row flagging LIKE-degraded search."""
        return {
            "seq": -1,
            "session_id": None,
            "kind": "_notice",
            "role": None,
            "name": None,
            "headline": "search degraded to LIKE (this SQLite lacks FTS5)",
            "content": (
                "NOTE: full-text search is unavailable (no FTS5 in this "
                "SQLite build), so this is a literal substring (LIKE) scan — "
                "no relevance ranking, and boolean/OR syntax is NOT supported "
                "(it would be matched literally). Search a single term at a "
                "time and scan the rows yourself."
            ),
        }

    def days_between(
        self,
        d1: object,
        d2: object,
        *,
        inclusive: bool = False,
    ) -> int:
        """Absolute number of days between two dates — order-independent.

        Each argument may be a date string or any value containing one (e.g. a
        stored timestamp); the first ``YYYY-MM-DD`` in it is used. LLM calendar
        arithmetic is flaky, so prefer this over computing the span by hand.
        Pass ``inclusive=True`` to count both endpoints.
        """
        n = abs((parse_date(d2) - parse_date(d1)).days)
        return n + 1 if inclusive else n

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
