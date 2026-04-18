# -*- coding: utf-8 -*-
"""Tests for model_factory message normalization integration."""

# pylint: disable=protected-access,redefined-outer-name
from types import SimpleNamespace

import pytest
from agentscope.formatter import OpenAIChatFormatter
from agentscope.message import Msg, ToolResultBlock

try:
    from agentscope.formatter import AnthropicChatFormatter
except ImportError:  # pragma: no cover - compatibility fallback
    AnthropicChatFormatter = None

try:
    from agentscope.formatter import GeminiChatFormatter
except ImportError:  # pragma: no cover - compatibility fallback
    GeminiChatFormatter = None

from qwenpaw.agents import model_factory
from qwenpaw.constant import MEDIA_UNSUPPORTED_PLACEHOLDER


def _media_messages() -> list[Msg]:
    """Create a list of messages with media blocks for testing."""
    return [
        Msg(
            name="user",
            role="user",
            content=[
                {
                    "type": "image",
                    "source": {
                        "type": "url",
                        "url": "file:///tmp/demo.png",
                    },
                },
            ],
        ),
        Msg(
            name="assistant",
            role="assistant",
            content=[
                {
                    "type": "tool_use",
                    "id": "call_1",
                    "name": "view_image",
                    "input": {},
                },
            ],
        ),
        Msg(
            name="system",
            role="system",
            content=[
                ToolResultBlock(
                    type="tool_result",
                    id="call_1",
                    name="view_image",
                    output=[
                        {
                            "type": "image",
                            "source": {
                                "type": "url",
                                "url": "file:///tmp/demo.png",
                            },
                        },
                    ],
                ),
            ],
        ),
    ]


def _assert_request_time_stripped(formatter_class) -> None:
    """Helper to assert that media is stripped from normalized messages."""
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

    # First message (user image) should be replaced with placeholder
    assert normalized[0].content == [
        {
            "type": "text",
            "text": MEDIA_UNSUPPORTED_PLACEHOLDER,
        },
    ]

    # Third message (tool result with image) should have output replaced
    assert normalized[2].content[0]["output"] == MEDIA_UNSUPPORTED_PLACEHOLDER

    # Original messages should be unchanged
    assert original[0].content[0]["type"] == "image"
    assert original[2].content[0]["output"][0]["type"] == "image"


def test_openai_formatter_normalizes_on_copy(monkeypatch) -> None:
    """Test that OpenAI formatter normalizes messages with media stripped."""
    monkeypatch.setattr(
        model_factory,
        "_supports_multimodal_for_current_model",
        lambda: False,
    )
    _assert_request_time_stripped(OpenAIChatFormatter)


def test_anthropic_formatter_normalizes_on_copy(monkeypatch) -> None:
    """Test Anthropic formatter normalizes messages with media stripped."""
    if AnthropicChatFormatter is None:
        pytest.skip("AnthropicChatFormatter not available")

    monkeypatch.setattr(
        model_factory,
        "_supports_multimodal_for_current_model",
        lambda: False,
    )
    _assert_request_time_stripped(AnthropicChatFormatter)


def test_gemini_formatter_normalizes_on_copy(monkeypatch) -> None:
    """Test that Gemini formatter normalizes messages with media stripped."""
    if GeminiChatFormatter is None:
        pytest.skip("GeminiChatFormatter not available")

    monkeypatch.setattr(
        model_factory,
        "_supports_multimodal_for_current_model",
        lambda: False,
    )
    _assert_request_time_stripped(GeminiChatFormatter)


def test_multimodal_support_preserves_media(monkeypatch) -> None:
    """Test that when multimodal is supported, media is preserved."""
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

    # Media should be preserved in normalized messages
    assert normalized[0].content[0]["type"] == "image"
    assert normalized[2].content[0]["output"][0]["type"] == "image"

    # Original should be unchanged
    assert original[0].content[0]["type"] == "image"


