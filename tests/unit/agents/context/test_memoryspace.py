# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,protected-access,unused-argument
"""Unit tests for :class:`MemorySpace` — the model's SQLite recall surface.

The security-critical guarantee is that the model, which runs arbitrary SQL
here, cannot escape the read-only attach of durable history. These tests pin
the SQLite-authorizer contract plus the recall ``scope`` semantics.
"""

import sqlite3
from pathlib import Path

import pytest

from qwenpaw.agents.context.scroll.history import HistoryStore
from qwenpaw.agents.context.scroll.memoryspace import (
    MemorySpace,
    fts_match_query,
    sanitize_suffix,
)
from qwenpaw.agents.context.types import LogEntry


@pytest.fixture
def history_db(tmp_path: Path) -> Path:
    """A durable store with two agents across two sessions."""
    h = HistoryStore(tmp_path / "history.db")
    h.append(
        session_id="s1",
        agent_id="ag1",
        dedup_key="m1",
        entry=LogEntry(
            kind="model_turn",
            role="assistant",
            content="tanks rolled in",
            headline="battle",
        ),
    )
    h.append(
        session_id="s2",
        agent_id="ag1",
        dedup_key="m2",
        entry=LogEntry(
            kind="model_turn",
            role="assistant",
            content="tanks regrouped later",
        ),
    )
    h.append(
        session_id="s3",
        agent_id="ag2",
        dedup_key="m3",
        entry=LogEntry(
            kind="model_turn",
            role="assistant",
            content="tanks of another agent",
        ),
    )
    h.close()
    return tmp_path / "history.db"


@pytest.fixture
def ms(history_db: Path) -> MemorySpace:
    space = MemorySpace(
        history_db_path=str(history_db),
        session_id="s1",
        agent_id="ag1",
    )
    yield space
    space.close()


# -- the read-only-attach contract ------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "ATTACH DATABASE ':memory:' AS other",
        "DETACH DATABASE hist",
        "INSERT INTO hist.conversation_history(session_id, kind) "
        "VALUES ('x', 'k')",
        "UPDATE hist.conversation_history SET content = 'tampered'",
        "DELETE FROM hist.conversation_history",
        "DROP TABLE hist.conversation_history",
    ],
)
def test_authorizer_blocks_escape_attempts(ms: MemorySpace, sql: str):
    with pytest.raises(sqlite3.Error):
        ms.sql_exec(sql)
    # And the durable data is untouched.
    assert (
        ms.sql_query(
            "SELECT COUNT(*) AS n FROM hist.conversation_history",
        )[
            0
        ]["n"]
        == 3
    )


def test_scratch_is_read_write(ms: MemorySpace):
    ms.sql_exec("CREATE TABLE notes(x INTEGER)")
    ms.sql_exec("INSERT INTO notes VALUES (42)")
    assert ms.sql_query("SELECT x FROM notes")[0]["x"] == 42
    assert "notes" in ms.tables()


def test_hist_is_readable(ms: MemorySpace):
    rows = ms.sql_query(
        "SELECT content FROM hist.conversation_history ORDER BY seq",
    )
    assert rows[0]["content"] == "tanks rolled in"


# -- recall scope semantics --------------------------------------------------


def test_search_default_is_this_agent_cross_session(ms: MemorySpace):
    contents = {r["content"] for r in ms.search("tanks")}
    # Both of ag1's turns (s1 + s2), none of ag2's — isolation by default.
    assert "tanks rolled in" in contents
    assert "tanks regrouped later" in contents
    assert "tanks of another agent" not in contents


def test_search_excludes_recall_tool_own_turns(tmp_path: Path):
    """The recall tool's own source/output must not surface as search hits, or
    a query matches the agent's earlier queries (self-pollution)."""
    h = HistoryStore(tmp_path / "history.db")
    h.append(
        session_id="s1",
        agent_id="ag1",
        dedup_key="real",
        entry=LogEntry(
            kind="model_turn",
            role="assistant",
            content="the car needs service after 10000 miles",
        ),
    )
    # The agent's own recall call (its Python source) and its printed output —
    # both carry the searched keywords and both must be excluded.
    h.append(
        session_id="s1",
        agent_id="ag1",
        dedup_key="recall_call",
        entry=LogEntry(
            kind="model_turn",
            role="assistant",
            name="recall_history_python",
            content='ms.search("car service")',
        ),
    )
    h.append(
        session_id="s1",
        agent_id="ag1",
        dedup_key="recall_out",
        entry=LogEntry(
            kind="tool_result",
            role="assistant",
            name="recall_history",
            content="stdout: searching for car service ...",
            tool_call_id="t1",
        ),
    )
    h.close()
    space = MemorySpace(
        history_db_path=str(tmp_path / "history.db"),
        session_id="s1",
        agent_id="ag1",
    )
    try:
        hits = space.search("car service")
        contents = [r["content"] for r in hits]
        assert contents == ["the car needs service after 10000 miles"]
    finally:
        space.close()


