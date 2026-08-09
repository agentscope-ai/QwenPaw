# -*- coding: utf-8 -*-
# pylint: disable=protected-access
from __future__ import annotations

from copy import deepcopy
import json
from typing import Any

import httpx
import pytest
from agentscope.credential import OpenAICredential
from agentscope.message import Msg, TextBlock

from qwenpaw.providers.openai_chat_model_compat import (
    _ChatCompletionFormatterWrapper,
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
    original_content = messages[0]["content"]
    assert isinstance(original_content, list)
    assert original_content[0]["delta"] is True


class _PollutedFormatter:
    def __init__(self, messages: list[dict[str, Any]]) -> None:
        self.messages = messages
        self.received_messages: list[Msg] | None = None
        self.relay_reasoning_content = True

    async def format(self, messages: list[Msg]) -> list[dict[str, Any]]:
        self.received_messages = messages
        return self.messages


async def test_formatter_wrapper_sanitizes_without_mutating() -> None:
    polluted = [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": "hello",
                    "delta": True,
                    "index": 0,
                },
            ],
        },
    ]
    formatter = _PollutedFormatter(polluted)
    wrapper = _ChatCompletionFormatterWrapper(formatter)

    sanitized = await wrapper.format([])

    assert sanitized == [
        {"role": "user", "content": [{"type": "text", "text": "hello"}]},
    ]
    assert polluted[0]["content"][0]["delta"] is True
    assert wrapper.relay_reasoning_content is True


async def test_call_api_sanitizes_formatted_messages_at_transport() -> None:
    polluted = [
        {
            "role": "system",
            "content": [
                {
                    "type": "input_text",
                    "text": "system prompt",
                    "status": "completed",
                },
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": "user prompt",
                    "delta": "user prompt",
                    "index": 0,
                    "status": "completed",
                    "object": "content",
                    "msg_id": "message-id",
                },
            ],
        },
    ]
    formatter = _PollutedFormatter(polluted)
    request_bodies: list[dict[str, Any]] = []

    async def handle_request(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        request_bodies.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "created": 0,
                "model": "test-model",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    },
                ],
            },
        )

    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(handle_request),
    )
    messages = [
        Msg(
            name="system",
            role="system",
            content=[TextBlock(text="system prompt")],
        ),
        Msg(
            name="user",
            role="user",
            content=[TextBlock(text="user prompt")],
        ),
    ]
    model = OpenAIChatModelCompat(
        credential=OpenAICredential(
            api_key="test-key",
            base_url="https://test.invalid/v1",
        ),
        model="test-model",
        stream=False,
        formatter=formatter,
        client_kwargs={"http_client": http_client},
    )

    try:
        response = await model._call_api("test-model", messages)
    finally:
        await http_client.aclose()

    assert response.is_last is True
    assert formatter.received_messages == messages
    assert request_bodies == [
        {
            "model": "test-model",
            "messages": [
                {
                    "role": "system",
                    "content": [{"type": "text", "text": "system prompt"}],
                },
                {
                    "role": "user",
                    "content": [{"type": "text", "text": "user prompt"}],
                },
            ],
            "stream": False,
        },
    ]
    assert polluted[0]["content"][0]["type"] == "input_text"
    assert polluted[1]["content"][0]["msg_id"] == "message-id"
