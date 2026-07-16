# -*- coding: utf-8 -*-
"""Tests for execution-time tool-call JSON repair and validation."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from agentscope.message import ToolCallBlock, ToolResultState
from agentscope.tool import ToolResponse

from qwenpaw.agents.middlewares import ToolCallInputRepairMiddleware


async def _run_middleware(raw: str, *, name: str = "write_file"):
    middleware = ToolCallInputRepairMiddleware()
    tool_call = ToolCallBlock(
        id="call-1",
        name=name,
        input=raw,
    )
    observed = []

    async def downstream(**kwargs):
        observed.append(kwargs["tool_call"].input)
        yield ToolResponse()

    events = [
        event
        async for event in middleware.on_acting(
            SimpleNamespace(),
            {"tool_call": tool_call},
            downstream,
        )
    ]
    return tool_call, observed, events


@pytest.mark.asyncio
async def test_repairs_format_only_error_and_persists_canonical_input():
    tool_call, observed, events = await _run_middleware(
        "{'file_path': 'report.txt', 'content': 'complete',}",
    )

    assert json.loads(tool_call.input) == {
        "file_path": "report.txt",
        "content": "complete",
    }
    assert observed == [tool_call.input]
    assert events[0].state == ToolResultState.SUCCESS


@pytest.mark.asyncio
async def test_repairs_large_complete_content():
    content = "large payload\n" * 5000
    raw = (
        json.dumps(
            {"file_path": "report.txt", "content": content},
            ensure_ascii=False,
        )[:-1]
        + ",}"
    )

    tool_call, observed, _ = await _run_middleware(raw)

    assert json.loads(tool_call.input)["content"] == content
    assert observed == [tool_call.input]


@pytest.mark.asyncio
async def test_rejects_repair_that_closes_truncated_file_content():
    raw = '{"file_path":"report.py","content":"print(123)'

    tool_call, observed, events = await _run_middleware(raw)

    assert tool_call.input == "{}"
    assert observed == []
    assert events[0].state == ToolResultState.ERROR
    assert "may be truncated" in events[0].content[0].text


@pytest.mark.asyncio
async def test_rejects_command_with_unterminated_heredoc():
    raw = json.dumps(
        {"command": "cat > /tmp/output.py << 'PY'\nprint('partial')"},
    )

    tool_call, observed, events = await _run_middleware(
        raw,
        name="execute_shell_command",
    )

    assert tool_call.input == "{}"
    assert observed == []
    assert events[0].state == ToolResultState.ERROR
    assert "unterminated heredoc" in events[0].content[0].text


@pytest.mark.asyncio
async def test_file_content_may_document_an_unterminated_heredoc_example():
    raw = json.dumps(
        {
            "file_path": "notes.md",
            "content": "Example syntax: cat << 'EOF'",
        },
    )

    tool_call, observed, events = await _run_middleware(raw)

    assert observed == [tool_call.input]
    assert events[0].state == ToolResultState.SUCCESS
