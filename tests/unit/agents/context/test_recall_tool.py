# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,protected-access
"""Unit tests for the structured ``recall_history`` tool.

The point of this tool is that the common recall ops (expand / search /
recall_tool) run in-process with bound parameters — no sandbox, no approval —
so fold stubs and the eviction index stay readable on platforms where the
sandboxed REPL can't run. These tests pin the op semantics, the
failure-vs-empty observation shapes (same discipline as the REPL's), and the
no-sandbox registration contract.
"""

import asyncio
import threading
from pathlib import Path

import pytest
from agentscope.message import ToolResultState

from qwenpaw.agents.context.scroll.history import HistoryStore
from qwenpaw.agents.context.scroll.memoryspace import MemorySpace
from qwenpaw.agents.context.scroll.recall_tool import (
    RECALL_PAGE_METADATA_KEY,
    RecallLoopGuard,
    make_recall_history,
)
from qwenpaw.agents.context.types import LogEntry


@pytest.fixture
def history_db(tmp_path: Path) -> Path:
    """A durable store with a past turn, a tool result, and an active turn."""
    h = HistoryStore(tmp_path / "history.db")
    h.append(
        session_id="s1",
        agent_id="ag1",
        dedup_key="u1",
        entry=LogEntry(kind="context_msg", role="user", content="hello there"),
    )
    h.append(
        session_id="s1",
        agent_id="ag1",
        dedup_key="m1",
        entry=LogEntry(
            kind="model_turn",
            role="assistant",
            content="the flight is AA231",
            headline="flight AA231",
        ),
    )
    h.append(
        session_id="s1",
        agent_id="ag1",
        dedup_key="t1",
        entry=LogEntry(
            kind="tool_result",
            role="assistant",
            name="grep",
            tool_call_id="call_abc",
            content="RESULT-FULL",
        ),
    )
    # The active turn: a later user request (search must never surface it).
    h.append(
        session_id="s1",
        agent_id="ag1",
        dedup_key="u2",
        entry=LogEntry(
            kind="context_msg",
            role="user",
            content="what was the flight again",
        ),
    )
    h.close()
    return tmp_path / "history.db"


@pytest.fixture
def tool(history_db: Path):
    return make_recall_history(
        history_db_path=str(history_db),
        session_id="s1",
        agent_id="ag1",
    )


def _text(chunk) -> str:
    return chunk.content[0].text


async def test_expand_returns_full_turns(tool):
    chunk = await tool(op="expand", lo=1, hi=3)
    assert chunk.state == ToolResultState.SUCCESS
    text = _text(chunk)
    assert "hello there" in text
    assert "the flight is AA231" in text
    assert "RESULT-FULL" in text
    assert "seq=1" in text


async def test_search_finds_evicted_turn_not_active_turn(tool):
    chunk = await tool(op="search", query="flight", k=10)
    assert chunk.state == ToolResultState.SUCCESS
    text = _text(chunk)
    assert "the flight is AA231" in text
    # The active turn (latest user request) is excluded from hits.
    assert "what was the flight again" not in text


async def test_recall_tool_by_call_id(tool):
    chunk = await tool(op="recall_tool", tool_call_id="call_abc")
    assert chunk.state == ToolResultState.SUCCESS
    assert "RESULT-FULL" in _text(chunk)


async def test_folded_recall_target_is_blocked_until_turn_changes(
    history_db: Path,
):
    guard = RecallLoopGuard()
    guard.begin_turn("user-1")
    guard.block("expand", {"op": "expand", "lo": 1, "hi": 3})
    guarded_tool = make_recall_history(
        history_db_path=str(history_db),
        session_id="s1",
        agent_id="ag1",
        loop_guard=guard,
    )

    blocked = await guarded_tool(op="expand", lo=1, hi=3)
    assert "RECALL LOOP BLOCKED" in _text(blocked)

    narrower = await guarded_tool(op="expand", lo=1, hi=2)
    assert "RECALL LOOP BLOCKED" not in _text(narrower)
    assert "hello there" in _text(narrower)

    guard.begin_turn("user-2")
    allowed_again = await guarded_tool(op="expand", lo=1, hi=3)
    assert "RECALL LOOP BLOCKED" not in _text(allowed_again)


