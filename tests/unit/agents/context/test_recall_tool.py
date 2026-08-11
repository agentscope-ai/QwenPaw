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
from agentscope.tool import FunctionTool

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
        entry=LogEntry(
            kind="context_msg",
            role="user",
            content="hello there",
            created_at="2024-11-05T09:00:00+00:00",
        ),
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
            created_at="2024-11-05T09:01:00+00:00",
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
            created_at="2024-11-05T09:02:00+00:00",
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
            created_at="2024-11-06T09:00:00+00:00",
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
    assert "created_at=2024-11-05T09:00:00+00:00" in text


@pytest.mark.parametrize(
    ("lo", "hi"),
    [
        ("1", "3"),
        ("001", 3),
        (1, "3"),
    ],
)
async def test_expand_accepts_ascii_decimal_string_seqs(tool, lo, hi):
    chunk = await tool(op="expand", lo=lo, hi=hi)

    assert chunk.state == ToolResultState.SUCCESS
    assert "expand [1, 3]" in _text(chunk)
    assert "the flight is AA231" in _text(chunk)


@pytest.mark.parametrize(
    "value",
    [True, 0, -1, 1.0, "", " 1", "1 ", "+1", "-1", "1.0", "１"],
)
@pytest.mark.parametrize("argument", ["lo", "hi"])
async def test_expand_rejects_non_positive_or_non_decimal_seqs(
    tool,
    argument,
    value,
):
    kwargs = {"lo": 1, "hi": 3, argument: value}

    chunk = await tool(op="expand", **kwargs)

    assert chunk.state == ToolResultState.ERROR
    assert 'invalid op="expand" seq span' in _text(chunk)
    assert argument in _text(chunk)


@pytest.mark.parametrize(
    ("lo", "hi"),
    [
        (3, 1),
        ("3", "1"),
        (3, "1"),
        ("3", 1),
    ],
)
async def test_expand_rejects_descending_seq_span(tool, lo, hi):
    chunk = await tool(op="expand", lo=lo, hi=hi)

    assert chunk.state == ToolResultState.ERROR
    text = _text(chunk)
    assert text.startswith('RECALL FAILED — invalid op="expand" seq span')
    assert "lo (3) must be less than or equal to hi (1)" in text
    assert "swap lo and hi and retry" in text


async def test_expand_accepts_single_seq_span(tool):
    chunk = await tool(op="expand", lo=1, hi=1)

    assert chunk.state == ToolResultState.SUCCESS
    text = _text(chunk)
    assert "expand [1, 1]" in text
    assert "hello there" in text


def test_expand_schema_accepts_integer_or_string_seqs(tool):
    properties = FunctionTool(tool).input_schema["properties"]

    for argument in ("lo", "hi"):
        accepted_types = {
            item["type"] for item in properties[argument]["anyOf"]
        }
        assert accepted_types == {"integer", "string", "null"}


async def test_search_finds_evicted_turn_not_active_turn(tool):
    chunk = await tool(op="search", query="flight", k=10)
    assert chunk.state == ToolResultState.SUCCESS
    text = _text(chunk)
    assert "turn_seq=1–3" in text
    assert "matched_seq=2" in text
    assert "hello there" in text
    assert "the flight is AA231" in text
    assert "RESULT-FULL" in text
    # The active turn (latest user request) is excluded from hits.
    assert "what was the flight again" not in text


async def test_search_user_hit_returns_same_complete_turn(tool):
    chunk = await tool(op="search", query="hello", k=10)

    assert chunk.state == ToolResultState.SUCCESS
    text = _text(chunk)
    assert "matched_seq=1" in text
    assert "hello there" in text
    assert "the flight is AA231" in text
    assert "RESULT-FULL" in text


