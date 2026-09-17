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


def test_search_uses_seq_as_stable_bm25_tie_breaker(tmp_path: Path):
    h = HistoryStore(tmp_path / "history.db")
    expected_seqs = []
    for index in range(3):
        expected_seqs.append(
            h.append(
                session_id="archive",
                agent_id="ag1",
                dedup_key=f"equal-{index}",
                entry=LogEntry(
                    kind="model_turn",
                    role="assistant",
                    content="identical ranking text",
                ),
            ),
        )
    h.close()
    space = MemorySpace(
        history_db_path=str(tmp_path / "history.db"),
        session_id="current",
        agent_id="ag1",
    )

    try:
        first = space.search("identical ranking", k=3)
        second = space.search("identical ranking", k=3)
    finally:
        space.close()

    assert [row["seq"] for row in first] == expected_seqs
    assert [row["seq"] for row in second] == expected_seqs


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
        legacy_expected = {
            "tanks question from earlier",
            "tanks were parked at base",
            "tanks moved in another session",
        }
        hits = space.search("tanks", k=10)
        assert {r["content"] for r in hits} == {
            "tanks question from earlier",
            "tanks moved in another session",
        }
        old_turn = next(
            row["turn"] for row in hits if row["session_id"] == "s1"
        )
        assert {row["content"] for row in old_turn} == {
            "tanks question from earlier",
            "tanks were parked at base",
        }
        legacy_hits = space.search(
            "tanks",
            k=10,
            include_turn=False,
        )
        assert {r["content"] for r in legacy_hits} == legacy_expected
        # The LIKE fallback applies the same exclusion.
        like = space._search_like("tanks", [("agent_id", "ag1")], None, 10)
        got = {r["content"] for r in like if r["kind"] != "_notice"}
        assert got == legacy_expected
    finally:
        space.close()


def test_search_returns_and_deduplicates_complete_turn(tmp_path: Path):
    history = HistoryStore(tmp_path / "history.db")
    user_seq = history.append(
        session_id="archive",
        agent_id="ag1",
        dedup_key="u1",
        entry=LogEntry(
            kind="context_msg",
            role="user",
            content="order question for a compass",
        ),
    )
    assistant_seq = history.append(
        session_id="archive",
        agent_id="ag1",
        dedup_key="a1",
        entry=LogEntry(
            kind="model_turn",
            role="assistant",
            content="order answer is north",
        ),
    )
    tool_seq = history.append(
        session_id="archive",
        agent_id="ag1",
        dedup_key="t1",
        entry=LogEntry(
            kind="tool_result",
            role="assistant",
            name="lookup",
            content="order receipt confirmed",
            tool_call_id="call-1",
        ),
    )
    history.append(
        session_id="archive",
        agent_id="ag1",
        dedup_key="u2",
        entry=LogEntry(
            kind="context_msg",
            role="user",
            content="unrelated active request",
        ),
    )
    history.close()
    space = MemorySpace(
        history_db_path=tmp_path / "history.db",
        session_id="archive",
        agent_id="ag1",
    )

    try:
        hits = space.search("order", k=10)
        user_hits = space.search("compass", k=10)
    finally:
        space.close()

    assert len(hits) == 1
    assert hits[0]["matched_seqs"] == [
        user_seq,
        assistant_seq,
        tool_seq,
    ]
    assert hits[0]["turn_start_seq"] == user_seq
    assert hits[0]["turn_end_seq"] == tool_seq
    assert [row["content"] for row in hits[0]["turn"]] == [
        "order question for a compass",
        "order answer is north",
        "order receipt confirmed",
    ]
    assert len(user_hits) == 1
    assert user_hits[0]["match_seq"] == user_seq
    assert user_hits[0]["turn"] == hits[0]["turn"]


