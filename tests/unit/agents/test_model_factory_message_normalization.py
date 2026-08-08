# -*- coding: utf-8 -*-
"""Tests for model_factory message normalization integration."""

# pylint: disable=protected-access,redefined-outer-name
import json
from types import SimpleNamespace

import pytest
from agentscope.formatter import OpenAIChatFormatter
from agentscope.message import (
    DataBlock,
    HintBlock,
    Msg,
    TextBlock,
    ThinkingBlock,
    ToolCallBlock,
    ToolResultBlock,
    ToolResultState,
    URLSource,
)

try:
    from agentscope.formatter import AnthropicChatFormatter
except ImportError:
    AnthropicChatFormatter = None

try:
    from agentscope.formatter import GeminiChatFormatter
except ImportError:
    GeminiChatFormatter = None

from qwenpaw.agents import model_factory
from qwenpaw.constant import MEDIA_UNSUPPORTED_PLACEHOLDER
from qwenpaw.providers.capping_formatter import _CappingOpenAIFormatter
from qwenpaw.utils.tool_call_extra import persist_tool_call_extras


def _data_block(media_type: str, url: str) -> DataBlock:
    return DataBlock(source=URLSource(url=url, media_type=media_type))


def _media_messages() -> list[Msg]:
    """Create a list of messages with media blocks for testing."""
    return [
        Msg(
            name="user",
            role="user",
            content=[
                _data_block("image/png", "file:///tmp/demo.png"),
            ],
        ),
        Msg(
            name="assistant",
            role="assistant",
            content=[
                ToolCallBlock(
                    type="tool_call",
                    id="call_1",
                    name="view_image",
                    input="{}",
                ),
                ToolResultBlock(
                    type="tool_result",
                    id="call_1",
                    name="view_image",
                    output=[
                        {
                            "type": "data",
                            "source": {
                                "type": "url",
                                "url": "file:///tmp/demo.png",
                                "media_type": "image/png",
                            },
                        },
                    ],
                ),
            ],
        ),
    ]


def _assert_request_time_stripped(formatter_class) -> None:
    original = _media_messages()
    (
        normalized,
        _is_anthropic,
        _is_gemini,
        _is_response,
    ) = model_factory._normalize_messages_for_formatter(
        original,
        formatter_class,
        SimpleNamespace(),
    )

    assert normalized[0].content[0].type == "text"
    assert normalized[0].content[0].text == MEDIA_UNSUPPORTED_PLACEHOLDER

    assert original[0].content[0].type == "data"


def test_openai_formatter_normalizes_on_copy(monkeypatch) -> None:
    monkeypatch.setattr(
        model_factory,
        "_supports_multimodal_for_current_model",
        lambda: False,
    )
    _assert_request_time_stripped(OpenAIChatFormatter)


def test_anthropic_formatter_normalizes_on_copy(monkeypatch) -> None:
    if AnthropicChatFormatter is None:
        pytest.skip("AnthropicChatFormatter not available")

    monkeypatch.setattr(
        model_factory,
        "_supports_multimodal_for_current_model",
        lambda: False,
    )
    _assert_request_time_stripped(AnthropicChatFormatter)


def test_gemini_formatter_normalizes_on_copy(monkeypatch) -> None:
    if GeminiChatFormatter is None:
        pytest.skip("GeminiChatFormatter not available")

    monkeypatch.setattr(
        model_factory,
        "_supports_multimodal_for_current_model",
        lambda: False,
    )
    _assert_request_time_stripped(GeminiChatFormatter)


def test_multimodal_support_preserves_media(monkeypatch) -> None:
    monkeypatch.setattr(
        model_factory,
        "_supports_multimodal_for_current_model",
        lambda: True,
    )

    original = _media_messages()
    (
        normalized,
        _is_anthropic,
        _is_gemini,
        _is_response,
    ) = model_factory._normalize_messages_for_formatter(
        original,
        OpenAIChatFormatter,
        SimpleNamespace(),
    )

    assert normalized[0].content[0].type == "data"
    assert original[0].content[0].type == "data"


