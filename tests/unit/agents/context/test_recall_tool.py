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

from pathlib import Path

import pytest
from agentscope.message import ToolResultState

from qwenpaw.agents.context.scroll.history import HistoryStore
from qwenpaw.agents.context.scroll.recall_tool import make_recall_history
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