def test_search_cjk_substring_returns_complete_turn(tmp_path: Path):
    history = HistoryStore(tmp_path / "history.db")
    user_seq = history.append(
        session_id="archive",
        agent_id="ag1",
        dedup_key="u1",
        entry=LogEntry(
            kind="context_msg",
            role="user",
            content="紫水晶河马在周二跳舞",
        ),
    )
    assistant_seq = history.append(
        session_id="archive",
        agent_id="ag1",
        dedup_key="a1",
        entry=LogEntry(
            kind="model_turn",
            role="assistant",
            content="我记住了这个暗号",
        ),
    )
    tool_seq = history.append(
        session_id="archive",
        agent_id="ag1",
        dedup_key="t1",
        entry=LogEntry(
            kind="tool_result",
            role="assistant",
            name="lookup",
            content="工具结果",
            tool_call_id="call-1",
        ),
    )
    history.close()
    space = MemorySpace(
        history_db_path=tmp_path / "history.db",
        session_id="current",
        agent_id="ag1",
    )

    try:
        hits = space.search("紫水晶河马", session_id="archive", k=10)
        legacy_hits = space.search(
            "紫水晶河马",
            session_id="archive",
            k=10,
            include_turn=False,
        )
    finally:
        space.close()

    assert len(hits) == 1
    assert hits[0]["match_seq"] == user_seq
    assert hits[0]["turn_start_seq"] == user_seq
    assert hits[0]["turn_end_seq"] == tool_seq
    assert hits[0]["turn_complete"] is True
    assert [row["seq"] for row in hits[0]["turn"]] == [
        user_seq,
        assistant_seq,
        tool_seq,
    ]
    assert [row["content"] for row in hits[0]["turn"]] == [
        "紫水晶河马在周二跳舞",
        "我记住了这个暗号",
        "工具结果",
    ]
    assert [row["seq"] for row in legacy_hits] == [user_seq]


def test_search_cjk_multiple_terms_are_and_combined(tmp_path: Path):
    history = HistoryStore(tmp_path / "history.db")
    user_seq = history.append(
        session_id="archive",
        agent_id="ag1",
        dedup_key="u1",
        entry=LogEntry(
            kind="context_msg",
            role="user",
            content="项目的截止日期是周二",
        ),
    )
    assistant_seq = history.append(
        session_id="archive",
        agent_id="ag1",
        dedup_key="a1",
        entry=LogEntry(
            kind="model_turn",
            role="assistant",
            content="好的，我记住了",
        ),
    )
    history.close()
    space = MemorySpace(
        history_db_path=tmp_path / "history.db",
        session_id="current",
        agent_id="ag1",
    )

    try:
        hits = space.search(
            "项目 截止日期",
            session_id="archive",
            k=10,
        )
    finally:
        space.close()

    assert len(hits) == 1
    assert hits[0]["match_seq"] == user_seq
    assert hits[0]["turn_complete"] is True
    assert [row["seq"] for row in hits[0]["turn"]] == [
        user_seq,
        assistant_seq,
    ]


def test_search_cjk_uppercase_or_matches_either_term(tmp_path: Path):
    history = HistoryStore(tmp_path / "history.db")
    project_seq = history.append(
        session_id="archive",
        agent_id="ag1",
        dedup_key="project",
        entry=LogEntry(
            kind="context_msg",
            role="user",
            content="项目状态",
        ),
    )
    deadline_seq = history.append(
        session_id="archive",
        agent_id="ag1",
        dedup_key="deadline",
        entry=LogEntry(
            kind="context_msg",
            role="user",
            content="截止日期",
        ),
    )
    history.close()
    space = MemorySpace(
        history_db_path=tmp_path / "history.db",
        session_id="current",
        agent_id="ag1",
    )

    try:
        hits = space.search(
            "项目 OR 截止日期",
            session_id="archive",
            k=10,
        )
        matching_rows = space.search(
            "项目 OR 截止日期",
            session_id="archive",
            k=10,
            include_turn=False,
        )
    finally:
        space.close()

    assert {hit["match_seq"] for hit in hits} == {
        project_seq,
        deadline_seq,
    }
    assert {row["content"] for row in matching_rows} == {
        "项目状态",
        "截止日期",
    }