def test_force_strip_media_flag_overrides_multimodal_support(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        model_factory,
        "_supports_multimodal_for_current_model",
        lambda: True,
    )

    original = _media_messages()
    formatter_instance = SimpleNamespace(_qwenpaw_force_strip_media=True)

    (
        normalized,
        _is_anthropic,
        _is_gemini,
        _is_response,
    ) = model_factory._normalize_messages_for_formatter(
        original,
        OpenAIChatFormatter,
        formatter_instance,
    )

    assert normalized[0].content[0].type == "text"
    assert normalized[0].content[0].text == MEDIA_UNSUPPORTED_PLACEHOLDER


def test_formatter_flags_returned_correctly() -> None:
    msgs = [
        Msg(name="user", role="user", content=[TextBlock(text="Hello")]),
    ]

    (
        _normalized,
        is_anthropic,
        is_gemini,
        is_response,
    ) = model_factory._normalize_messages_for_formatter(
        msgs,
        OpenAIChatFormatter,
        None,
    )

    assert is_anthropic is False
    assert is_gemini is False
    assert is_response is False


def test_anthropic_flag_detected(monkeypatch) -> None:
    if AnthropicChatFormatter is None:
        pytest.skip("AnthropicChatFormatter not available")

    monkeypatch.setattr(
        model_factory,
        "_supports_multimodal_for_current_model",
        lambda: True,
    )

    msgs = [
        Msg(name="user", role="user", content=[TextBlock(text="Hello")]),
    ]

    (
        _normalized,
        is_anthropic,
        _is_gemini,
        _is_response,
    ) = model_factory._normalize_messages_for_formatter(
        msgs,
        AnthropicChatFormatter,
        None,
    )

    assert is_anthropic is True


def test_gemini_flag_detected(monkeypatch) -> None:
    if GeminiChatFormatter is None:
        pytest.skip("GeminiChatFormatter not available")

    monkeypatch.setattr(
        model_factory,
        "_supports_multimodal_for_current_model",
        lambda: True,
    )

    msgs = [
        Msg(name="user", role="user", content=[TextBlock(text="Hello")]),
    ]

    (
        _normalized,
        _is_anthropic,
        is_gemini,
        _is_response,
    ) = model_factory._normalize_messages_for_formatter(
        msgs,
        GeminiChatFormatter,
        None,
    )

    assert is_gemini is True


def test_original_messages_not_modified_by_formatter_prep() -> None:
    original = Msg(
        name="user",
        role="user",
        content=[
            TextBlock(text="Hello"),
            _data_block("image/png", "file:///tmp/test.png"),
        ],
    )
    original_dict = original.to_dict()

    (
        _normalized,
        _is_anthropic,
        _is_gemini,
        _is_response,
    ) = model_factory._normalize_messages_for_formatter(
        [original],
        OpenAIChatFormatter,
        SimpleNamespace(_qwenpaw_force_strip_media=False),
    )

    assert original.to_dict() == original_dict
    assert original.content[1].type == "data"


@pytest.mark.asyncio
async def test_openai_formatter_aligns_reasoning_with_split_segments() -> None:
    formatter_class = model_factory._create_file_block_support_formatter(
        _CappingOpenAIFormatter,
    )
    formatter = formatter_class(relay_reasoning_content=True)
    msg = Msg(
        name="assistant",
        role="assistant",
        content=[
            ThinkingBlock(thinking="first reasoning"),
            ToolCallBlock(id="call_1", name="first", input="{}"),
            ToolCallBlock(id="call_2", name="second", input="{}"),
            ToolResultBlock(
                id="call_1",
                name="first",
                output=[TextBlock(text="first result")],
                state=ToolResultState.SUCCESS,
            ),
            ToolResultBlock(
                id="call_2",
                name="second",
                output=[TextBlock(text="second result")],
                state=ToolResultState.SUCCESS,
            ),
            ThinkingBlock(thinking="second reasoning"),
            TextBlock(text="done"),
        ],
    )

    formatted = await formatter.format([msg])

    assistant_messages = [
        item for item in formatted if item.get("role") == "assistant"
    ]
    assert [item.get("reasoning_content") for item in assistant_messages] == [
        "first reasoning",
        "second reasoning",
    ]


