# -*- coding: utf-8 -*-
# pylint: disable=protected-access,unused-argument,wrong-import-position
"""Tests for tool-result pruning middleware."""

from __future__ import annotations

import asyncio
import logging
import sys
import threading
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
    build_truncation_metadata,
    MAX_TRUNCATION_NOTICE_BYTES,
    ToolResultPruner,
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
    assert truncation["excerpt_bytes"] <= 512
    assert len(truncation["notice"].encode("utf-8")) <= 1024
    assert len(result_text.encode("utf-8")) <= (
        512 + MAX_TRUNCATION_NOTICE_BYTES
    )
    assert truncation["file_path"]
    assert truncation["file_size_bytes"] == len(text.encode("utf-8"))
    assert truncation["start_line"] == 1
    assert result_text.endswith(truncation["notice"])

    saved = list(tmp_path.iterdir())
    assert len(saved) == 1
    assert saved[0].read_text(encoding="utf-8") == text


@pytest.mark.asyncio
async def test_tool_response_write_failure_fails_open(
    tmp_path,
    monkeypatch,
    caplog,
):
    tool_results_dir = tmp_path / "tool_results"
    middleware = ToolResultPruningMiddleware(
        recent_max_bytes=512,
        tool_results_dir=str(tool_results_dir),
    )
    text = "\n".join("x" * 80 for _ in range(30))
    response = ToolResponse(
        id="call-1",
        content=[TextBlock(type="text", text=text)],
    )

    def fail_save(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(
        "qwenpaw.agents.tools.utils.save_text_output",
        fail_save,
    )

    result = middleware.prune_tool_response(response)

    assert result is response
    assert result.content[0].text == text
    assert TRUNCATION_NOTICE_MARKER not in result.content[0].text
    assert TRUNCATION_METADATA_KEY not in result.metadata
    assert not tool_results_dir.exists()
    assert "returning the original result" in caplog.text


def test_notice_has_independent_one_kib_budget():
    metadata = build_truncation_metadata(
        file_path="/" + "long-path/" * 300,
        file_size_bytes=100_000,
        total_lines=1000,
        start_line=1,
        max_bytes=512,
        excerpt_bytes=500,
        read_from=10,
    )

    info = metadata[TRUNCATION_METADATA_KEY]["0"]
    assert info["file_path"].startswith("/long-path/")
    assert len(info["notice"].encode("utf-8")) <= 1024
    assert TRUNCATION_NOTICE_MARKER in info["notice"]


def test_notice_quotes_saved_file_path():
    metadata = build_truncation_metadata(
        file_path="/tmp/tool results/output.txt",
        file_size_bytes=1000,
        total_lines=20,
        start_line=1,
        max_bytes=512,
        excerpt_bytes=500,
        read_from=10,
    )

    notice = metadata[TRUNCATION_METADATA_KEY]["0"]["notice"]
    assert 'file_path="/tmp/tool results/output.txt" start_line=10' in notice


def test_retruncate_does_not_allow_byte_slack():
    text = "\n".join("x" * 20 for _ in range(100))
    first, metadata = truncate_text_output(
        text,
        total_lines=100,
        max_bytes=1000,
    )
    second, updated = truncate_text_output(
        first,
        max_bytes=950,
        metadata=metadata,
    )

    info = updated[TRUNCATION_METADATA_KEY]["0"]
    excerpt = second[: -len(info["notice"])]
    assert len(excerpt.encode("utf-8")) <= 950
    assert info["max_bytes"] == 950


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


@pytest.mark.asyncio
async def test_configured_background_result_processor_prunes_response(
    tmp_path,
):
    pruning = ToolResultPruningMiddleware(
        recent_max_bytes=512,
        tool_results_dir=str(tmp_path),
    )
    coordinator_middleware = ToolCoordinatorMiddleware(
        ToolCoordinator(),
        background_result_processor=pruning.prune_tool_response_async,
    )
    text = "\n".join("x" * 80 for _ in range(30))
    response = ToolResponse(
        id="call-bg",
        content=[TextBlock(type="text", text=text)],
    )

    processor = coordinator_middleware._background_result_processor
    assert processor is not None
    result = await processor(response)

    result_text = result.content[0].text
    info = result.metadata[TRUNCATION_METADATA_KEY]["0"]
    assert TRUNCATION_NOTICE_MARKER in result_text
    assert info["excerpt_bytes"] <= 512
    assert result_text.endswith(info["notice"])
    assert len(result_text.encode("utf-8")) <= (
        512 + MAX_TRUNCATION_NOTICE_BYTES
    )
    saved = list(tmp_path.iterdir())
    assert len(saved) == 1
    assert saved[0].read_text(encoding="utf-8") == text


@pytest.mark.asyncio
async def test_async_response_pruning_runs_in_worker_thread(
    tmp_path,
    monkeypatch,
):
    pruning = ToolResultPruningMiddleware(
        recent_max_bytes=128,
        tool_results_dir=str(tmp_path),
    )
    response = ToolResponse(
        content=[TextBlock(type="text", text="line\n" * 100)],
    )
    calls = []

    async def fake_to_thread(func, *args):
        calls.append((func, args))
        return func(*args)

    monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)

    result = await pruning.prune_tool_response_async(response)

    assert calls == [(pruning.prune_tool_response, (response,))]
    assert TRUNCATION_NOTICE_MARKER in result.content[0].text
    assert len(list(tmp_path.iterdir())) == 1