def test_search_like_metacharacters_are_literal(tmp_path: Path):
    history = HistoryStore(tmp_path / "history.db")
    for index, content in enumerate(
        (
            "项目_编号",
            "项目X编号",
            "项目%进度",
            "项目任意长度进度",
            "项目\\路径",
        ),
    ):
        history.append(
            session_id="archive",
            agent_id="ag1",
            dedup_key=f"row-{index}",
            entry=LogEntry(
                kind="model_turn",
                role="assistant",
                content=content,
            ),
        )
    history.close()
    space = MemorySpace(
        history_db_path=tmp_path / "history.db",
        session_id="current",
        agent_id="ag1",
    )

    try:
        underscore = space.search(
            "项目_编号",
            session_id="archive",
            include_turn=False,
        )
        percent = space.search(
            "项目%进度",
            session_id="archive",
            include_turn=False,
        )
        backslash = space.search(
            "项目\\路径",
            session_id="archive",
            include_turn=False,
        )
    finally:
        space.close()

    assert [row["content"] for row in underscore] == ["项目_编号"]
    assert [row["content"] for row in percent] == ["项目%进度"]
    assert [row["content"] for row in backslash] == ["项目\\路径"]


def test_search_loads_duplicate_hit_turn_once(
    tmp_path: Path,
    monkeypatch,
):
    history = HistoryStore(tmp_path / "history.db")
    history.append(
        session_id="archive",
        agent_id="ag1",
        dedup_key="user",
        entry=LogEntry(
            kind="context_msg",
            role="user",
            content="find the repeated records",
        ),
    )
    matched = []
    for index in range(100):
        matched.append(
            history.append(
                session_id="archive",
                agent_id="ag1",
                dedup_key=f"match-{index}",
                entry=LogEntry(
                    kind="model_turn",
                    role="assistant",
                    content=f"duplicate-needle result {index}",
                ),
            ),
        )
    history.append(
        session_id="archive",
        agent_id="ag1",
        dedup_key="next-user",
        entry=LogEntry(
            kind="context_msg",
            role="user",
            content="current unrelated request",
        ),
    )
    history.close()
    space = MemorySpace(
        history_db_path=tmp_path / "history.db",
        session_id="archive",
        agent_id="ag1",
    )
    load_calls = 0
    original = space._load_turn

    def counted_load(*args, **kwargs):
        nonlocal load_calls
        load_calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(space, "_load_turn", counted_load)
    try:
        rows = space.search("duplicate-needle", k=100)
    finally:
        space.close()

    turns = [row for row in rows if row["kind"] != "_notice"]
    assert len(turns) == 1
    assert turns[0]["matched_seqs"] == matched
    assert load_calls == 1


def test_search_pages_until_it_finds_k_distinct_turns(tmp_path: Path):
    history = HistoryStore(tmp_path / "history.db")
    history.append(
        session_id="archive",
        agent_id="ag1",
        dedup_key="first-user",
        entry=LogEntry(
            kind="context_msg",
            role="user",
            content="first question",
        ),
    )
    for index in range(80):
        history.append(
            session_id="archive",
            agent_id="ag1",
            dedup_key=f"first-hit-{index}",
            entry=LogEntry(
                kind="model_turn",
                role="assistant",
                content=f"needle {index}",
            ),
        )
    second_start = history.append(
        session_id="archive",
        agent_id="ag1",
        dedup_key="second-user",
        entry=LogEntry(
            kind="context_msg",
            role="user",
            content="second question",
        ),
    )
    history.append(
        session_id="archive",
        agent_id="ag1",
        dedup_key="second-hit",
        entry=LogEntry(
            kind="model_turn",
            role="assistant",
            content="needle " + ("lower ranked filler " * 40),
        ),
    )
    history.close()
    space = MemorySpace(
        history_db_path=tmp_path / "history.db",
        session_id="current",
        agent_id="ag1",
    )
    try:
        rows = space.search("needle", k=2)
    finally:
        space.close()

    turns = [row for row in rows if row["kind"] != "_notice"]
    assert len(turns) == 2
    assert second_start in {row["turn_start_seq"] for row in turns}
    assert not [row for row in rows if row["kind"] == "_notice"]


