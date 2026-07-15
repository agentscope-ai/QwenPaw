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
import time
from collections import deque
from dataclasses import dataclass
from datetime import date
from pathlib import Path

_DEFAULT_ROW_CAP = 1000
_SAVED_TOOL_CANDIDATE_PAGE_SIZE = 200
_SAVED_TOOL_SCAN_MAX_BYTES = 32 * 1024 * 1024
_SAVED_TOOL_SCAN_MAX_SECONDS = 2.0

# The recall tool's own turns (its ``ms.*`` source + printed output) are
# durable but must never surface as *search hits* — otherwise a query matches
# the agent's own earlier queries/tracebacks (self-pollution). New rows are
# already kept out of the FTS index (see ``history._RECALL_TOOL_NAMES``); this
# filter also covers the LIKE fallback. Must match the recall tool names in
# ``repl.py`` and ``recall_tool.py``.
_RECALL_TOOL_NAMES = (
    "recall_history_python",
    "recall_history",
)
_RECALL_EXCL_PLACEHOLDERS = ", ".join("?" for _ in _RECALL_TOOL_NAMES)

# User-role stub rows the runtime injects to keep a turn going ("Continue
# working on the task."). They are not real requests: the active-turn floor
# must anchor on the request that STARTED the turn, or the floor jumps to the
# stub and the real request becomes searchable mid-turn again (echo loop).
# Values must match SYNTHETIC_USER_MESSAGE_TAGS in qwenpaw.constant (this
# module stays stdlib-only for the sandboxed REPL, so no import).
_SYNTHETIC_USER_TAGS = ("loop_continuation", "auto_continue")

_DATE_RE = re.compile(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})")
_SAVED_TOOL_FILE_RE = re.compile(
    r"call `read_file` with file_path="
    r'(?:"(?P<quoted>[^"]*)"|(?P<legacy>.+?))'
    r"\s+start_line=(?P<start_line>\d+)",
)

_FTS_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
# FTS5's boolean operators are UPPERCASE-only; we pass these through bare so a
# query like ``tank OR aquarium`` casts a wide net, while every other token is
# quoted as a literal phrase. A lowercase ``or`` stays a search term.
_FTS_OPERATORS = frozenset({"AND", "OR", "NOT"})