def test_force_strip_media_flag_overrides_multimodal_support(
    monkeypatch,
) -> None:
    """Test that _qwenpaw_force_strip_media flag forces media stripping."""
    monkeypatch.setattr(
        model_factory,
        "_supports_multimodal_for_current_model",
        lambda: True,  # Model supports multimodal
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

    # Media should be stripped despite multimodal support
    assert normalized[0].content[0]["type"] == "text"
    assert normalized[0].content[0]["text"] == MEDIA_UNSUPPORTED_PLACEHOLDER


def test_formatter_flags_returned_correctly() -> None:
    """Test that formatter family flags are returned correctly."""
    msgs = [Msg(name="user", role="user", content="Hello")]

    (
        _normalized,
        is_anthropic,
        is_gemini,
    ) = model_factory._normalize_messages_for_formatter(
        msgs,
        OpenAIChatFormatter,
        None,
    )

    # OpenAI formatter should not be anthropic or gemini
    assert is_anthropic is False
    assert is_gemini is False


def test_anthropic_flag_detected(monkeypatch) -> None:
    """Test that Anthropic formatter is correctly detected."""
    if AnthropicChatFormatter is None:
        pytest.skip("AnthropicChatFormatter not available")

    monkeypatch.setattr(
        model_factory,
        "_supports_multimodal_for_current_model",
        lambda: True,
    )

    msgs = [Msg(name="user", role="user", content="Hello")]

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
    """Test that Gemini formatter is correctly detected."""
    if GeminiChatFormatter is None:
        pytest.skip("GeminiChatFormatter not available")

    monkeypatch.setattr(
        model_factory,
        "_supports_multimodal_for_current_model",
        lambda: True,
    )

    msgs = [Msg(name="user", role="user", content="Hello")]

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
    """Test that preparing messages for formatter doesn't modify originals."""
    original = Msg(
        name="user",
        role="user",
        content=[
            {"type": "text", "text": "Hello"},
            {
                "type": "image",
                "source": {"type": "url", "url": "file:///tmp/test.png"},
            },
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

    # Original message should be completely unchanged
    assert original.to_dict() == original_dict
    assert original.content[1]["type"] == "image"


# -----------------------------------------------------------------------------
# target_family propagation tests
# -----------------------------------------------------------------------------


def _messages_with_extra_content() -> list[Msg]:
    """Create messages that include Gemini-specific extra_content."""
    return [
        Msg(
            name="assistant",
            role="assistant",
            content=[
                {
                    "type": "tool_use",
                    "id": "call_ec",
                    "name": "search",
                    "input": {"q": "hello"},
                    "extra_content": {"thought_signature": "sig_abc"},
                },
            ],
        ),
        Msg(
            name="system",
            role="system",
            content=[
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
    """OpenAI formatter should strip extra_content from tool_use blocks."""
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

    assert "extra_content" not in normalized[0].content[0]


def test_anthropic_formatter_strips_extra_content(monkeypatch) -> None:
    """Anthropic formatter should strip extra_content from tool_use blocks."""
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

    assert "extra_content" not in normalized[0].content[0]


def test_gemini_formatter_preserves_extra_content(monkeypatch) -> None:
    """Gemini formatter should keep extra_content on tool_use blocks."""
    if GeminiChatFormatter is None:
        pytest.skip("GeminiChatFormatter not available")

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
        GeminiChatFormatter,
        SimpleNamespace(),
    )

    block = normalized[0].content[0]
    assert "extra_content" in block
    assert block["extra_content"]["thought_signature"] == "sig_abc"


def test_extra_content_original_preserved(monkeypatch) -> None:
    """Cleaning for any target must not mutate the original messages."""
    monkeypatch.setattr(
        model_factory,
        "_supports_multimodal_for_current_model",
        lambda: True,
    )

    msgs = _messages_with_extra_content()
    original_block = msgs[0].content[0].copy()

    model_factory._normalize_messages_for_formatter(
        msgs,
        OpenAIChatFormatter,
        SimpleNamespace(),
    )

    assert msgs[0].content[0] == original_block