def test_search_marks_partial_when_raw_hit_cap_hides_turns(tmp_path: Path):
    history = HistoryStore(tmp_path / "history.db")
    history.append(
        session_id="archive",
        agent_id="ag1",
        dedup_key="first-user",
        entry=LogEntry(
            kind="context_msg",
            role="user",
            content="first question",
        ),
    )
    for index in range(20):
        history.append(
            session_id="archive",
            agent_id="ag1",
            dedup_key=f"first-hit-{index}",
            entry=LogEntry(
                kind="model_turn",
                role="assistant",
                content=f"needle {index}",
            ),
        )
    history.append(
        session_id="archive",
        agent_id="ag1",
        dedup_key="second-user",
        entry=LogEntry(
            kind="context_msg",
            role="user",
            content="second question",
        ),
    )
    history.append(
        session_id="archive",
        agent_id="ag1",
        dedup_key="second-hit",
        entry=LogEntry(
            kind="model_turn",
            role="assistant",
            content="needle " + ("lower ranked filler " * 40),
        ),
    )
    history.close()
    space = MemorySpace(
        history_db_path=tmp_path / "history.db",
        session_id="current",
        agent_id="ag1",
        row_cap=10,
    )
    try:
        rows = space.search("needle", k=2)
    finally:
        space.close()

    turns = [row for row in rows if row["kind"] != "_notice"]
    notices = [row for row in rows if row["kind"] == "_notice"]
    assert len(turns) == 1
    assert len(notices) == 1
    assert "maximum 10 matching rows" in notices[0]["content"]


def test_search_turn_expansion_has_total_row_budget(tmp_path: Path):
    history = HistoryStore(tmp_path / "history.db")
    turn_seqs = [
        history.append(
            session_id="archive",
            agent_id="ag1",
            dedup_key="user",
            entry=LogEntry(
                kind="context_msg",
                role="user",
                content="budget question",
            ),
        ),
    ]
    for index in range(10):
        turn_seqs.append(
            history.append(
                session_id="archive",
                agent_id="ag1",
                dedup_key=f"row-{index}",
                entry=LogEntry(
                    kind="model_turn",
                    role="assistant",
                    content=f"budget-needle row {index}",
                ),
            ),
        )
    history.close()
    space = MemorySpace(
        history_db_path=tmp_path / "history.db",
        session_id="current",
        agent_id="ag1",
        search_turn_max_rows=3,
    )
    try:
        rows = space.search("budget-needle", k=10)
    finally:
        space.close()

    result = next(row for row in rows if row["kind"] != "_notice")
    turn = result["turn"]
    assert len([row for row in turn if not row.get("_truncated")]) == 3
    assert turn[-1]["_truncated"] is True
    assert result["turn_end_seq"] == turn_seqs[-1]
    assert result["turn_loaded_end_seq"] == turn_seqs[2]
    assert result["turn_complete"] is False
    notices = [row for row in rows if row["kind"] == "_notice"]
    assert len(notices) == 1
    assert "total turn row budget" in notices[0]["content"]


def test_search_turn_expansion_has_total_byte_budget(tmp_path: Path):
    history = HistoryStore(tmp_path / "history.db")
    user_seq = history.append(
        session_id="archive",
        agent_id="ag1",
        dedup_key="user",
        entry=LogEntry(
            kind="context_msg",
            role="user",
            content="small byte budget question",
        ),
    )
    actual_end = history.append(
        session_id="archive",
        agent_id="ag1",
        dedup_key="large",
        entry=LogEntry(
            kind="model_turn",
            role="assistant",
            content="byte-budget-needle " + ("x" * 2000),
        ),
    )
    history.close()
    space = MemorySpace(
        history_db_path=tmp_path / "history.db",
        session_id="current",
        agent_id="ag1",
        search_turn_max_bytes=600,
    )
    try:
        rows = space.search("byte-budget-needle")
    finally:
        space.close()

    result = next(row for row in rows if row["kind"] != "_notice")
    turn = result["turn"]
    assert len([row for row in turn if not row.get("_truncated")]) == 1
    assert turn[-1]["_truncated"] is True
    assert result["turn_end_seq"] == actual_end
    assert result["turn_loaded_end_seq"] == user_seq
    assert result["turn_complete"] is False
    notices = [row for row in rows if row["kind"] == "_notice"]
    assert len(notices) == 1
    assert "total turn byte budget" in notices[0]["content"]


