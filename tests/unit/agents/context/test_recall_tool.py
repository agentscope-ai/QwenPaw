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
    _render_page,
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


async def test_duplicate_recall_is_blocked_only_within_current_turn(
    history_db: Path,
):
    guard = RecallLoopGuard()
    guard.begin_turn("user-1")
    guarded_tool = make_recall_history(
        history_db_path=str(history_db),
        session_id="s1",
        agent_id="ag1",
        loop_guard=guard,
    )

    first = await guarded_tool(op="expand", lo=1, hi=3)
    duplicate = await guarded_tool(op="expand", lo=1, hi=3)
    narrower = await guarded_tool(op="expand", lo=1, hi=2)

    assert first.state == ToolResultState.SUCCESS
    assert duplicate.state == ToolResultState.ERROR
    assert "RECALL LOOP BLOCKED" in _text(duplicate)
    assert narrower.state == ToolResultState.SUCCESS

    guard.begin_turn("user-2")
    next_turn = await guarded_tool(op="expand", lo=1, hi=3)
    assert next_turn.state == ToolResultState.SUCCESS


async def test_concurrent_duplicate_recall_executes_query_once(
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
    calls = 0
    original_expand = MemorySpace.expand

    def blocking_expand(self, lo, hi):
        nonlocal calls
        calls += 1
        started.set()
        assert release.wait(timeout=5)
        return original_expand(self, lo, hi)

    monkeypatch.setattr(MemorySpace, "expand", blocking_expand)

    first_task = asyncio.create_task(
        guarded_tool(op="expand", lo=1, hi=3),
    )
    assert await asyncio.to_thread(started.wait, 5)
    duplicate = await guarded_tool(op="expand", lo=1, hi=3)
    release.set()
    first = await first_task
    completed_duplicate = await guarded_tool(op="expand", lo=1, hi=3)

    assert first.state == ToolResultState.SUCCESS
    assert duplicate.state == ToolResultState.ERROR
    assert "already running" in _text(duplicate)
    assert completed_duplicate.state == ToolResultState.ERROR
    assert calls == 1


async def test_large_recall_is_cursor_paginated(
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
        page_max_bytes=1024,
    )

    chunk = await bounded_tool(op="expand", lo=1, hi=1)
    assert len(_text(chunk).encode("utf-8")) <= 1024
    assert "[recall page incomplete]" in _text(chunk)
    page = chunk.metadata[RECALL_PAGE_METADATA_KEY]
    assert page["next_cursor"]

    duplicate = await bounded_tool(op="expand", lo=1, hi=1)
    assert duplicate.state == ToolResultState.ERROR
    assert "RECALL LOOP BLOCKED" in _text(duplicate)

    pages = 1
    while page["next_cursor"]:
        chunk = await bounded_tool(
            op="expand",
            lo=1,
            hi=1,
            cursor=page["next_cursor"],
        )
        pages += 1
        assert len(_text(chunk).encode("utf-8")) <= 1024
        page = chunk.metadata[RECALL_PAGE_METADATA_KEY]
        assert pages < 200

    assert pages > 1
    assert page["complete"] is True
    assert "[recall page complete]" in _text(chunk)


def test_render_page_with_long_utf8_label_always_advances():
    rows = [
        {
            "seq": 1,
            "kind": "model_turn",
            "role": "assistant",
            "content": "page content " * 200,
        },
    ]
    label = "搜索" * 100

    _, first = _render_page(
        rows,
        label=label,
        cursor=None,
        max_bytes=1000,
        request_fingerprint="request",
    )
    _, second = _render_page(
        rows,
        label=label,
        cursor=first["next_cursor"],
        max_bytes=1000,
        request_fingerprint="request",
    )

    assert first["next_cursor"] is not None
    assert second["next_cursor"] != first["next_cursor"]


def test_render_page_fails_when_byte_limit_cannot_make_progress():
    rows = [{"seq": 1, "kind": "model_turn", "content": "content"}]

    with pytest.raises(ValueError, match="too small to make progress"):
        _render_page(
            rows,
            label="搜索" * 100,
            cursor=None,
            max_bytes=100,
            request_fingerprint="request",
        )


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
        page_max_bytes=1024,
    )

    chunk = await bounded_tool(
        op="recall_tool",
        tool_call_id="call-large",
    )

    assert f"file_path={str(artifact)!r}" in _text(chunk)
    assert "start_line=37" in _text(chunk)


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
        page_max_bytes=1024,
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
    guard = RecallLoopGuard()
    guard.begin_turn("user-1")
    bounded_tool = make_recall_history(
        history_db_path=str(db_path),
        session_id="current",
        agent_id="ag1",
        loop_guard=guard,
        page_max_bytes=1024,
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

    restarted = await bounded_tool(
        op="search",
        query="snapshotneedle",
        k=10,
    )
    assert restarted.state == ToolResultState.SUCCESS
    assert restarted.metadata[RECALL_PAGE_METADATA_KEY]["total_rows"] == 2


def test_old_completion_cannot_block_same_request_in_new_turn():
    guard = RecallLoopGuard()
    payload = {"lo": 1, "hi": 3}
    guard.begin_turn("user-1")
    old_generation, notice = guard.claim("expand", payload)
    assert old_generation is not None
    assert notice is None

    guard.begin_turn("user-2")
    new_generation, notice = guard.claim("expand", payload)
    assert new_generation is not None
    assert notice is None

    guard.finish("expand", payload, old_generation, block=True)
    assert guard.is_blocked("expand", payload) is False
    guard.finish("expand", payload, new_generation, block=True)
    assert guard.is_blocked("expand", payload) is True


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


async def test_unknown_op_observation_is_byte_bounded(history_db: Path):
    bounded_tool = make_recall_history(
        history_db_path=str(history_db),
        session_id="s1",
        agent_id="ag1",
        page_max_bytes=1024,
    )

    chunk = await bounded_tool(op="坏" * 50_000)

    assert chunk.state == ToolResultState.ERROR
    assert len(_text(chunk).encode("utf-8")) <= 1024
    assert "recall observation truncated" in _text(chunk)
    assert chunk.metadata == {}


async def test_empty_search_observation_is_byte_bounded(
    history_db: Path,
    monkeypatch,
):
    monkeypatch.setattr(MemorySpace, "search", lambda *_args, **_kwargs: [])
    bounded_tool = make_recall_history(
        history_db_path=str(history_db),
        session_id="s1",
        agent_id="ag1",
        page_max_bytes=1024,
    )

    chunk = await bounded_tool(op="search", query="q" * 50_000)

    assert chunk.state == ToolResultState.SUCCESS
    assert len(_text(chunk).encode("utf-8")) <= 1024
    assert "recall observation truncated" in _text(chunk)
    page = chunk.metadata[RECALL_PAGE_METADATA_KEY]
    assert page["next_cursor"] is None
    assert page["complete"] is True
    assert set(chunk.metadata) == {RECALL_PAGE_METADATA_KEY}


async def test_execution_error_observation_is_byte_bounded(
    history_db: Path,
    monkeypatch,
):
    def raise_large_error(*_args, **_kwargs):
        raise ValueError("x" * 50_000)

    monkeypatch.setattr(MemorySpace, "expand", raise_large_error)
    bounded_tool = make_recall_history(
        history_db_path=str(history_db),
        session_id="s1",
        agent_id="ag1",
        page_max_bytes=1024,
    )

    chunk = await bounded_tool(op="expand", lo=1, hi=1)

    assert chunk.state == ToolResultState.ERROR
    assert len(_text(chunk).encode("utf-8")) <= 1024
    assert "recall observation truncated" in _text(chunk)
    assert chunk.metadata == {}


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
