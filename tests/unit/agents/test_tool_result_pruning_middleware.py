# -*- coding: utf-8 -*-
# pylint: disable=protected-access,unused-argument,wrong-import-position
"""Tests for tool-result pruning middleware."""

from __future__ import annotations

import sys
import types
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator

import pytest
from agentscope.message import Msg, TextBlock, ToolResultBlock, ToolResultState
from agentscope.tool import ToolChunk, ToolResponse

html2text_stub = types.ModuleType("html2text")
html2text_stub.HTML2Text = type("HTML2Text", (), {})
sys.modules.setdefault("html2text", html2text_stub)

from qwenpaw.agents.middlewares import (  # noqa: E402
    ToolResultPruningMiddleware,
)
from qwenpaw.agents.tools.utils import (  # noqa: E402
    truncate_text_output,
    TRUNCATION_METADATA_KEY,
)
from qwenpaw.config.config import (  # noqa: E402
    LightContextConfig,
    ToolResultPruningConfig,
)
from qwenpaw.constant import TRUNCATION_NOTICE_MARKER  # noqa: E402
from qwenpaw.runtime.builder import AgentBuilder  # noqa: E402
from qwenpaw.tool_calls import (  # noqa: E402
    ToolCoordinator,
    ToolCoordinatorMiddleware,
)


@dataclass
class _ToolCall:
    id: str = "call-1"
    name: str = "test_tool"
    input: dict[str, Any] = field(default_factory=dict)


async def _collect(iterator: AsyncGenerator[Any, None]) -> list[Any]:
    events: list[Any] = []
    async for item in iterator:
        events.append(item)
    return events


@pytest.mark.asyncio
async def test_tool_response_is_pruned_before_yield(tmp_path):
    middleware = ToolResultPruningMiddleware(
        recent_max_bytes=512,
        tool_results_dir=str(tmp_path),
    )
    text = "\n".join("x" * 80 for _ in range(30))
    response = ToolResponse(
        id="call-1",
        content=[TextBlock(type="text", text=text)],
    )

    async def next_handler() -> AsyncGenerator[Any, None]:
        yield response

    agent = type(
        "AgentStub",
        (),
        {"state": type("StateStub", (), {"context": []})()},
    )()

    events = await _collect(
        middleware.on_acting(
            agent,
            {"tool_call": object()},
            next_handler,
        ),
    )

    result = events[0]
    result_text = result.content[0].text
    assert result is response
    assert TRUNCATION_NOTICE_MARKER in result_text
    assert len(result_text.encode("utf-8")) < len(text.encode("utf-8"))
    truncation = result.metadata[TRUNCATION_METADATA_KEY]["0"]
    assert truncation["file_path"]
    assert truncation["file_size_bytes"] == len(text.encode("utf-8"))
    assert truncation["start_line"] == 1
    assert result_text.endswith(truncation["notice"])

    saved = list(tmp_path.iterdir())
    assert len(saved) == 1
    assert saved[0].read_text(encoding="utf-8") == text


@pytest.mark.asyncio
async def test_multi_block_tool_response_keeps_metadata_isolated(tmp_path):
    middleware = ToolResultPruningMiddleware(
        recent_max_bytes=300,
        tool_results_dir=str(tmp_path),
    )
    first_text = "\n".join(f"first-{i}: " + "x" * 40 for i in range(80))
    second_source = "\n".join(f"second-{i}: " + "y" * 40 for i in range(80))
    second_text, second_metadata = truncate_text_output(
        second_source,
        start_line=50,
        total_lines=129,
        max_bytes=1200,
        file_path="/tmp/second.txt",
    )
    response = ToolResponse(
        id="call-1",
        content=[TextBlock(text=first_text), TextBlock(text=second_text)],
        metadata=second_metadata,
    )

    async def next_handler() -> AsyncGenerator[Any, None]:
        yield response

    agent = type(
        "AgentStub",
        (),
        {"state": type("StateStub", (), {"context": []})()},
    )()
    result = (
        await _collect(
            middleware.on_acting(agent, {}, next_handler),
        )
    )[0]

    by_block = result.metadata[TRUNCATION_METADATA_KEY]
    assert by_block["0"]["start_line"] == 1
    assert by_block["1"]["start_line"] == 50
    assert by_block["1"]["file_path"] == "/tmp/second.txt"
    assert result.content[0].text.endswith(by_block["0"]["notice"])
    assert result.content[1].text.endswith(by_block["1"]["notice"])


@pytest.mark.asyncio
async def test_outer_pruning_caps_coordinator_final_tool_chunk_response(
    tmp_path,
):
    pruning = ToolResultPruningMiddleware(
        recent_max_bytes=512,
        tool_results_dir=str(tmp_path),
    )
    coordinator = ToolCoordinator()
    coordinator_middleware = ToolCoordinatorMiddleware(coordinator)
    tool_call = _ToolCall()
    text = "\n".join("x" * 80 for _ in range(30))

    async def next_handler(
        tool_call: _ToolCall,
    ) -> AsyncGenerator[Any, None]:
        yield ToolChunk(
            is_last=True,
            state=ToolResultState.SUCCESS,
            content=[TextBlock(type="text", text=text)],
        )

    async def coordinator_handler() -> AsyncGenerator[Any, None]:
        async for event in coordinator_middleware.on_acting(
            agent,
            {"tool_call": tool_call},
            next_handler,
        ):
            yield event

    agent = type(
        "AgentStub",
        (),
        {
            "_request_context": {
                "session_id": "session-1",
                "agent_id": "agent-1",
                "root_session_id": "root-1",
            },
            "state": type("StateStub", (), {"context": []})(),
        },
    )()

    events = await _collect(
        pruning.on_acting(
            agent,
            {"tool_call": tool_call},
            coordinator_handler,
        ),
    )

    final_response = events[-1]
    result_text = final_response.content[0].text
    assert isinstance(final_response, ToolResponse)
    assert TRUNCATION_NOTICE_MARKER in result_text
    assert len(result_text.encode("utf-8")) < len(text.encode("utf-8"))


