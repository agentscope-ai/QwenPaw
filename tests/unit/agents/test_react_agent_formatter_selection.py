# -*- coding: utf-8 -*-
# pylint: disable=protected-access
from __future__ import annotations

from agentscope.formatter import OpenAIChatFormatter

try:
    from agentscope.formatter import AnthropicChatFormatter
except ImportError:  # pragma: no cover - compatibility fallback
    AnthropicChatFormatter = None

try:
    from agentscope.formatter import GeminiChatFormatter
except ImportError:  # pragma: no cover - compatibility fallback
    GeminiChatFormatter = None

from copaw.agents.react_agent import CoPawAgent


def _make_agent_with_formatter(formatter):
    agent = object.__new__(CoPawAgent)
    agent.formatter = formatter
    return agent


def test_detects_openai_compatible_formatter() -> None:
    agent = _make_agent_with_formatter(OpenAIChatFormatter())
    assert agent._uses_openai_compatible_formatter() is True


def test_rejects_anthropic_formatter() -> None:
    if AnthropicChatFormatter is None:
        return
    agent = _make_agent_with_formatter(AnthropicChatFormatter())
    assert agent._uses_openai_compatible_formatter() is False


def test_rejects_gemini_formatter() -> None:
    if GeminiChatFormatter is None:
        return
    agent = _make_agent_with_formatter(GeminiChatFormatter())
    assert agent._uses_openai_compatible_formatter() is False


def test_toggles_openai_formatter_media_strip_flag() -> None:
    formatter = OpenAIChatFormatter()
    agent = _make_agent_with_formatter(formatter)

    agent._set_openai_formatter_media_strip(True)
    assert getattr(formatter, "_copaw_force_strip_media") is True

    agent._set_openai_formatter_media_strip(False)
    assert getattr(formatter, "_copaw_force_strip_media") is False