def test_recall_guard_ignores_parameters_unused_by_operation():
    guard = RecallLoopGuard()
    guard.begin_turn("user-1")

    guard.block("expand", {"lo": 1, "hi": 3})
    assert guard.is_blocked(
        "expand",
        {"lo": 1, "hi": 3, "k": 99, "query": "ignored"},
    )

    guard.block("search", {"query": "flight", "k": 10})
    assert guard.is_blocked(
        "search",
        {"query": "flight", "k": 10, "lo": 1, "hi": 999},
    )

    guard.block("recall_tool", {"tool_call_id": "call-1"})
    assert guard.is_blocked(
        "recall_tool",
        {"tool_call_id": "call-1", "k": 77, "all_agents": True},
    )
    assert not guard.is_blocked(
        "recall_tool",
        {"tool_call_id": "call-1", "cursor": "0:100"},
    )


async def test_large_recall_is_cursor_paginated_without_derived_artifact(
    tmp_path: Path,
):
    history = HistoryStore(tmp_path / "large-history.db")
    history.append(
        session_id="old",
        agent_id="ag1",
        dedup_key="large",
        entry=LogEntry(
            kind="model_turn",
            role="assistant",
            content="line of history\n" * 5000,
        ),
    )
    history.close()
    guard = RecallLoopGuard()
    guard.begin_turn("user-1")
    bounded_tool = make_recall_history(
        history_db_path=str(tmp_path / "large-history.db"),
        session_id="current",
        agent_id="ag1",
        loop_guard=guard,
        tool_result_max_bytes=1024,
        tool_results_dir=str(tmp_path / "tool-results"),
    )

    chunk = await bounded_tool(op="expand", lo=1, hi=1)
    assert len(_text(chunk).encode("utf-8")) <= 1024
    assert "[recall page incomplete]" in _text(chunk)
    page = chunk.metadata[RECALL_PAGE_METADATA_KEY]
    assert page["next_cursor"]
    assert not (tmp_path / "tool-results").exists()

    repeated = await bounded_tool(op="expand", lo=1, hi=1)
    assert "RECALL LOOP BLOCKED" in _text(repeated)

    pages = 1
    while page["next_cursor"]:
        chunk = await bounded_tool(
            op="expand",
            lo=1,
            hi=1,
            cursor=page["next_cursor"],
        )
        pages += 1
        assert "RECALL LOOP BLOCKED" not in _text(chunk)
        assert len(_text(chunk).encode("utf-8")) <= 1024
        page = chunk.metadata[RECALL_PAGE_METADATA_KEY]
        assert pages < 200

    assert pages > 1
    assert page["complete"] is True
    assert "[recall page complete]" in _text(chunk)


async def test_large_historical_tool_result_exposes_artifact_on_first_page(
    tmp_path: Path,
):
    artifact = tmp_path / "original-tool-output.txt"
    artifact.write_text(
        "original result with final sentinel",
        encoding="utf-8",
    )
    history = HistoryStore(tmp_path / "artifact-history.db")
    history.append(
        session_id="old",
        agent_id="ag1",
        dedup_key="large-tool",
        entry=LogEntry(
            kind="tool_result",
            role="assistant",
            name="shell",
            tool_call_id="call-large",
            content="preview line\n" * 5000,
            metadata={
                "qwenpaw_truncation": {
                    "0": {
                        "artifact_id": artifact.name,
                        "artifact_sha256": "abc123",
                        "file_path": str(artifact),
                        "start_line": 37,
                    },
                },
            },
        ),
    )
    history.close()
    bounded_tool = make_recall_history(
        history_db_path=str(tmp_path / "artifact-history.db"),
        session_id="current",
        agent_id="ag1",
        tool_result_max_bytes=1024,
        tool_results_dir=str(tmp_path / "derived-results"),
    )

    chunk = await bounded_tool(
        op="recall_tool",
        tool_call_id="call-large",
    )

    assert str(artifact) in _text(chunk)
    assert artifact.name in _text(chunk)
    assert "start_line=37" in _text(chunk)
    assert not (tmp_path / "derived-results").exists()


