# -*- coding: utf-8 -*-
"""Tests for message_request_normalizer module."""

# pylint: disable=redefined-outer-name,protected-access
import pytest
from agentscope.message import Msg, ToolResultBlock

from qwenpaw.agents.utils.message_request_normalizer import (
    _clone_msg,
    _clone_messages,
    _strip_media_blocks_in_place,
    normalize_messages_for_model_request,
)
from qwenpaw.constant import MEDIA_UNSUPPORTED_PLACEHOLDER


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture
def text_message():
    """Create a simple text message."""
    return Msg(
        name="user",
        role="user",
        content=[{"type": "text", "text": "Hello world"}],
    )


@pytest.fixture
def image_message():
    """Create a message with an image block."""
    return Msg(
        name="user",
        role="user",
        content=[
            {
                "type": "image",
                "source": {
                    "type": "url",
                    "url": "file:///tmp/test.png",
                },
            },
        ],
    )


@pytest.fixture
def video_message():
    """Create a message with a video block."""
    return Msg(
        name="user",
        role="user",
        content=[
            {
                "type": "video",
                "source": {
                    "type": "url",
                    "url": "file:///tmp/test.mp4",
                },
            },
        ],
    )


@pytest.fixture
def audio_message():
    """Create a message with an audio block."""
    return Msg(
        name="user",
        role="user",
        content=[
            {
                "type": "audio",
                "source": {
                    "type": "url",
                    "url": "file:///tmp/test.mp3",
                },
            },
        ],
    )


@pytest.fixture
def tool_result_with_image():
    """Create a tool result message with image in output."""
    return Msg(
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
                            "url": "file:///tmp/result.png",
                        },
                    },
                ],
            ),
        ],
    )


@pytest.fixture
def mixed_content_message():
    """Create a message with mixed content including media."""
    return Msg(
        name="user",
        role="user",
        content=[
            {"type": "text", "text": "Look at this:"},
            {
                "type": "image",
                "source": {
                    "type": "url",
                    "url": "file:///tmp/image.png",
                },
            },
            {"type": "text", "text": "And this video:"},
            {
                "type": "video",
                "source": {
                    "type": "url",
                    "url": "file:///tmp/video.mp4",
                },
            },
        ],
    )


# -----------------------------------------------------------------------------
# _clone_msg tests
# -----------------------------------------------------------------------------


def test_clone_msg_creates_independent_copy(text_message):
    """Test that _clone_msg creates a deep copy of the message."""
    cloned = _clone_msg(text_message)

    # Should be equal but not the same object
    assert cloned.to_dict() == text_message.to_dict()
    assert cloned is not text_message
    assert cloned.content is not text_message.content


def test_clone_msg_modifications_dont_affect_original(text_message):
    """Test that modifying clone doesn't affect original message."""
    cloned = _clone_msg(text_message)

    # Modify the clone
    cloned.content[0]["text"] = "Modified text"

    # Original should be unchanged
    assert text_message.content[0]["text"] == "Hello world"


# -----------------------------------------------------------------------------
# _clone_messages tests
# -----------------------------------------------------------------------------


def test_clone_messages_copies_list(text_message, image_message):
    """Test that _clone_messages copies a list of messages."""
    msgs = [text_message, image_message]
    cloned = _clone_messages(msgs)

    assert len(cloned) == 2
    assert cloned[0].to_dict() == text_message.to_dict()
    assert cloned[1].to_dict() == image_message.to_dict()
    assert cloned[0] is not text_message
    assert cloned[1] is not image_message


# -----------------------------------------------------------------------------
# _strip_media_blocks_in_place tests
# -----------------------------------------------------------------------------


def test_strip_media_blocks_removes_image(image_message):
    """Test that image blocks are removed and replaced with placeholder."""
    msgs = [image_message]
    count = _strip_media_blocks_in_place(msgs)

    assert count == 1
    assert len(msgs[0].content) == 1
    assert msgs[0].content[0]["type"] == "text"
    assert msgs[0].content[0]["text"] == MEDIA_UNSUPPORTED_PLACEHOLDER


def test_strip_media_blocks_removes_video(video_message):
    """Test that video blocks are removed and replaced with placeholder."""
    msgs = [video_message]
    count = _strip_media_blocks_in_place(msgs)

    assert count == 1
    assert len(msgs[0].content) == 1
    assert msgs[0].content[0]["type"] == "text"
    assert msgs[0].content[0]["text"] == MEDIA_UNSUPPORTED_PLACEHOLDER


def test_strip_media_blocks_removes_audio(audio_message):
    """Test that audio blocks are removed and replaced with placeholder."""
    msgs = [audio_message]
    count = _strip_media_blocks_in_place(msgs)

    assert count == 1
    assert len(msgs[0].content) == 1
    assert msgs[0].content[0]["type"] == "text"
    assert msgs[0].content[0]["text"] == MEDIA_UNSUPPORTED_PLACEHOLDER