def test_search_execution_timeout_is_enforced(history_db: Path):
    space = MemorySpace(
        history_db_path=history_db,
        session_id="s1",
        agent_id="ag1",
        search_max_seconds=0,
    )
    try:
        with pytest.raises(TimeoutError, match="execution timeout"):
            space.search("tanks")
    finally:
        space.close()


def test_search_groups_imported_kind_by_user_role(tmp_path: Path):
    history = HistoryStore(tmp_path / "history.db")
    user_seq = history.append(
        session_id="beam-batch",
        agent_id="ag1",
        dedup_key="beam-u1",
        entry=LogEntry(
            kind="beam_chat_turn",  # type: ignore[arg-type]
            role="user",
            content="How many Jira tasks did I log?",
            created_at="2024-11-05T00:00:00+00:00",
        ),
    )
    assistant_seq = history.append(
        session_id="beam-batch",
        agent_id="ag1",
        dedup_key="beam-a1",
        entry=LogEntry(
            kind="beam_chat_turn",  # type: ignore[arg-type]
            role="assistant",
            content="You logged 18 Jira tasks.",
            created_at="2024-11-05T00:00:00+00:00",
        ),
    )
    history.append(
        session_id="beam-batch",
        agent_id="ag1",
        dedup_key="beam-u2",
        entry=LogEntry(
            kind="beam_chat_turn",  # type: ignore[arg-type]
            role="user",
            content="A separate benchmark question",
            created_at="2024-11-06T00:00:00+00:00",
        ),
    )
    history.close()
    space = MemorySpace(
        history_db_path=tmp_path / "history.db",
        session_id="probe",
        agent_id="ag1",
    )

    try:
        assistant_hit = space.search(
            "18 Jira",
            kind="beam_chat_turn",
        )
        user_hit = space.search(
            "How many",
            kind="beam_chat_turn",
        )
    finally:
        space.close()

    assert len(assistant_hit) == 1
    assert assistant_hit[0]["turn_start_seq"] == user_seq
    assert assistant_hit[0]["turn_end_seq"] == assistant_seq
    assert [row["content"] for row in assistant_hit[0]["turn"]] == [
        "How many Jira tasks did I log?",
        "You logged 18 Jira tasks.",
    ]
    assert user_hit[0]["turn"] == assistant_hit[0]["turn"]


def test_search_turn_does_not_cross_session_or_agent(tmp_path: Path):
    history = HistoryStore(tmp_path / "history.db")
    for session_id, agent_id, suffix in (
        ("s1", "ag1", "one"),
        ("s2", "ag1", "two"),
        ("s1", "ag2", "three"),
    ):
        history.append(
            session_id=session_id,
            agent_id=agent_id,
            dedup_key=f"u-{suffix}",
            entry=LogEntry(
                kind="context_msg",
                role="user",
                content=f"needle request {suffix}",
            ),
        )
        history.append(
            session_id=session_id,
            agent_id=agent_id,
            dedup_key=f"a-{suffix}",
            entry=LogEntry(
                kind="model_turn",
                role="assistant",
                content=f"answer {suffix}",
            ),
        )
    history.close()
    space = MemorySpace(
        history_db_path=tmp_path / "history.db",
        session_id="current",
        agent_id="ag1",
    )

    try:
        hits = space.search("needle", all_agents=True, k=10)
    finally:
        space.close()

    assert len(hits) == 3
    for hit in hits:
        assert {
            (row["session_id"], row["agent_id"]) for row in hit["turn"]
        } == {
            (hit["session_id"], hit["agent_id"]),
        }


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


