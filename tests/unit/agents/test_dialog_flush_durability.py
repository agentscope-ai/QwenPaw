# -*- coding: utf-8 -*-
# pylint: disable=protected-access,too-few-public-methods
"""Tests for Issue #6542 — per-turn dialog durability (fsync + middleware)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any, AsyncGenerator

import pytest

from agentscope.message import Msg

from qwenpaw.agents import offloader as offloader_mod
from qwenpaw.agents.middlewares import DialogFlushMiddleware


def _make_msg(idx: int, ts_date: str = "2026-07-31") -> Msg:
    m = Msg(
        name=f"u{idx}",
        content=[{"type": "text", "text": f"hello {idx}"}],
        role="user",
    )
    # Force the text block's created_at to a deterministic timestamp so
    # the offloader's msg.timestamp property groups writes into the
    # expected YYYY-MM-DD.jsonl file instead of today's real date.
    # AgentScope 2.0 Msg.timestamp composes this from last block.
    m.content[-1].created_at = f"{ts_date}T10:00:0{idx}.000000"
    return m


@pytest.mark.asyncio
async def test_offload_context_calls_fsync_after_write(tmp_path: Path):
    fsync_calls: list[str] = []

    def fake_fsync(fd: int) -> None:  # noqa: D401 - type stubs don't help
        fsync_calls.append(os.fstat(fd).st_size > 0 and "ok" or "empty")

    off = offloader_mod.QwenPawOffloader(
        dialog_path=str(tmp_path / "dialog"),
        tool_results_dir=str(tmp_path / "tr"),
    )
    msgs = [_make_msg(1), _make_msg(2)]
    saved = offloader_mod.os.fsync
    try:
        offloader_mod.os.fsync = fake_fsync
        result = await off.offload_context("sess1", msgs)
    finally:
        offloader_mod.os.fsync = saved

    assert result.endswith("2026-07-31.jsonl")
    assert fsync_calls and all(c == "ok" for c in fsync_calls)
    lines = Path(result).read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    payloads = [json.loads(line) for line in lines]
    # content is a list of TextBlock dicts in Msg.to_dict() output.
    first_text = payloads[0]["content"][0]["text"]
    second_text = payloads[1]["content"][0]["text"]
    assert first_text == "hello 1"
    assert second_text == "hello 2"


@pytest.mark.asyncio
async def test_offload_tool_result_calls_fsync(tmp_path: Path):
    fsync_calls: list[bool] = []

    def fake_fsync(_fd: int) -> None:
        fsync_calls.append(True)

    class FakeToolResult:
        type = "tool_result"
        output = "a very normal tool output\nwith newlines"

    off = offloader_mod.QwenPawOffloader(
        dialog_path=str(tmp_path / "dialog"),
        tool_results_dir=str(tmp_path / "tr"),
    )
    saved = offloader_mod.os.fsync
    try:
        offloader_mod.os.fsync = fake_fsync
        result = await off.offload_tool_result(
            "sess1",
            FakeToolResult(),  # type: ignore[arg-type]
        )
    finally:
        offloader_mod.os.fsync = saved

    assert fsync_calls == [True]
    assert Path(result).read_text(encoding="utf-8") == FakeToolResult.output


class _RecordOffloader:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[Any]]] = []

    async def offload_context(self, session_id: str, msgs: list[Any]) -> str:
        self.calls.append((session_id, list(msgs)))
        return ""


async def _run_reply(
    mw: DialogFlushMiddleware,
    agent: Any,
    events: list[Any],
) -> list[Any]:
    collected: list[Any] = []

    async def _next(**_kw: Any) -> AsyncGenerator[Any, None]:
        for e in events:
            yield e

    async for item in mw.on_reply(agent, {"prompt": "hi"}, _next):
        collected.append(item)
    return collected


@pytest.mark.asyncio
async def test_dialog_flush_persists_only_new_tail():
    off = _RecordOffloader()
    state = SimpleNamespace(session_id="sess-abc", context=[])
    agent = SimpleNamespace(offloader=off, state=state)
    mw = DialogFlushMiddleware()
    context = state.context

    for i in range(1, 6):
        context.append(_make_msg(i))

    out = await _run_reply(mw, agent, ["chunk1", "chunk2"])
    assert out == ["chunk1", "chunk2"]
    # First turn: everything is new → call with all 5 messages.
    assert len(off.calls) == 1
    assert off.calls[0][0] == "sess-abc"
    assert [m.content[0].text for m in off.calls[0][1]] == [
        "hello 1",
        "hello 2",
        "hello 3",
        "hello 4",
        "hello 5",
    ]

    # Second turn without new messages → offloader must not be called again.
    off.calls.clear()
    await _run_reply(mw, agent, ["chunk3"])
    assert not off.calls

    # Append two new messages → offloader sees only the tail.
    context.append(_make_msg(6))
    context.append(_make_msg(7))
    await _run_reply(mw, agent, ["chunk4"])
    assert len(off.calls) == 1
    assert [m.content[0].text for m in off.calls[0][1]] == [
        "hello 6",
        "hello 7",
    ]


@pytest.mark.asyncio
async def test_dialog_flush_noop_without_offloader():
    state = SimpleNamespace(session_id="s", context=[_make_msg(1)])
    agent = SimpleNamespace(offloader=None, state=state)
    mw = DialogFlushMiddleware()
    await _run_reply(mw, agent, ["ok"])
    # No exceptions, and state counter is not set when no offloader.
    assert getattr(state, DialogFlushMiddleware._STATE_KEY, None) is None