def test_strip_media_blocks_handles_tool_result_with_media(
    tool_result_with_image,
):
    """Test that media blocks inside tool_result output are removed."""
    msgs = [tool_result_with_image]
    count = _strip_media_blocks_in_place(msgs)

    assert count == 1
    tool_result = msgs[0].content[0]
    assert tool_result["output"] == MEDIA_UNSUPPORTED_PLACEHOLDER


def test_strip_media_blocks_handles_mixed_content(mixed_content_message):
    """Test that mixed content has only media blocks removed."""
    msgs = [mixed_content_message]
    count = _strip_media_blocks_in_place(msgs)

    assert count == 2  # image + video
    # Should have 2 text blocks remaining
    assert len(msgs[0].content) == 2
    assert msgs[0].content[0]["type"] == "text"
    assert msgs[0].content[0]["text"] == "Look at this:"
    assert msgs[0].content[1]["type"] == "text"
    assert msgs[0].content[1]["text"] == "And this video:"


def test_strip_media_blocks_preserves_non_media_content(text_message):
    """Test that non-media content is preserved."""
    msgs = [text_message]
    count = _strip_media_blocks_in_place(msgs)

    assert count == 0
    assert msgs[0].content == text_message.content


def test_strip_media_blocks_handles_empty_content():
    """Test that messages with empty content are handled gracefully."""
    msg = Msg(name="user", role="user", content=[])
    msgs = [msg]
    count = _strip_media_blocks_in_place(msgs)

    assert count == 0
    assert msgs[0].content == []


def test_strip_media_blocks_handles_string_content():
    """Test that messages with string content are skipped."""
    msg = Msg(name="user", role="user", content="Plain text message")
    msgs = [msg]
    count = _strip_media_blocks_in_place(msgs)

    assert count == 0
    assert msgs[0].content == "Plain text message"


# -----------------------------------------------------------------------------
# normalize_messages_for_model_request tests
# -----------------------------------------------------------------------------


def test_normalize_with_multimodal_support_keeps_media(image_message):
    """Test that media is preserved when multimodal is supported."""
    msgs = [image_message]
    normalized = normalize_messages_for_model_request(
        msgs,
        supports_multimodal=True,
    )

    # Original should be unchanged
    assert msgs[0].content[0]["type"] == "image"

    # Normalized copy should also have media
    assert normalized[0].content[0]["type"] == "image"
    assert normalized[0] is not msgs[0]


def test_normalize_without_multimodal_support_strips_media(image_message):
    """Test that media is stripped when multimodal is not supported."""
    msgs = [image_message]
    normalized = normalize_messages_for_model_request(
        msgs,
        supports_multimodal=False,
    )

    # Original should be unchanged
    assert msgs[0].content[0]["type"] == "image"

    # Normalized should have placeholder
    assert normalized[0].content[0]["type"] == "text"
    assert normalized[0].content[0]["text"] == MEDIA_UNSUPPORTED_PLACEHOLDER


def test_normalize_preserves_original_messages(mixed_content_message):
    """Test that original messages are never modified."""
    original_dict = mixed_content_message.to_dict()

    normalize_messages_for_model_request(
        [mixed_content_message],
        supports_multimodal=False,
    )

    # Original should be exactly the same
    assert mixed_content_message.to_dict() == original_dict


def test_normalize_returns_new_message_instances(text_message):
    """Test that normalized messages are new instances."""
    msgs = [text_message]
    normalized = normalize_messages_for_model_request(
        msgs,
        supports_multimodal=True,
    )

    assert normalized[0] is not msgs[0]
    assert normalized[0].content is not msgs[0].content


# -----------------------------------------------------------------------------
# Integration tests with multiple messages
# -----------------------------------------------------------------------------


def test_normalize_conversation_with_multiple_messages():
    """Test normalizing a conversation with multiple messages."""
    msgs = [
        Msg(
            name="user",
            role="user",
            content=[
                {"type": "text", "text": "Hello"},
                {
                    "type": "image",
                    "source": {"type": "url", "url": "file:///tmp/1.png"},
                },
            ],
        ),
        Msg(
            name="assistant",
            role="assistant",
            content=[{"type": "text", "text": "I see the image"}],
        ),
        Msg(
            name="user",
            role="user",
            content=[
                {
                    "type": "video",
                    "source": {"type": "url", "url": "file:///tmp/1.mp4"},
                },
            ],
        ),
    ]

    normalized = normalize_messages_for_model_request(
        msgs,
        supports_multimodal=False,
    )

    # First message: text preserved, image stripped
    assert len(normalized[0].content) == 1
    assert normalized[0].content[0]["text"] == "Hello"

    # Second message: unchanged
    assert normalized[1].content == [
        {"type": "text", "text": "I see the image"},
    ]

    # Third message: video replaced with placeholder
    assert len(normalized[2].content) == 1
    assert normalized[2].content[0]["text"] == MEDIA_UNSUPPORTED_PLACEHOLDER

    # Originals unchanged
    assert msgs[0].content[1]["type"] == "image"
    assert msgs[2].content[0]["type"] == "video"