def test_search_filters_by_created_at_calendar_dates(tmp_path: Path):
    history = HistoryStore(tmp_path / "history.db")
    rows = [
        (
            "u1",
            "context_msg",
            "user",
            "Jira sprint alpha",
            "2024-11-05T08:00:00+08:00",
        ),
        (
            "a1",
            "model_turn",
            "assistant",
            "logged 18 tasks",
            "2024-11-05T08:01:00+08:00",
        ),
        (
            "u2",
            "context_msg",
            "user",
            "Jira sprint beta",
            "2024-11-06T23:00:00-08:00",
        ),
        (
            "a2",
            "model_turn",
            "assistant",
            "logged 21 tasks",
            "2024-11-06T23:01:00-08:00",
        ),
        (
            "u3",
            "context_msg",
            "user",
            "unrelated current boundary",
            "2024-11-07T00:00:00Z",
        ),
    ]
    for key, kind, role, content, created_at in rows:
        history.append(
            session_id="archive",
            agent_id="ag1",
            dedup_key=key,
            entry=LogEntry(
                kind=kind,
                role=role,
                content=content,
                created_at=created_at,
            ),
        )
    history.close()
    space = MemorySpace(
        history_db_path=tmp_path / "history.db",
        session_id="current",
        agent_id="ag1",
    )

    try:
        exact = space.search("tasks", created_on="2024-11-05")
        date_only = space.search("", created_on="2024-11-06")
        date_range = space.search(
            "Jira",
            created_from="2024-11-05",
            created_to="2024-11-06",
        )
        space._fts_ok = False
        like = space.search("tasks", created_on="2024-11-05")
    finally:
        space.close()

    assert len(exact) == 1
    assert exact[0]["content"] == "logged 18 tasks"
    assert exact[0]["created_at"].startswith("2024-11-05")
    assert {row["content"] for row in exact[0]["turn"]} == {
        "Jira sprint alpha",
        "logged 18 tasks",
    }
    assert len(date_only) == 1
    assert date_only[0]["turn_start_seq"] == 3
    assert len(date_range) == 2
    assert {row["content"] for row in like if row["seq"] >= 0} == {
        "logged 18 tasks",
    }


def test_date_only_search_keeps_null_content_rows(tmp_path: Path):
    history = HistoryStore(tmp_path / "history.db")
    target_seq = history.append(
        session_id="archive",
        agent_id="ag1",
        dedup_key="structured",
        entry=LogEntry(
            kind="context_msg",
            role="user",
            content=None,
            blocks=[{"type": "text", "text": "structured history"}],
            created_at="2024-11-05T08:00:00Z",
        ),
    )
    history.append(
        session_id="archive",
        agent_id="ag1",
        dedup_key="next-day",
        entry=LogEntry(
            kind="context_msg",
            role="user",
            content="next boundary",
            created_at="2024-11-06T08:00:00Z",
        ),
    )
    history.close()
    space = MemorySpace(
        history_db_path=tmp_path / "history.db",
        session_id="current",
        agent_id="ag1",
    )
    space._fts_ok = False
    try:
        matching_rows = space.search(
            "",
            created_on="2024-11-05",
            include_turn=False,
        )
        turns = space.search("", created_on="2024-11-05")
    finally:
        space.close()

    assert [row["seq"] for row in matching_rows] == [target_seq]
    assert matching_rows[0]["content"] is None
    assert len(turns) == 1
    assert turns[0]["turn_start_seq"] == target_seq
    assert turns[0]["turn"][0]["content"] is None
    assert "structured history" in turns[0]["turn"][0]["blocks"]
    assert all(row["kind"] != "_notice" for row in turns)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"created_on": "2024-02-30"},
        {
            "created_on": "2024-11-05",
            "created_from": "2024-11-01",
        },
        {
            "created_from": "2024-11-06",
            "created_to": "2024-11-05",
        },
    ],
)
def test_search_rejects_invalid_created_at_filters(
    ms: MemorySpace,
    kwargs: dict,
):
    with pytest.raises(ValueError):
        ms.search("tanks", **kwargs)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"created_on": "9999-12-31"},
        {"created_from": "9999-12-31", "created_to": "9999-12-31"},
    ],
)
def test_search_accepts_date_max_without_overflow(
    tmp_path: Path,
    kwargs: dict,
):
    history = HistoryStore(tmp_path / "history.db")
    target_seq = history.append(
        session_id="archive",
        agent_id="ag1",
        dedup_key="max-date",
        entry=LogEntry(
            kind="model_turn",
            role="assistant",
            content="last representable day",
            created_at="9999-12-31T23:59:59.999999+14:00",
        ),
    )
    history.append(
        session_id="archive",
        agent_id="ag1",
        dedup_key="previous-date",
        entry=LogEntry(
            kind="model_turn",
            role="assistant",
            content="previous representable day",
            created_at="9999-12-30T23:59:59Z",
        ),
    )
    history.close()
    space = MemorySpace(
        history_db_path=tmp_path / "history.db",
        session_id="current",
        agent_id="ag1",
    )
    try:
        rows = space.search(
            "representable",
            include_turn=False,
            **kwargs,
        )
    finally:
        space.close()

    assert [row["seq"] for row in rows] == [target_seq]


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