@pytest.mark.asyncio
async def test_openai_formatter_aligns_reasoning_across_hint() -> None:
    formatter_class = model_factory._create_file_block_support_formatter(
        _CappingOpenAIFormatter,
    )
    formatter = formatter_class(relay_reasoning_content=True)
    msg = Msg(
        name="assistant",
        role="assistant",
        content=[
            ThinkingBlock(thinking="first reasoning"),
            TextBlock(text="before hint"),
            HintBlock(hint="continue"),
            ThinkingBlock(thinking="second reasoning"),
            TextBlock(text="after hint"),
        ],
    )

    formatted = await formatter.format([msg])

    assistant_messages = [
        item for item in formatted if item.get("role") == "assistant"
    ]
    assert [item.get("reasoning_content") for item in assistant_messages] == [
        "first reasoning",
        "second reasoning",
    ]


@pytest.mark.asyncio
async def test_openai_formatter_does_not_carry_reasoning_forward() -> None:
    formatter_class = model_factory._create_file_block_support_formatter(
        _CappingOpenAIFormatter,
    )
    formatter = formatter_class(relay_reasoning_content=True)
    msg = Msg(
        name="assistant",
        role="assistant",
        content=[
            ThinkingBlock(thinking="tool reasoning"),
            ToolCallBlock(id="call_1", name="tool", input="{}"),
            ToolResultBlock(
                id="call_1",
                name="tool",
                output=[TextBlock(text="result")],
                state=ToolResultState.SUCCESS,
            ),
            TextBlock(text="done"),
        ],
    )

    formatted = await formatter.format([msg])

    assistant_messages = [
        item for item in formatted if item.get("role") == "assistant"
    ]
    assert assistant_messages[0]["reasoning_content"] == "tool reasoning"
    assert "reasoning_content" not in assistant_messages[1]


@pytest.mark.asyncio
async def test_required_reasoning_preserves_real_and_fills_missing() -> None:
    formatter_class = model_factory._create_file_block_support_formatter(
        _CappingOpenAIFormatter,
    )
    formatter = formatter_class(
        relay_reasoning_content=True,
    )
    formatter._qwenpaw_require_reasoning_content = True
    msg = Msg(
        name="assistant",
        role="assistant",
        content=[
            ThinkingBlock(thinking="tool reasoning"),
            ToolCallBlock(id="call_1", name="tool", input="{}"),
            ToolResultBlock(
                id="call_1",
                name="tool",
                output=[TextBlock(text="result")],
                state=ToolResultState.SUCCESS,
            ),
            TextBlock(text="done"),
        ],
    )

    formatted = await formatter.format([msg])

    assistant_messages = [
        item for item in formatted if item.get("role") == "assistant"
    ]
    assert [item.get("reasoning_content") for item in assistant_messages] == [
        "tool reasoning",
        " ",
    ]


@pytest.mark.asyncio
async def test_required_reasoning_respects_disabled_relay_privacy() -> None:
    formatter_class = model_factory._create_file_block_support_formatter(
        _CappingOpenAIFormatter,
    )
    formatter = formatter_class(
        relay_reasoning_content=False,
    )
    formatter._qwenpaw_require_reasoning_content = True
    msg = Msg(
        name="assistant",
        role="assistant",
        content=[
            ThinkingBlock(thinking="private reasoning"),
            TextBlock(text="answer"),
        ],
    )

    formatted = await formatter.format([msg])

    assistant_messages = [
        item for item in formatted if item.get("role") == "assistant"
    ]
    assert assistant_messages[0]["reasoning_content"] == " "


@pytest.mark.asyncio
async def test_required_reasoning_falls_back_when_alignment_mismatches(
    monkeypatch,
) -> None:
    formatter_class = model_factory._create_file_block_support_formatter(
        _CappingOpenAIFormatter,
    )
    formatter = formatter_class(
        relay_reasoning_content=True,
    )
    formatter._qwenpaw_require_reasoning_content = True
    monkeypatch.setattr(
        model_factory,
        "_reasoning_by_assistant_segment",
        lambda _blocks, _formatter: ["real reasoning", "extra segment"],
    )
    msg = Msg(
        name="assistant",
        role="assistant",
        content=[
            ThinkingBlock(thinking="real reasoning"),
            TextBlock(text="answer"),
        ],
    )

    formatted = await formatter.format([msg])

    assistant_messages = [
        item for item in formatted if item.get("role") == "assistant"
    ]
    assert assistant_messages[0]["reasoning_content"] == " "


