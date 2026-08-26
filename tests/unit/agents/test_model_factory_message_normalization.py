# -*- coding: utf-8 -*-
"""Tests for model_factory message normalization integration."""

# pylint: disable=protected-access,redefined-outer-name,mixed-line-endings
import asyncio
import base64
import json
from io import BytesIO
import threading
from types import SimpleNamespace

import httpx
import pytest
from agentscope.formatter import OpenAIChatFormatter
from agentscope.message import (
    Base64Source,
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

from PIL import Image

from qwenpaw.agents import model_factory
from qwenpaw.constant import MEDIA_UNSUPPORTED_PLACEHOLDER
from qwenpaw.providers.capping_formatter import (
    _CappingAnthropicFormatter,
    _CappingDashScopeFormatter,
    _CappingGeminiFormatter,
    _CappingOpenAIFormatter,
)
from qwenpaw.utils.tool_call_extra import persist_tool_call_extras


def _data_block(media_type: str, url: str) -> DataBlock:
    return DataBlock(source=URLSource(url=url, media_type=media_type))


def _base64_data_block(media_type: str, content: bytes) -> DataBlock:
    return DataBlock(
        source=Base64Source(
            media_type=media_type,
            data=base64.b64encode(content).decode("ascii"),
        ),
    )


def _png_bytes(size: tuple[int, int]) -> bytes:
    output = BytesIO()
    Image.new("RGB", size, color="red").save(output, format="PNG")
    return output.getvalue()


def test_anthropic_dedup_key_uses_immutable_base64_directly() -> None:
    block = _base64_data_block("image/png", b"immutable-content")

    key = model_factory._anthropic_media_dedup_key(block.source)

    assert key == ("base64", "image/png", block.source.data)
    assert key[2] is block.source.data


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


@pytest.mark.asyncio
async def test_anthropic_dedup_uses_complete_media_content(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        model_factory,
        "_supports_multimodal_for_current_model",
        lambda: True,
    )
    formatter_class = model_factory._create_file_block_support_formatter(
        _CappingAnthropicFormatter,
    )
    formatter = formatter_class()
    first = _base64_data_block("image/png", b"version-one")
    second = _base64_data_block("image/png", b"version-two")
    msg = Msg(name="user", role="user", content=[first, second])

    formatted = await formatter.format([msg])

    content = formatted[0]["content"]
    assert [item["type"] for item in content] == ["image", "image"]
    assert formatter._qwenpaw_last_wire_media_count == 2


@pytest.mark.asyncio
async def test_anthropic_dedup_omits_identical_media(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        model_factory,
        "_supports_multimodal_for_current_model",
        lambda: True,
    )
    formatter_class = model_factory._create_file_block_support_formatter(
        _CappingAnthropicFormatter,
    )
    formatter = formatter_class()
    first = _base64_data_block("image/png", b"same-version")
    second = _base64_data_block("image/png", b"same-version")
    msg = Msg(name="user", role="user", content=[first, second])

    formatted = await formatter.format([msg])

    content = formatted[0]["content"]
    assert [item["type"] for item in content] == ["image", "text"]
    assert "omitted" in content[1]["text"]
    assert formatter._qwenpaw_last_wire_media_count == 1


@pytest.mark.asyncio
async def test_request_time_image_resize_preserves_original(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        model_factory,
        "_supports_multimodal_for_current_model",
        lambda: True,
    )
    monkeypatch.setenv("QWENPAW_MAX_IMAGE_PIXELS", "1250")
    formatter_class = model_factory._create_file_block_support_formatter(
        _CappingOpenAIFormatter,
    )
    formatter = formatter_class()
    original = _base64_data_block("image/png", _png_bytes((100, 50)))
    msg = Msg(name="user", role="user", content=[original])

    formatted = await formatter.format([msg])

    image_url = formatted[0]["content"][0]["image_url"]["url"]
    resized_data = image_url.split(",", 1)[1]
    with Image.open(BytesIO(base64.b64decode(resized_data))) as resized:
        assert resized.size == (50, 25)
    with Image.open(
        BytesIO(base64.b64decode(original.source.data)),
    ) as untouched:
        assert untouched.size == (100, 50)


@pytest.mark.asyncio
async def test_resize_failure_preserves_media_dedup_context(
    monkeypatch,
) -> None:
    monkeypatch.setenv("QWENPAW_MAX_IMAGE_PIXELS", "invalid")
    formatter_class = model_factory._create_file_block_support_formatter(
        _CappingOpenAIFormatter,
    )
    formatter = formatter_class()
    previous_context = {"existing-media"}
    outer_token = model_factory._FORMATTER_SEEN_MEDIA_KEYS.set(
        previous_context,
    )
    msg = Msg(
        name="user",
        role="user",
        content=[TextBlock(text="hello")],
    )

    try:
        with pytest.raises(
            ValueError,
            match="QWENPAW_MAX_IMAGE_PIXELS must be zero or a positive",
        ):
            await formatter.format([msg])

        assert model_factory._FORMATTER_SEEN_MEDIA_KEYS.get() is (
            previous_context
        )
    finally:
        model_factory._FORMATTER_SEEN_MEDIA_KEYS.reset(outer_token)


@pytest.mark.asyncio
async def test_formatter_resets_wire_media_count_before_failure(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        model_factory,
        "_supports_multimodal_for_current_model",
        lambda: True,
    )
    formatter_class = model_factory._create_file_block_support_formatter(
        _CappingAnthropicFormatter,
    )
    formatter = formatter_class()
    valid = Msg(
        name="user",
        role="user",
        content=[_base64_data_block("image/png", b"valid")],
    )
    await formatter.format([valid])
    assert formatter._qwenpaw_last_wire_media_count == 1

    async def fail_format(_self, _msgs):
        raise RuntimeError("formatter failed")

    monkeypatch.setattr(_CappingAnthropicFormatter, "format", fail_format)
    with pytest.raises(RuntimeError, match="formatter failed"):
        await formatter.format([valid])

    assert formatter._qwenpaw_last_wire_media_count == 0


@pytest.mark.asyncio
async def test_dashscope_audio_strip_flag_preserves_other_media(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        model_factory,
        "_supports_multimodal_for_current_model",
        lambda: True,
    )
    formatter_class = model_factory._create_file_block_support_formatter(
        _CappingDashScopeFormatter,
    )
    formatter = formatter_class()
    audio_block = _base64_data_block("audio/mpeg", b"audio")
    msg = Msg(
        name="user",
        role="user",
        content=[
            TextBlock(text="Mixed media"),
            _base64_data_block("image/png", b"image"),
            audio_block,
            _base64_data_block("video/mp4", b"video"),
        ],
    )
    original = msg.model_dump(mode="json")

    first_request = await formatter.format([msg])

    assert [block["type"] for block in first_request[0]["content"]] == [
        "text",
        "image_url",
        "input_audio",
        "video_url",
    ]
    assert first_request[0]["content"][2] == {
        "type": "input_audio",
        "input_audio": {
            "data": (f"data:audio/mpeg;base64,{audio_block.source.data}"),
            "format": "mp3",
        },
    }
    assert formatter._qwenpaw_last_wire_media_count == 3
    assert formatter._qwenpaw_last_wire_audio_count == 1

    formatter._qwenpaw_force_strip_audio = True
    retry_request = await formatter.format([msg])

    assert [block["type"] for block in retry_request[0]["content"]] == [
        "text",
        "image_url",
        "video_url",
    ]
    assert formatter._qwenpaw_last_wire_media_count == 2
    assert formatter._qwenpaw_last_wire_audio_count == 0
    assert msg.model_dump(mode="json") == original


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


@pytest.mark.asyncio
async def test_local_video_preparation_does_not_block_event_loop(
    tmp_path,
    monkeypatch,
) -> None:
    """Local media reads must run outside the formatter event loop."""
    video_path = tmp_path / "clip.mp4"
    video_path.write_bytes(b"video")
    entered = threading.Event()
    release = threading.Event()
    original_reader = model_factory._read_local_media

    def blocking_reader(path: str, max_bytes: int = 0):
        entered.set()
        release.wait(timeout=2)
        return original_reader(path, max_bytes)

    monkeypatch.setattr(
        model_factory,
        "_read_local_media",
        blocking_reader,
    )
    user_msg = Msg(
        name="user",
        role="user",
        content=[
            _data_block("video/mp4", f"file://{video_path}"),
        ],
    )
    tool_msg = Msg(
        name="assistant",
        role="assistant",
        content=[
            ToolCallBlock(
                id="call_1",
                name="view_video",
                input="{}",
            ),
            ToolResultBlock(
                id="call_1",
                name="view_video",
                output=[
                    _data_block("video/mp4", f"file://{video_path}"),
                ],
                state=ToolResultState.SUCCESS,
            ),
        ],
    )
    preparation = asyncio.create_task(
        model_factory._prepare_media_sources(
            [user_msg, tool_msg],
            _CappingOpenAIFormatter,
            include_hint_videos=True,
        ),
    )
    await asyncio.wait_for(asyncio.to_thread(entered.wait), timeout=1)

    ticks = 0
    deadline = asyncio.get_running_loop().time() + 0.05
    while asyncio.get_running_loop().time() < deadline:
        ticks += 1
        await asyncio.sleep(0)

    release.set()
    await preparation

    assert ticks > 0
    assert user_msg.content[0].source.data == "dmlkZW8="


@pytest.mark.asyncio
async def test_remote_media_preparation_does_not_block_event_loop(
    monkeypatch,
) -> None:
    """Remote downloads are awaited before in-memory wire formatting."""
    entered = asyncio.Event()
    release = asyncio.Event()

    async def delayed_download(_url: str, _max_bytes: int):
        entered.set()
        await release.wait()
        return model_factory._LocalMediaRead(True, 5, "aW1hZ2U=")

    monkeypatch.setattr(
        model_factory,
        "_download_remote_media",
        delayed_download,
    )
    monkeypatch.setattr(
        model_factory,
        "_supports_multimodal_for_current_model",
        lambda: True,
    )
    formatter_class = model_factory._create_file_block_support_formatter(
        _CappingAnthropicFormatter,
    )
    formatter = formatter_class()
    formatting = asyncio.create_task(
        formatter.format(
            [
                Msg(
                    name="user",
                    role="user",
                    content=[
                        _data_block(
                            "image/png",
                            "https://example.com/image.png",
                        ),
                    ],
                ),
            ],
        ),
    )
    await asyncio.wait_for(entered.wait(), timeout=1)

    ticks = 0
    deadline = asyncio.get_running_loop().time() + 0.05
    while asyncio.get_running_loop().time() < deadline:
        ticks += 1
        await asyncio.sleep(0)

    release.set()
    formatted = await formatting

    assert ticks > 0
    assert formatted[0]["content"][0]["source"]["data"] == "aW1hZ2U="


@pytest.mark.asyncio
async def test_concurrent_media_preparation_is_request_local(
    monkeypatch,
) -> None:
    """Concurrent formatter calls keep downloaded media isolated."""

    async def fake_download(url: str, _max_bytes: int):
        await asyncio.sleep(0)
        encoded = "Zmlyc3Q=" if "first" in url else "c2Vjb25k"
        return model_factory._LocalMediaRead(True, 6, encoded)

    monkeypatch.setattr(
        model_factory,
        "_download_remote_media",
        fake_download,
    )
    monkeypatch.setattr(
        model_factory,
        "_supports_multimodal_for_current_model",
        lambda: True,
    )
    formatter_class = model_factory._create_file_block_support_formatter(
        _CappingAnthropicFormatter,
    )
    formatter = formatter_class()

    async def format_url(url: str):
        return await formatter.format(
            [
                Msg(
                    name="user",
                    role="user",
                    content=[_data_block("image/png", url)],
                ),
            ],
        )

    first, second = await asyncio.gather(
        format_url("https://example.com/first.png"),
        format_url("https://example.com/second.png"),
    )

    assert first[0]["content"][0]["source"]["data"] == "Zmlyc3Q="
    assert second[0]["content"][0]["source"]["data"] == "c2Vjb25k"


@pytest.mark.asyncio
async def test_remote_media_preparation_propagates_cancellation(
    monkeypatch,
) -> None:
    """Cancelling a formatter call also cancels its remote download."""
    entered = asyncio.Event()
    cancelled = asyncio.Event()

    async def pending_download(_url: str, _max_bytes: int):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    monkeypatch.setattr(
        model_factory,
        "_download_remote_media",
        pending_download,
    )
    monkeypatch.setattr(
        model_factory,
        "_supports_multimodal_for_current_model",
        lambda: True,
    )
    formatter_class = model_factory._create_file_block_support_formatter(
        _CappingAnthropicFormatter,
    )
    formatter = formatter_class()
    formatting = asyncio.create_task(
        formatter.format(
            [
                Msg(
                    name="user",
                    role="user",
                    content=[
                        _data_block(
                            "image/png",
                            "https://example.com/pending.png",
                        ),
                    ],
                ),
            ],
        ),
    )
    await asyncio.wait_for(entered.wait(), timeout=1)

    formatting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await formatting
    await asyncio.wait_for(cancelled.wait(), timeout=1)


@pytest.mark.asyncio
async def test_remote_media_download_rejects_reported_oversize(
    monkeypatch,
) -> None:
    """Reject oversized remote media before consuming its response body."""
    body_read = False

    class TrackingStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            nonlocal body_read
            body_read = True
            yield b"oversized"

    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers={"content-length": "10"},
            stream=TrackingStream(),
            request=request,
        ),
    )
    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        model_factory.httpx,
        "AsyncClient",
        lambda **kwargs: original_client(
            transport=transport,
            **kwargs,
        ),
    )

    prepared = await model_factory._download_remote_media(
        "https://example.com/image.png",
        5,
    )

    assert prepared == model_factory._LocalMediaRead(True, 10, None)
    assert not body_read


