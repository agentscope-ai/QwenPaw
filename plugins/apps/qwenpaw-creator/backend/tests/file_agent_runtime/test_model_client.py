# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=protected-access,use-implicit-booleaness-not-comparison
from __future__ import annotations

import asyncio
import json

from agentscope.message import (
    DataBlock,
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
    AgentModelError,
    AgentStreamCallbackError,
    AgentStreamCallbackPassthrough,
    AgentModelTurn,
    AgentScopeAgentChatClient,
    AgentScopeVlmChatClient,
    AgentToolCall,
    CallbackAgentChatClient,
    records_to_agentscope_messages,
)
from services.file_agent_runtime import model_client


pytestmark = pytest.mark.unit


def _configure_text_model(monkeypatch: pytest.MonkeyPatch) -> None:
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


def test_user_native_media_is_rehydrated_as_agentscope_data_blocks() -> None:
    messages = records_to_agentscope_messages(
        [
            {"role": "system", "content": "schema"},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "理解全部素材"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "https://cdn.example.com/a.png"},
                    },
                    {
                        "type": "video_url",
                        "video_url": {
                            "url": "https://cdn.example.com/b.mp4",
                            "fps": 0.1,
                        },
                    },
                ],
            },
        ],
    )

    assert isinstance(messages[1].content[0], TextBlock)
    assert [
        str(block.source.url)
        for block in messages[1].content[1:]
        if isinstance(block, DataBlock)
    ] == [
        "https://cdn.example.com/a.png",
        "https://cdn.example.com/b.mp4",
    ]


def test_vlm_client_uses_creator_vlm_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        model_client.model_config,
        "get_vlm_api_key",
        lambda: "vlm-key",
    )
    monkeypatch.setattr(
        model_client.model_config,
        "get_vlm_base_url",
        lambda: "https://vlm.example/v1",
    )
    monkeypatch.setattr(
        model_client.model_config,
        "get_vlm_model_name",
        lambda: "qwen3.7-plus",
    )
    monkeypatch.setattr(
        model_client.model_config,
        "get_vlm_timeout_seconds",
        lambda: 180,
    )

    configured = AgentScopeVlmChatClient()._configured_model()

    assert isinstance(configured, DashScopeChatModel)


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


def test_agentscope_client_degrades_repaired_non_object_tool_arguments() -> (
    None
):
    class NonObjectToolArgumentsModel:
        model = "qwen3.7-plus"

        async def __call__(self, messages, *, tools=None):
            del messages
            assert tools
            return ChatResponse(
                id="response-non-object-tool",
                content=[
                    ToolCallBlock(
                        id="call-read-non-object",
                        name="read_project",
                        input='["project-1",]',
                    ),
                ],
                is_last=True,
            )

    async def scenario() -> AgentModelTurn:
        client = AgentScopeAgentChatClient(
            NonObjectToolArgumentsModel(),  # type: ignore[arg-type]
        )
        return await client.complete(
            messages=[{"role": "user", "content": "读取项目"}],
            tools=_tools(),
        )

    turn = asyncio.run(scenario())

    call = turn.tool_calls[0]
    assert call.arguments == {}
    assert call.parse_error is not None
    assert "无法自动修复" in call.parse_error


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


def test_truncated_tool_arguments_are_repaired_into_an_object() -> None:
    truncated = (
        '{"projectId":"project-1","jsonArgs":{"elements":{"e1":{"name":"a'
    )

    async def scenario():
        client = AgentScopeAgentChatClient(
            _final_tool_call_model(truncated),  # type: ignore[arg-type]
        )
        return await client.complete(messages=[], tools=_tools())

    turn = asyncio.run(scenario())
    call = turn.tool_calls[0]
    assert call.parse_error is None
    assert call.arguments == {
        "projectId": "project-1",
        "jsonArgs": {"elements": {"e1": {"name": "a"}}},
    }


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


def test_default_client_does_not_constrain_max_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_text_model(monkeypatch)
    client = AgentScopeAgentChatClient()
    assert client.max_tokens is None
    configured = client._configured_model()
    assert configured.parameters.max_tokens is None


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