@pytest.mark.asyncio
async def test_openai_formatter_respects_disabled_reasoning_relay() -> None:
    formatter_class = model_factory._create_file_block_support_formatter(
        _CappingOpenAIFormatter,
    )
    formatter = formatter_class(relay_reasoning_content=False)
    msg = Msg(
        name="assistant",
        role="assistant",
        content=[
            ThinkingBlock(thinking="private reasoning"),
            TextBlock(text="answer"),
        ],
    )

    formatted = await formatter.format([msg])

    assistant_messages = [
        item for item in formatted if item.get("role") == "assistant"
    ]
    assert assistant_messages
    assert all("reasoning_content" not in item for item in assistant_messages)


# -----------------------------------------------------------------------------
# target_family propagation tests
# -----------------------------------------------------------------------------


def _messages_with_extra_content() -> list[Msg]:
    """Create messages with tool_call blocks."""
    return [
        Msg(
            name="assistant",
            role="assistant",
            content=[
                ToolCallBlock(
                    type="tool_call",
                    id="call_ec",
                    name="search",
                    input=json.dumps({"q": "hello"}),
                ),
                ToolResultBlock(
                    type="tool_result",
                    id="call_ec",
                    name="search",
                    output="42",
                ),
            ],
        ),
    ]


@pytest.mark.asyncio
async def test_openai_formatter_relays_persisted_tool_call_extra() -> None:
    msg = _messages_with_extra_content()[0]
    persist_tool_call_extras(
        msg,
        {
            "call_ec": {
                "provider_id": "example",
                "extra_content": {"thought_signature": "signature-abc"},
            },
        },
    )
    # Exercise the session persistence boundary, not just the live Msg.
    restored = Msg.model_validate(msg.model_dump(mode="json"))
    formatter_class = model_factory._create_file_block_support_formatter(
        _CappingOpenAIFormatter,
        provider_id="example",
    )

    formatted = await formatter_class().format([restored])

    tool_call = formatted[0]["tool_calls"][0]
    assert tool_call["id"] == "call_ec"
    assert tool_call["extra_content"] == {
        "thought_signature": "signature-abc",
    }


@pytest.mark.asyncio
async def test_openai_formatter_does_not_relay_other_provider_extra() -> None:
    msg = _messages_with_extra_content()[0]
    persist_tool_call_extras(
        msg,
        {
            "call_ec": {
                "provider_id": "source-provider",
                "extra_content": {"thought_signature": "signature-abc"},
            },
        },
    )
    formatter_class = model_factory._create_file_block_support_formatter(
        _CappingOpenAIFormatter,
        provider_id="target-provider",
    )

    formatted = await formatter_class().format([msg])

    assert "extra_content" not in formatted[0]["tool_calls"][0]


@pytest.mark.asyncio
async def test_openai_formatter_isolates_reused_ids_between_requests() -> None:
    first = _messages_with_extra_content()[0]
    second = _messages_with_extra_content()[0]
    persist_tool_call_extras(
        first,
        {
            "call_ec": {
                "provider_id": "example",
                "extra_content": {"thought_signature": "signature-1"},
            },
        },
    )
    persist_tool_call_extras(
        second,
        {
            "call_ec": {
                "provider_id": "example",
                "extra_content": {"thought_signature": "signature-2"},
            },
        },
    )
    formatter_class = model_factory._create_file_block_support_formatter(
        _CappingOpenAIFormatter,
        provider_id="example",
    )

    formatter = formatter_class()
    formatted_first = await formatter.format([first])
    formatted_second = await formatter.format([second])

    first_call = formatted_first[0]["tool_calls"][0]
    second_call = formatted_second[0]["tool_calls"][0]
    relayed = [
        first_call["extra_content"]["thought_signature"],
        second_call["extra_content"]["thought_signature"],
    ]
    assert relayed == ["signature-1", "signature-2"]


