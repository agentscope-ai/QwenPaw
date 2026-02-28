from __future__ import annotations

import pytest

from copaw.app.channels.media_utils import classify_media_kind, pick_attachment_url
from copaw.app.channels.telegram.channel import _resolve_telegram_file_url


def test_classify_media_kind_by_mime_and_suffix() -> None:
    assert classify_media_kind(mime_type="image/png", filename="x.bin") == "image"
    assert classify_media_kind(mime_type="", filename="x.mp4") == "video"
    assert classify_media_kind(mime_type="audio/mpeg", filename="x.bin") == "audio"
    assert classify_media_kind(mime_type="", filename="x.unknown") == "file"


def test_pick_attachment_url_prefers_supported_keys() -> None:
    att = {"proxy_url": "https://proxy", "download_url": "https://download"}
    assert pick_attachment_url(att) == "https://download"
    assert pick_attachment_url({"name": "n"}) == ""


class _FakeTgFile:
    def __init__(self, file_path: str):
        self.file_path = file_path


class _FakeBot:
    def __init__(self, file_path: str):
        self._file_path = file_path

    async def get_file(self, _file_id: str):
        return _FakeTgFile(self._file_path)


@pytest.mark.asyncio
async def test_resolve_telegram_file_url_builds_api_file_url() -> None:
    bot = _FakeBot("photos/file_1.jpg")
    url = await _resolve_telegram_file_url(
        bot=bot,
        file_id="fid",
        bot_token="token123",
    )
    assert url == "https://api.telegram.org/file/bottoken123/photos/file_1.jpg"


@pytest.mark.asyncio
async def test_resolve_telegram_file_url_keeps_http_path() -> None:
    bot = _FakeBot("https://cdn.example.com/f.mp4")
    url = await _resolve_telegram_file_url(
        bot=bot,
        file_id="fid",
        bot_token="token123",
    )
    assert url == "https://cdn.example.com/f.mp4"

