# -*- coding: utf-8 -*-
"""Integration tests for cross-provider message normalization.

Simulates a conversation that starts on one provider and is then formatted
for a *different* provider.  The key invariant: provider-specific artefacts
from the first provider must not leak into the request payload for the
second provider, while the original in-memory messages must remain untouched.
"""

# pylint: disable=protected-access,redefined-outer-name
import json
from types import SimpleNamespace

import pytest
from agentscope.formatter import OpenAIChatFormatter
from agentscope.message import (
    Msg,
    TextBlock,
    ThinkingBlock,
    ToolCallBlock,
    ToolResultBlock,
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


def _gemini_session_history() -> list[Msg]:
    """Simulate a history built while Gemini was the active model."""
    return [
        Msg(
            name="user",
            role="user",
            content=[TextBlock(text="Find the weather in Tokyo")],
        ),
        Msg(
            name="assistant",
            role="assistant",
            content=[
                ToolCallBlock(
                    type="tool_call",
                    id="tc_gemini_1",
                    name="get_weather",
                    input=json.dumps({"city": "Tokyo"}),
                ),
                ToolResultBlock(
                    type="tool_result",
                    id="tc_gemini_1",
                    name="get_weather",
                    output="Sunny, 25°C",
                ),
            ],
        ),
        Msg(
            name="assistant",
            role="assistant",
            content=[
                TextBlock(text="The weather in Tokyo is sunny and 25°C."),
            ],
        ),
    ]


def _openai_session_history() -> list[Msg]:
    """Simulate a plain history with no provider-specific artefacts."""
    return [
        Msg(
            name="user",
            role="user",
            content=[TextBlock(text="Say hello")],
        ),
        Msg(
            name="assistant",
            role="assistant",
            content=[TextBlock(text="Hello!")],
        ),
    ]


# ---------------------------------------------------------------------------
# Gemini → OpenAI switch
# ---------------------------------------------------------------------------


def test_gemini_history_to_openai(monkeypatch) -> None:
    monkeypatch.setattr(
        model_factory,
        "_supports_multimodal_for_current_model",
        lambda: True,
    )

    history = _gemini_session_history()
    original_dict = history[1].to_dict()

    (
        normalized,
        is_anthropic,
        is_gemini,
    ) = model_factory._normalize_messages_for_formatter(
        history,
        OpenAIChatFormatter,
        SimpleNamespace(),
    )

    assert is_anthropic is False
    assert is_gemini is False

    tool_call_block = normalized[1].content[0]
    assert tool_call_block.type == "tool_call"
    assert tool_call_block.id == "tc_gemini_1"

    assert history[1].to_dict() == original_dict


# ---------------------------------------------------------------------------
# Gemini → Anthropic switch
# ---------------------------------------------------------------------------


def test_gemini_history_to_anthropic(monkeypatch) -> None:
    if AnthropicChatFormatter is None:
        pytest.skip("AnthropicChatFormatter not available")

    monkeypatch.setattr(
        model_factory,
        "_supports_multimodal_for_current_model",
        lambda: True,
    )

    history = _gemini_session_history()

    (
        _,
        is_anthropic,
        _is_gemini,
    ) = model_factory._normalize_messages_for_formatter(
        history,
        AnthropicChatFormatter,
        SimpleNamespace(),
    )

    assert is_anthropic is True


# ---------------------------------------------------------------------------
# Gemini → Gemini (same provider, no stripping)
# ---------------------------------------------------------------------------


def test_gemini_history_stays_gemini(monkeypatch) -> None:
    if GeminiChatFormatter is None:
        pytest.skip("GeminiChatFormatter not available")

    monkeypatch.setattr(
        model_factory,
        "_supports_multimodal_for_current_model",
        lambda: True,
    )

    history = _gemini_session_history()

    (
        normalized,
        _is_anthropic,
        is_gemini,
    ) = model_factory._normalize_messages_for_formatter(
        history,
        GeminiChatFormatter,
        SimpleNamespace(),
    )

    assert is_gemini is True
    block = normalized[1].content[0]
    assert block.type == "tool_call"


# ---------------------------------------------------------------------------
# OpenAI → Gemini (nothing to strip, no crash)
# ---------------------------------------------------------------------------


def test_openai_history_to_gemini(monkeypatch) -> None:
    if GeminiChatFormatter is None:
        pytest.skip("GeminiChatFormatter not available")

    monkeypatch.setattr(
        model_factory,
        "_supports_multimodal_for_current_model",
        lambda: True,
    )

    history = _openai_session_history()

    (
        normalized,
        _is_anthropic,
        is_gemini,
    ) = model_factory._normalize_messages_for_formatter(
        history,
        GeminiChatFormatter,
        SimpleNamespace(),
    )

    assert is_gemini is True
    assert normalized[0].content[0].text == "Say hello"
    assert normalized[1].content[0].text == "Hello!"


# ---------------------------------------------------------------------------
# Multiple tool calls in one message
# ---------------------------------------------------------------------------


def test_gemini_multi_toolcall_to_openai(monkeypatch) -> None:
    monkeypatch.setattr(
        model_factory,
        "_supports_multimodal_for_current_model",
        lambda: True,
    )

    msgs = [
        Msg(
            name="assistant",
            role="assistant",
            content=[
                ToolCallBlock(
                    type="tool_call",
                    id="tc_a",
                    name="fn_a",
                    input="{}",
                ),
                ToolCallBlock(
                    type="tool_call",
                    id="tc_b",
                    name="fn_b",
                    input="{}",
                ),
                ToolResultBlock(
                    type="tool_result",
                    id="tc_a",
                    name="fn_a",
                    output="ok_a",
                ),
                ToolResultBlock(
                    type="tool_result",
                    id="tc_b",
                    name="fn_b",
                    output="ok_b",
                ),
            ],
        ),
    ]

    (
        normalized,
        _is_anthropic,
        _is_gemini,
    ) = model_factory._normalize_messages_for_formatter(
        msgs,
        OpenAIChatFormatter,
        SimpleNamespace(),
    )

    for block in normalized[0].content:
        if getattr(block, "type", None) == "tool_call":
            assert not hasattr(block, "extra_content") or not getattr(
                block,
                "extra_content",
                None,
            )


# ---------------------------------------------------------------------------
# Thinking blocks cross-provider
# ---------------------------------------------------------------------------


def _history_with_thinking() -> list[Msg]:
    return [
        Msg(
            name="user",
            role="user",
            content=[TextBlock(text="Think about this")],
        ),
        Msg(
            name="assistant",
            role="assistant",
            content=[
                ThinkingBlock(thinking="Let me consider..."),
                TextBlock(text="Here is my answer."),
            ],
        ),
    ]


def test_thinking_blocks_preserved_for_openai(monkeypatch) -> None:
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
        _history_with_thinking(),
        OpenAIChatFormatter,
        SimpleNamespace(),
    )

    blocks = normalized[1].content
    thinking_blocks = [
        b for b in blocks if getattr(b, "type", None) == "thinking"
    ]
    assert len(thinking_blocks) == 1
    assert thinking_blocks[0].thinking == "Let me consider..."