@pytest.mark.asyncio
async def test_remote_media_download_caps_chunked_response(
    monkeypatch,
) -> None:
    """Stop a remote download when streamed bytes cross the limit."""

    class ChunkedStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"123"
            yield b"456"

    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            stream=ChunkedStream(),
            request=request,
        ),
    )
    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        model_factory.httpx,
        "AsyncClient",
        lambda **kwargs: original_client(
            transport=transport,
            **kwargs,
        ),
    )

    prepared = await model_factory._download_remote_media(
        "https://example.com/image.png",
        5,
    )

    assert prepared.exists
    assert prepared.size > 5
    assert prepared.encoded is None


@pytest.mark.asyncio
async def test_remote_media_oversize_becomes_placeholder(
    monkeypatch,
) -> None:
    """Replace oversized remote media before downstream formatting."""

    async def oversized_download(_url: str, max_bytes: int):
        return model_factory._LocalMediaRead(
            True,
            max_bytes + 1,
            None,
        )

    monkeypatch.setattr(
        model_factory,
        "_download_remote_media",
        oversized_download,
    )
    monkeypatch.setattr(
        model_factory,
        "_supports_multimodal_for_current_model",
        lambda: True,
    )
    formatter_class = model_factory._create_file_block_support_formatter(
        _CappingAnthropicFormatter,
    )
    formatter = formatter_class(max_bytes=5)

    formatted = await formatter.format(
        [
            Msg(
                name="user",
                role="user",
                content=[
                    _data_block(
                        "image/png",
                        "https://example.com/image.png",
                    ),
                ],
            ),
        ],
    )

    assert "remote media is 6 bytes" in formatted[0]["content"][0]["text"]


