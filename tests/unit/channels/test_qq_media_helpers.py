# -*- coding: utf-8 -*-
"""Tests for QQ channel static media/quote helpers.

Covers _find_quoted_element, _content_type_to_media_type,
_make_content_part, and _resolve_media_url_and_path, which previously
had no coverage.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

from types import SimpleNamespace

import pytest

from qwenpaw.app.channels.qq.channel import QQChannel
from qwenpaw.schemas import (
    AudioContent,
    ContentType,
    FileContent,
    ImageContent,
    VideoContent,
)


# ---------------------------------------------------------------------------
# _find_quoted_element
# ---------------------------------------------------------------------------


class TestFindQuotedElement:
    def test_no_msg_elements_returns_none(self):
        assert QQChannel._find_quoted_element({}) is None

    def test_msg_elements_not_list_returns_none(self):
        assert QQChannel._find_quoted_element({"msg_elements": "x"}) is None

    def test_no_ref_idx_returns_none(self):
        data = {
            "msg_elements": [{"msg_idx": "1"}],
            "message_scene": {"ext": ["msg_idx=1"]},
        }
        assert QQChannel._find_quoted_element(data) is None

    def test_matches_ref_msg_idx(self):
        quoted = {"msg_idx": "2", "content": "original"}
        data = {
            "msg_elements": [{"msg_idx": "1"}, quoted],
            "message_scene": {"ext": ["ref_msg_idx=2", "msg_idx=1"]},
        }
        assert QQChannel._find_quoted_element(data) is quoted

    def test_fallback_to_other_idx(self):
        other = {"msg_idx": "9", "content": "other"}
        data = {
            "msg_elements": [{"msg_idx": "1"}, other],
            "message_scene": {"ext": ["ref_msg_idx=5", "msg_idx=1"]},
        }
        assert QQChannel._find_quoted_element(data) is other

    def test_non_dict_elements_skipped(self):
        data = {
            "msg_elements": ["not-a-dict"],
            "message_scene": {"ext": ["ref_msg_idx=2"]},
        }
        assert QQChannel._find_quoted_element(data) is None

    def test_empty_scene_ext(self):
        quoted = {"msg_idx": "2"}
        data = {"msg_elements": [quoted], "message_scene": None}
        # no scene ext -> no ref_idx -> None
        assert QQChannel._find_quoted_element(data) is None


# ---------------------------------------------------------------------------
# _content_type_to_media_type
# ---------------------------------------------------------------------------


class TestContentTypeToMediaType:
    def test_image(self):
        assert QQChannel._content_type_to_media_type(ContentType.IMAGE) == 1

    def test_video(self):
        assert QQChannel._content_type_to_media_type(ContentType.VIDEO) == 2

    def test_audio_maps_to_file(self):
        assert QQChannel._content_type_to_media_type(ContentType.AUDIO) == 4

    def test_file(self):
        assert QQChannel._content_type_to_media_type(ContentType.FILE) == 4

    def test_voice_extension_maps_to_audio(self):
        for ext in ("voice.amr", "voice.silk", "voice.slk"):
            assert (
                QQChannel._content_type_to_media_type(
                    ContentType.AUDIO,
                    source_path=ext,
                )
                == 3
            )

    def test_mp3_stays_file(self):
        assert (
            QQChannel._content_type_to_media_type(
                ContentType.AUDIO,
                source_path="song.mp3",
            )
            == 4
        )

    def test_unknown_type_returns_none(self):
        assert QQChannel._content_type_to_media_type(ContentType.TEXT) is None
        assert QQChannel._content_type_to_media_type("bogus") is None


# ---------------------------------------------------------------------------
# _make_content_part
# ---------------------------------------------------------------------------


class TestMakeContentPart:
    def test_image_part(self):
        part = QQChannel._make_content_part("image", "/tmp/a.png", "")
        assert isinstance(part, ImageContent)
        assert part.image_url == "/tmp/a.png"

    def test_video_part(self):
        part = QQChannel._make_content_part("video", "/tmp/v.mp4", "")
        assert isinstance(part, VideoContent)
        assert part.video_url == "/tmp/v.mp4"

    def test_audio_part(self):
        part = QQChannel._make_content_part("audio", "/tmp/a.amr", "")
        assert isinstance(part, AudioContent)
        assert part.data == "/tmp/a.amr"

    def test_file_part_with_filename(self):
        part = QQChannel._make_content_part("file", "/tmp/f.pdf", "f.pdf")
        assert isinstance(part, FileContent)
        assert part.filename == "f.pdf"
        assert part.file_url == "/tmp/f.pdf"

    def test_unknown_type_returns_none(self):
        assert QQChannel._make_content_part("bogus", "/tmp/x", "") is None


# ---------------------------------------------------------------------------
# _resolve_media_url_and_path
# ---------------------------------------------------------------------------


@pytest.fixture
def channel(tmp_path):
    from qwenpaw.app.channels.renderer import ChannelDisplayConfig

    async def process(*a, **kw):
        yield SimpleNamespace(object="message", status="completed")

    return QQChannel(
        process=process,
        enabled=True,
        app_id="app",
        client_secret="secret",
        bot_prefix="[Bot] ",
        media_dir=str(tmp_path / "media"),
        display_config=ChannelDisplayConfig(),
    )


class TestResolveMediaUrlAndPath:
    def test_image_http_url(self, channel):
        part = ImageContent(
            type=ContentType.IMAGE,
            image_url="https://cdn.example.com/a.png",
        )
        url, local = channel._resolve_media_url_and_path(part)
        assert url == "https://cdn.example.com/a.png"
        assert local is None

    def test_file_local_path(self, channel, tmp_path):
        target = tmp_path / "doc.pdf"
        target.write_bytes(b"%PDF")
        part = FileContent(
            type=ContentType.FILE,
            file_url=str(target),
            filename="doc.pdf",
        )
        url, local = channel._resolve_media_url_and_path(part)
        assert local == str(target)
        # An existing local file yields no remote URL.
        assert url is None
        assert url is None

    def test_file_url_protocol(self, channel, tmp_path):
        target = tmp_path / "local.png"
        target.write_bytes(b"\x89PNG")
        part = ImageContent(
            type=ContentType.IMAGE,
            image_url=f"file://{target}",
        )
        url, local = channel._resolve_media_url_and_path(part)
        assert local == str(target)
        assert url is None

    def test_video_url(self, channel):
        part = VideoContent(
            type=ContentType.VIDEO,
            video_url="https://cdn.example.com/v.mp4",
        )
        url, local = channel._resolve_media_url_and_path(part)
        assert url == "https://cdn.example.com/v.mp4"
        # An http(s) URL yields no local download path.
        assert local is None

    def test_audio_data(self, channel, tmp_path):
        target = tmp_path / "a.amr"
        target.write_bytes(b"#!AMR")
        part = AudioContent(type=ContentType.AUDIO, data=str(target))
        url, local = channel._resolve_media_url_and_path(part)
        assert local == str(target)
        # An existing local file yields no remote URL.
        assert url is None

    def test_nonexistent_path_treated_as_url(self, channel):
        part = AudioContent(type=ContentType.AUDIO, data="/nope/missing.amr")
        url, local = channel._resolve_media_url_and_path(part)
        # not a file:// or http(s) and not on disk -> kept as url
        assert url == "/nope/missing.amr"
        assert local is None

    def test_text_type_returns_none_pair(self, channel):
        part = SimpleNamespace(type=ContentType.TEXT)
        url, local = channel._resolve_media_url_and_path(part)
        assert url is None
        assert local is None

    def test_empty_value_returns_none_pair(self, channel):
        part = ImageContent(type=ContentType.IMAGE, image_url="")
        url, local = channel._resolve_media_url_and_path(part)
        assert url is None
        assert local is None