def test_search_excludes_the_active_turn(tmp_path: Path):
    """The current request and its in-progress reply must not surface as
    hits: they are already in the live window, and a second recall round
    would otherwise top-k-match the previous round's quoted findings
    (echo loop). Earlier turns of the SAME session stay searchable."""
    h = HistoryStore(tmp_path / "history.db")
    rows = [
        ("old_u", "context_msg", "user", "tanks question from earlier"),
        ("old_a", "model_turn", "assistant", "tanks were parked at base"),
        # The ACTIVE turn: the latest user request + the reply being written.
        ("cur_u", "context_msg", "user", "tanks question retried"),
        ("cur_a", "model_turn", "assistant", "tanks quote from last recall"),
    ]
    for key, kind, role, content in rows:
        h.append(
            session_id="s1",
            agent_id="ag1",
            dedup_key=key,
            entry=LogEntry(kind=kind, role=role, content=content),
        )
    h.append(  # another session is untouched by the exclusion
        session_id="s2",
        agent_id="ag1",
        dedup_key="other",
        entry=LogEntry(
            kind="model_turn",
            role="assistant",
            content="tanks moved in another session",
        ),
    )
    h.close()
    space = MemorySpace(
        history_db_path=str(tmp_path / "history.db"),
        session_id="s1",
        agent_id="ag1",
    )
    try:
        expected = {
            "tanks question from earlier",
            "tanks were parked at base",
            "tanks moved in another session",
        }
        assert {r["content"] for r in space.search("tanks", k=10)} == expected
        # The LIKE fallback applies the same exclusion.
        like = space._search_like("tanks", [("agent_id", "ag1")], None, 10)
        got = {r["content"] for r in like if r["kind"] != "_notice"}
        assert got == expected
    finally:
        space.close()


def test_active_turn_floor_is_computed_once_per_instance(
    ms: MemorySpace,
    monkeypatch,
):
    """The MAX(seq) scan behind the active-turn exclusion is memoized: a
    single search consults the floor twice (FTS path + LIKE fallback) and the
    read-only history can't change under the instance, so it must run at most
    once — the cost that accrues on large histories in the recall subprocess.
    """
    calls = {"n": 0}
    real = ms._compute_active_turn_floor

    def counting():
        calls["n"] += 1
        return real()

    monkeypatch.setattr(ms, "_compute_active_turn_floor", counting)

    # Consult it across every path that would otherwise re-query.
    ms.search("tanks", k=5)
    ms._search_like("tanks", [("agent_id", "ag1")], None, 5)
    ms._active_turn_floor()

    assert calls["n"] == 1


def test_active_turn_floor_ignores_continuation_stubs(tmp_path: Path):
    """A loop-continuation stub row (user-role, tagged) must not move the
    active-turn floor: the floor anchors on the REAL request that started
    the turn, so the whole still-live extended turn stays excluded from
    search instead of leaking back in as echo."""
    h = HistoryStore(tmp_path / "history.db")
    rows = [
        ("old", "model_turn", "assistant", "tanks parked at base", None),
        ("req", "context_msg", "user", "tanks question", None),
        ("a1", "model_turn", "assistant", "tanks quote from recall", None),
        (
            "stub",
            "context_msg",
            "user",
            "Continue working on the task.",
            {"qwenpaw_tag": "loop_continuation"},
        ),
        ("a2", "model_turn", "assistant", "tanks continued reply", None),
    ]
    for key, kind, role, content, metadata in rows:
        h.append(
            session_id="s1",
            agent_id="ag1",
            dedup_key=key,
            entry=LogEntry(
                kind=kind,
                role=role,
                content=content,
                metadata=metadata or {},
            ),
        )
    h.close()
    space = MemorySpace(
        history_db_path=str(tmp_path / "history.db"),
        session_id="s1",
        agent_id="ag1",
    )
    try:
        # Floor = the real request's seq (NOT the stub's): everything from
        # the request onward is active-turn and excluded from search.
        hits = {r["content"] for r in space.search("tanks", k=10)}
        assert hits == {"tanks parked at base"}
    finally:
        space.close()