@pytest.mark.asyncio
async def test_formatter_base_call_does_not_block_event_loop() -> None:
    """Base formatter runs on the event loop after media preparation."""
    observed_loop = None

    class BlockingFormatter(OpenAIChatFormatter):
        """Formatter that records the loop used for wire formatting."""

        async def format(self, _msgs):
            nonlocal observed_loop
            observed_loop = asyncio.get_running_loop()
            return [{"role": "user", "content": "formatted"}]

    formatter_class = model_factory._create_file_block_support_formatter(
        BlockingFormatter,
    )
    formatter = formatter_class()
    loop = asyncio.get_running_loop()
    formatted = await formatter.format(
        [Msg(name="user", role="user", content=[TextBlock(text="hello")])],
    )
    assert observed_loop is loop
    assert formatted == [{"role": "user", "content": "formatted"}]


@pytest.mark.asyncio
async def test_openai_formatter_uses_prepared_local_video(
    tmp_path,
    monkeypatch,
) -> None:
    """The formatter must consume local video data prepared off-thread."""
    monkeypatch.setattr(
        model_factory,
        "_supports_multimodal_for_current_model",
        lambda: True,
    )
    video_path = tmp_path / "clip.mp4"
    video_path.write_bytes(b"video")
    formatter_class = model_factory._create_file_block_support_formatter(
        _CappingOpenAIFormatter,
    )
    formatter = formatter_class()
    msg = Msg(
        name="user",
        role="user",
        content=[
            _data_block("video/mp4", f"file://{video_path}"),
        ],
    )

    formatted = await formatter.format([msg])

    video_items = [
        item
        for message in formatted
        for item in message.get("content") or []
        if isinstance(item, dict) and item.get("type") == "video_url"
    ]
    assert len(video_items) == 1
    assert video_items[0]["video_url"]["url"].startswith(
        "data:video/mp4;base64,",
    )


