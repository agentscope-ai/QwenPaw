# -*- coding: utf-8 -*-
"""Tests for request-to-AgentScope message conversion."""

from qwenpaw.constant import (
    EXTERNAL_USER_QUERY_MESSAGE_TAG,
    QWENPAW_CLIENT_MESSAGE_ID_KEY,
    QWENPAW_MESSAGE_TAG_KEY,
)
from qwenpaw.runtime.message_convert import _request_input_to_msgs
from qwenpaw.schemas import (
    AudioContent,
    FileContent,
    ImageContent,
    Message,
    Role,
    TextContent,
    VideoContent,
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


def test_local_media_content_becomes_file_url_data_blocks(tmp_path):
    image_path = tmp_path / "pic.png"
    audio_path = tmp_path / "voice.mp3"
    video_path = tmp_path / "demo.mp4"
    file_path = tmp_path / "doc.pdf"

    messages = _request_input_to_msgs(
        [
            Message(
                role=Role.USER,
                content=[
                    ImageContent(image_url=str(image_path)),
                    AudioContent(data=str(audio_path)),
                    VideoContent(video_url=str(video_path)),
                    FileContent(file_url=str(file_path), filename="doc.pdf"),
                ],
            ),
        ],
    )

    assert [str(block.source.url) for block in messages[0].content] == [
        image_path.resolve().as_uri(),
        audio_path.resolve().as_uri(),
        video_path.resolve().as_uri(),
        file_path.resolve().as_uri(),
    ]
    assert [block.source.media_type for block in messages[0].content] == [
        "image/png",
        "audio/mpeg",
        "video/mp4",
        "application/octet-stream",
    ]
