# -*- coding: utf-8 -*-
"""Unit tests for QQ media helper modules."""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

import pytest

from copaw.app.channels.qq.audio_convert import (
    is_audio_file as audio_convert_is_audio_file,
    should_transcode_voice,
)
from copaw.app.channels.qq.chunked_upload import get_media_file_type
from copaw.app.channels.qq.file_utils import (
    file_exists,
    format_file_size,
    get_file_hash,
    get_file_size,
    get_max_upload_size,
    is_audio_file as file_utils_is_audio_file,
    is_local_path,
)
from copaw.app.channels.qq.media_tags import (
    SendQueueItem,
    fix_path_encoding,
    parse_media_tags,
)
from copaw.app.channels.qq.ssrf_guard import is_safe_url


def _create_temp_file(content: bytes, suffix: str = "") -> Path:
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        temp_file.write(content)
        temp_file.flush()
        return Path(temp_file.name)
    finally:
        temp_file.close()


class TestFileUtils:
    @pytest.mark.parametrize(
        ("path", "expected"),
        [
            ("https://example.com/cat.png", False),
            ("s3://bucket/object.mp3", False),
            ("./relative/file.wav", True),
            ("C:/temp/file.txt", True),
            ("notes.txt", True),
        ],
    )
    def test_is_local_path(self, path: str, expected: bool) -> None:
        assert is_local_path(path) is expected

    def test_get_file_hash(self) -> None:
        content = b"qq media hash test"
        temp_path = _create_temp_file(content, suffix=".bin")

        try:
            assert get_file_hash(str(temp_path)) == hashlib.sha256(content).hexdigest()
        finally:
            temp_path.unlink(missing_ok=True)

    def test_get_file_size(self) -> None:
        content = b"1234567890"
        temp_path = _create_temp_file(content, suffix=".dat")

        try:
            assert get_file_size(str(temp_path)) == len(content)
        finally:
            temp_path.unlink(missing_ok=True)

    def test_format_file_size(self) -> None:
        assert format_file_size(512) == "512 B"
        assert format_file_size(1024) == "1 KB"
        assert format_file_size(1536) == "1.5 KB"
        assert format_file_size(1024 * 1024) == "1 MB"

    @pytest.mark.parametrize(
        ("mime_type", "expected"),
        [
            ("image/png", 30 * 1024 * 1024),
            ("video/mp4", 100 * 1024 * 1024),
            ("audio/mpeg", 10 * 1024 * 1024),
            ("application/pdf", 100 * 1024 * 1024),
        ],
    )
    def test_get_max_upload_size(self, mime_type: str, expected: int) -> None:
        assert get_max_upload_size(mime_type) == expected

    @pytest.mark.parametrize(
        ("file_path", "expected"),
        [
            ("voice.MP3", True),
            ("clip.ogg", True),
            ("image.png", False),
        ],
    )
    def test_is_audio_file(self, file_path: str, expected: bool) -> None:
        assert file_utils_is_audio_file(file_path) is expected

    def test_file_exists(self) -> None:
        temp_path = _create_temp_file(b"exists", suffix=".txt")
        missing_path = temp_path.with_name(f"{temp_path.stem}_missing.txt")

        try:
            assert file_exists(str(temp_path)) is True
            assert file_exists(str(missing_path)) is False
        finally:
            temp_path.unlink(missing_ok=True)


class TestMediaTags:
    def test_parse_media_tags_image(self) -> None:
        text = '<qqimg src="https://example.com/cat.png" />'

        assert parse_media_tags(text) == [
            SendQueueItem(type="image", content="https://example.com/cat.png")
        ]

    def test_parse_media_tags_voice(self) -> None:
        text = "<qqvoice>voice.silk</qqvoice>"

        assert parse_media_tags(text) == [
            SendQueueItem(type="voice", content="voice.silk")
        ]

    def test_parse_media_tags_mixed(self) -> None:
        text = (
            'Look <qqimg src="https://example.com/cat.png" />'
            " and listen to "
            "<qqvoice>voice.silk</qqvoice>!"
        )

        assert parse_media_tags(text) == [
            SendQueueItem(type="text", content="Look "),
            SendQueueItem(type="image", content="https://example.com/cat.png"),
            SendQueueItem(type="text", content=" and listen to "),
            SendQueueItem(type="voice", content="voice.silk"),
            SendQueueItem(type="text", content="!"),
        ]

    def test_fix_path_encoding(self) -> None:
        raw_path = '  "C:\\\\Users\\\\alice\\\\voice.mp3"  '

        assert fix_path_encoding(raw_path) == r"C:\Users\alice\voice.mp3"


class TestAudioConvert:
    @pytest.mark.parametrize(
        ("path", "expected"),
        [
            (Path("voice.ogg"), True),
            (Path("voice.silk"), True),
            (Path("notes.txt"), False),
        ],
    )
    def test_is_audio_file(self, path: Path, expected: bool) -> None:
        assert audio_convert_is_audio_file(path) is expected

    @pytest.mark.parametrize(
        ("path", "expected"),
        [
            (Path("voice.mp3"), True),
            (Path("voice.silk"), False),
            (Path("notes.txt"), False),
        ],
    )
    def test_should_transcode_voice(self, path: Path, expected: bool) -> None:
        assert should_transcode_voice(path) is expected


class TestSsrfGuard:
    @pytest.mark.parametrize(
        "url",
        [
            "https://example.com/media.png",
            "http://example.com:8080/file.bin",
            "https://cdn.example.com:8443/voice.silk",
        ],
    )
    def test_is_safe_url_allowed(self, url: str) -> None:
        assert is_safe_url(url) is True

    @pytest.mark.parametrize(
        "url",
        [
            "ftp://example.com/file.txt",
            "http://localhost/file.txt",
            "http://169.254.169.254/latest/meta-data/",
            "https://example.com:22/blocked",
        ],
    )
    def test_is_safe_url_blocked(self, url: str) -> None:
        assert is_safe_url(url) is False


class TestChunkedUpload:
    @pytest.mark.parametrize(
        ("media_type", "expected"),
        [
            ("image", 1),
            ("video", 2),
            ("audio", 3),
            ("voice", 3),
            ("file", 4),
            ("IMAGE", 1),
            ("unknown", 4),
        ],
    )
    def test_get_media_file_type(self, media_type: str, expected: int) -> None:
        assert get_media_file_type(media_type) == expected