@pytest.mark.asyncio
async def test_formatter_applies_custom_local_media_limit(
    tmp_path,
    monkeypatch,
) -> None:
    """The async preparation stage honors formatter-specific media caps."""
    monkeypatch.setattr(
        model_factory,
        "_supports_multimodal_for_current_model",
        lambda: True,
    )
    image_path = tmp_path / "large.png"
    image_path.write_bytes(b"image")
    formatter_class = model_factory._create_file_block_support_formatter(
        _CappingOpenAIFormatter,
    )
    formatter = formatter_class(max_bytes=4)
    msg = Msg(
        name="user",
        role="user",
        content=[
            _data_block("image/png", f"file://{image_path}"),
        ],
    )

    formatted = await formatter.format([msg])

    item = formatted[0]["content"][0]
    assert item["type"] == "text"
    assert "exceeds inline limit of 4 bytes" in item["text"]


@pytest.mark.asyncio
async def test_anthropic_hint_uses_prepared_local_video(
    tmp_path,
    monkeypatch,
) -> None:
    """Anthropic must preserve local videos nested in a HintBlock."""
    if AnthropicChatFormatter is None:
        pytest.skip("AnthropicChatFormatter not available")

    monkeypatch.setattr(
        model_factory,
        "_supports_multimodal_for_current_model",
        lambda: True,
    )
    original_reader = model_factory._read_local_media
    worker_reads: list[str] = []

    def counted_reader(path: str, max_bytes: int = 0):
        worker_reads.append(path)
        return original_reader(path, max_bytes)

    monkeypatch.setattr(
        model_factory,
        "_read_local_media",
        counted_reader,
    )
    video_path = tmp_path / "hint-clip.mp4"
    video_path.write_bytes(b"video")
    formatter_class = model_factory._create_file_block_support_formatter(
        _CappingAnthropicFormatter,
    )
    formatter = formatter_class()
    msg = Msg(
        name="assistant",
        role="assistant",
        content=[
            HintBlock(
                hint=[
                    _data_block("video/mp4", f"file://{video_path}"),
                ],
            ),
        ],
    )

    formatted = await formatter.format([msg])

    video_items = [
        item
        for message in formatted
        for item in message.get("content") or []
        if isinstance(item, dict) and item.get("type") == "video"
    ]
    assert len(video_items) == 1
    assert video_items[0]["source"]["type"] == "base64"
    assert video_items[0]["source"]["data"] == "dmlkZW8="
    assert len(worker_reads) == 1