def test_search_rows_carry_session_id(ms: MemorySpace):
    # Cross-session/agent search is only useful if a hit says which session it
    # came from — the model needs ``session_id`` to follow up (it used to guess
    # the key and crash with KeyError).
    rows = {r["content"]: r for r in ms.search("tanks", all_agents=True)}
    assert rows["tanks rolled in"]["session_id"] == "s1"
    assert rows["tanks regrouped later"]["session_id"] == "s2"


def test_fts_match_query_passes_boolean_operators():
    # Bare UPPERCASE AND/OR/NOT are FTS5 operators (so the model can cast a
    # wide net); every other token is a quoted literal; a plain query is AND.
    assert fts_match_query("tank OR aquarium") == '"tank" OR "aquarium"'
    assert fts_match_query("plain words") == '"plain" "words"'
    # lowercase 'or' is a search term, not an operator
    assert fts_match_query("salt or pepper") == '"salt" "or" "pepper"'
    # punctuation operators are still neutralised
    assert fts_match_query("F-15") == '"F" "15"'


def test_search_or_widens_beyond_a_single_term(tmp_path: Path):
    h = HistoryStore(tmp_path / "history.db")
    h.append(
        session_id="s1",
        agent_id="ag1",
        dedup_key="a",
        entry=LogEntry(
            kind="model_turn",
            role="user",
            content="cleaned the goldfish tank",
        ),
    )
    h.append(
        session_id="s1",
        agent_id="ag1",
        dedup_key="b",
        entry=LogEntry(
            kind="model_turn",
            role="user",
            content="bought an aquarium filter",
        ),
    )
    h.close()
    space = MemorySpace(
        history_db_path=str(tmp_path / "history.db"),
        session_id="s1",
        agent_id="ag1",
    )
    try:
        # OR matches EITHER term (2 rows); the AND form would match neither.
        assert len(space.search("tank OR aquarium")) == 2
        assert len(space.search("tank aquarium")) == 0
    finally:
        space.close()


def test_search_all_agents_spans_the_workspace(ms: MemorySpace):
    contents = {r["content"] for r in ms.search("tanks", all_agents=True)}
    assert "tanks of another agent" in contents
    assert len(contents) == 3


def test_search_pins_to_an_explicit_session(ms: MemorySpace):
    # ms is on s1, but an explicit session_id targets a different one.
    contents = {r["content"] for r in ms.search("tanks", session_id="s2")}
    assert contents == {"tanks regrouped later"}


def test_search_pins_to_an_explicit_agent(ms: MemorySpace):
    # The default agent scope hides ag2; pin to it to read its history.
    contents = {r["content"] for r in ms.search("tanks", agent_id="ag2")}
    assert contents == {"tanks of another agent"}


def test_explicit_target_takes_precedence(ms: MemorySpace):
    # An explicit session_id wins even against all_agents=True.
    contents = {
        r["content"]
        for r in ms.search("tanks", all_agents=True, session_id="s1")
    }
    assert contents == {"tanks rolled in"}


def test_row_cap_truncates_with_marker(history_db: Path):
    space = MemorySpace(
        history_db_path=str(history_db),
        session_id="s1",
        agent_id="ag1",
        row_cap=2,
    )
    try:
        rows = space.sql_query("SELECT seq FROM hist.conversation_history")
        assert rows[-1].get("_truncated") is True
        assert len([r for r in rows if "_truncated" not in r]) == 2
    finally:
        space.close()


def _hits(rows: list[dict]) -> set:
    """Result contents minus the LIKE-degraded notice row."""
    return {r["content"] for r in rows if r["kind"] != "_notice"}


