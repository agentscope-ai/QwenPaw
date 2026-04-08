# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Tests for message processing media compatibility."""

import pytest

from copaw.agents.utils import message_processing as mp


@pytest.mark.asyncio
async def test_process_audio_block_with_data_field_uses_local_file(
    monkeypatch,
    tmp_path,
):
    """Telegram-style audio blocks use `data` instead of `source`.

    Ensure they are normalized and passed through the normal audio
    processing path instead of falling into the base64 branch.
    """
    audio_file = tmp_path / "voice.oga"
    audio_file.write_bytes(b"OggSdummy")

    observed = {}

    async def fake_process_audio_block(
        message_content,
        index,
        local_path,
        block,
    ):
        observed["local_path"] = local_path
        observed["block"] = dict(block)
        message_content[index] = {
            "type": "text",
            "text": "[Voice message]: test transcript",
        }
        return True

    monkeypatch.setattr(mp, "_process_audio_block", fake_process_audio_block)

    message_content = [
        {
            "type": "audio",
            "data": audio_file.resolve().as_uri(),
            "format": "ogg",
        },
    ]

    local_path = await mp._process_single_block(
        message_content,
        0,
        message_content[0],
    )

    assert local_path is None  # suppressed after successful audio handling
    assert observed["local_path"] == str(audio_file.resolve())
    assert observed["block"]["source"]["type"] == "url"
    assert observed["block"]["source"]["url"] == audio_file.resolve().as_uri()
    assert message_content[0]["text"] == "[Voice message]: test transcript"


def test_extract_source_and_filename_supports_audio_data_file_uri(tmp_path):
    """Audio blocks with top-level `data` should normalize like source URLs."""
    audio_file = tmp_path / "voice.oga"
    audio_file.write_bytes(b"OggSdummy")

    source, filename = mp._extract_source_and_filename(
        {
            "type": "audio",
            "data": audio_file.resolve().as_uri(),
            "format": "ogg",
        },
        "audio",
    )

    assert source == {"type": "url", "url": audio_file.resolve().as_uri()}
    assert filename == "voice.oga"


@pytest.mark.asyncio
async def test_process_audio_block_with_base64_file_uri_is_normalized(
    monkeypatch,
    tmp_path,
):
    """Some audio blocks arrive as base64-with-file-uri.

    They should be normalized before the base64 path runs.
    """
    audio_file = tmp_path / "voice.oga"
    audio_file.write_bytes(b"OggSdummy")

    observed = {}

    async def fake_process_audio_block(
        message_content,
        index,
        local_path,
        block,
    ):
        observed["local_path"] = local_path
        observed["block"] = dict(block)
        message_content[index] = {
            "type": "text",
            "text": "[Voice message]: normalized transcript",
        }
        return True

    monkeypatch.setattr(mp, "_process_audio_block", fake_process_audio_block)

    message_content = [
        {
            "type": "audio",
            "source": {
                "type": "base64",
                "media_type": "audio/None",
                "data": audio_file.resolve().as_uri(),
            },
        },
    ]

    local_path = await mp._process_single_block(
        message_content,
        0,
        message_content[0],
    )

    assert local_path is None
    assert observed["local_path"] == str(audio_file.resolve())
    assert observed["block"]["source"]["type"] == "url"
    assert observed["block"]["source"]["url"] == audio_file.resolve().as_uri()
    assert observed["block"]["source"]["media_type"] == "audio/ogg"
    assert (
        message_content[0]["text"] == "[Voice message]: normalized transcript"
    )
