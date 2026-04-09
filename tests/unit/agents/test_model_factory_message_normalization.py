# -*- coding: utf-8 -*-
# pylint: disable=protected-access
from __future__ import annotations

from types import SimpleNamespace

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

from copaw.agents import model_factory


def _media_messages() -> list[Msg]:
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

    assert normalized[0].content == [
        {
            "type": "text",
            "text": (
                "[Media content removed - model does not support this "
                "media type]"
            ),
        },
    ]
    assert normalized[2].content[0]["output"] == (
        "[Media content removed - model does not support this media type]"
    )
    assert original[0].content[0]["type"] == "image"
    assert original[2].content[0]["output"][0]["type"] == "image"


def test_openai_formatter_normalizes_on_copy(monkeypatch) -> None:
    monkeypatch.setattr(
        model_factory,
        "_supports_multimodal_for_current_model",
        lambda: False,
    )
    _assert_request_time_stripped(OpenAIChatFormatter)


def test_anthropic_formatter_normalizes_on_copy(monkeypatch) -> None:
    if AnthropicChatFormatter is None:
        return
    monkeypatch.setattr(
        model_factory,
        "_supports_multimodal_for_current_model",
        lambda: False,
    )
    _assert_request_time_stripped(AnthropicChatFormatter)


def test_gemini_formatter_normalizes_on_copy(monkeypatch) -> None:
    if GeminiChatFormatter is None:
        return
    monkeypatch.setattr(
        model_factory,
        "_supports_multimodal_for_current_model",
        lambda: False,
    )
    _assert_request_time_stripped(GeminiChatFormatter)