async def test_cursor_is_bound_to_original_search_arguments(tmp_path: Path):
    db_path = tmp_path / "fingerprint-history.db"
    history = HistoryStore(db_path)
    history.append(
        session_id="old",
        agent_id="ag1",
        dedup_key="large-search-row",
        entry=LogEntry(
            kind="model_turn",
            role="assistant",
            content="alpha beta evidence\n" * 500,
        ),
    )
    history.close()
    bounded_tool = make_recall_history(
        history_db_path=str(db_path),
        session_id="current",
        agent_id="ag1",
        tool_result_max_bytes=1024,
    )

    first = await bounded_tool(op="search", query="alpha", k=10)
    cursor = first.metadata[RECALL_PAGE_METADATA_KEY]["next_cursor"]
    assert cursor.startswith("v1.")

    continuation = await bounded_tool(
        op="search",
        query="alpha",
        k=10,
        cursor=cursor,
    )
    assert continuation.state == ToolResultState.SUCCESS

    changed_query = await bounded_tool(
        op="search",
        query="beta",
        k=10,
        cursor=cursor,
    )
    assert changed_query.state == ToolResultState.ERROR
    assert "different recall request" in _text(changed_query)

    changed_k = await bounded_tool(
        op="search",
        query="alpha",
        k=20,
        cursor=cursor,
    )
    assert changed_k.state == ToolResultState.ERROR
    assert "different recall request" in _text(changed_k)


async def test_cursor_detects_result_snapshot_drift(tmp_path: Path):
    db_path = tmp_path / "snapshot-history.db"
    history = HistoryStore(db_path)
    history.append(
        session_id="old",
        agent_id="ag1",
        dedup_key="first-result",
        entry=LogEntry(
            kind="model_turn",
            role="assistant",
            content="snapshotneedle\n" * 500,
        ),
    )
    history.close()
    bounded_tool = make_recall_history(
        history_db_path=str(db_path),
        session_id="current",
        agent_id="ag1",
        tool_result_max_bytes=1024,
    )

    first = await bounded_tool(op="search", query="snapshotneedle", k=10)
    cursor = first.metadata[RECALL_PAGE_METADATA_KEY]["next_cursor"]

    history = HistoryStore(db_path)
    history.append(
        session_id="old",
        agent_id="ag1",
        dedup_key="new-result",
        entry=LogEntry(
            kind="model_turn",
            role="assistant",
            content="new snapshotneedle result",
        ),
    )
    history.close()

    drifted = await bounded_tool(
        op="search",
        query="snapshotneedle",
        k=10,
        cursor=cursor,
    )
    assert drifted.state == ToolResultState.ERROR
    assert "results changed since the previous page" in _text(drifted)


async def test_duplicate_concurrent_recall_executes_query_once(
    history_db: Path,
    monkeypatch,
):
    guard = RecallLoopGuard()
    guard.begin_turn("user-1")
    guarded_tool = make_recall_history(
        history_db_path=str(history_db),
        session_id="s1",
        agent_id="ag1",
        loop_guard=guard,
    )
    started = threading.Event()
    release = threading.Event()
    query_calls = 0
    original_expand = MemorySpace.expand

    def slow_expand(self, lo, hi):
        nonlocal query_calls
        query_calls += 1
        started.set()
        assert release.wait(timeout=2)
        return original_expand(self, lo, hi)

    monkeypatch.setattr(MemorySpace, "expand", slow_expand)

    first_task = asyncio.create_task(
        guarded_tool(op="expand", lo=1, hi=3),
    )
    assert await asyncio.to_thread(started.wait, 1)
    try:
        duplicate = await guarded_tool(op="expand", lo=1, hi=3)
        assert "RECALL LOOP BLOCKED" in _text(duplicate)
        assert "already running" in _text(duplicate)
        assert query_calls == 1
    finally:
        release.set()
    first = await first_task
    assert "RECALL LOOP BLOCKED" not in _text(first)

    # A completed target is terminal for this turn, even when its result was
    # small. A narrower target remains available.
    repeated = await guarded_tool(op="expand", lo=1, hi=3)
    assert "RECALL LOOP BLOCKED" in _text(repeated)
    assert query_calls == 1

    narrower = await guarded_tool(op="expand", lo=1, hi=2)
    assert "RECALL LOOP BLOCKED" not in _text(narrower)
    assert query_calls == 2