def test_retruncate_uses_metadata(tmp_path):
    middleware = ToolResultPruningMiddleware(tool_results_dir=str(tmp_path))
    text = "\n".join(f"line-{i}: " + "x" * 60 for i in range(100))

    first, metadata = middleware._truncate_tool_result(text, 2000)
    info = metadata[TRUNCATION_METADATA_KEY]["0"]
    corrupted = first.replace("starts at line 1", "starts at line 999")
    second, updated = middleware._truncate_tool_result(
        corrupted,
        500,
        metadata,
    )

    new_info = updated[TRUNCATION_METADATA_KEY]["0"]
    assert new_info["start_line"] == 1
    assert new_info["max_bytes"] == 500
    assert new_info["file_path"] == info["file_path"]
    assert second.endswith(new_info["notice"])


def test_retruncate_with_incomplete_metadata_fails_open_without_error():
    text = (
        "\n".join(f"line-{i}: " + "x" * 60 for i in range(100))
        + TRUNCATION_NOTICE_MARKER
        + "\nlegacy notice"
    )
    malformed = {
        TRUNCATION_METADATA_KEY: {
            "0": {
                "notice": TRUNCATION_NOTICE_MARKER + "\nlegacy notice",
                "file_path": "/tmp/result.txt",
            },
        },
    }

    result, patch = truncate_text_output(
        text,
        max_bytes=300,
        metadata=malformed,
    )

    assert result == text
    assert not patch


def test_historical_multi_block_metadata_is_isolated(tmp_path):
    middleware = ToolResultPruningMiddleware(
        recent_max_bytes=300,
        tool_results_dir=str(tmp_path),
    )
    first_text = "\n".join(f"first-{i}: " + "x" * 40 for i in range(80))
    second_source = "\n".join(f"second-{i}: " + "y" * 40 for i in range(80))
    second_text, second_metadata = truncate_text_output(
        second_source,
        start_line=50,
        total_lines=129,
        max_bytes=1200,
        file_path="/tmp/historical-second.txt",
    )
    result_block = ToolResultBlock(
        id="call-1",
        name="test_tool",
        output=[TextBlock(text=first_text), TextBlock(text=second_text)],
        metadata=second_metadata,
    )
    messages = [
        Msg(name="assistant", role="assistant", content=[result_block]),
    ]

    middleware._prune_tool_results(messages)

    by_block = result_block.metadata[TRUNCATION_METADATA_KEY]
    assert by_block["0"]["start_line"] == 1
    assert by_block["1"]["start_line"] == 50
    assert by_block["1"]["file_path"] == "/tmp/historical-second.txt"
    assert result_block.output[0].text.endswith(by_block["0"]["notice"])
    assert result_block.output[1].text.endswith(by_block["1"]["notice"])


def test_builder_places_pruning_outside_tool_coordinator(tmp_path):
    agent_config = types.SimpleNamespace(
        id="agent-1",
        running=types.SimpleNamespace(
            light_context_config=LightContextConfig(
                strategy="native",
                tool_result_pruning_config=ToolResultPruningConfig(),
            ),
        ),
    )
    ctx = types.SimpleNamespace(
        app_services=types.SimpleNamespace(tool_coordinator=ToolCoordinator()),
        workspace=types.SimpleNamespace(workspace_dir=str(tmp_path)),
    )

    middlewares = AgentBuilder._build_middlewares(ctx, agent_config)

    pruning_index = next(
        idx
        for idx, middleware in enumerate(middlewares)
        if isinstance(middleware, ToolResultPruningMiddleware)
    )
    coordinator_index = next(
        idx
        for idx, middleware in enumerate(middlewares)
        if isinstance(middleware, ToolCoordinatorMiddleware)
    )
    assert pruning_index < coordinator_index


def test_builder_adds_pruning_for_scroll_strategy(tmp_path):
    agent_config = types.SimpleNamespace(
        id="agent-1",
        running=types.SimpleNamespace(
            light_context_config=LightContextConfig(
                strategy="scroll",
                tool_result_pruning_config=ToolResultPruningConfig(),
            ),
        ),
    )
    ctx = types.SimpleNamespace(
        app_services=types.SimpleNamespace(tool_coordinator=ToolCoordinator()),
        workspace=types.SimpleNamespace(workspace_dir=str(tmp_path)),
    )

    middlewares = AgentBuilder._build_middlewares(ctx, agent_config)

    assert any(
        isinstance(middleware, ToolResultPruningMiddleware)
        for middleware in middlewares
    )
    assert any(
        isinstance(middleware, ToolCoordinatorMiddleware)
        for middleware in middlewares
    )