def test_like_fallback_preserves_uppercase_or(ms: MemorySpace):
    """The public OR contract also holds when FTS5 is unavailable."""
    ms._fts_ok = False

    assert _hits(ms.search("rolled OR regrouped")) == {
        "tanks rolled in",
        "tanks regrouped later",
    }


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


# -- strict date arithmetic -------------------------------------------------


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        ("2024-11-01", "2024-12-16", 45),
        ("2024-12-16", "2024-11-01", -45),
        ("2024-02-28", "2024-03-01", 2),
        ("2023-02-28", "2023-03-01", 1),
        (
            "2024-11-01T23:59:59.123456+08:00",
            "2024-12-16T00:00:00Z",
            45,
        ),
        (
            "2024-11-01T00:00-07:00",
            "2024-10-31T23:59+14:00",
            -1,
        ),
    ],
)
def test_days_between_is_signed_and_accepts_iso_timestamps(
    ms: MemorySpace,
    start: str,
    end: str,
    expected: int,
):
    assert ms.days_between(start, end) == expected


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        ("2024-11-01", "2024-11-01", 1),
        ("2024-11-01", "2024-11-02", 2),
        ("2024-11-02", "2024-11-01", -2),
    ],
)
def test_days_between_inclusive_preserves_direction(
    ms: MemorySpace,
    start: str,
    end: str,
    expected: int,
):
    assert ms.days_between(start, end, inclusive=True) == expected


@pytest.mark.parametrize(
    "value",
    [
        "2023-02-29",
        "2024-02-30",
        "2024/11/01",
        "prefix 2024-11-01",
        "2024-11-01 12:30:00Z",
        "2024-11-01T12:30:00+24:00",
        "2024-11-01T12:30:00 PST",
        " 2024-11-01",
    ],
)
def test_days_between_rejects_invalid_or_non_strict_dates(
    ms: MemorySpace,
    value: str,
):
    with pytest.raises(ValueError, match="invalid ISO date or timestamp"):
        ms.days_between(value, "2024-12-16")


def test_days_between_rejects_unsupported_types(ms: MemorySpace):
    with pytest.raises(TypeError, match="must be an ISO string"):
        ms.days_between(20241101, "2024-12-16")


# -- intent-named recall helpers --------------------------------------------


def test_expand_returns_full_turns_in_span(ms: MemorySpace):
    rows = ms.expand(1, 99)
    assert [r["content"] for r in rows] == ["tanks rolled in"]


def test_expand_includes_legacy_unowned_rows(history_db: Path):
    history = HistoryStore(history_db)
    legacy_seq = history.append(
        session_id="legacy",
        agent_id=None,
        dedup_key="legacy-null-agent",
        entry=LogEntry(
            kind="model_turn",
            role="assistant",
            content="legacy unowned turn",
        ),
    )
    history.close()
    space = MemorySpace(
        history_db_path=str(history_db),
        session_id="legacy",
        agent_id="ag1",
    )
    try:
        rows = space.expand(legacy_seq, legacy_seq)
    finally:
        space.close()

    assert [row["content"] for row in rows] == ["legacy unowned turn"]


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


def test_saved_tool_paths_prefer_structured_artifact_metadata(tmp_path: Path):
    artifact = tmp_path / "metadata-only-result.txt"
    artifact.write_text("structured artifact\n", encoding="utf-8")
    history = HistoryStore(tmp_path / "history.db")
    history.close()
    space = MemorySpace(
        history_db_path=tmp_path / "history.db",
        session_id="current",
        agent_id="ag1",
    )

    try:
        paths = space._saved_tool_paths(
            "preview without a legacy path notice",
            {
                "qwenpaw_truncation": {
                    "0": {
                        "file_path": str(artifact),
                    },
                },
            },
        )
    finally:
        space.close()

    assert paths == [artifact.resolve()]


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


