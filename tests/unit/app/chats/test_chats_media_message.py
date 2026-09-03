# -*- coding: utf-8 -*-
"""Tests for chat message media-block building and legacy memory parsing.

Covers _build_media_message_from_block (image/audio/video/file from url
and base64 sources), parse_legacy_memory_state (marks stripping, summary
extraction), and the nested _resolve_media_type classification, which
previously had no coverage.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument,use-implicit-booleaness-not-comparison  # noqa: E501
from __future__ import annotations


from agentscope.message import Msg, TextBlock

from qwenpaw.app.chats.utils import (
    _build_media_message_from_block,
    parse_legacy_memory_state,
)
from qwenpaw.schemas import ContentType


META = {"original_id": "id-1"}


# ---------------------------------------------------------------------------
# _build_media_message_from_block
# ---------------------------------------------------------------------------


class TestBuildMediaMessageFromBlock:
    def test_image_from_url(self):
        block = {
            "output": [
                {
                    "type": "image",
                    "source": {"type": "url", "url": "https://x/a.png"},
                },
            ],
        }
        msg = _build_media_message_from_block(block, "assistant", META)
        assert msg is not None
        assert msg.metadata == META
        content = msg.content[0]
        assert content.type == ContentType.IMAGE

    def test_image_from_base64(self):
        block = {
            "output": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": "aGk=",
                    },
                },
            ],
        }
        msg = _build_media_message_from_block(block, "assistant", META)
        content = msg.content[0]
        assert content.type == ContentType.IMAGE
        assert "data:image/png;base64,aGk=" in content.image_url

    def test_audio_from_url_with_format(self):
        block = {
            "output": [
                {
                    "type": "audio",
                    "source": {"type": "url", "url": "https://x/a.mp3"},
                },
            ],
        }
        msg = _build_media_message_from_block(block, "assistant", META)
        content = msg.content[0]
        assert content.type == ContentType.AUDIO

    def test_audio_from_base64(self):
        block = {
            "output": [
                {
                    "type": "audio",
                    "source": {
                        "type": "base64",
                        "media_type": "audio/wav",
                        "data": "aGk=",
                    },
                },
            ],
        }
        msg = _build_media_message_from_block(block, "assistant", META)
        content = msg.content[0]
        assert content.type == ContentType.AUDIO

    def test_video_from_url(self):
        block = {
            "output": [
                {
                    "type": "video",
                    "source": {"type": "url", "url": "https://x/v.mp4"},
                },
            ],
        }
        msg = _build_media_message_from_block(block, "assistant", META)
        content = msg.content[0]
        assert content.type == ContentType.VIDEO

    def test_video_from_base64(self):
        block = {
            "output": [
                {
                    "type": "video",
                    "source": {
                        "type": "base64",
                        "media_type": "video/mp4",
                        "data": "aGk=",
                    },
                },
            ],
        }
        msg = _build_media_message_from_block(block, "assistant", META)
        content = msg.content[0]
        assert content.type == ContentType.VIDEO

    def test_file_from_url_with_filename(self):
        block = {
            "output": [
                {
                    "type": "file",
                    "filename": "doc.pdf",
                    "source": {"type": "url", "url": "https://x/doc.pdf"},
                },
            ],
        }
        msg = _build_media_message_from_block(block, "assistant", META)
        content = msg.content[0]
        assert content.type == ContentType.FILE
        assert content.filename == "doc.pdf"

    def test_file_from_base64(self):
        block = {
            "output": [
                {
                    "type": "file",
                    "filename": "doc.pdf",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": "aGk=",
                    },
                },
            ],
        }
        msg = _build_media_message_from_block(block, "assistant", META)
        content = msg.content[0]
        assert content.type == ContentType.FILE

    def test_file_from_string_source(self):
        block = {
            "output": [
                {
                    "type": "file",
                    "filename": "d.txt",
                    "source": "https://x/d.txt",
                },
            ],
        }
        msg = _build_media_message_from_block(block, "assistant", META)
        content = msg.content[0]
        assert content.type == ContentType.FILE

    def test_data_block_classified_by_media_type(self):
        block = {
            "output": [
                {
                    "type": "data",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": "aGk=",
                    },
                },
            ],
        }
        msg = _build_media_message_from_block(block, "assistant", META)
        content = msg.content[0]
        assert content.type == ContentType.IMAGE

    def test_data_block_application_maps_to_file(self):
        block = {
            "output": [
                {
                    "type": "data",
                    "filename": "f.bin",
                    "source": {
                        "type": "base64",
                        "media_type": "application/octet-stream",
                        "data": "aGk=",
                    },
                },
            ],
        }
        msg = _build_media_message_from_block(block, "assistant", META)
        content = msg.content[0]
        assert content.type == ContentType.FILE

    def test_no_media_items_returns_none(self):
        block = {
            "output": [
                {"type": "text", "text": "no media"},
            ],
        }
        assert (
            _build_media_message_from_block(block, "assistant", META) is None
        )

    def test_output_not_list_returns_none(self):
        assert (
            _build_media_message_from_block(
                {"output": "plain"},
                "assistant",
                META,
            )
            is None
        )

    def test_mixed_media_items_all_included(self):
        block = {
            "output": [
                {
                    "type": "image",
                    "source": {"type": "url", "url": "https://x/a.png"},
                },
                {"type": "text", "text": "skipped"},
                {
                    "type": "audio",
                    "source": {"type": "url", "url": "https://x/b.mp3"},
                },
            ],
        }
        msg = _build_media_message_from_block(block, "assistant", META)
        assert len(msg.content) == 2

    def test_non_dict_items_skipped(self):
        block = {
            "output": [
                "not-a-dict",
                {
                    "type": "image",
                    "source": {"type": "url", "url": "https://x/a.png"},
                },
            ],
        }
        msg = _build_media_message_from_block(block, "assistant", META)
        assert len(msg.content) == 1


# ---------------------------------------------------------------------------
# parse_legacy_memory_state
# ---------------------------------------------------------------------------


class TestParseLegacyMemoryState:
    def test_marks_stripped(self):
        msg_dict = Msg(
            name="user",
            role="user",
            content=[TextBlock(type="text", text="hi")],
        ).to_dict()
        raw = {"content": [[msg_dict, ["HINT"]]], "_compressed_summary": "sum"}
        messages, summary = parse_legacy_memory_state(raw)
        assert len(messages) == 1
        assert summary == "sum"

    def test_bare_payload_accepted(self):
        msg_dict = Msg(
            name="user",
            role="user",
            content=[TextBlock(type="text", text="hi")],
        ).to_dict()
        raw = {"content": [msg_dict]}
        messages, summary = parse_legacy_memory_state(raw)
        assert len(messages) == 1
        assert summary == ""

    def test_msg_instances_passed_through(self):
        msg = Msg(
            name="user",
            role="user",
            content=[TextBlock(type="text", text="hi")],
        )
        raw = {"content": [msg]}
        messages, _ = parse_legacy_memory_state(raw)
        assert messages[0] is msg

    def test_empty_content(self):
        messages, summary = parse_legacy_memory_state({"content": []})
        assert messages == []
        assert summary == ""

    def test_missing_keys(self):
        messages, summary = parse_legacy_memory_state({})
        assert messages == []
        assert summary == ""

    def test_invalid_payload_types_skipped(self):
        raw = {"content": [42, None]}
        messages, _ = parse_legacy_memory_state(raw)
        assert messages == []