@pytest.mark.asyncio
async def test_on_acting_offloads_current_and_historical_pruning(
    monkeypatch,
):
    pruning = ToolResultPruningMiddleware()
    response = ToolResponse(
        content=[TextBlock(type="text", text="small result")],
    )
    event_loop_thread = threading.get_ident()
    calls: list[tuple[str, int]] = []

    def prune_response(value):
        calls.append(("response", threading.get_ident()))
        return value

    def prune_history(messages):
        calls.append(("history", threading.get_ident()))

    monkeypatch.setattr(pruning, "prune_tool_response", prune_response)
    monkeypatch.setattr(pruning, "_prune_tool_results", prune_history)

    async def next_handler() -> AsyncGenerator[Any, None]:
        yield response

    agent = type(
        "AgentStub",
        (),
        {"state": type("StateStub", (), {"context": []})()},
    )()

    assert await _collect(
        pruning.on_acting(agent, {}, next_handler),
    ) == [response]
    assert [name for name, _ in calls] == ["response", "history"]
    assert all(thread_id != event_loop_thread for _, thread_id in calls)


def test_retruncate_uses_metadata(tmp_path):
    pruner = ToolResultPruner(tmp_path)
    text = "\n".join(f"line-{i}: " + "x" * 60 for i in range(100))

    first, metadata = pruner.prune_text(text, max_bytes=2000)
    info = metadata[TRUNCATION_METADATA_KEY]["0"]
    corrupted = first.replace("starts at line 1", "starts at line 999")
    second, updated = pruner.prune_text(
        corrupted,
        max_bytes=500,
        metadata=metadata,
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
    coordinator_middleware = middlewares[coordinator_index]
    assert (
        coordinator_middleware._background_result_processor
        == middlewares[pruning_index].prune_tool_response_async
    )


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


def test_context_config_disables_agentscope_duplicate_tool_result_cap():
    agent_config = types.SimpleNamespace(
        running=types.SimpleNamespace(
            light_context_config=LightContextConfig(
                strategy="scroll",
                tool_result_pruning_config=ToolResultPruningConfig(
                    enabled=True,
                    pruning_recent_msg_max_bytes=200_000,
                ),
            ),
        ),
    )

    context_config = AgentBuilder._build_context_config(agent_config)

    assert context_config.tool_result_limit == 2**63 - 1


@pytest.mark.asyncio
async def test_agentscope_does_not_resplit_pruned_tool_result():
    from agentscope.agent import Agent

    agent_config = types.SimpleNamespace(
        running=types.SimpleNamespace(
            light_context_config=LightContextConfig(
                strategy="scroll",
                tool_result_pruning_config=ToolResultPruningConfig(
                    enabled=True,
                ),
            ),
        ),
    )
    context_config = AgentBuilder._build_context_config(agent_config)

    class _TokenModel:
        async def count_tokens(self, *args, **kwargs):
            return 60_000

    shim = types.SimpleNamespace(
        name="agent",
        model=_TokenModel(),
        context_config=context_config,
    )
    result = ToolResultBlock(
        id="call-large",
        name="execute_shell_command",
        output=[TextBlock(text="already byte-bounded")],
        metadata={TRUNCATION_METADATA_KEY: {"0": {"file_path": "saved"}}},
    )

    reserved, offloaded = await Agent._split_tool_result_for_compression(
        shim,
        result,
    )

    assert reserved is result
    assert offloaded is None
    assert reserved.metadata == result.metadata


def test_context_config_keeps_agentscope_cap_when_pruning_is_disabled():
    from agentscope.agent import ContextConfig

    agent_config = types.SimpleNamespace(
        running=types.SimpleNamespace(
            light_context_config=LightContextConfig(
                strategy="scroll",
                tool_result_pruning_config=ToolResultPruningConfig(
                    enabled=False,
                ),
            ),
        ),
    )

    context_config = AgentBuilder._build_context_config(agent_config)

    assert (
        context_config.tool_result_limit
        == ContextConfig.model_fields["tool_result_limit"].default
    )


def test_explicit_legacy_scroll_tool_cap_warns_once_and_is_not_saved(
    caplog,
    monkeypatch,
):
    import qwenpaw.config.config as config_module

    monkeypatch.setattr(config_module, "_legacy_scroll_tool_cap_warned", False)
    with caplog.at_level(logging.WARNING, logger="qwenpaw.config.config"):
        config = LightContextConfig(
            strategy="scroll",
            scroll_config={"tool_output_token_cap": 1200},
        )
        LightContextConfig(
            strategy="scroll",
            scroll_config={"tool_output_token_cap": 1200},
        )

    assert "tool_output_token_cap is deprecated and ignored" in caplog.text
    assert "pruning_recent_msg_max_bytes" in caplog.text
    assert "bytes, not tokens" in caplog.text
    assert caplog.text.count("tool_output_token_cap is deprecated") == 1
    assert "tool_output_token_cap" not in config.model_dump()["scroll_config"]


def test_default_legacy_scroll_tool_cap_does_not_warn(caplog):
    with caplog.at_level(logging.WARNING, logger="qwenpaw.config.config"):
        LightContextConfig(strategy="scroll")

    assert "tool_output_token_cap is deprecated and ignored" not in caplog.text


def test_scroll_pruning_disabled_leaves_current_result_unbounded(tmp_path):
    agent_config = types.SimpleNamespace(
        id="agent-1",
        running=types.SimpleNamespace(
            light_context_config=LightContextConfig(
                strategy="scroll",
                tool_result_pruning_config=ToolResultPruningConfig(
                    enabled=False,
                ),
            ),
        ),
    )
    ctx = types.SimpleNamespace(
        app_services=types.SimpleNamespace(tool_coordinator=ToolCoordinator()),
        workspace=types.SimpleNamespace(workspace_dir=str(tmp_path)),
    )
    middlewares = AgentBuilder._build_middlewares(ctx, agent_config)
    pruning = next(
        middleware
        for middleware in middlewares
        if isinstance(middleware, ToolResultPruningMiddleware)
    )
    text = "line\n" * 20_000
    response = ToolResponse(content=[TextBlock(text=text)])

    result = pruning.prune_tool_response(response)

    assert result.content[0].text == text
    assert TRUNCATION_NOTICE_MARKER not in result.content[0].text
    assert not list((tmp_path / "tool_results").glob("*"))
