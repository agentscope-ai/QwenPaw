# -*- coding: utf-8 -*-
from agentscope.message import Msg

from copaw.agents.model_factory import (
    _normalize_messages_for_model,
)


def test_normalize_string_content_to_text_block() -> None:
    msg = Msg(name="assistant", content="hello", role="assistant")

    normalized = _normalize_messages_for_model([msg])

    assert isinstance(normalized[0].content, list)
    assert normalized[0].content == [{"type": "text", "text": "hello"}]


def test_normalize_non_dict_block_to_text_block() -> None:
    msg = Msg(
        name="assistant",
        content=[{"type": "text", "text": "ok"}, 123],
        role="assistant",
    )

    normalized = _normalize_messages_for_model([msg])

    assert normalized[0].content == [
        {"type": "text", "text": "ok"},
        {"type": "text", "text": "123"},
    ]


def test_normalize_file_scheme_image_block() -> None:
    msg = Msg(
        name="assistant",
        content=[
            {
                "type": "image",
                "source": {"type": "url", "url": "file:///tmp/a.png"},
            },
        ],
        role="assistant",
    )

    normalized = _normalize_messages_for_model([msg])

    assert normalized[0].content == [
        {
            "type": "text",
            "text": "[Local media omitted for model call]",
        },
    ]


def test_normalize_windows_file_scheme_image_block() -> None:
    msg = Msg(
        name="assistant",
        content=[
            {
                "type": "image",
                "source": {
                    "type": "url",
                    "url": "file:///C:/tmp/a.png",
                },
            },
        ],
        role="assistant",
    )

    normalized = _normalize_messages_for_model([msg])

    assert normalized[0].content == [
        {
            "type": "text",
            "text": "[Local media omitted for model call]",
        },
    ]


def test_normalize_file_scheme_file_block() -> None:
    msg = Msg(
        name="assistant",
        content=[
            {
                "type": "file",
                "filename": "report.csv",
                "source": {
                    "type": "url",
                    "url": "file:///home/lcy/report.csv",
                },
            },
        ],
        role="assistant",
    )

    normalized = _normalize_messages_for_model([msg])

    assert normalized[0].content == [
        {
            "type": "text",
            "text": "[Local file omitted for model call]",
        },
    ]


def test_normalize_plain_local_path_image_block() -> None:
    msg = Msg(
        name="assistant",
        content=[
            {
                "type": "image",
                "source": {
                    "type": "url",
                    "url": "/tmp/plain-path.png",
                },
            },
        ],
        role="assistant",
    )

    normalized = _normalize_messages_for_model([msg])

    assert normalized[0].content == [
        {
            "type": "text",
            "text": "[Local media omitted for model call]",
        },
    ]


def test_normalize_plain_windows_path_image_block() -> None:
    msg = Msg(
        name="assistant",
        content=[
            {
                "type": "image",
                "source": {
                    "type": "url",
                    "url": "C:/tmp/plain-path.png",
                },
            },
        ],
        role="assistant",
    )

    normalized = _normalize_messages_for_model([msg])

    assert normalized[0].content == [
        {
            "type": "text",
            "text": "[Local media omitted for model call]",
        },
    ]


def test_normalize_local_media_in_tool_result_output() -> None:
    msg = Msg(
        name="system",
        content=[
            {
                "type": "tool_result",
                "id": "tool_123",
                "name": "send_file_to_user",
                "output": [
                    {
                        "type": "image",
                        "source": {
                            "type": "url",
                            "url": "file:///home/lcy/page-1773199016.png",
                        },
                    },
                    {"type": "text", "text": "已成功发送文件"},
                ],
            },
        ],
        role="system",
    )

    normalized = _normalize_messages_for_model([msg])

    assert normalized[0].content == [
        {
            "type": "tool_result",
            "id": "tool_123",
            "name": "send_file_to_user",
            "output": [
                {
                    "type": "text",
                    "text": "[Local media omitted for model call]",
                },
                {"type": "text", "text": "已成功发送文件"},
            ],
        },
    ]


