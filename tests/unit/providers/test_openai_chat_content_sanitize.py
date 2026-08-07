# -*- coding: utf-8 -*-
from __future__ import annotations

from copy import deepcopy

import pytest
from agentscope.model import OpenAIChatModel

from qwenpaw.providers.openai_chat_model_compat import (
    OpenAIChatModelCompat,
    _sanitize_chat_completion_messages,
)


def test_polluted_text_content_keeps_only_wire_fields() -> None:
    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "delta": False,
                    "index": None,
                    "status": "created",
                    "object": "content",
                    "msg_id": None,
                    "text": "测试",
                    "runtime_extra": "drop me",
                },
            ],
        },
    ]

    assert _sanitize_chat_completion_messages(messages) == [
        {
            "role": "user",
            "content": [{"type": "text", "text": "测试"}],
        },
    ]


@pytest.mark.parametrize("content_type", ["input_text", "output_text"])
def test_response_text_types_become_chat_completion_text(
    content_type: str,
) -> None:
    messages = [
        {
            "role": "assistant",
            "content": [
                {
                    "type": content_type,
                    "text": "history",
                    "status": "completed",
                    "extra": "drop me",
                },
            ],
        },
    ]

    assert _sanitize_chat_completion_messages(messages)[0]["content"] == [
        {"type": "text", "text": "history"},
    ]


def test_mixed_content_is_sanitized_item_by_item() -> None:
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": "prompt"},
                {
                    "type": "text",
                    "text": "reply",
                    "index": 1,
                    "internal": True,
                },
                {"type": "input_audio", "input_audio": {"data": "abc"}},
            ],
        },
    ]

    assert _sanitize_chat_completion_messages(messages)[0]["content"] == [
        {"type": "text", "text": "prompt"},
        {"type": "text", "text": "reply"},
        {"type": "input_audio", "input_audio": {"data": "abc"}},
    ]


def test_image_url_content_is_preserved_without_runtime_fields() -> None:
    image = {
        "type": "image_url",
        "image_url": {"url": "https://example.com/image.png"},
        "delta": False,
        "index": 0,
        "status": "created",
        "object": "content",
        "msg_id": "message-id",
    }
    messages = [{"role": "user", "content": [image]}]

    assert _sanitize_chat_completion_messages(messages)[0]["content"] == [
        {
            "type": "image_url",
            "image_url": {"url": "https://example.com/image.png"},
        },
    ]


def test_plain_string_content_is_preserved() -> None:
    messages = [{"role": "user", "content": "hello"}]

    sanitized = _sanitize_chat_completion_messages(messages)

    assert sanitized[0]["content"] == "hello"


def test_sanitizing_does_not_mutate_original_messages() -> None:
    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": "hello",
                    "delta": True,
                },
            ],
        },
    ]
    original = deepcopy(messages)

    sanitized = _sanitize_chat_completion_messages(messages)

    assert sanitized is not messages
    assert sanitized[0] is not messages[0]
    assert sanitized[0]["content"] is not messages[0]["content"]
    assert messages == original
    assert messages[0]["content"][0]["delta"] is True


async def test_call_api_passes_sanitized_messages_to_base(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_call_api(self, *args, **kwargs):
        del self, kwargs
        captured["messages"] = args[1]
        return "ok"

    monkeypatch.setattr(OpenAIChatModel, "_call_api", fake_call_api)

    model = object.__new__(OpenAIChatModelCompat)
    model._default_headers = None
    model._extra_generate_kwargs = {}
    model._output_token_param = "max_tokens"
    messages = [
        {
            "role": "system",
            "content": [
                {"type": "input_text", "text": "system prompt"},
            ],
        },
    ]

    assert await model._call_api("model", messages) == "ok"
    assert captured["messages"] == [
        {
            "role": "system",
            "content": [{"type": "text", "text": "system prompt"}],
        },
    ]
    assert messages[0]["content"][0]["type"] == "input_text"