async def test_search_cjk_substring_returns_same_complete_turn(
    tmp_path: Path,
):
    db_path = tmp_path / "cjk-history.db"
    history = HistoryStore(db_path)
    history.append(
        session_id="archive",
        agent_id="ag1",
        dedup_key="u1",
        entry=LogEntry(
            kind="context_msg",
            role="user",
            content="紫水晶河马在周二跳舞",
        ),
    )
    history.append(
        session_id="archive",
        agent_id="ag1",
        dedup_key="a1",
        entry=LogEntry(
            kind="model_turn",
            role="assistant",
            content="我记住了这个暗号",
        ),
    )
    history.append(
        session_id="archive",
        agent_id="ag1",
        dedup_key="t1",
        entry=LogEntry(
            kind="tool_result",
            role="assistant",
            name="lookup",
            content="工具结果",
            tool_call_id="call-cjk",
        ),
    )
    history.close()
    recall = make_recall_history(
        history_db_path=str(db_path),
        session_id="current",
        agent_id="ag1",
    )

    chunk = await recall(
        op="search",
        query="紫水晶河马",
        session_id="archive",
        k=10,
    )

    assert chunk.state == ToolResultState.SUCCESS
    text = _text(chunk)
    assert "matched_seq=1" in text
    assert "turn_seq=1–3" in text
    assert "紫水晶河马在周二跳舞" in text
    assert "我记住了这个暗号" in text
    assert "工具结果" in text