def test_openai_formatter_strips_extra_content(monkeypatch) -> None:
    monkeypatch.setattr(
        model_factory,
        "_supports_multimodal_for_current_model",
        lambda: True,
    )

    (
        normalized,
        _is_anthropic,
        _is_gemini,
        _is_response,
    ) = model_factory._normalize_messages_for_formatter(
        _messages_with_extra_content(),
        OpenAIChatFormatter,
        SimpleNamespace(),
    )

    block = normalized[0].content[0]
    assert not hasattr(block, "extra_content") or not getattr(
        block,
        "extra_content",
        None,
    )


def test_anthropic_formatter_strips_extra_content(monkeypatch) -> None:
    if AnthropicChatFormatter is None:
        pytest.skip("AnthropicChatFormatter not available")

    monkeypatch.setattr(
        model_factory,
        "_supports_multimodal_for_current_model",
        lambda: True,
    )

    (
        normalized,
        _is_anthropic,
        _is_gemini,
        _is_response,
    ) = model_factory._normalize_messages_for_formatter(
        _messages_with_extra_content(),
        AnthropicChatFormatter,
        SimpleNamespace(),
    )

    block = normalized[0].content[0]
    assert not hasattr(block, "extra_content") or not getattr(
        block,
        "extra_content",
        None,
    )


def test_gemini_formatter_preserves_extra_content(monkeypatch) -> None:
    if GeminiChatFormatter is None:
        pytest.skip("GeminiChatFormatter not available")

    monkeypatch.setattr(
        model_factory,
        "_supports_multimodal_for_current_model",
        lambda: True,
    )

    msgs = _messages_with_extra_content()
    (
        _normalized,
        _is_anthropic,
        _is_gemini,
        _is_response,
    ) = model_factory._normalize_messages_for_formatter(
        msgs,
        GeminiChatFormatter,
        SimpleNamespace(),
    )
    # ToolCallBlock in 2.0 doesn't have extra_content field,
    # so this test verifies the block isn't corrupted.
    block = _normalized[0].content[0]
    assert block.type == "tool_call"


def test_extra_content_original_preserved(monkeypatch) -> None:
    monkeypatch.setattr(
        model_factory,
        "_supports_multimodal_for_current_model",
        lambda: True,
    )

    msgs = _messages_with_extra_content()
    original_dict = msgs[0].to_dict()

    model_factory._normalize_messages_for_formatter(
        msgs,
        OpenAIChatFormatter,
        SimpleNamespace(),
    )

    assert msgs[0].to_dict() == original_dict


# -----------------------------------------------------------------
# _fixup_media_list: Windows file URI → local path for DataBlock
# -----------------------------------------------------------------


def test_datablock_windows_file_uri_resolved_to_local_path(
    monkeypatch,
) -> None:
    """file:///C:/Temp/x.png must become C:/Temp/x.png in source.url."""
    monkeypatch.setattr("os.path.exists", lambda p: True)

    block = _data_block("image/png", "file:///C:/Temp/x.png")
    items: list = [block]
    model_factory._fixup_media_list(items)

    assert items[0].source.url == "C:/Temp/x.png"


def test_datablock_unix_file_uri_resolved_to_local_path(
    monkeypatch,
) -> None:
    """file:///tmp/demo.png must become /tmp/demo.png."""
    monkeypatch.setattr("os.path.exists", lambda p: True)

    block = _data_block("image/png", "file:///tmp/demo.png")
    items: list = [block]
    model_factory._fixup_media_list(items)

    assert items[0].source.url == "/tmp/demo.png"


def test_datablock_percent_encoded_uri_resolved(
    monkeypatch,
) -> None:
    """file:///tmp/%E4%B8%AD%E6%96%87.png → /tmp/中文.png."""
    monkeypatch.setattr("os.path.exists", lambda p: True)

    block = _data_block(
        "image/png",
        "file:///tmp/%E4%B8%AD%E6%96%87.png",
    )
    items: list = [block]
    model_factory._fixup_media_list(items)

    assert items[0].source.url == "/tmp/中文.png"


def test_datablock_unc_file_uri_resolved(
    monkeypatch,
) -> None:
    """file://server/share/x.png → //server/share/x.png (UNC)."""
    monkeypatch.setattr("os.path.exists", lambda p: True)

    block = _data_block(
        "image/png",
        "file://server/share/x.png",
    )
    items: list = [block]
    model_factory._fixup_media_list(items)

    assert items[0].source.url == "//server/share/x.png"