@pytest.mark.asyncio
async def test_dashscope_hint_prepares_local_video_once(
    tmp_path,
    monkeypatch,
) -> None:
    """DashScope hint videos are prepared once before wire formatting."""
    monkeypatch.setattr(
        model_factory,
        "_supports_multimodal_for_current_model",
        lambda: True,
    )

    original_reader = model_factory._read_local_media
    reads: list[str] = []

    def counted_reader(path: str, max_bytes: int = 0):
        reads.append(path)
        return original_reader(path, max_bytes)

    monkeypatch.setattr(
        model_factory,
        "_read_local_media",
        counted_reader,
    )
    video_path = tmp_path / "dashscope-hint-clip.mp4"
    video_path.write_bytes(b"video")
    formatter_class = model_factory._create_file_block_support_formatter(
        _CappingDashScopeFormatter,
    )
    formatter = formatter_class()
    msg = Msg(
        name="assistant",
        role="assistant",
        content=[
            HintBlock(
                hint=[
                    _data_block("video/mp4", f"file://{video_path}"),
                ],
            ),
        ],
    )

    formatted = await formatter.format([msg])

    video_item = formatted[0]["content"][0]
    assert video_item["type"] == "video_url"
    assert video_item["video_url"]["url"].startswith(
        "data:video/mp4;base64,",
    )
    assert len(reads) == 1