async def test_search_cjk_multiple_terms_returns_complete_turn(
    tmp_path: Path,
):
    db_path = tmp_path / "cjk-multiple-terms.db"
    history = HistoryStore(db_path)
    history.append(
        session_id="archive",
        agent_id="ag1",
        dedup_key="u1",
        entry=LogEntry(
            kind="context_msg",
            role="user",
            content="项目的截止日期是周二",
        ),
    )
    history.append(
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
    recall = make_recall_history(
        history_db_path=str(db_path),
        session_id="current",
        agent_id="ag1",
    )

    chunk = await recall(
        op="search",
        query="项目 截止日期",
        session_id="archive",
        k=10,
    )

    assert chunk.state == ToolResultState.SUCCESS
    text = _text(chunk)
    assert "matched_seq=1" in text
    assert "turn_seq=1–2" in text
    assert "项目的截止日期是周二" in text
    assert "好的，我记住了" in text


async def test_search_cjk_uppercase_or_does_not_report_false_empty(
    tmp_path: Path,
):
    db_path = tmp_path / "cjk-or.db"
    history = HistoryStore(db_path)
    history.append(
        session_id="archive",
        agent_id="ag1",
        dedup_key="project",
        entry=LogEntry(
            kind="context_msg",
            role="user",
            content="项目状态",
        ),
    )
    history.append(
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
    recall = make_recall_history(
        history_db_path=str(db_path),
        session_id="current",
        agent_id="ag1",
    )

    chunk = await recall(
        op="search",
        query="项目 OR 截止日期",
        session_id="archive",
        k=10,
    )

    assert chunk.state == ToolResultState.SUCCESS
    text = _text(chunk)
    assert "项目状态" in text
    assert "截止日期" in text
    assert "0 rows" not in text


async def test_search_filters_and_displays_created_at(tool):
    chunk = await tool(
        op="search",
        query="flight",
        created_on="2024-11-05",
        k=10,
    )
    wrong_date = await tool(
        op="search",
        query="flight",
        created_on="2024-11-04",
        k=10,
    )
    date_only = await tool(
        op="search",
        query="",
        created_from="2024-11-05",
        created_to="2024-11-05",
        k=10,
    )

    assert chunk.state == ToolResultState.SUCCESS
    assert "created_at=2024-11-05T09:01:00+00:00" in _text(chunk)
    assert "the flight is AA231" in _text(chunk)
    assert wrong_date.state == ToolResultState.SUCCESS
    assert _text(wrong_date).startswith("0 rows")
    assert date_only.state == ToolResultState.SUCCESS
    assert "hello there" in _text(date_only)
    assert "RESULT-FULL" in _text(date_only)


async def test_date_search_renders_safe_blocks_only_turn(tmp_path: Path):
    db_path = tmp_path / "blocks-only.db"
    history = HistoryStore(db_path)
    history.append(
        session_id="archive",
        agent_id="ag1",
        dedup_key="structured",
        entry=LogEntry(
            kind="context_msg",
            role="user",
            content=None,
            blocks=[
                {"type": "text", "text": "structured history"},
                {
                    "type": "tool_call",
                    "id": "call-structured",
                    "name": "lookup",
                    "input": {"topic": "launch"},
                },
                {
                    "type": "data",
                    "name": "diagram.png",
                    "source": {
                        "type": "url",
                        "media_type": "image/png",
                        "url": "https://example.invalid/diagram.png",
                    },
                },
                {
                    "type": "data",
                    "name": "embedded.png",
                    "source": {
                        "type": "url",
                        "media_type": "image/png",
                        "url": "data:image/png;base64,DO-NOT-RENDER",
                    },
                },
            ],
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
    recall = make_recall_history(
        history_db_path=str(db_path),
        session_id="current",
        agent_id="ag1",
    )

    chunk = await recall(
        op="search",
        query="",
        created_on="2024-11-05",
    )

    assert chunk.state == ToolResultState.SUCCESS
    text = _text(chunk)
    assert "structured history" in text
    assert "[tool_call name=lookup id=call-structured]" in text
    assert 'input={"topic":"launch"}' in text
    assert "[image: diagram.png — https://example.invalid/diagram.png]" in text
    assert "[image: embedded.png — <image/png>]" in text
    assert "DO-NOT-RENDER" not in text


async def test_search_rejects_invalid_created_at_filters(tool):
    invalid = await tool(
        op="search",
        query="flight",
        created_on="2024-02-30",
    )
    conflicting = await tool(
        op="search",
        query="flight",
        created_on="2024-11-05",
        created_from="2024-11-01",
    )

    assert invalid.state == ToolResultState.ERROR
    assert "invalid ISO date" in _text(invalid)
    assert conflicting.state == ToolResultState.ERROR
    assert "cannot be combined" in _text(conflicting)


async def test_search_saved_tool_output_keeps_match_excerpt(tmp_path: Path):
    artifact = tmp_path / "saved-tool-output.txt"
    artifact.write_text("the deepneedle is here\n", encoding="utf-8")
    history = HistoryStore(tmp_path / "history.db")
    history.append(
        session_id="archive",
        agent_id="ag1",
        dedup_key="u1",
        entry=LogEntry(
            kind="context_msg",
            role="user",
            content="inspect the saved output",
        ),
    )
    history.append(
        session_id="archive",
        agent_id="ag1",
        dedup_key="t1",
        entry=LogEntry(
            kind="tool_result",
            role="assistant",
            name="shell",
            tool_call_id="call-saved",
            content=(
                "[tool output truncated]\n"
                "If more content is needed, call `read_file` with "
                f"file_path={artifact} start_line=1 to read more."
            ),
        ),
    )
    history.close()
    saved_tool = make_recall_history(
        history_db_path=str(tmp_path / "history.db"),
        session_id="current",
        agent_id="ag1",
    )

    chunk = await saved_tool(op="search", query="deepneedle", k=10)

    assert chunk.state == ToolResultState.SUCCESS
    text = _text(chunk)
    assert "[matched content excerpt]" in text
    assert "deepneedle" in text
    assert "inspect the saved output" in text
    assert str(artifact) in text


async def test_search_saved_tool_output_preserves_uppercase_or(
    tmp_path: Path,
):
    artifact = tmp_path / "saved-tool-output-or.txt"
    artifact.write_text("项目状态\n", encoding="utf-8")
    history = HistoryStore(tmp_path / "history.db")
    history.append(
        session_id="archive",
        agent_id="ag1",
        dedup_key="t1",
        entry=LogEntry(
            kind="tool_result",
            role="assistant",
            name="shell",
            tool_call_id="call-saved-or",
            content=(
                "[tool output truncated]\n"
                "If more content is needed, call `read_file` with "
                f"file_path={artifact} start_line=1 to read more."
            ),
        ),
    )
    history.close()
    recall = make_recall_history(
        history_db_path=str(tmp_path / "history.db"),
        session_id="current",
        agent_id="ag1",
    )

    chunk = await recall(
        op="search",
        query="项目 OR 截止日期",
        k=10,
    )

    assert chunk.state == ToolResultState.SUCCESS
    text = _text(chunk)
    assert "0 rows" not in text
    assert "[matched content excerpt]" in text
    assert "项目状态" in text
    assert str(artifact) in text


async def test_recall_tool_by_call_id(tool):
    chunk = await tool(op="recall_tool", tool_call_id="call_abc")
    assert chunk.state == ToolResultState.SUCCESS
    assert "RESULT-FULL" in _text(chunk)


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        ("2024-11-01", "2024-12-16", 45),
        ("2024-12-16", "2024-11-01", -45),
        (
            "2024-02-28T23:00:00-08:00",
            "2024-03-01T01:00:00Z",
            2,
        ),
    ],
)
async def test_days_between_uses_shared_date_semantics(
    tool,
    start: str,
    end: str,
    expected: int,
):
    chunk = await tool(op="days_between", start=start, end=end)

    assert chunk.state == ToolResultState.SUCCESS
    assert _text(chunk).endswith(f"= {expected}")
    assert chunk.metadata == {}


async def test_days_between_supports_signed_inclusive_ranges(tool):
    chunk = await tool(
        op="days_between",
        start="2024-11-02",
        end="2024-11-01",
        inclusive=True,
    )

    assert chunk.state == ToolResultState.SUCCESS
    assert _text(chunk).endswith("= -2")


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (None, "2024-12-16"),
        ("2024-11-01", None),
        ("2024-02-30", "2024-12-16"),
        ("2024-11-01 12:00:00Z", "2024-12-16"),
    ],
)
async def test_days_between_rejects_missing_or_invalid_dates(
    tool,
    start: str | None,
    end: str | None,
):
    chunk = await tool(op="days_between", start=start, end=end)

    assert chunk.state == ToolResultState.ERROR
    assert _text(chunk).startswith("RECALL FAILED")
    assert "history genuinely holds nothing" not in _text(chunk)


