# -*- coding: utf-8 -*-
"""Tests for message_processing utils.

Covers:
- is_first_user_interaction
- prepend_to_message_content
"""
# pylint: disable=redefined-outer-name
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agentscope.message import DataBlock, Msg, TextBlock, URLSource

from qwenpaw.agents.utils.message_processing import (
    _process_audio_block,
    is_first_user_interaction,
    prepend_to_message_content,
    process_file_and_media_blocks_in_message,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _msg(role: str, content="content"):
    m = MagicMock()
    m.role = role
    m.content = content
    return m


def _audio_message(audio_path, media_type="audio/opus"):
    block = DataBlock(
        source=URLSource(
            url=audio_path.resolve().as_uri(),
            media_type=media_type,
        ),
    )
    return Msg(name="user", role="user", content=[block]), block


def _mock_transcription(result=None):
    return patch(
        "qwenpaw.agents.utils.audio_transcription.transcribe_audio",
        new=AsyncMock(return_value=result),
    )


@pytest.fixture
def _audio_config():
    config = MagicMock()
    config.agents.audio_mode = "auto"
    config.agents.language = "en"
    with patch(
        "qwenpaw.agents.utils.message_processing.load_config",
        return_value=config,
    ):
        yield config


# ---------------------------------------------------------------------------
# is_first_user_interaction
# ---------------------------------------------------------------------------


class TestIsFirstUserInteraction:
    """P0: first user interaction detection."""

    def test_empty_messages_returns_false(self):
        assert is_first_user_interaction([]) is False

    def test_single_user_no_assistant_is_first(self):
        msgs = [_msg("user")]
        assert is_first_user_interaction(msgs) is True

    def test_user_with_assistant_is_not_first(self):
        msgs = [_msg("user"), _msg("assistant")]
        assert is_first_user_interaction(msgs) is False

    def test_multiple_users_is_not_first(self):
        msgs = [_msg("user"), _msg("user")]
        assert is_first_user_interaction(msgs) is False

    def test_system_then_user_is_first(self):
        """System messages before the user message are skipped."""
        msgs = [_msg("system"), _msg("user")]
        assert is_first_user_interaction(msgs) is True

    def test_multiple_system_then_user_is_first(self):
        msgs = [_msg("system"), _msg("system"), _msg("user")]
        assert is_first_user_interaction(msgs) is True

    def test_system_user_assistant_is_not_first(self):
        msgs = [_msg("system"), _msg("user"), _msg("assistant")]
        assert is_first_user_interaction(msgs) is False

    def test_only_system_messages_returns_false(self):
        msgs = [_msg("system"), _msg("system")]
        assert is_first_user_interaction(msgs) is False

    def test_only_assistant_returns_false(self):
        msgs = [_msg("assistant")]
        assert is_first_user_interaction(msgs) is False


# ---------------------------------------------------------------------------
# prepend_to_message_content
# ---------------------------------------------------------------------------


class TestPrependToMessageContent:
    """P0: guidance text is prepended to the message."""

    def test_prepend_to_string_content(self):
        msg = _msg("user", content="hello")
        prepend_to_message_content(msg, "guidance")
        assert msg.content == "guidance\n\nhello"

    def test_prepend_to_string_content_empty_string(self):
        msg = _msg("user", content="")
        prepend_to_message_content(msg, "guidance")
        assert msg.content == "guidance\n\n"

    def test_prepend_to_list_with_text_block(self):
        """Prepends into the first text block dict."""
        msg = _msg(
            "user",
            content=[
                {"type": "text", "text": "original"},
            ],
        )
        prepend_to_message_content(msg, "guidance")
        assert msg.content[0]["text"] == "guidance\n\noriginal"

    def test_prepend_inserts_block_when_no_text_block(self):
        """No text block → inserts new block at start."""
        msg = _msg(
            "user",
            content=[
                {"type": "image", "url": "http://img"},
            ],
        )
        prepend_to_message_content(msg, "guidance")
        first = msg.content[0]
        assert getattr(first, "type", None) == "text"
        assert getattr(first, "text", None) == "guidance"

    def test_prepend_to_non_list_non_str_content_noop(self):
        """Non-string, non-list content is left untouched."""
        msg = _msg("user", content=42)
        prepend_to_message_content(msg, "guidance")
        assert msg.content == 42

    def test_prepend_modifies_first_text_block_only(self):
        """Only the first text block is modified."""
        msg = _msg(
            "user",
            content=[
                {"type": "text", "text": "first"},
                {"type": "text", "text": "second"},
            ],
        )
        prepend_to_message_content(msg, "guidance")
        assert msg.content[0]["text"] == "guidance\n\nfirst"
        assert msg.content[1]["text"] == "second"

    def test_prepend_preserves_other_blocks(self):
        """Non-text blocks after the text block are preserved."""
        msg = _msg(
            "user",
            content=[
                {"type": "text", "text": "text"},
                {"type": "image", "url": "http://img"},
            ],
        )
        prepend_to_message_content(msg, "guidance")
        assert len(msg.content) == 2
        assert msg.content[1]["type"] == "image"


class TestProcessAudioDataBlock:
    """P0: local AgentScope audio blocks reach transcription."""

    @pytest.mark.asyncio
    async def test_local_audio_is_replaced_with_transcription(
        self,
        tmp_path,
        _audio_config,
    ):
        audio_path = tmp_path / "voice note.opus"
        msg, _ = _audio_message(audio_path)

        with _mock_transcription("hello from voice") as transcribe:
            await process_file_and_media_blocks_in_message(msg)

        transcribe.assert_awaited_once_with(str(audio_path.resolve()))
        assert len(msg.content) == 1
        assert isinstance(msg.content[0], TextBlock)
        assert msg.content[0].text == "[Voice message]: hello from voice"

    @pytest.mark.asyncio
    async def test_failed_transcription_keeps_local_path_hint(
        self,
        tmp_path,
        _audio_config,
    ):
        audio_path = tmp_path / "voice.opus"
        msg, _ = _audio_message(audio_path)

        with _mock_transcription():
            await process_file_and_media_blocks_in_message(msg)

        assert len(msg.content) == 2
        assert isinstance(msg.content[0], TextBlock)
        assert msg.content[0].text == "[Voice message]: (audio file received)"
        assert isinstance(msg.content[1], TextBlock)
        assert str(audio_path.resolve()) in msg.content[1].text

    @pytest.mark.asyncio
    async def test_native_audio_remains_data_block(
        self,
        tmp_path,
        _audio_config,
    ):
        audio_path = tmp_path / "voice.wav"
        msg, block = _audio_message(audio_path, "audio/wav")
        _audio_config.agents.audio_mode = "native"

        with _mock_transcription() as transcribe:
            await process_file_and_media_blocks_in_message(msg)

        transcribe.assert_not_awaited()
        assert msg.content == [block]
        assert block.source.media_type == "audio/wav"

    @pytest.mark.asyncio
    async def test_legacy_audio_replacement_remains_dict(
        self,
        tmp_path,
        _audio_config,
    ):
        audio_path = tmp_path / "voice.opus"
        block = {
            "type": "audio",
            "source": {
                "type": "url",
                "url": audio_path.resolve().as_uri(),
                "media_type": "audio/opus",
            },
        }
        content = [block]

        with _mock_transcription("legacy voice"):
            handled = await _process_audio_block(
                content,
                0,
                str(audio_path),
                block,
            )

        assert handled is True
        assert content == [
            {"type": "text", "text": "[Voice message]: legacy voice"},
        ]