@pytest.mark.asyncio
async def test_openai_hint_skips_local_video_preparation(
    tmp_path,
    monkeypatch,
) -> None:
    """OpenAI must not pre-read a HintBlock video it will discard."""
    monkeypatch.setattr(
        model_factory,
        "_supports_multimodal_for_current_model",
        lambda: True,
    )

    def unexpected_reader(path: str):
        raise AssertionError(f"unexpected worker-thread read: {path}")

    monkeypatch.setattr(
        model_factory,
        "_read_local_media",
        unexpected_reader,
    )
    video_path = tmp_path / "openai-hint-clip.mp4"
    video_path.write_bytes(b"video")
    formatter_class = model_factory._create_file_block_support_formatter(
        _CappingOpenAIFormatter,
    )
    formatter = formatter_class()
    msg = Msg(
        name="assistant",
        role="assistant",
        content=[
            HintBlock(
                hint=[
                    _data_block("video/mp4", f"file://{video_path}"),
                ],
            ),
        ],
    )

    formatted = await formatter.format([msg])

    assert formatted == []


@pytest.mark.asyncio
async def test_openai_hint_prepares_supported_local_media(
    tmp_path,
    monkeypatch,
) -> None:
    """Supported OpenAI hint media is prepared exactly once."""
    monkeypatch.setattr(
        model_factory,
        "_supports_multimodal_for_current_model",
        lambda: True,
    )
    original_reader = model_factory._read_local_media
    reads: list[str] = []

    def counted_reader(path: str, max_bytes: int = 0):
        reads.append(path)
        return original_reader(path, max_bytes)

    monkeypatch.setattr(
        model_factory,
        "_read_local_media",
        counted_reader,
    )
    image_path = tmp_path / "openai-hint.png"
    image_path.write_bytes(b"image")
    formatter_class = model_factory._create_file_block_support_formatter(
        _CappingOpenAIFormatter,
    )
    formatter = formatter_class()
    msg = Msg(
        name="assistant",
        role="assistant",
        content=[
            HintBlock(
                hint=[
                    _data_block("image/png", f"file://{image_path}"),
                ],
            ),
        ],
    )

    formatted = await formatter.format([msg])

    image_item = formatted[0]["content"][0]
    assert image_item["type"] == "image_url"
    assert image_item["image_url"]["url"].startswith(
        "data:image/png;base64,",
    )
    assert len(reads) == 1


@pytest.mark.asyncio
async def test_gemini_formatter_prepares_local_video_once(
    tmp_path,
    monkeypatch,
) -> None:
    """Gemini media is prepared before its in-memory formatter call."""
    if GeminiChatFormatter is None:
        pytest.skip("GeminiChatFormatter not available")

    monkeypatch.setattr(
        model_factory,
        "_supports_multimodal_for_current_model",
        lambda: True,
    )

    original_reader = model_factory._read_local_media
    reads: list[str] = []

    def counted_reader(path: str, max_bytes: int = 0):
        reads.append(path)
        return original_reader(path, max_bytes)

    monkeypatch.setattr(
        model_factory,
        "_read_local_media",
        counted_reader,
    )
    video_path = tmp_path / "gemini-clip.mp4"
    video_path.write_bytes(b"video")
    formatter_class = model_factory._create_file_block_support_formatter(
        _CappingGeminiFormatter,
    )
    formatter = formatter_class()
    msg = Msg(
        name="user",
        role="user",
        content=[
            _data_block("video/mp4", f"file://{video_path}"),
        ],
    )

    formatted = await formatter.format([msg])

    assert formatted[0]["parts"][0]["inline_data"]["data"] == "dmlkZW8="
    assert len(reads) == 1


@pytest.mark.asyncio
async def test_openai_formatter_promotes_prepared_tool_video(
    tmp_path,
) -> None:
    """Tool-result video promotion must use prepared media data."""
    video_path = tmp_path / "tool-clip.mp4"
    video_path.write_bytes(b"video")
    msg = SimpleNamespace(
        content=[
            {
                "type": "tool_result",
                "id": "call_1",
                "name": "view_video",
                "output": [
                    {
                        "type": "video",
                        "source": {
                            "type": "url",
                            "url": f"file://{video_path}",
                            "media_type": "video/mp4",
                        },
                    },
                ],
            },
        ],
    )
    await model_factory._prepare_media_sources(
        [msg],
        _CappingOpenAIFormatter,
        include_hint_videos=True,
    )
    formatted = model_factory._promote_tool_result_videos(
        [msg],
        [
            {
                "role": "tool",
                "tool_call_id": "call_1",
                "content": "tool output",
            },
        ],
    )

    video_items = [
        item
        for message in formatted
        for item in message.get("content") or []
        if isinstance(item, dict) and item.get("type") == "video_url"
    ]
    assert len(video_items) == 1
    assert video_items[0]["video_url"]["url"].startswith(
        "data:video/mp4;base64,",
    )