def test_like_fallback_respects_scope(ms: MemorySpace):
    """Force the no-FTS path; scope + explicit targeting still hold."""
    ms._fts_ok = False
    contents = _hits(ms.search("tanks"))
    assert "tanks of another agent" not in contents
    assert "tanks rolled in" in contents
    # explicit targeting works on the LIKE path too
    pinned = _hits(ms.search("tanks", agent_id="ag2"))
    assert pinned == {"tanks of another agent"}


def test_like_fallback_emits_degradation_notice(ms: MemorySpace):
    """Without FTS5 the model must be told search degraded to a LIKE scan, so
    it stops using OR/boolean grammar that silently matches nothing."""
    ms._fts_ok = False
    rows = ms.search("tanks")
    assert rows[0]["kind"] == "_notice"
    assert "FTS5" in rows[0]["content"]
    # The notice shares the row schema, so a content-iterating loop is safe.
    assert set(rows[0].keys()) >= {"seq", "kind", "role", "content"}


def test_no_notice_when_fts_available(ms: MemorySpace):
    """The notice is FTS-unavailable-only — a normal FTS build never sees it,
    even when a query degrades to LIKE for lack of word tokens."""
    # All-punctuation query falls back to LIKE, but FTS5 *is* available here.
    rows = ms.search("!!!")
    assert all(r["kind"] != "_notice" for r in rows)


# -- intent-named recall helpers --------------------------------------------


def test_expand_returns_full_turns_in_span(ms: MemorySpace):
    rows = ms.expand(1, 99)
    # Globally-unique seq spans every session/agent, so expand is unscoped.
    assert {r["content"] for r in rows} == {
        "tanks rolled in",
        "tanks regrouped later",
        "tanks of another agent",
    }


def test_recall_tool_is_agent_scoped_by_default(history_db: Path, tmp_path):
    h = HistoryStore(history_db)
    h.append(
        session_id="s9",
        agent_id="ag2",
        dedup_key="tcX",
        entry=LogEntry(
            kind="tool_result",
            role="assistant",
            content="other agent tool",
            tool_call_id="shared",
        ),
    )
    h.close()
    space = MemorySpace(
        history_db_path=str(history_db),
        session_id="s1",
        agent_id="ag1",
    )
    try:
        # ag1 has no 'shared' tcid → empty; widening reaches ag2's row.
        assert not space.recall_tool("shared")
        assert len(space.recall_tool("shared", all_agents=True)) == 1
    finally:
        space.close()


# -- session / agent discovery ----------------------------------------------


def test_sessions_lists_this_agents_conversations(ms: MemorySpace):
    rows = {r["session_id"]: r for r in ms.sessions()}
    # ag1 ran in s1 and s2; ag2's s3 is hidden by the default agent scope.
    assert set(rows) == {"s1", "s2"}
    assert rows["s1"]["turns"] == 1


def test_sessions_all_agents_spans_the_workspace(ms: MemorySpace):
    ids = {r["session_id"] for r in ms.sessions(all_agents=True)}
    assert ids == {"s1", "s2", "s3"}


def test_session_is_agent_scoped_by_default(ms: MemorySpace):
    # ag2's s3 is hidden by the default agent scope: session ids are not
    # globally unique (main/local/cron:<job> recur across agents), so the
    # default must not leak another agent's conversation. all_agents widens.
    assert ms.session("s3") == []
    rows = ms.session("s3", all_agents=True)
    assert [r["content"] for r in rows] == ["tanks of another agent"]


def test_agents_is_workspace_wide(ms: MemorySpace):
    rows = {r["agent_id"]: r for r in ms.agents()}
    assert set(rows) == {"ag1", "ag2"}
    assert rows["ag1"]["sessions"] == 2  # s1 + s2


def test_sanitize_suffix():
    assert sanitize_suffix(None) == "scratch"
    assert sanitize_suffix("a-b.c/d") == "a_b_c_d"
    assert sanitize_suffix("ok_123") == "ok_123"


# -- SQL values are bound, not f-string-concatenated ------------------------


