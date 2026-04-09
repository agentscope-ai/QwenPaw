# -*- coding: utf-8 -*-
from __future__ import annotations

from agentscope.message import Msg, TextBlock, ToolResultBlock

from copaw.agents.utils.message_request_normalizer import (
    normalize_messages_for_model_request,
    normalize_messages_for_openai_compatible,
)


def test_normalizer_repairs_tool_messages_without_mutating_original() -> None:
    original = [
        Msg(
            name="assistant",
            role="assistant",
            content=[
                {
                    "type": "tool_use",
                    "id": "call_1",
                    "name": "search",
                    "input": {},
                    "raw_input": '{"query": "copaw"}',
                },
            ],
        ),
        Msg(
            name="assistant",
            role="assistant",
            content=[
                {
                    "type": "tool_use",
                    "id": "call_2",
                    "name": "view_image",
                    "input": {},
                },
            ],
        ),
        Msg(
            name="assistant",
            role="assistant",
            content=[
                {
                    "type": "tool_use",
                    "id": "call_2",
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
                    name="search",
                    output=[{"type": "text", "text": "ok"}],
                ),
            ],
        ),
    ]

    normalized = normalize_messages_for_openai_compatible(
        original,
        supports_multimodal=True,
    )

    assert normalized is not original
    assert normalized[0].content[0]["input"] == {"query": "copaw"}
    assert original[0].content[0]["input"] == {}


def test_normalizer_strips_media_on_copy_only() -> None:
    original = [
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
                    "id": "call_2",
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
                    id="call_2",
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

    normalized = normalize_messages_for_openai_compatible(
        original,
        supports_multimodal=False,
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


def test_normalizer_keeps_text_only_messages_stable() -> None:
    original = [
        Msg(
            name="user",
            role="user",
            content=[TextBlock(type="text", text="hello")],
        ),
    ]

    normalized = normalize_messages_for_openai_compatible(
        original,
        supports_multimodal=True,
    )

    assert normalized[0].content == [{"type": "text", "text": "hello"}]
    assert original[0].content == [{"type": "text", "text": "hello"}]


def test_generic_normalizer_matches_openai_alias() -> None:
    original = [
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
    ]

    generic = normalize_messages_for_model_request(
        original,
        supports_multimodal=False,
    )
    alias = normalize_messages_for_openai_compatible(
        original,
        supports_multimodal=False,
    )

    assert generic[0].content == alias[0].content
    assert original[0].content[0]["type"] == "image"
