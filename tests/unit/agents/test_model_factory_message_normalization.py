# -*- coding: utf-8 -*-
"""Tests for model_factory message normalization integration."""

# pylint: disable=protected-access,redefined-outer-name
import json
from types import SimpleNamespace

import pytest
from agentscope.formatter import OpenAIChatFormatter
from agentscope.message import (
    DataBlock,
    Msg,
    TextBlock,
    ToolCallBlock,
    ToolResultBlock,
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
    ) = model_factory._normalize_messages_for_formatter(
        msgs,
        OpenAIChatFormatter,
        None,
    )

    assert is_anthropic is False
    assert is_gemini is False


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
    ) = model_factory._normalize_messages_for_formatter(
        [original],
        OpenAIChatFormatter,
        SimpleNamespace(_qwenpaw_force_strip_media=False),
    )

    assert original.to_dict() == original_dict
    assert original.content[1].type == "data"


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