def test_recall_values_with_sql_metacharacters_are_bound(tmp_path: Path):
    """Recall must bind ``session_id``/``agent_id``/``tool_call_id`` as SQL
    parameters, never f-string them in. A value carrying a single quote (e.g.
    ``O'Brien's task``) would otherwise break the WHERE clause or open an
    injection; here it must round-trip cleanly and match only its own row."""
    quoted_session = "O'Brien's task"
    quoted_agent = "ag'1"
    quoted_tcid = "tc'1"
    h = HistoryStore(tmp_path / "history.db")
    h.append(
        session_id=quoted_session,
        agent_id=quoted_agent,
        dedup_key="m1",
        entry=LogEntry(
            kind="tool_result",
            role="assistant",
            content="briefing for the quoted session",
            tool_call_id=quoted_tcid,
        ),
    )
    # A decoy under a different agent the scoped recall must NOT return.
    h.append(
        session_id=quoted_session,
        agent_id="ag2",
        dedup_key="m2",
        entry=LogEntry(
            kind="model_turn",
            role="assistant",
            content="other agent same session name",
        ),
    )
    h.close()
    space = MemorySpace(
        history_db_path=str(tmp_path / "history.db"),
        session_id=quoted_session,
        agent_id=quoted_agent,
    )
    try:
        # session(): the path ekzhu flagged — agent-scoped, value bound.
        rows = space.session(quoted_session)
        assert [r["content"] for r in rows] == [
            "briefing for the quoted session",
        ]
        # recall_tool(): tool_call_id bound, not concatenated.
        rows = space.recall_tool(quoted_tcid)
        assert [r["content"] for r in rows] == [
            "briefing for the quoted session",
        ]
        # search() with an explicit quoted agent_id pin — both MATCH arg and
        # the lineage filter are bound.
        rows = space.search("briefing", agent_id=quoted_agent)
        assert [r["content"] for r in rows] == [
            "briefing for the quoted session",
        ]
        # LIKE fallback path takes the same bound (col, value) filters.
        # (Drop the leading FTS-unavailable notice row the LIKE path adds.)
        space._fts_ok = False
        rows = space.search("briefing", agent_id=quoted_agent)
        assert [r["content"] for r in rows if r["kind"] != "_notice"] == [
            "briefing for the quoted session",
        ]
    finally:
        space.close()


# -- saved tool-output search -----------------------------------------------


def _saved_tool_notice(path: Path, *, quoted: bool = False) -> str:
    rendered_path = f'"{path}"' if quoted else str(path)
    return (
        "[tool output truncated]\n"
        "If more content is needed, call `read_file` with "
        f"file_path={rendered_path} start_line=1 to read more."
    )


def test_saved_tool_paths_accept_quoted_and_legacy_paths_with_spaces(
    tmp_path: Path,
):
    artifact_dir = tmp_path / "tool results with spaces"
    artifact_dir.mkdir()
    quoted_file = artifact_dir / "quoted result.txt"
    quoted_file.write_text("quoted\n", encoding="utf-8")
    legacy_file = artifact_dir / "legacy result.txt"
    legacy_file.write_text("legacy\n", encoding="utf-8")
    history = HistoryStore(tmp_path / "history.db")
    history.close()
    space = MemorySpace(
        history_db_path=tmp_path / "history.db",
        session_id="current",
        agent_id="ag1",
    )

    try:
        paths = space._saved_tool_paths(
            _saved_tool_notice(quoted_file, quoted=True)
            + "\n"
            + _saved_tool_notice(legacy_file),
        )
    finally:
        space.close()

    assert paths == [quoted_file.resolve(), legacy_file.resolve()]


def test_saved_tool_search_checks_each_multiblock_artifact(tmp_path: Path):
    decoy_file = tmp_path / "first-block.txt"
    decoy_file.write_text("nothing relevant\n", encoding="utf-8")
    target_file = tmp_path / "second-block.txt"
    target_file.write_text("the deepneedle is here\n", encoding="utf-8")
    history = HistoryStore(tmp_path / "history.db")
    history.append(
        session_id="archive",
        agent_id="ag1",
        dedup_key="multi-block-result",
        entry=LogEntry(
            kind="tool_result",
            role="assistant",
            content=(
                _saved_tool_notice(decoy_file)
                + "\n\n"
                + _saved_tool_notice(target_file)
            ),
            tool_call_id="multi-block-call",
        ),
    )
    history.close()
    space = MemorySpace(
        history_db_path=tmp_path / "history.db",
        session_id="current",
        agent_id="ag1",
    )

    try:
        rows = space.search("deepneedle", k=1)
    finally:
        space.close()

    assert len(rows) == 1
    assert rows[0]["kind"] == "tool_result"
    assert f"file_path={target_file}" in rows[0]["content"]
    assert "deepneedle" in rows[0]["content"]


