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


def test_search_scope_agent_is_default_and_cross_session(ms: MemorySpace):
    contents = {r["content"] for r in ms.search("tanks")}
    # Both of ag1's turns (s1 + s2), none of ag2's.
    assert "tanks rolled in" in contents
    assert "tanks regrouped later" in contents
    assert "tanks of another agent" not in contents


def test_search_scope_session_limits_to_this_conversation(ms: MemorySpace):
    contents = {r["content"] for r in ms.search("tanks", scope="session")}
    assert contents == {"tanks rolled in"}


def test_search_scope_all_spans_every_agent(ms: MemorySpace):
    contents = {r["content"] for r in ms.search("tanks", scope="all")}
    assert "tanks of another agent" in contents
    assert len(contents) == 3


def test_unknown_scope_fails_safe_to_agent(ms: MemorySpace):
    """A typo'd scope must NOT leak other agents — it falls back to agent."""
    contents = {r["content"] for r in ms.search("tanks", scope="bogus")}
    assert "tanks of another agent" not in contents


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


def test_like_fallback_respects_scope(ms: MemorySpace):
    """Force the no-FTS path and confirm scoping still holds."""
    ms._fts_ok = False
    contents = {
        r["content"] for r in ms._search_like("tanks", "agent", None, 10)
    }
    assert "tanks of another agent" not in contents
    assert "tanks rolled in" in contents


# -- intent-named recall helpers --------------------------------------------


def test_expand_returns_full_turns_in_span(ms: MemorySpace):
    rows = ms.expand(1, 99)
    # Globally-unique seq spans every session/agent, so expand is unscoped.
    assert {r["content"] for r in rows} == {
        "tanks rolled in",
        "tanks regrouped later",
        "tanks of another agent",
    }


def test_outline_returns_only_headlined_rows(ms: MemorySpace):
    rows = ms.outline(1, 99)
    assert [r["headline"] for r in rows] == ["battle"]


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


def test_sanitize_suffix():
    assert sanitize_suffix(None) == "scratch"
    assert sanitize_suffix("a-b.c/d") == "a_b_c_d"
    assert sanitize_suffix("ok_123") == "ok_123"