@dataclass
class _ScanBudget:
    """Shared byte budget for one saved-artifact recall operation."""

    remaining: int
    deadline: float
    exhausted: bool = False

    def is_exhausted(self) -> bool:
        if not self.exhausted and time.monotonic() >= self.deadline:
            self.exhausted = True
        return self.exhausted

    def read_line(self, file_obj) -> bytes | None:  # noqa: ANN001
        """Read at most the remaining budget from one binary line."""
        if self.remaining <= 0 or self.is_exhausted():
            self.exhausted = True
            return None
        raw = file_obj.readline(self.remaining + 1)
        if not raw:
            return b""
        if len(raw) > self.remaining:
            raw = raw[: self.remaining]
            self.remaining = 0
            self.exhausted = True
            return raw
        self.remaining -= len(raw)
        return raw


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
        saved_tool_scan_max_bytes: int = _SAVED_TOOL_SCAN_MAX_BYTES,
        saved_tool_scan_max_seconds: float = _SAVED_TOOL_SCAN_MAX_SECONDS,
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
        self._saved_tool_scan_max_bytes = max(0, saved_tool_scan_max_bytes)
        self._saved_tool_scan_max_seconds = max(
            0.0,
            saved_tool_scan_max_seconds,
        )
        self._session_suffix = sanitize_suffix(session_id)
        self._fts_ok: bool | None = None  # cached FTS5-availability check
        self._history_root: Path | None = None
        # Cached active-turn floor. ``hist`` is attached read-only, so
        # MAX(seq) can't change over this instance's life — compute it once.
        # A separate flag distinguishes "not computed yet" from a real
        # ``None`` result (no session / no active user turn).
        self._floor_cache: int | None = None
        self._floor_computed: bool = False
        if history_db_path is not None:
            abs_path = Path(history_db_path).expanduser().resolve()
            self._history_root = abs_path.parent
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
        rows = self._select(
            "SELECT seq, kind, role, name, tool_input, tool_state, content "
            "FROM hist.conversation_history "
            "WHERE " + " AND ".join(where) + " ORDER BY seq",
            tuple(params),
        )
        return self._attach_saved_tool_file_matches(rows, "")

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
        live window (folded tool results carry their own expand
        address). ``search`` excludes that span: without it, a second recall
        round top-k-matches the agent's OWN in-progress turn — the previous
        round's quoted findings and the request itself — and the echoes drown
        the real hits. ``expand`` / ``recall_tool`` / ``session`` stay
        unfiltered (verbatim replay is their point).

        Memoized per instance: a single ``search`` can consult the floor twice
        (the FTS path and the LIKE fallback), and the underlying ``hist`` is
        read-only, so the MAX(seq) scan runs at most once per MemorySpace
        rather than once per call site — the cost that matters on large
        histories in the recall subprocess.
        """
        if not self._floor_computed:
            self._floor_cache = self._compute_active_turn_floor()
            self._floor_computed = True
        return self._floor_cache

    def _compute_active_turn_floor(self) -> int | None:
        """Uncached MAX(seq) scan behind :meth:`_active_turn_floor`.

        Anchors on the latest REAL user request: runtime continuation stubs
        (tagged user-role rows) extend a turn rather than starting one, so
        they never move the floor.
        """
        if not self._session_id:
            return None
        where = ["session_id = ?", "kind = 'context_msg'", "role = 'user'"]
        params: list = [self._session_id]
        if self._agent_id:
            where.append("agent_id = ?")
            params.append(self._agent_id)
        for tag in _SYNTHETIC_USER_TAGS:
            where.append("(metadata IS NULL OR metadata NOT LIKE ?)")
            params.append(f'%"{tag}"%')
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
        (FTS5), with saved tool-output file fallback.

        Returns up to ``k`` rows ranked by relevance (bm25), each a dict with
        keys: ``seq``, ``session_id``, ``kind``, ``role``, ``name``,
        ``headline``, ``content`` (the FULL turn text — the answer is often
        buried late in a long, multi-topic turn, so don't judge from the head
        of it). By default searches this agent across
        all its sessions. Pass ``all_agents=True`` to span every agent, or pin
        a *specific* conversation / agent with ``session_id='cron:<job>'``
        and/or ``agent_id='<other>'`` (these AND-combine and take precedence).
        ``kind`` optionally filters by row kind. If matching content lives in
        a saved full tool-output file (because the history row only retained a
        truncated preview), search can return a ``tool_result`` row whose
        content is a small excerpt around the matching saved-file line, plus
        the file path. Artifact candidates are paged and files are streamed
        under a total byte/time budget; a ``_notice`` row explicitly reports
        when that fallback search is partial. The query is plain text:
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
            rows = [
                {kk: r[kk] for kk in r.keys()}
                for r in self._conn.execute(sql, params)
            ]
        except sqlite3.OperationalError:
            # Backstop: any residual MATCH-grammar edge case the sanitizer
            # missed degrades to LIKE rather than crashing the recall call.
            return self._search_like(query, targets, kind, int(k))
        if kind not in (None, "tool_result") or len(rows) >= int(k):
            return rows
        rows.extend(
            self._search_saved_tool_files(
                query,
                targets,
                limit=max(0, int(k) - len(rows)),
            ),
        )
        return rows

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
        if kind in (None, "tool_result") and len(rows) < int(k):
            rows.extend(
                self._search_saved_tool_files(
                    query,
                    targets,
                    limit=max(0, int(k) - len(rows)),
                ),
            )
        # If this is the *FTS-unavailable* fallback (not just an
        # all-punctuation query on an FTS-capable build), tell the model its
        # search degraded:
        # LIKE is a literal substring scan with no ranking and no boolean/OR
        # grammar, so it must query one term at a time. The notice shares the
        # row schema so a ``r["content"]`` loop over results never breaks.
        if not self._fts_available():
            rows.insert(0, self._like_notice())
        return rows

    def _saved_tool_candidates(
        self,
        targets: list[tuple[str, str]],
        *,
        limit: int = _SAVED_TOOL_CANDIDATE_PAGE_SIZE,
        before_seq: int | None = None,
    ) -> list[dict]:
        """Tool-result rows whose truncated preview points at a saved file."""
        where = [
            "kind = 'tool_result'",
            "content LIKE '%call `read_file` with file_path=%'",
            f"(name IS NULL OR name NOT IN ({_RECALL_EXCL_PLACEHOLDERS}))",
        ]
        params: list = [*_RECALL_TOOL_NAMES]
        excl = self._active_turn_exclusion()
        if excl:
            where.append(excl[0])
            params.extend(excl[1])
        for col, val in targets:
            where.append(f"{col} = ?")
            params.append(val)
        if before_seq is not None:
            where.append("seq < ?")
            params.append(int(before_seq))
        sql = (
            "SELECT seq, session_id, kind, role, name, headline, "
            "tool_call_id, content FROM hist.conversation_history "
            "WHERE " + " AND ".join(where) + " ORDER BY seq DESC LIMIT ?"
        )
        params.append(int(limit))
        return [
            {kk: r[kk] for kk in r.keys()}
            for r in self._conn.execute(sql, params)
        ]

    def _search_saved_tool_files(  # pylint: disable=too-many-branches
        self,
        query: str,
        targets: list[tuple[str, str]],
        *,
        limit: int,
    ) -> list[dict]:
        """Search full saved tool-result files referenced by history rows."""
        if limit <= 0:
            return []
        needles = self._query_needles(query)
        if not needles:
            return []
        rows: list[dict] = []
        seen: set[tuple[int, str, int]] = set()
        budget = self._new_saved_tool_scan_budget()
        before_seq: int | None = None
        while len(rows) < limit and not budget.is_exhausted():
            candidates = self._saved_tool_candidates(
                targets,
                before_seq=before_seq,
            )
            if not candidates:
                break
            next_before_seq = min(
                int(candidate["seq"]) for candidate in candidates
            )
            for row in candidates:
                if budget.is_exhausted():
                    break
                for path in self._saved_tool_paths(row.get("content")):
                    if budget.is_exhausted():
                        break
                    matches = self._file_line_matches(
                        path,
                        needles,
                        budget=budget,
                    )
                    for match in matches:
                        key = (
                            int(row["seq"]),
                            str(path),
                            int(match["line"]),
                        )
                        if key in seen:
                            continue
                        seen.add(key)
                        rows.append(
                            {
                                "seq": row["seq"],
                                "session_id": row.get("session_id"),
                                "kind": row.get("kind"),
                                "role": row.get("role"),
                                "name": row.get("name"),
                                "headline": (
                                    "saved tool output match at "
                                    f"{path.name}:{match['line']}"
                                ),
                                "content": (
                                    f"[saved tool output match]\n"
                                    f"tool_call_id="
                                    f"{row.get('tool_call_id') or ''}\n"
                                    f"file_path={path}\n"
                                    f"line={match['line']}\n"
                                    f"{match['excerpt']}"
                                ),
                            },
                        )
                        if len(rows) >= limit:
                            return rows
                    if budget.is_exhausted():
                        break
            before_seq = next_before_seq
            if len(candidates) < _SAVED_TOOL_CANDIDATE_PAGE_SIZE:
                break
        if budget.is_exhausted() and len(rows) < limit:
            rows.append(self._artifact_scan_notice())
        return rows

    def _attach_saved_tool_file_matches(
        self,
        rows: list[dict],
        query: str,
    ) -> list[dict]:
        """Annotate recall_tool rows with saved-file metadata when present."""
        needles = self._query_needles(query)
        out: list[dict] = []
        budget = self._new_saved_tool_scan_budget()
        for row in rows:
            out.append(row)
            for path in self._saved_tool_paths(row.get("content")):
                extra = {
                    "seq": row.get("seq"),
                    "kind": "_saved_tool_output",
                    "role": None,
                    "name": row.get("name"),
                    "tool_input": None,
                    "tool_state": row.get("tool_state"),
                    "content": (
                        "Full saved tool output is available at "
                        f"file_path={path}."
                    ),
                }
                if needles and not budget.is_exhausted():
                    matches = self._file_line_matches(
                        path,
                        needles,
                        limit=3,
                        budget=budget,
                    )
                    if matches:
                        content = str(extra["content"])
                        extra["content"] = (
                            content
                            + "\n\n"
                            + "\n\n".join(
                                f"match line {m['line']}:\n{m['excerpt']}"
                                for m in matches
                            )
                        )
                out.append(extra)
                if budget.is_exhausted():
                    out.append(self._artifact_scan_notice())
                    return out
        return out

    def _new_saved_tool_scan_budget(self) -> _ScanBudget:
        return _ScanBudget(
            remaining=self._saved_tool_scan_max_bytes,
            deadline=time.monotonic() + self._saved_tool_scan_max_seconds,
        )

    def _saved_tool_paths(self, content: object) -> list[Path]:
        """Extract and validate all saved tool-result paths from notices."""
        if self._history_root is None:
            return []
        try:
            root = self._history_root.resolve()
        except OSError:
            return []
        paths: list[Path] = []
        seen: set[Path] = set()
        for match in _SAVED_TOOL_FILE_RE.finditer(str(content or "")):
            raw_path = match.group("quoted")
            if raw_path is None:
                raw_path = match.group("legacy")
            if not raw_path:
                continue
            try:
                path = Path(raw_path).expanduser().resolve()
                path.relative_to(root)
            except (OSError, ValueError):
                continue
            if path in seen or not path.is_file():
                continue
            seen.add(path)
            paths.append(path)
        return paths

    @staticmethod
    def _query_needles(query: str) -> list[str]:
        """Plain AND-style terms suitable for a saved-file line scan."""
        return [
            tok.casefold()
            for tok in _FTS_TOKEN_RE.findall(query)
            if tok not in _FTS_OPERATORS
        ]

    @staticmethod
    def _file_line_matches(  # pylint: disable=too-many-branches
        path: Path,
        needles: list[str],
        *,
        limit: int = 5,
        context: int = 1,
        budget: _ScanBudget | None = None,
    ) -> list[dict]:
        """Stream line matches with bounded memory and byte consumption."""
        if not needles or limit <= 0:
            return []
        if budget is None:
            budget = _ScanBudget(
                remaining=_SAVED_TOOL_SCAN_MAX_BYTES,
                deadline=time.monotonic() + _SAVED_TOOL_SCAN_MAX_SECONDS,
            )
        matches: list[dict] = []
        previous = deque(maxlen=max(0, context))
        pending: list[dict] = []
        try:
            file_obj = path.open("rb")
        except OSError:
            return []
        with file_obj:
            line_no = 0
            while len(matches) < limit:
                raw = budget.read_line(file_obj)
                if raw in (None, b""):
                    break
                line_no += 1
                line = raw.decode("utf-8", errors="replace").rstrip("\r\n")

                for item in list(pending):
                    item["lines"].append((line_no, line))
                    item["remaining"] -= 1
                    if item["remaining"] <= 0:
                        matches.append(
                            MemorySpace._finish_file_match(item),
                        )
                        pending.remove(item)
                if len(matches) >= limit:
                    break

                folded = line.casefold()
                if all(needle in folded for needle in needles):
                    item = {
                        "line": line_no,
                        "lines": [*previous, (line_no, line)],
                        "remaining": max(0, context),
                    }
                    if context > 0:
                        pending.append(item)
                    else:
                        matches.append(MemorySpace._finish_file_match(item))
                previous.append((line_no, line))
                if budget.is_exhausted():
                    break
        for item in pending:
            if len(matches) >= limit:
                break
            matches.append(MemorySpace._finish_file_match(item))
        return matches

    @staticmethod
    def _finish_file_match(item: dict) -> dict:
        excerpt = "\n".join(
            f"{line_no}: {line}" for line_no, line in item["lines"]
        )
        return {"line": item["line"], "excerpt": excerpt}

    @staticmethod
    def _artifact_scan_notice() -> dict:
        """Flag that saved tool-output search stopped at its scan budget."""
        return {
            "seq": -1,
            "session_id": None,
            "kind": "_notice",
            "role": None,
            "name": None,
            "headline": "saved tool output search was partial",
            "content": (
                "NOTE: saved tool-output search reached its total scan byte "
                "or time budget. Results are partial; narrow the query or "
                "recall a specific tool_call_id/file_path."
            ),
        }

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