async def test_days_between_rejects_pagination_cursor(tool):
    chunk = await tool(
        op="days_between",
        start="2024-11-01",
        end="2024-12-16",
        cursor="not-used-for-date-math",
    )

    assert chunk.state == ToolResultState.ERROR
    assert "does not paginate" in _text(chunk)


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

    first = await guarded_tool(op="expand", lo="1", hi="3")
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


async def test_cancelled_recall_keeps_claim_until_worker_finishes(
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

    def blocking_first_expand(self, lo, hi):
        nonlocal calls
        calls += 1
        if calls == 1:
            started.set()
            assert release.wait(timeout=5)
        return original_expand(self, lo, hi)

    monkeypatch.setattr(MemorySpace, "expand", blocking_first_expand)
    first_task = asyncio.create_task(
        guarded_tool(op="expand", lo=1, hi=3),
    )
    assert await asyncio.to_thread(started.wait, 5)

    first_task.cancel()
    await asyncio.sleep(0)
    try:
        duplicate = await guarded_tool(op="expand", lo=1, hi=3)

        assert duplicate.state == ToolResultState.ERROR
        assert "already running" in _text(duplicate)
        assert calls == 1
        assert not first_task.done()
    finally:
        release.set()

    with pytest.raises(asyncio.CancelledError):
        await first_task

    retry = await guarded_tool(op="expand", lo=1, hi=3)
    assert retry.state == ToolResultState.SUCCESS
    assert calls == 2


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
        session_id="old",
        agent_id="ag1",
        loop_guard=guard,
        page_max_bytes=1024,
    )

    chunk = await bounded_tool(op="expand", lo="1", hi="1")
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

    changed_date = await bounded_tool(
        op="search",
        query="alpha",
        k=10,
        created_on="2024-11-05",
        cursor=cursor,
    )
    assert changed_date.state == ToolResultState.ERROR
    assert "different recall request" in _text(changed_date)


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