def test_normalize_local_media_in_deep_nested_structure() -> None:
    msg = Msg(
        name="system",
        content=[
            {
                "type": "tool_result",
                "id": "tool_nested",
                "name": "complex_tool",
                "output": [
                    {
                        "type": "text",
                        "text": "result",
                    },
                    {
                        "nested": {
                            "items": [
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "url",
                                        "url": "file:///home/lcy/secret.png",
                                    },
                                },
                            ],
                        },
                    },
                ],
            },
        ],
        role="system",
    )

    normalized = _normalize_messages_for_model([msg])

    nested_item = normalized[0].content[0]["output"][1]["nested"]["items"][0]
    assert nested_item == {
        "type": "text",
        "text": "[Local media omitted for model call]",
    }


def test_normalize_uppercase_file_scheme_url() -> None:
    msg = Msg(
        name="assistant",
        content=[
            {
                "type": "image",
                "source": {
                    "type": "url",
                    "url": "FILE:///tmp/case.png",
                },
            },
        ],
        role="assistant",
    )

    normalized = _normalize_messages_for_model([msg])

    assert normalized[0].content == [
        {
            "type": "text",
            "text": "[Local media omitted for model call]",
        },
    ]


def test_normalize_relative_local_path_url() -> None:
    msg = Msg(
        name="assistant",
        content=[
            {
                "type": "image",
                "source": {
                    "type": "url",
                    "url": "./images/local.png",
                },
            },
        ],
        role="assistant",
    )

    normalized = _normalize_messages_for_model([msg])

    assert normalized[0].content == [
        {
            "type": "text",
            "text": "[Local media omitted for model call]",
        },
    ]


def test_normalize_plain_local_path_file_block() -> None:
    msg = Msg(
        name="assistant",
        content=[
            {
                "type": "file",
                "filename": "report.csv",
                "source": "/home/lcy/report.csv",
            },
        ],
        role="assistant",
    )

    normalized = _normalize_messages_for_model([msg])

    assert normalized[0].content == [
        {
            "type": "text",
            "text": "[Local file omitted for model call]",
        },
    ]


def test_normalize_non_dict_in_tool_result_output() -> None:
    msg = Msg(
        name="system",
        content=[
            {
                "type": "tool_result",
                "id": "tool_456",
                "name": "example_tool",
                "output": [
                    {"type": "text", "text": "ok"},
                    123,
                ],
            },
        ],
        role="system",
    )

    normalized = _normalize_messages_for_model([msg])

    assert normalized[0].content == [
        {
            "type": "tool_result",
            "id": "tool_456",
            "name": "example_tool",
            "output": [
                {"type": "text", "text": "ok"},
                {"type": "text", "text": "123"},
            ],
        },
    ]


def test_normalize_string_content_with_local_path_redacted() -> None:
    msg = Msg(
        name="assistant",
        content="saved at file:///home/lcy/secret.png and /tmp/a.png",
        role="assistant",
    )

    normalized = _normalize_messages_for_model([msg])

    assert normalized[0].content == [
        {
            "type": "text",
            "text": "saved at [LOCAL_PATH] and [LOCAL_PATH]",
        },
    ]


def test_normalize_string_content_keeps_https_url() -> None:
    msg = Msg(
        name="assistant",
        content="see https://example.com/a.png and /tmp/a.png",
        role="assistant",
    )

    normalized = _normalize_messages_for_model([msg])

    assert normalized[0].content == [
        {
            "type": "text",
            "text": "see https://example.com/a.png and [LOCAL_PATH]",
        },
    ]


def test_normalize_preserves_message_content_isolation() -> None:
    msg = Msg(
        name="assistant",
        content=[
            {
                "type": "image",
                "source": {
                    "type": "url",
                    "url": "file:///tmp/a.png",
                },
            },
            {"type": "text", "text": "hello"},
        ],
        role="assistant",
    )
    original_text_block = msg.content[1]

    normalized = _normalize_messages_for_model([msg])

    assert normalized[0].content[1] == original_text_block
    assert normalized[0].content[1] is not original_text_block
