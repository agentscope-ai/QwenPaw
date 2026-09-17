# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,protected-access
"""ms.search() must never crash on raw user/model text.

FTS5 MATCH takes a query grammar, not plain text, so queries like ``C++`` or
``foo-bar`` would raise sqlite3.OperationalError. fts_match_query() rewrites
them into a safe expression (SQLite's missing plainto_tsquery), and search()
backstops anything left over by falling back to the LIKE scan.
"""

import sqlite3

import pytest

from qwenpaw.agents.context.scroll.history import HistoryStore
from qwenpaw.agents.context.scroll.memoryspace import (
    MemorySpace,
    fts_match_query,
)
from qwenpaw.agents.context.types import LogEntry


def test_fts_match_query_quotes_each_word_token():
    assert fts_match_query("foo bar") == '"foo" "bar"'


def test_fts_match_query_strips_operator_punctuation():
    # + - ( ) etc. are FTS5 operators; they must not reach MATCH raw.
    assert fts_match_query("C++") == '"C"'
    assert fts_match_query("foo-bar") == '"foo" "bar"'
    assert fts_match_query("what?") == '"what"'


def test_fts_match_query_neutralises_keywords():
    # AND/OR/NOT now pass through as FTS boolean operators (for wide nets);
    # other FTS keywords (NEAR) stay literals.
    assert fts_match_query("a OR b") == '"a" OR "b"'
    assert fts_match_query("a NEAR b") == '"a" "NEAR" "b"'


def test_fts_match_query_empty_when_all_punctuation():
    assert fts_match_query("++") == ""
    assert fts_match_query("???") == ""


def test_fts_match_query_doubles_embedded_quote():
    assert fts_match_query('say "hi') == '"say" "hi"'


@pytest.fixture
def ms(tmp_path):
    store = HistoryStore(tmp_path / "history.db")
    store.append(
        session_id="s1",
        agent_id="ag1",
        dedup_key="m1",
        entry=LogEntry(
            kind="model_turn",
            role="assistant",
            content="discussing C++ and foo-bar templates",
            headline="cpp talk",
        ),
    )
    store.close()
    space = MemorySpace(
        history_db_path=str(store.path),
        session_id="s1",
        agent_id="ag1",
    )
    yield space
    space.close()


@pytest.mark.parametrize(
    "query",
    ["C++", "foo-bar", "what?", 'say "hi', "a OR b", "(unbalanced", "++"],
)
def test_search_never_raises_on_messy_query(ms, query):
    # Must return a list, not raise — that is the whole bug.
    assert isinstance(ms.search(query), list)


def test_search_finds_rows_for_plain_query(ms):
    rows = ms.search("templates")
    assert any("templates" in r["content"] for r in rows)


def test_search_falls_back_to_like_on_operationalerror(ms, monkeypatch):
    # Make the sanitizer emit an invalid MATCH expression so the REAL FTS5
    # engine raises; the backstop should catch it and the LIKE scan should
    # still return the matching row.
    monkeypatch.setattr(
        "qwenpaw.agents.context.scroll.memoryspace.fts_match_query",
        lambda _raw: '"',  # unterminated FTS5 string -> OperationalError
    )
    with pytest.raises(sqlite3.OperationalError):
        # Guard: confirm the bad expression really does blow up FTS5.
        ms._conn.execute(
            "SELECT 1 FROM hist.conversation_history_fts "
            "WHERE conversation_history_fts MATCH ?",
            ('"',),
        ).fetchall()
    rows = ms.search("templates")
    assert any("templates" in r["content"] for r in rows)