def test_recall_tool_annotates_each_multiblock_artifact(tmp_path: Path):
    first_file = tmp_path / "first-block.txt"
    first_file.write_text("first block\n", encoding="utf-8")
    second_file = tmp_path / "second-block.txt"
    second_file.write_text("second block\n", encoding="utf-8")
    history = HistoryStore(tmp_path / "history.db")
    history.append(
        session_id="archive",
        agent_id="ag1",
        dedup_key="multi-block-result",
        entry=LogEntry(
            kind="tool_result",
            role="assistant",
            content=(
                _saved_tool_notice(first_file)
                + "\n\n"
                + _saved_tool_notice(second_file)
            ),
            tool_call_id="multi-block-call",
        ),
    )
    history.close()
    space = MemorySpace(
        history_db_path=tmp_path / "history.db",
        session_id="current",
        agent_id="ag1",
    )

    try:
        rows = space.recall_tool("multi-block-call")
    finally:
        space.close()

    artifacts = [
        row["content"] for row in rows if row["kind"] == "_saved_tool_output"
    ]
    assert artifacts == [
        f"Full saved tool output is available at file_path={first_file}.",
        f"Full saved tool output is available at file_path={second_file}.",
    ]


def test_saved_tool_search_pages_past_first_200_candidates(tmp_path: Path):
    target_file = tmp_path / "target.txt"
    target_file.write_text("the deepneedle is here\n", encoding="utf-8")
    decoy_file = tmp_path / "decoy.txt"
    decoy_file.write_text("nothing relevant\n", encoding="utf-8")
    history = HistoryStore(tmp_path / "history.db")
    history.append(
        session_id="archive",
        agent_id="ag1",
        dedup_key="oldest-target",
        entry=LogEntry(
            kind="tool_result",
            role="assistant",
            content=_saved_tool_notice(target_file),
            tool_call_id="target-call",
        ),
    )
    for index in range(200):
        history.append(
            session_id="archive",
            agent_id="ag1",
            dedup_key=f"newer-decoy-{index}",
            entry=LogEntry(
                kind="tool_result",
                role="assistant",
                content=_saved_tool_notice(decoy_file),
                tool_call_id=f"decoy-{index}",
            ),
        )
    history.close()
    space = MemorySpace(
        history_db_path=tmp_path / "history.db",
        session_id="current",
        agent_id="ag1",
    )

    try:
        rows = space.search("deepneedle", k=1)
    finally:
        space.close()

    assert len(rows) == 1
    assert rows[0]["kind"] == "tool_result"
    assert "tool_call_id=target-call" in rows[0]["content"]
    assert "deepneedle" in rows[0]["content"]


def test_saved_tool_file_search_streams_without_read_text(
    tmp_path: Path,
    monkeypatch,
):
    artifact = tmp_path / "large.txt"
    artifact.write_text(
        "before\nneedle match\nafter\n",
        encoding="utf-8",
    )

    def fail_read_text(*args, **kwargs):
        raise AssertionError("saved artifact search must stream")

    monkeypatch.setattr(Path, "read_text", fail_read_text)

    matches = MemorySpace._file_line_matches(artifact, ["needle"])

    assert matches == [
        {
            "line": 2,
            "excerpt": "1: before\n2: needle match\n3: after",
        },
    ]


def test_saved_tool_search_reports_exhausted_scan_budget(tmp_path: Path):
    artifact = tmp_path / "large.txt"
    artifact.write_text("x" * 100 + " needle\n", encoding="utf-8")
    history = HistoryStore(tmp_path / "history.db")
    history.append(
        session_id="archive",
        agent_id="ag1",
        dedup_key="large-result",
        entry=LogEntry(
            kind="tool_result",
            role="assistant",
            content=_saved_tool_notice(artifact),
            tool_call_id="large-call",
        ),
    )
    history.close()
    space = MemorySpace(
        history_db_path=tmp_path / "history.db",
        session_id="current",
        agent_id="ag1",
        saved_tool_scan_max_bytes=32,
    )

    try:
        rows = space.search("needle", k=3)
    finally:
        space.close()

    notices = [row for row in rows if row["kind"] == "_notice"]
    assert len(notices) == 1
    assert "Results are partial" in notices[0]["content"]
