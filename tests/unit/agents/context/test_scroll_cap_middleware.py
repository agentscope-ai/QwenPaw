# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Tests for scroll tool-result capping."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from agentscope.message import TextBlock
from agentscope.tool import ToolResponse

from qwenpaw.agents.context.scroll.cap_middleware import (
    ToolResultCapMiddleware,
)
from qwenpaw.agents.context.scroll.history import HistoryStore
from qwenpaw.constant import TRUNCATION_NOTICE_MARKER


class FakeModel:
    async def count_tokens(self, *_args, **_kwargs) -> int:
        return 1000


def _all_text(response: ToolResponse) -> str:
    return "".join(
        block.text
        for block in response.content
        if getattr(block, "type", None) == "text"
    )


@pytest.mark.asyncio
async def test_scroll_cap_uses_file_truncation_notice_and_keeps_raw_recallable(
    tmp_path,
):
    store = HistoryStore(tmp_path / "history.db")
    cap = ToolResultCapMiddleware(
        history=store,
        model=FakeModel(),
        session_id="s1",
        agent_id="ag1",
        token_cap=100,
        tool_results_dir=tmp_path / "tool_results",
        preview_max_bytes=120,
    )
    text = "\n".join(f"line {idx}: {'x' * 20}" for idx in range(40))
    response = ToolResponse(
        id="call-1",
        content=[TextBlock(type="text", text=text)],
    )

    result = await cap._cap(
        response,
        SimpleNamespace(id="call-1", name="long_tool"),
    )

    out = _all_text(result)
    assert TRUNCATION_NOTICE_MARKER in out
    assert "read_file" in out
    assert "file_path=" in out
    assert "recall_history" not in out

    saved = list((tmp_path / "tool_results").iterdir())
    assert len(saved) == 1
    assert saved[0].read_text(encoding="utf-8") == text

    row = store._conn.execute(
        "SELECT content, tool_call_id FROM conversation_history "
        "WHERE kind='tool_result'",
    ).fetchone()
    assert row["content"] == text
    assert row["tool_call_id"] == "call-1"
    store.close()
