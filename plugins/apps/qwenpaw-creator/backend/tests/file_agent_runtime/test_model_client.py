# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=protected-access,use-implicit-booleaness-not-comparison
from __future__ import annotations

import asyncio
import json

from agentscope.message import (
    TextBlock,
    ThinkingBlock,
    ToolCallBlock,
    ToolResultBlock,
    ToolResultState,
)
from agentscope.model import DashScopeChatModel
from agentscope.model._model_response import ChatResponse
import pytest

from services.file_agent_runtime.model_client import (
    MAX_RATE_LIMIT_RETRIES,
    AgentModelError,
    AgentStreamCallbackError,
    AgentStreamCallbackPassthrough,
    AgentModelTurn,
    AgentScopeAgentChatClient,
    AgentScopeVlmChatClient,
    AgentToolCall,
    CallbackAgentChatClient,
    RateLimitExhaustedError,
    RateLimitRetryNotice,
    records_to_agentscope_messages,
)
from services.file_agent_runtime import model_client

pytestmark = pytest.mark.unit


def _configure_text_model(
    monkeypatch: pytest.MonkeyPatch,
    *,
    protocol: str = "",
) -> None:
    monkeypatch.setattr(
        model_client.model_config,
        "get_text_api_key",
        lambda: "test-api-key",
    )
    monkeypatch.setattr(
        model_client.model_config,
        "get_text_base_url",
        lambda: "https://model.example/v1",
    )
    monkeypatch.setattr(
        model_client.model_config,
        "get_text_model_name",
        lambda: "qwen3.7-plus",
    )
    monkeypatch.setattr(
        model_client.model_config,
        "get_text_protocol",
        lambda: protocol,
    )


def _tools() -> list[dict[str, object]]:
    return [
        {
            "type": "function",
            "function": {
                "name": "read_project",
                "parameters": {
                    "type": "object",
                    "properties": {"projectId": {"type": "string"}},
                    "required": ["projectId"],
                },
            },
        },
    ]


def test_default_client_constructs_real_agentscope_dashscope_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_text_model(monkeypatch)

    configured = AgentScopeAgentChatClient()._configured_model()

    assert isinstance(configured, DashScopeChatModel)


def test_anthropic_protocol_constructs_anthropic_chat_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agentscope.model import AnthropicChatModel

    _configure_text_model(
        monkeypatch,
        protocol="Anthropic Claude",
    )
    monkeypatch.setattr(
        model_client.model_config,
        "get_text_base_url",
        lambda: "https://api.anthropic.com",
    )

    configured = AgentScopeAgentChatClient()._configured_model()

    assert isinstance(configured, AnthropicChatModel)


def test_minimax_protocol_constructs_anthropic_chat_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agentscope.model import AnthropicChatModel

    _configure_text_model(
        monkeypatch,
        protocol="MiniMax",
    )
    monkeypatch.setattr(
        model_client.model_config,
        "get_text_base_url",
        lambda: "https://api.minimaxi.com/anthropic",
    )

    configured = AgentScopeAgentChatClient()._configured_model()

    assert isinstance(configured, AnthropicChatModel)


def test_gemini_protocol_constructs_gemini_chat_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agentscope.model import GeminiChatModel

    _configure_text_model(
        monkeypatch,
        protocol="Google Gemini",
    )
    monkeypatch.setattr(
        model_client.model_config,
        "get_text_base_url",
        lambda: "https://generativelanguage.googleapis.com",
    )

    configured = AgentScopeAgentChatClient()._configured_model()

    assert isinstance(configured, GeminiChatModel)


