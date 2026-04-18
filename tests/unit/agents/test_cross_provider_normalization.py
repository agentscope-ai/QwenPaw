# -*- coding: utf-8 -*-
"""Integration tests for cross-provider message normalization.

Simulates a conversation that starts on one provider and is then formatted
for a *different* provider.  The key invariant: provider-specific artefacts
from the first provider must not leak into the request payload for the
second provider, while the original in-memory messages must remain untouched.
"""

# pylint: disable=protected-access,redefined-outer-name
from types import SimpleNamespace

import pytest
from agentscope.formatter import OpenAIChatFormatter
from agentscope.message import Msg, ToolResultBlock

try:
    from agentscope.formatter import AnthropicChatFormatter
except ImportError:  # pragma: no cover
    AnthropicChatFormatter = None

try:
    from agentscope.formatter import GeminiChatFormatter
except ImportError:  # pragma: no cover
    GeminiChatFormatter = None

from qwenpaw.agents import model_factory


def _gemini_session_history() -> list[Msg]:
    """Simulate a history that was built while Gemini was the active model.

    Includes:
    * An assistant message with a tool_use block carrying ``extra_content``
      (Gemini's ``thought_signature``).
    * A matching tool_result.
    * A final assistant text reply.
    """
    return [
        Msg(name="user", role="user", content="Find the weather in Tokyo"),
        Msg(
            name="assistant",
            role="assistant",
            content=[
                {
                    "type": "tool_use",
                    "id": "tc_gemini_1",
                    "name": "get_weather",
                    "input": {"city": "Tokyo"},
                    "extra_content": {
                        "thought_signature": "gemini_sig_abc",
                    },
                },
            ],
        ),
        Msg(
            name="system",
            role="system",
            content=[
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
            content="The weather in Tokyo is sunny and 25°C.",
        ),
    ]


def _openai_session_history() -> list[Msg]:
    """Simulate a plain history with no provider-specific artefacts."""
    return [
        Msg(name="user", role="user", content="Say hello"),
        Msg(name="assistant", role="assistant", content="Hello!"),
    ]


# ---------------------------------------------------------------------------
# Gemini → OpenAI switch
# ---------------------------------------------------------------------------


def test_gemini_history_to_openai(monkeypatch) -> None:
    """Switching from Gemini to OpenAI should strip extra_content."""
    monkeypatch.setattr(
        model_factory,
        "_supports_multimodal_for_current_model",
        lambda: True,
    )

    history = _gemini_session_history()
    original_ec = history[1].content[0]["extra_content"].copy()

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

    tool_use_block = normalized[1].content[0]
    assert "extra_content" not in tool_use_block
    assert tool_use_block["id"] == "tc_gemini_1"
    assert tool_use_block["input"] == {"city": "Tokyo"}

    # Original history must be unchanged.
    assert history[1].content[0]["extra_content"] == original_ec


# ---------------------------------------------------------------------------
# Gemini → Anthropic switch
# ---------------------------------------------------------------------------


def test_gemini_history_to_anthropic(monkeypatch) -> None:
    """Switching from Gemini to Anthropic should strip extra_content."""
    if AnthropicChatFormatter is None:
        pytest.skip("AnthropicChatFormatter not available")

    monkeypatch.setattr(
        model_factory,
        "_supports_multimodal_for_current_model",
        lambda: True,
    )

    history = _gemini_session_history()

    (
        normalized,
        is_anthropic,
        _is_gemini,
    ) = model_factory._normalize_messages_for_formatter(
        history,
        AnthropicChatFormatter,
        SimpleNamespace(),
    )

    assert is_anthropic is True
    assert "extra_content" not in normalized[1].content[0]


# ---------------------------------------------------------------------------
# Gemini → Gemini (same provider, no stripping)
# ---------------------------------------------------------------------------


def test_gemini_history_stays_gemini(monkeypatch) -> None:
    """Staying on Gemini should preserve extra_content."""
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
    assert "extra_content" in block
    assert block["extra_content"]["thought_signature"] == "gemini_sig_abc"


# ---------------------------------------------------------------------------
# OpenAI → Gemini (nothing to strip, no crash)
# ---------------------------------------------------------------------------


def test_openai_history_to_gemini(monkeypatch) -> None:
    """Plain OpenAI history should work fine when switching to Gemini."""
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
    assert normalized[0].content == "Say hello"
    assert normalized[1].content == "Hello!"


# ---------------------------------------------------------------------------
# Multiple tool calls in one message
# ---------------------------------------------------------------------------


def test_gemini_multi_toolcall_to_openai(monkeypatch) -> None:
    """Multiple tool_use blocks with extra_content all get cleaned."""
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
                {
                    "type": "tool_use",
                    "id": "tc_a",
                    "name": "fn_a",
                    "input": {},
                    "extra_content": {"thought_signature": "sig_a"},
                },
                {
                    "type": "tool_use",
                    "id": "tc_b",
                    "name": "fn_b",
                    "input": {},
                    "extra_content": {"thought_signature": "sig_b"},
                },
            ],
        ),
        Msg(
            name="system",
            role="system",
            content=[
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
        if block.get("type") == "tool_use":
            assert "extra_content" not in block


# ---------------------------------------------------------------------------
# Thinking blocks cross-provider: stored in memory as provider-agnostic
# {"type": "thinking", "thinking": "..."} — should survive normalization
# for ALL target families.
# ---------------------------------------------------------------------------


def _history_with_thinking() -> list[Msg]:
    """Simulate a history that contains Anthropic-style thinking blocks."""
    return [
        Msg(name="user", role="user", content="Think about this"),
        Msg(
            name="assistant",
            role="assistant",
            content=[
                {"type": "thinking", "thinking": "Let me consider..."},
                {"type": "text", "text": "Here is my answer."},
            ],
        ),
    ]


def test_thinking_blocks_preserved_for_openai(monkeypatch) -> None:
    """Thinking blocks in memory must survive normalization for OpenAI."""
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
    thinking_blocks = [b for b in blocks if b.get("type") == "thinking"]
    assert len(thinking_blocks) == 1
    assert thinking_blocks[0]["thinking"] == "Let me consider..."


def test_thinking_blocks_preserved_for_anthropic(monkeypatch) -> None:
    """Thinking blocks must survive normalization for Anthropic."""
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
    thinking_blocks = [b for b in blocks if b.get("type") == "thinking"]
    assert len(thinking_blocks) == 1


def test_thinking_blocks_preserved_for_gemini(monkeypatch) -> None:
    """Thinking blocks must survive normalization for Gemini."""
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
    thinking_blocks = [b for b in blocks if b.get("type") == "thinking"]
    assert len(thinking_blocks) == 1


# ---------------------------------------------------------------------------
# raw_input repair survives across provider switches
# ---------------------------------------------------------------------------


def _history_with_raw_input_needing_repair() -> list[Msg]:
    """Simulate tool_use with empty input but valid raw_input."""
    return [
        Msg(
            name="assistant",
            role="assistant",
            content=[
                {
                    "type": "tool_use",
                    "id": "tc_repair",
                    "name": "search",
                    "input": {},
                    "raw_input": '{"query": "hello"}',
                },
            ],
        ),
        Msg(
            name="system",
            role="system",
            content=[
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
    """raw_input must repair empty input BEFORE being stripped."""
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
    assert block["input"] == {"query": "hello"}
    assert "raw_input" not in block
