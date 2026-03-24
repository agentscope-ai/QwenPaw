# -*- coding: utf-8 -*-
from __future__ import annotations

from copy import deepcopy

from copaw.agents.model_factory import (
    _sanitize_anthropic_history_tool_result_media,
)
from copaw.agents.react_agent import is_bad_request_or_media_error


def _make_tool_result_message(
    tool_use_id: str,
    *,
    text: str = "Image loaded: a.png",
    include_image: bool = True,
) -> dict:
    content: list[dict] = []
    if include_image:
        content.append(
            {
                "type": "image",
                "source": {"type": "url", "url": "/tmp/a.png"},
            },
        )
    if text:
        content.append({"type": "text", "text": text})
    return {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": content,
            },
        ],
    }


def test_sanitize_history_tool_results_strips_media_but_keeps_text() -> None:
    messages = [
        {"role": "user", "content": [{"type": "text", "text": "look"}]},
        {
            "role": "assistant",
            "content": [
                {
                    "id": "toolu_1",
                    "type": "tool_use",
                    "name": "view_image",
                    "input": {"image_path": "/tmp/a.png"},
                },
            ],
        },
        _make_tool_result_message("toolu_1"),
        {
            "role": "assistant",
            "content": [{"type": "text", "text": "I can see it."}],
        },
        {"role": "user", "content": [{"type": "text", "text": "继续"}]},
    ]

    original = deepcopy(messages)
    sanitized = _sanitize_anthropic_history_tool_result_media(messages)

    tool_result = sanitized[2]["content"][0]
    assert tool_result["content"] == [
        {"type": "text", "text": "Image loaded: a.png"},
    ]
    tool_result["content"][0]["text"] = "mutated"
    assert (
        messages[2]["content"][0]["content"][1]["text"]
        == "Image loaded: a.png"
    )
    assert messages == original


def test_sanitize_history_tool_results_preserves_trailing_current_suffix() -> (
    None
):
    messages = [
        {"role": "user", "content": [{"type": "text", "text": "look"}]},
        {
            "role": "assistant",
            "content": [
                {
                    "id": "toolu_1",
                    "type": "tool_use",
                    "name": "view_image",
                    "input": {"image_path": "/tmp/a.png"},
                },
            ],
        },
        _make_tool_result_message("toolu_1"),
        {
            "role": "assistant",
            "content": [{"type": "text", "text": "I can see it."}],
        },
        {
            "role": "assistant",
            "content": [
                {
                    "id": "toolu_2",
                    "type": "tool_use",
                    "name": "view_image",
                    "input": {"image_path": "/tmp/b.png"},
                },
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "toolu_2",
                    "content": [
                        {
                            "type": "image",
                            "source": {"type": "url", "url": "/tmp/b.png"},
                        },
                        {"type": "text", "text": "Image loaded: b.png"},
                    ],
                },
            ],
        },
    ]

    sanitized = _sanitize_anthropic_history_tool_result_media(messages)

    historical_result = sanitized[2]["content"][0]
    trailing_result = sanitized[-1]["content"][0]

    assert historical_result["content"] == [
        {"type": "text", "text": "Image loaded: a.png"},
    ]
    assert trailing_result["content"][0]["type"] == "image"
    assert trailing_result["content"][0]["source"]["url"] == "/tmp/b.png"


def test_bad_request_detector_matches_anthropic_tool_result_source_bug() -> (
    None
):
    class FakeAnthropicError(Exception):
        status_code = 500

        def __str__(self) -> str:
            return (
                "Error code: 500 - {'error': {'code': '500', "
                '"message": "\'ClaudeContentBlockToolResult\' object '
                "has no attribute 'source'\"}}"
            )

    assert is_bad_request_or_media_error(FakeAnthropicError())


def test_bad_request_detector_ignores_unrelated_source_attribute_errors() -> (
    None
):
    class FakeGenericError(Exception):
        status_code = 500

        def __str__(self) -> str:
            return "RuntimeError: object has no attribute 'source'"

    assert not is_bad_request_or_media_error(FakeGenericError())