def test_history_is_rehydrated_as_agentscope_tool_blocks() -> None:
    messages = records_to_agentscope_messages(
        [
            {"role": "system", "content": "schema"},
            {"role": "user", "content": "读取项目"},
            {
                "role": "assistant",
                "content": "先读取。",
                "tool_calls": [
                    {
                        "id": "call-read-1",
                        "type": "function",
                        "function": {
                            "name": "read_project",
                            "arguments": '{"projectId":"project-1"}',
                        },
                    },
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call-read-1",
                "name": "read_project",
                "content": '{"ok":false}',
                "failed": True,
            },
        ],
    )

    assert messages[0].role == "system"
    assert messages[1].role == "user"
    assert messages[2].role == "assistant"
    call = messages[2].content[-1]
    assert isinstance(call, ToolCallBlock)
    assert call.id == "call-read-1"
    assert call.name == "read_project"
    assert json.loads(call.input) == {"projectId": "project-1"}
    assert messages[3].role == "assistant"
    result = messages[3].content[0]
    assert isinstance(result, ToolResultBlock)
    assert result.id == call.id
    assert result.name == call.name
    assert result.output == '{"ok":false}'
    assert result.state == ToolResultState.ERROR.value


def test_vlm_anthropic_protocol_constructs_anthropic_chat_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agentscope.model import AnthropicChatModel

    monkeypatch.setattr(
        model_client.model_config,
        "get_vlm_api_key",
        lambda: "vlm-key",
    )
    monkeypatch.setattr(
        model_client.model_config,
        "get_vlm_base_url",
        lambda: "https://api.anthropic.com",
    )
    monkeypatch.setattr(
        model_client.model_config,
        "get_vlm_model_name",
        lambda: "claude-sonnet-4-20250514",
    )
    monkeypatch.setattr(
        model_client.model_config,
        "get_vlm_timeout_seconds",
        lambda: 180,
    )
    monkeypatch.setattr(
        model_client.model_config,
        "get_vlm_protocol",
        lambda: "Anthropic Claude",
    )

    configured = AgentScopeVlmChatClient()._configured_model()

    assert isinstance(configured, AnthropicChatModel)


def test_agentscope_client_streams_native_blocks_and_raw_argument_deltas() -> (
    None
):
    class StreamingAgentScopeModel:
        model = "qwen3.7-plus"

        def __init__(self) -> None:
            self.messages = None
            self.tools = None

        async def __call__(self, messages, *, tools=None):
            self.messages = messages
            self.tools = tools

            async def chunks():
                yield ChatResponse(
                    id="response-stream-1",
                    content=[
                        ThinkingBlock(thinking="先"),
                        TextBlock(text="项目"),
                        ToolCallBlock(
                            id="call-read-1",
                            name="read_project",
                            input='{"project',
                        ),
                    ],
                    is_last=False,
                )
                yield ChatResponse(
                    id="response-stream-1",
                    content=[
                        ThinkingBlock(thinking="分析"),
                        TextBlock(text="已读取"),
                        ToolCallBlock(
                            id="call-read-1",
                            name="read_project",
                            input='Id":"project-1"}',
                        ),
                    ],
                    is_last=False,
                )
                yield ChatResponse(
                    id="response-stream-1",
                    content=[
                        ThinkingBlock(thinking="先分析"),
                        TextBlock(text="项目已读取"),
                        ToolCallBlock(
                            id="call-read-1",
                            name="read_project",
                            input='{"projectId":"project-1"}',
                        ),
                    ],
                    is_last=True,
                )

            return chunks()

    text_deltas: list[str] = []
    thinking_deltas: list[str] = []
    tool_deltas: list[tuple[str, str, str]] = []

    async def on_text_delta(delta: str) -> None:
        text_deltas.append(delta)

    async def on_thinking_delta(delta: str) -> None:
        thinking_deltas.append(delta)

    async def on_tool_call_delta(
        call_id: str,
        name: str,
        arguments_delta: str,
    ) -> None:
        tool_deltas.append((call_id, name, arguments_delta))

    async def scenario():
        provider = StreamingAgentScopeModel()
        client = AgentScopeAgentChatClient(provider)  # type: ignore[arg-type]
        turn = await client.complete(
            messages=[
                {"role": "system", "content": "schema"},
                {"role": "user", "content": "读取项目"},
            ],
            tools=_tools(),
            on_text_delta=on_text_delta,
            on_thinking_delta=on_thinking_delta,
            on_tool_call_delta=on_tool_call_delta,
        )
        return provider, turn

    provider, turn = asyncio.run(scenario())

    assert provider.messages is not None
    assert [message.role for message in provider.messages] == [
        "system",
        "user",
    ]
    assert provider.tools == _tools()
    assert turn == AgentModelTurn(
        content="项目已读取",
        thinking="先分析",
        tool_calls=(
            AgentToolCall(
                call_id="call-read-1",
                name="read_project",
                arguments={"projectId": "project-1"},
            ),
        ),
        provider_message_id="response-stream-1",
    )
    assert text_deltas == ["项目", "已读取"]
    assert thinking_deltas == ["先", "分析"]
    assert tool_deltas == [
        ("call-read-1", "read_project", '{"project'),
        ("call-read-1", "read_project", 'Id":"project-1"}'),
    ]
    assert turn.tool_calls[0].raw_arguments == '{"projectId":"project-1"}'
    assert turn.tool_calls[0].raw_arguments_bytes == 25
    assert turn.tool_calls[0].provider_chunk_count == 2
    assert turn.finish_reason == "completed"


def test_agentscope_client_repairs_truncated_native_tool_argument_json() -> (
    None
):
    class MalformedToolArgumentsModel:
        model = "qwen3.7-plus"

        async def __call__(self, messages, *, tools=None):
            del messages
            assert tools
            return ChatResponse(
                id="response-repaired-tool",
                content=[
                    ToolCallBlock(
                        id="call-read-repaired",
                        name="read_project",
                        input='{"projectId":"project-1","baseEtag":"etag-truncated',
                    ),
                ],
                is_last=True,
            )

    async def scenario() -> AgentModelTurn:
        client = AgentScopeAgentChatClient(
            MalformedToolArgumentsModel(),  # type: ignore[arg-type]
        )
        return await client.complete(
            messages=[{"role": "user", "content": "读取项目"}],
            tools=_tools(),
        )

    turn = asyncio.run(scenario())

    assert turn.tool_calls == (
        AgentToolCall(
            call_id="call-read-repaired",
            name="read_project",
            arguments={
                "projectId": "project-1",
                "baseEtag": "etag-truncated",
            },
        ),
    )
    repaired_call = turn.tool_calls[0]
    assert repaired_call.arguments_repaired is True
    assert repaired_call.raw_arguments_bytes == len(
        '{"projectId":"project-1","baseEtag":"etag-truncated'.encode(
            "utf-8",
        ),
    )
    assert repaired_call.strict_json_error is not None


def _final_tool_call_model(raw_input: str):
    class FinalToolCallModel:
        model = "qwen3.7-plus"

        async def __call__(self, messages, *, tools=None):
            async def chunks():
                yield ChatResponse(
                    id="response-broken-1",
                    content=[
                        ToolCallBlock(
                            id="call-jq-1",
                            name="read_project",
                            input=raw_input,
                        ),
                    ],
                    is_last=True,
                )

            return chunks()

    return FinalToolCallModel()


def test_unrecoverable_tool_arguments_degrade_to_parse_error() -> None:
    async def scenario():
        client = AgentScopeAgentChatClient(
            _final_tool_call_model('"oops'),  # type: ignore[arg-type]
        )
        return await client.complete(messages=[], tools=_tools())

    turn = asyncio.run(scenario())
    call = turn.tool_calls[0]
    assert call.arguments == {}
    assert call.parse_error is not None
    assert "无法自动修复" in call.parse_error
    assert "oops" in call.parse_error


def test_agentscope_client_preserves_stream_control_exceptions() -> None:
    class StreamingAgentScopeModel:
        model = "qwen3.7-plus"

        async def __call__(self, _messages, *, tools=None):
            del tools

            async def chunks():
                yield ChatResponse(
                    id="response-control",
                    content=[TextBlock(text="部分输出")],
                    is_last=False,
                )
                yield ChatResponse(
                    id="response-control",
                    content=[TextBlock(text="完整输出")],
                    is_last=True,
                )

            return chunks()

    class StopStreaming(AgentStreamCallbackPassthrough):
        pass

    async def stop(_delta: str) -> None:
        raise StopStreaming("run revoked")

    async def scenario() -> None:
        client = AgentScopeAgentChatClient(StreamingAgentScopeModel())  # type: ignore[arg-type]
        with pytest.raises(StopStreaming, match="run revoked"):
            await client.complete(
                messages=[{"role": "user", "content": "开始"}],
                tools=[],
                on_text_delta=stop,
            )

    asyncio.run(scenario())


def test_agentscope_client_returns_unknown_native_tool_for_model_correction() -> (
    None
):
    class UnknownToolModel:
        model = "qwen3.7-plus"

        async def __call__(self, messages, *, tools=None):
            del messages
            assert tools
            return ChatResponse(
                id="response-unknown-tool",
                content=[
                    ToolCallBlock(
                        id="call-unknown",
                        name="invented_tool",
                        input='{"projectId":"project-1"}',
                    ),
                ],
                is_last=True,
            )

    async def scenario():
        client = AgentScopeAgentChatClient(  # type: ignore[arg-type]
            UnknownToolModel(),
        )
        return await client.complete(
            messages=[{"role": "user", "content": "读取"}],
            tools=_tools(),
        )

    turn = asyncio.run(scenario())
    assert len(turn.tool_calls) == 1
    assert turn.tool_calls[0].name == "invented_tool"
    assert turn.tool_calls[0].arguments == {"projectId": "project-1"}


@pytest.mark.parametrize(
    "markup",
    [
        "<function=glob_search><parameter=pattern>story/outline.md</parameter></function>",
        '<tool_call>{"name":"read_project","arguments":{}}</tool_call>',
    ],
)
def test_agentscope_client_rejects_textual_tool_markup_before_text_callback(
    markup: str,
) -> None:
    class TextualToolModel:
        model = "qwen3.7-plus"

        def __init__(self) -> None:
            self.calls = 0

        async def __call__(self, messages, *, tools=None):
            del messages
            assert tools
            self.calls += 1
            return ChatResponse(
                id="response-text-tool",
                content=[TextBlock(text=markup)],
                is_last=True,
            )

    text_deltas: list[str] = []

    async def collect(delta: str) -> None:
        text_deltas.append(delta)

    async def scenario() -> TextualToolModel:
        provider = TextualToolModel()
        client = AgentScopeAgentChatClient(provider)  # type: ignore[arg-type]
        with pytest.raises(AgentModelError, match="ToolCallBlock"):
            await client.complete(
                messages=[{"role": "user", "content": "读取"}],
                tools=_tools(),
                on_text_delta=collect,
            )
        return provider

    provider = asyncio.run(scenario())
    # Markup degradation is stochastic, so the turn is retried before the
    # run is failed: original attempt plus four retries.
    assert provider.calls == 5
    assert text_deltas == []


def test_callback_client_keeps_stream_callback_failures_outside_model_errors() -> (
    None
):
    async def callback(_messages, _tools) -> AgentModelTurn:
        return AgentModelTurn(content="即将持久化")

    async def fail_persistence(_delta: str) -> None:
        raise OSError("runtime lock timeout")

    async def scenario() -> None:
        with pytest.raises(AgentStreamCallbackError) as raised:
            await CallbackAgentChatClient(callback).complete(
                messages=[{"role": "user", "content": "开始"}],
                tools=[],
                on_text_delta=fail_persistence,
            )
        assert isinstance(raised.value.cause, OSError)
        assert str(raised.value.cause) == "runtime lock timeout"

    asyncio.run(scenario())


def test_agentscope_client_retries_rate_limited_turns_until_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        model_client,
        "_rate_limit_retry_delay",
        lambda _attempt: 0.0,
    )

    class ThrottledModel:
        model = "qwen3.7-plus"

        def __init__(self) -> None:
            self.calls = 0

        async def __call__(self, messages, *, tools=None):
            del messages, tools
            self.calls += 1
            raise RuntimeError(
                "<429> Throttling.RateQuota: Requests rate limit exceeded",
            )

    notices: list[RateLimitRetryNotice] = []

    async def on_retry(notice: RateLimitRetryNotice) -> None:
        notices.append(notice)

    async def scenario():
        provider = ThrottledModel()
        client = AgentScopeAgentChatClient(provider)  # type: ignore[arg-type]
        with pytest.raises(RateLimitExhaustedError) as raised:
            await client.complete(
                messages=[{"role": "user", "content": "开始"}],
                tools=_tools(),
                on_rate_limit_retry=on_retry,
            )
        return provider, raised.value

    provider, error = asyncio.run(scenario())

    # One original attempt plus every retry, then the run is given up on.
    assert provider.calls == MAX_RATE_LIMIT_RETRIES + 1
    assert error.retries == MAX_RATE_LIMIT_RETRIES
    assert [(notice.attempt, notice.max_attempts) for notice in notices] == [
        (attempt, MAX_RATE_LIMIT_RETRIES) for attempt in range(1, 6)
    ]


def test_agentscope_client_recovers_after_rate_limited_turns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        model_client,
        "_rate_limit_retry_delay",
        lambda _attempt: 0.0,
    )

    class ThrottledThenHealthyModel:
        model = "qwen3.7-plus"

        def __init__(self) -> None:
            self.calls = 0

        async def __call__(self, messages, *, tools=None):
            del messages, tools
            self.calls += 1
            if self.calls <= 2:
                raise RuntimeError("429 Too Many Requests")
            return ChatResponse(
                id="response-rate-limit-recover",
                content=[TextBlock(text="恢复完成")],
                is_last=True,
            )

    notices: list[RateLimitRetryNotice] = []

    async def on_retry(notice: RateLimitRetryNotice) -> None:
        notices.append(notice)

    async def scenario():
        provider = ThrottledThenHealthyModel()
        client = AgentScopeAgentChatClient(provider)  # type: ignore[arg-type]
        turn = await client.complete(
            messages=[{"role": "user", "content": "开始"}],
            tools=_tools(),
            on_rate_limit_retry=on_retry,
        )
        return provider, turn

    provider, turn = asyncio.run(scenario())

    assert provider.calls == 3
    assert turn.content == "恢复完成"
    assert [notice.attempt for notice in notices] == [1, 2]