def test_agentscope_client_retries_one_empty_provider_turn() -> None:
    class EmptyThenTextModel:
        model = "qwen3.7-plus"

        def __init__(self) -> None:
            self.calls = 0

        async def __call__(self, messages, *, tools=None):
            del messages, tools
            self.calls += 1
            if self.calls == 1:
                return ChatResponse(
                    id="response-empty",
                    content=[ThinkingBlock(thinking="分析完成")],
                    is_last=True,
                )
            return ChatResponse(
                id="response-retry",
                content=[TextBlock(text="素材理解已写入")],
                is_last=True,
            )

    async def scenario():
        provider = EmptyThenTextModel()
        client = AgentScopeAgentChatClient(provider)  # type: ignore[arg-type]
        turn = await client.complete(
            messages=[{"role": "user", "content": "理解素材"}],
            tools=_tools(),
        )
        return provider, turn

    provider, turn = asyncio.run(scenario())

    assert provider.calls == 2
    assert turn.content == "素材理解已写入"
    assert turn.provider_message_id == "response-retry"


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

        async def __call__(self, messages, *, tools=None):
            del messages
            assert tools
            return ChatResponse(
                id="response-text-tool",
                content=[TextBlock(text=markup)],
                is_last=True,
            )

    text_deltas: list[str] = []

    async def collect(delta: str) -> None:
        text_deltas.append(delta)

    async def scenario() -> None:
        client = AgentScopeAgentChatClient(TextualToolModel())  # type: ignore[arg-type]
        with pytest.raises(AgentModelError, match="ToolCallBlock"):
            await client.complete(
                messages=[{"role": "user", "content": "读取"}],
                tools=_tools(),
                on_text_delta=collect,
            )

    asyncio.run(scenario())
    assert text_deltas == []


def test_agentscope_client_withholds_split_textual_tool_markup() -> None:
    class SplitTextualToolModel:
        model = "qwen3.7-plus"

        async def __call__(self, messages, *, tools=None):
            del messages
            assert tools

            async def chunks():
                yield ChatResponse(
                    id="response-split-text-tool",
                    content=[TextBlock(text="先检查。<func")],
                    is_last=False,
                )
                yield ChatResponse(
                    id="response-split-text-tool",
                    content=[
                        TextBlock(
                            text="tion=glob_search><parameter=pattern>story/outline.md",
                        ),
                    ],
                    is_last=False,
                )
                yield ChatResponse(
                    id="response-split-text-tool",
                    content=[
                        TextBlock(
                            text=(
                                "先检查。<function=glob_search><parameter=pattern>"
                                "story/outline.md</parameter></function>"
                            ),
                        ),
                    ],
                    is_last=True,
                )

            return chunks()

    text_deltas: list[str] = []

    async def collect(delta: str) -> None:
        text_deltas.append(delta)

    async def scenario() -> None:
        client = AgentScopeAgentChatClient(SplitTextualToolModel())  # type: ignore[arg-type]
        with pytest.raises(
            AgentModelError,
            match="AgentScope model request failed",
        ):
            await client.complete(
                messages=[{"role": "user", "content": "读取"}],
                tools=_tools(),
                on_text_delta=collect,
            )

    asyncio.run(scenario())
    assert text_deltas == ["先检查。"]
    assert all(
        "<function" not in delta and "<parameter" not in delta
        for delta in text_deltas
    )


def test_callback_client_replays_complete_turn_through_stream_callbacks() -> (
    None
):
    callback_inputs: list[
        tuple[list[dict[str, object]], list[dict[str, object]]]
    ] = []

    async def callback(messages, tools) -> AgentModelTurn:
        callback_inputs.append(
            (
                [dict(item) for item in messages],
                [dict(item) for item in tools],
            ),
        )
        return AgentModelTurn(
            content="修改完成",
            thinking="先读取项目",
            tool_calls=(
                AgentToolCall(
                    call_id="call-read-1",
                    name="read_project",
                    arguments={"projectId": "project-1"},
                ),
            ),
            provider_message_id="callback-message-1",
        )

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

    messages = [{"role": "user", "content": "读取项目"}]
    tools = _tools()

    async def scenario() -> AgentModelTurn:
        return await CallbackAgentChatClient(callback).complete(
            messages=messages,
            tools=tools,
            on_text_delta=on_text_delta,
            on_thinking_delta=on_thinking_delta,
            on_tool_call_delta=on_tool_call_delta,
        )

    turn = asyncio.run(scenario())

    assert turn == AgentModelTurn(
        content="修改完成",
        thinking="先读取项目",
        tool_calls=(
            AgentToolCall(
                call_id="call-read-1",
                name="read_project",
                arguments={"projectId": "project-1"},
            ),
        ),
        provider_message_id="callback-message-1",
    )
    assert callback_inputs == [(messages, tools)]
    assert text_deltas == ["修改完成"]
    assert thinking_deltas == ["先读取项目"]
    assert tool_deltas == [
        ("call-read-1", "read_project", '{"projectId":"project-1"}'),
    ]


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
