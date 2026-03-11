# -*- coding: utf-8 -*-
from agentscope.message import Msg

from copaw.agents.model_factory import _normalize_messages_for_model


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
            "text": "[Local media omitted for model call: /tmp/a.png]",
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
            "text": "[Local media omitted for model call: C:/tmp/a.png]",
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
            "text": "[Local file omitted for model call: report.csv]",
        },
    ]
