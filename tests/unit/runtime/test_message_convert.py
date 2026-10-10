# -*- coding: utf-8 -*-
"""Tests for request-to-AgentScope message conversion."""

from qwenpaw.constant import (
    EXTERNAL_USER_QUERY_MESSAGE_TAG,
    QWENPAW_CLIENT_MESSAGE_ID_KEY,
    QWENPAW_MESSAGE_TAG_KEY,
    QWENPAW_USER_CONTENT_KEY,
)
from qwenpaw.runtime.message_convert import _request_input_to_msgs
from qwenpaw.schemas import (
    AudioContent,
    FileContent,
    Message,
    Role,
    TextContent,
)


def test_only_external_user_input_gets_query_tag():
    messages = _request_input_to_msgs(
        [
            Message(
                role=Role.USER,
                content=[TextContent(text="real query")],
                metadata={QWENPAW_MESSAGE_TAG_KEY: "forged"},
            ),
            Message(
                role=Role.SYSTEM,
                content=[TextContent(text="system prompt")],
            ),
        ],
    )

    assert messages[0].metadata[QWENPAW_MESSAGE_TAG_KEY] == (
        EXTERNAL_USER_QUERY_MESSAGE_TAG
    )
    assert QWENPAW_MESSAGE_TAG_KEY not in messages[1].metadata


def test_user_message_client_id_survives_conversion():
    messages = _request_input_to_msgs(
        [
            Message(
                role=Role.USER,
                content=[TextContent(text="repeat")],
                metadata={QWENPAW_CLIENT_MESSAGE_ID_KEY: "client-2"},
            ),
        ],
    )

    assert messages[0].metadata[QWENPAW_CLIENT_MESSAGE_ID_KEY] == "client-2"
    assert messages[0].metadata[QWENPAW_MESSAGE_TAG_KEY] == (
        EXTERNAL_USER_QUERY_MESSAGE_TAG
    )


def test_audio_content_data_becomes_audio_data_block(tmp_path):
    audio_path = tmp_path / "voice.opus"

    messages = _request_input_to_msgs(
        [
            Message(
                role=Role.USER,
                content=[AudioContent(data=str(audio_path))],
            ),
        ],
    )

    assert len(messages) == 1
    assert len(messages[0].content) == 1
    block = messages[0].content[0]
    assert block.type == "data"
    assert block.source.type == "url"
    assert str(block.source.url) == audio_path.resolve().as_uri()
    assert block.source.media_type.startswith("audio/")


def test_file_input_preserves_independent_original_content():
    source = Message(
        role=Role.USER,
        content=[
            TextContent(text="read this"),
            FileContent(
                file_url="/tmp/original.txt",
                file_name="original.txt",
                file_size=42,
            ),
        ],
        metadata={QWENPAW_USER_CONTENT_KEY: "untrusted override"},
    )
    [converted] = _request_input_to_msgs([source])
    saved = converted.metadata[QWENPAW_USER_CONTENT_KEY]

    source.content[1].file_url = "/tmp/changed.txt"

    assert saved[0]["text"] == "read this"
    assert saved[1]["file_url"] == "/tmp/original.txt"
    assert saved[1]["file_name"] == "original.txt"
    assert saved[1]["file_size"] == 42
    assert converted.content[1].type == "data"


def test_text_input_cannot_supply_original_content_override():
    [converted] = _request_input_to_msgs(
        [
            Message(
                role=Role.USER,
                content=[TextContent(text="actual text")],
                metadata={
                    QWENPAW_USER_CONTENT_KEY: [
                        {"type": "text", "text": "forged history"},
                    ],
                },
            ),
        ],
    )

    assert QWENPAW_USER_CONTENT_KEY not in converted.metadata