def test_old_turn_completion_cannot_poison_new_turn_claim():
    guard = RecallLoopGuard()
    payload = {"lo": 1, "hi": 30}
    guard.begin_turn("user-1")
    old_generation, notice = guard.claim("expand", payload)
    assert old_generation is not None
    assert notice is None

    guard.begin_turn("user-2")
    new_generation, notice = guard.claim("expand", payload)
    assert new_generation is not None
    assert notice is None

    guard.finish(
        "expand",
        payload,
        old_generation,
        block=True,
    )
    assert not guard.is_blocked("expand", payload)

    # The new claim is still present; a concurrent duplicate remains blocked.
    duplicate_generation, duplicate_notice = guard.claim("expand", payload)
    assert duplicate_generation is None
    assert "already running" in (duplicate_notice or "")
    guard.finish(
        "expand",
        payload,
        new_generation,
        block=False,
    )


async def test_recall_queries_run_outside_event_loop(tool, monkeypatch):
    event_loop_thread = threading.get_ident()
    query_threads: list[int] = []
    original_expand = MemorySpace.expand

    def tracked_expand(self, lo, hi):
        query_threads.append(threading.get_ident())
        return original_expand(self, lo, hi)

    monkeypatch.setattr(MemorySpace, "expand", tracked_expand)

    chunk = await tool(op="expand", lo=1, hi=3)

    assert chunk.state == ToolResultState.SUCCESS
    assert query_threads
    assert all(thread_id != event_loop_thread for thread_id in query_threads)


async def test_empty_span_reads_as_genuine_absence(tool):
    chunk = await tool(op="expand", lo=900, hi=905)
    # Empty is a successful read, worded as evidence of absence — the
    # opposite shape from a failure.
    assert chunk.state == ToolResultState.SUCCESS
    text = _text(chunk)
    assert text.startswith("0 rows")
    assert "genuinely holds nothing" in text
    assert "RECALL FAILED" not in text


async def test_unknown_op_fails_loudly(tool):
    chunk = await tool(op="everything")
    assert chunk.state == ToolResultState.ERROR
    assert _text(chunk).startswith("RECALL FAILED")


async def test_missing_params_fail_loudly(tool):
    for kwargs in (
        {"op": "expand"},  # no lo/hi
        {"op": "search"},  # no query
        {"op": "recall_tool"},  # no tool_call_id
    ):
        chunk = await tool(**kwargs)
        assert chunk.state == ToolResultState.ERROR
        assert _text(chunk).startswith("RECALL FAILED")


async def test_invalid_cursor_fails_instead_of_skipping_history(tool):
    chunk = await tool(op="expand", lo=1, hi=3, cursor="999:0")
    assert chunk.state == ToolResultState.ERROR
    assert "exact value returned by recall_history" in _text(chunk)


async def test_broken_db_is_a_failure_not_an_empty_history(tmp_path: Path):
    """An unreadable store must produce RECALL FAILED, never '0 rows'."""
    bad = tmp_path / "not-a-db"
    bad.write_text("garbage", encoding="utf-8")
    tool = make_recall_history(
        history_db_path=str(bad),
        session_id="s1",
        agent_id="ag1",
    )
    chunk = await tool(op="expand", lo=1, hi=1)
    assert chunk.state == ToolResultState.ERROR
    assert "RECALL FAILED" in _text(chunk)


def test_descriptor_needs_no_sandbox(tool):
    """The registration contract this tool exists for: in-process, async,
    and — unlike the REPL — no sandbox requirement, so governance never
    routes it through SANDBOX_FALLBACK / approval."""
    desc = tool._tool_descriptor
    assert desc.name == "recall_history"
    assert desc.requires_sandbox == ()
    assert desc.async_execution is True


def test_governance_registers_internal_type():
    """RecallHistory is an internal governance type: policy Phase 0 allows it
    outright — no deep scan, no sandbox fallback, no approval prompt."""
    from qwenpaw.governance.tool_registry import DEFAULT_REGISTRY

    assert DEFAULT_REGISTRY.get_type("RecallHistory") == "internal"
    assert (
        DEFAULT_REGISTRY.python_to_policy_name("recall_history")
        == "RecallHistory"
    )