def test_unsigned_thinking_blocks_dropped_for_anthropic(monkeypatch) -> None:
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
        _history_with_thinking(),
        AnthropicChatFormatter,
        SimpleNamespace(),
    )

    blocks = normalized[1].content
    thinking_blocks = [
        b for b in blocks if getattr(b, "type", None) == "thinking"
    ]
    assert thinking_blocks == []
    text_blocks = [b for b in blocks if getattr(b, "type", None) == "text"]
    assert len(text_blocks) == 1


def test_signed_thinking_blocks_preserved_for_anthropic(monkeypatch) -> None:
    if AnthropicChatFormatter is None:
        pytest.skip("AnthropicChatFormatter not available")

    monkeypatch.setattr(
        model_factory,
        "_supports_multimodal_for_current_model",
        lambda: True,
    )

    history = [
        Msg(
            name="user",
            role="user",
            content=[TextBlock(text="Think about this")],
        ),
        Msg(
            name="assistant",
            role="assistant",
            content=[
                ThinkingBlock(
                    thinking="Let me consider...",
                    signature="sig-from-claude",
                ),
                TextBlock(text="Here is my answer."),
            ],
        ),
    ]

    (
        normalized,
        _is_anthropic,
        _is_gemini,
    ) = model_factory._normalize_messages_for_formatter(
        history,
        AnthropicChatFormatter,
        SimpleNamespace(),
    )

    blocks = normalized[1].content
    thinking_blocks = [
        b for b in blocks if getattr(b, "type", None) == "thinking"
    ]
    assert len(thinking_blocks) == 1
    assert thinking_blocks[0].signature == "sig-from-claude"


def test_thinking_blocks_preserved_for_gemini(monkeypatch) -> None:
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
        _history_with_thinking(),
        GeminiChatFormatter,
        SimpleNamespace(),
    )

    blocks = normalized[1].content
    thinking_blocks = [
        b for b in blocks if getattr(b, "type", None) == "thinking"
    ]
    assert len(thinking_blocks) == 1


# ---------------------------------------------------------------------------
# raw_input repair survives across provider switches
# ---------------------------------------------------------------------------


def _history_with_raw_input_needing_repair() -> list[Msg]:
    return [
        Msg(
            name="assistant",
            role="assistant",
            content=[
                ToolCallBlock(
                    type="tool_call",
                    id="tc_repair",
                    name="search",
                    input="{}",
                ),
                ToolResultBlock(
                    type="tool_result",
                    id="tc_repair",
                    name="search",
                    output="found it",
                ),
            ],
        ),
    ]


def test_raw_input_repair_works_before_cross_provider_clean(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        model_factory,
        "_supports_multimodal_for_current_model",
        lambda: True,
    )

    history = _history_with_raw_input_needing_repair()

    (
        normalized,
        _is_anthropic,
        _is_gemini,
    ) = model_factory._normalize_messages_for_formatter(
        history,
        OpenAIChatFormatter,
        SimpleNamespace(),
    )

    block = normalized[0].content[0]
    assert not hasattr(block, "raw_input") or not getattr(
        block,
        "raw_input",
        None,
    )