def test_saved_tool_search_preserves_uppercase_or(tmp_path: Path):
    artifact = tmp_path / "saved-tool-output.txt"
    artifact.write_text("项目状态\n", encoding="utf-8")
    history = HistoryStore(tmp_path / "history.db")
    history.append(
        session_id="archive",
        agent_id="ag1",
        dedup_key="saved-result",
        entry=LogEntry(
            kind="tool_result",
            role="assistant",
            content=_saved_tool_notice(artifact),
            tool_call_id="saved-call",
        ),
    )
    history.close()
    space = MemorySpace(
        history_db_path=tmp_path / "history.db",
        session_id="current",
        agent_id="ag1",
    )

    try:
        rows = space.search("项目 OR 截止日期", k=10)
    finally:
        space.close()

    assert len(rows) == 1
    assert rows[0]["kind"] == "tool_result"
    assert f"file_path={artifact}" in rows[0]["content"]
    assert "项目状态" in rows[0]["content"]


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
        "Full saved tool output is available at "
        f"file_path={str(first_file)!r} start_line=1.",
        "Full saved tool output is available at "
        f"file_path={str(second_file)!r} start_line=1.",
    ]


def test_recall_tool_returns_preview_when_artifact_expired(tmp_path: Path):
    artifact = tmp_path / "expired-result.txt"
    artifact.write_text("complete output\n", encoding="utf-8")
    history = HistoryStore(tmp_path / "history.db")
    history.append(
        session_id="archive",
        agent_id="ag1",
        dedup_key="expired-result",
        entry=LogEntry(
            kind="tool_result",
            role="assistant",
            content="bounded preview",
            tool_call_id="expired-call",
            metadata={
                "qwenpaw_truncation": {
                    "0": {
                        "file_path": str(artifact),
                        "start_line": 1,
                    },
                },
            },
        ),
    )
    history.close()
    artifact.unlink()
    space = MemorySpace(
        history_db_path=tmp_path / "history.db",
        session_id="current",
        agent_id="ag1",
    )

    try:
        rows = space.recall_tool("expired-call")
    finally:
        space.close()

    assert rows[0]["kind"] == "_saved_tool_output_unavailable"
    assert "ARTIFACT_UNAVAILABLE" in rows[0]["content"]
    assert rows[1]["kind"] == "tool_result"
    assert rows[1]["content"] == "bounded preview"


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

    matches = MemorySpace._file_line_matches(artifact, [["needle"]])

    assert matches == [
        {
            "line": 2,
            "excerpt": "1: before\n2: needle match\n3: after",
        },
    ]


def test_saved_tool_file_search_keeps_and_terms_on_same_line(
    tmp_path: Path,
):
    artifact = tmp_path / "and-terms.txt"
    artifact.write_text(
        "foo\nbar\nfoo bar\n",
        encoding="utf-8",
    )
    needle_groups = MemorySpace._query_needle_groups("foo bar")

    matches = MemorySpace._file_line_matches(
        artifact,
        needle_groups,
        context=0,
    )

    assert matches == [{"line": 3, "excerpt": "3: foo bar"}]


def test_attach_saved_tool_preserves_preview_when_scan_budget_exhausts(
    tmp_path: Path,
):
    artifact = tmp_path / "large.txt"
    artifact.write_text("x" * 100 + " needle\n", encoding="utf-8")
    history = HistoryStore(tmp_path / "history.db")
    history.close()
    space = MemorySpace(
        history_db_path=tmp_path / "history.db",
        session_id="current",
        agent_id="ag1",
        saved_tool_scan_max_bytes=32,
    )

    try:
        rows = space._attach_saved_tool_file_matches(
            [
                {
                    "seq": 1,
                    "kind": "tool_result",
                    "role": "assistant",
                    "name": "read_file",
                    "content": (
                        "bounded preview retained in history\n"
                        + _saved_tool_notice(artifact)
                    ),
                },
            ],
            "needle",
        )
    finally:
        space.close()

    notices = [row for row in rows if row["kind"] == "_notice"]
    assert len(notices) == 1
    assert "Results are partial" in notices[0]["content"]
    previews = [row for row in rows if row["kind"] == "tool_result"]
    assert len(previews) == 1
    assert "bounded preview retained in history" in previews[0]["content"]
