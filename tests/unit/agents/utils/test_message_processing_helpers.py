# -*- coding: utf-8 -*-
"""Tests for message-processing pure helpers.

Covers _audio_text_block, _extract_source_and_filename,
_quote_display_filename (security bounding), _format_uploaded_file_hint
(localization), _media_type_from_path, _local_file_url,
_update_block_with_local_path, _handle_download_failure,
is_first_user_interaction, prepend_to_message_content, and
_coerce_block_to_dict, which were previously untested.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

from types import SimpleNamespace

import pytest
from agentscope.message import TextBlock

from qwenpaw.agents.utils import message_processing as mp


# ---------------------------------------------------------------------------
# _audio_text_block
# ---------------------------------------------------------------------------


class TestAudioTextBlock:
    def test_dict_block_returns_dict(self):
        result = mp._audio_text_block({"type": "audio"}, "transcribed")
        assert result == {"type": "text", "text": "transcribed"}

    def test_object_block_returns_textblock(self):
        result = mp._audio_text_block(TextBlock(text="old"), "transcribed")
        assert isinstance(result, TextBlock)
        assert result.text == "transcribed"


# ---------------------------------------------------------------------------
# _extract_source_and_filename
# ---------------------------------------------------------------------------


class TestExtractSourceAndFilename:
    def test_file_block(self):
        block = {"source": {"x": 1}, "filename": "a.pdf"}
        source, filename = mp._extract_source_and_filename(block, "file")
        assert source == {"x": 1}
        assert filename == "a.pdf"

    def test_file_block_missing_filename(self):
        block = {"source": {"x": 1}}
        source, filename = mp._extract_source_and_filename(block, "file")
        # A "file" block returns its source dict verbatim.
        assert source == {"x": 1}
        assert filename is None

    def test_media_block_url_source(self):
        block = {
            "source": {
                "type": "url",
                "url": "https://cdn.example.com/a/b.png",
            },
        }
        source, filename = mp._extract_source_and_filename(block, "image")
        assert filename == "b.png"
        assert source["type"] == "url"

    def test_media_block_non_dict_source(self):
        block = {"source": "plain-string"}
        source, filename = mp._extract_source_and_filename(block, "image")
        assert source is None
        assert filename is None

    def test_media_block_base64_source_no_filename(self):
        block = {"source": {"type": "base64", "data": "abc"}}
        source, filename = mp._extract_source_and_filename(block, "audio")
        assert source["type"] == "base64"
        assert filename is None

    def test_url_without_path_gives_no_filename(self):
        block = {"source": {"type": "url", "url": "https://example.com"}}
        _, filename = mp._extract_source_and_filename(block, "video")
        assert filename is None


# ---------------------------------------------------------------------------
# _quote_display_filename (security-critical bounding)
# ---------------------------------------------------------------------------


class TestQuoteDisplayFilename:
    def test_simple_name_quoted(self):
        assert mp._quote_display_filename("report.pdf") == '"report.pdf"'

    def test_non_string_returns_none(self):
        assert mp._quote_display_filename(123) is None
        assert mp._quote_display_filename(None) is None

    def test_dot_entries_rejected(self):
        assert mp._quote_display_filename(".") is None
        assert mp._quote_display_filename("..") is None

    def test_windows_path_basenames(self):
        assert mp._quote_display_filename("C:\\dir\\file.txt") == (
            '"file.txt"'
        )

    def test_long_name_truncated(self):
        long_name = "x" * 500
        result = mp._quote_display_filename(long_name)
        # quoted result includes the 200-char bound plus quotes
        assert result == '"' + "x" * 200 + '"'

    def test_non_printable_chars_escaped(self):
        result = mp._quote_display_filename("a\u2028b")
        assert "\u2028" not in result
        assert "a" in result and "b" in result

    def test_unicode_kept_readable(self):
        result = mp._quote_display_filename("报告.pdf")
        assert "报告.pdf" in result


# ---------------------------------------------------------------------------
# _format_uploaded_file_hint
# ---------------------------------------------------------------------------


class TestFormatUploadedFileHint:
    def test_chinese_with_filename(self):
        result = mp._format_uploaded_file_hint("/tmp/f", "a.pdf", "zh")
        assert "用户上传文件" in result
        assert '"a.pdf"' in result
        assert "/tmp/f" in result

    def test_english_without_filename(self):
        result = mp._format_uploaded_file_hint("/tmp/f", None, "en")
        assert result == "User uploaded a file, downloaded to /tmp/f"

    def test_chinese_without_filename(self):
        result = mp._format_uploaded_file_hint("/tmp/f", None, "zh")
        assert result == "用户上传文件，已经下载到 /tmp/f"


# ---------------------------------------------------------------------------
# _media_type_from_path
# ---------------------------------------------------------------------------


class TestMediaTypeFromPath:
    @pytest.mark.parametrize(
        ("path", "expected"),
        [
            ("a.amr", "audio/amr"),
            ("a.wav", "audio/wav"),
            ("a.mp3", "audio/mp3"),
            ("a.opus", "audio/opus"),
            ("a.ogg", "audio/ogg"),
            ("a.flac", "audio/flac"),
            ("a.m4a", "audio/mp4"),
            ("a.aac", "audio/aac"),
        ],
    )
    def test_known_extensions(self, path, expected):
        assert mp._media_type_from_path(path) == expected

    def test_unknown_falls_back(self):
        assert mp._media_type_from_path("a.xyz") == "audio/octet-stream"
        assert mp._media_type_from_path("noext") == "audio/octet-stream"

    def test_case_insensitive(self):
        assert mp._media_type_from_path("A.WAV") == "audio/wav"


# ---------------------------------------------------------------------------
# _local_file_url
# ---------------------------------------------------------------------------


class TestLocalFileUrl:
    def test_file_url_prefix(self, tmp_path):
        target = tmp_path / "f.wav"
        target.write_bytes(b"x")
        url = mp._local_file_url(str(target))
        assert url == f"file://{target.resolve()}"

    def test_relative_path_resolved(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        url = mp._local_file_url("rel.txt")
        assert url.startswith("file://")
        assert str(tmp_path / "rel.txt") in url


# ---------------------------------------------------------------------------
# _update_block_with_local_path
# ---------------------------------------------------------------------------


class TestUpdateBlockWithLocalPath:
    def test_file_block_source_set_and_filename_defaulted(self):
        block = {}
        result = mp._update_block_with_local_path(
            block,
            "file",
            "/tmp/downloaded.pdf",
        )
        assert result["source"] == "/tmp/downloaded.pdf"
        assert result["filename"] == "downloaded.pdf"

    def test_file_block_keeps_existing_filename(self):
        block = {"filename": "orig.pdf"}
        result = mp._update_block_with_local_path(block, "file", "/tmp/x.pdf")
        assert result["filename"] == "orig.pdf"

    def test_audio_block_gets_url_source_with_media_type(self):
        block = {}
        result = mp._update_block_with_local_path(
            block,
            "audio",
            "/tmp/voice.wav",
        )
        assert result["source"]["type"] == "url"
        assert result["source"]["url"].startswith("file://")
        assert result["source"]["media_type"] == "audio/wav"


# ---------------------------------------------------------------------------
# _handle_download_failure
# ---------------------------------------------------------------------------


class TestHandleDownloadFailure:
    def test_file_failure_returns_error_text(self):
        result = mp._handle_download_failure("file")
        assert result["type"] == "text"
        assert "Error" in result["text"]

    def test_media_failure_returns_none(self):
        assert mp._handle_download_failure("image") is None
        assert mp._handle_download_failure("audio") is None


# ---------------------------------------------------------------------------
# is_first_user_interaction
# ---------------------------------------------------------------------------


def _msg(role):
    return SimpleNamespace(role=role)


class TestIsFirstUserInteraction:
    def test_first_interaction(self):
        messages = [_msg("system"), _msg("user")]
        assert mp.is_first_user_interaction(messages) is True

    def test_with_assistant_reply_not_first(self):
        messages = [_msg("user"), _msg("assistant")]
        assert mp.is_first_user_interaction(messages) is False

    def test_multiple_user_messages_not_first(self):
        messages = [_msg("user"), _msg("user")]
        assert mp.is_first_user_interaction(messages) is False

    def test_system_prompts_ignored(self):
        messages = [_msg("system"), _msg("system"), _msg("user")]
        assert mp.is_first_user_interaction(messages) is True

    def test_empty_messages(self):
        assert mp.is_first_user_interaction([]) is False


# ---------------------------------------------------------------------------
# prepend_to_message_content
# ---------------------------------------------------------------------------


class TestPrependToMessageContent:
    def test_string_content_prepended(self):
        msg = SimpleNamespace(content="hello")
        mp.prepend_to_message_content(msg, "guidance")
        assert msg.content == "guidance\n\nhello"

    def test_dict_text_block_prepended(self):
        msg = SimpleNamespace(
            content=[{"type": "text", "text": "body"}],
        )
        mp.prepend_to_message_content(msg, "note")
        assert msg.content[0]["text"].startswith("note")

    def test_non_text_first_block_inserts_new(self):
        msg = SimpleNamespace(
            content=[{"type": "image", "source": "x"}],
        )
        mp.prepend_to_message_content(msg, "note")
        inserted = msg.content[0]
        # Inserted block is a TextBlock (pydantic), not a dict.
        assert getattr(inserted, "type", None) == "text"
        assert getattr(inserted, "text", None) == "note"

    def test_unsupported_content_type_untouched(self):
        msg = SimpleNamespace(content=42)
        mp.prepend_to_message_content(msg, "guidance")
        assert msg.content == 42


# ---------------------------------------------------------------------------
# _coerce_block_to_dict
# ---------------------------------------------------------------------------


class TestCoerceBlockToDict:
    def test_dict_passthrough(self):
        block = {"type": "image"}
        assert mp._coerce_block_to_dict(block) is block

    def test_text_block_returns_none(self):
        assert mp._coerce_block_to_dict(TextBlock(text="x")) is None

    def test_data_block_url_image_mapped(self):
        source = SimpleNamespace(
            type="url",
            url="https://x/a.png",
            media_type="image/png",
        )
        block = SimpleNamespace(type="data", source=source, name="a.png")
        result = mp._coerce_block_to_dict(block)
        assert result["type"] == "image"
        assert result["source"]["type"] == "url"
        assert result["filename"] == "a.png"

    def test_data_block_file_url_strips_file_prefix(self):
        source = SimpleNamespace(
            type="url",
            url="file:///tmp/x.png",
            media_type="image/png",
        )
        block = SimpleNamespace(type="data", source=source, name=None)
        result = mp._coerce_block_to_dict(block)
        assert result["source"]["url"] == "/tmp/x.png"

    def test_data_block_base64_audio(self):
        source = SimpleNamespace(
            type="base64",
            data="abc",
            media_type="audio/wav",
        )
        block = SimpleNamespace(type="data", source=source, name="v.wav")
        result = mp._coerce_block_to_dict(block)
        assert result["type"] == "audio"
        assert result["source"]["data"] == "abc"

    def test_data_block_application_maps_to_file(self):
        source = SimpleNamespace(
            type="base64",
            data="abc",
            media_type="application/pdf",
        )
        block = SimpleNamespace(type="data", source=source, name="d.pdf")
        result = mp._coerce_block_to_dict(block)
        assert result["type"] == "file"

    def test_data_block_no_source_returns_none(self):
        block = SimpleNamespace(type="data", source=None)
        assert mp._coerce_block_to_dict(block) is None

    def test_data_block_unknown_source_type_returns_none(self):
        source = SimpleNamespace(type="weird", media_type="image/png")
        block = SimpleNamespace(type="data", source=source)
        assert mp._coerce_block_to_dict(block) is None

    def test_pydantic_media_block_model_dumped(self):
        class FakeBlock:
            type = "image"

            def model_dump(self):
                return {"type": "image", "source": {"url": "u"}}

        result = mp._coerce_block_to_dict(FakeBlock())
        assert result["type"] == "image"

    def test_plain_object_media_block_without_dump_returns_none(self):
        block = SimpleNamespace(type="image")
        assert mp._coerce_block_to_dict(block) is None
