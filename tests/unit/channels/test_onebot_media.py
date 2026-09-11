# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Unit tests for OneBot inbound media localization."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import aiohttp
import pytest

from qwenpaw.app.channels.onebot.media import (
    OneBotInboundMedia,
    _download_suffix,
    _safe_filename_stem,
    _suffix_from_bytes,
)
from qwenpaw.schemas import (
    ContentType,
    FileContent,
    ImageContent,
    TextContent,
)


class _FakeContent:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    async def iter_chunked(self, _size: int):
        for chunk in self._chunks:
            yield chunk


class _FakeResponse:
    def __init__(
        self,
        chunks: list[bytes],
        *,
        content_type: str = "application/octet-stream",
        content_length: int | None = None,
        error: Exception | None = None,
    ) -> None:
        self.content = _FakeContent(chunks)
        self.content_length = content_length
        self.headers = {"Content-Type": content_type}
        self._error = error

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    def raise_for_status(self) -> None:
        if self._error is not None:
            raise self._error


class _FakeSession:
    def __init__(self, response: _FakeResponse) -> None:
        self.closed = False
        self.response = response
        self.requests: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.requests.append((url, kwargs))
        return self.response

    async def close(self) -> None:
        self.closed = True


def _make_media(
    media_dir: Path,
    *,
    max_download_bytes: int = 1_000_000,
    call_api: AsyncMock | None = None,
) -> OneBotInboundMedia:
    return OneBotInboundMedia(
        media_dir=media_dir,
        max_download_bytes=max_download_bytes,
        call_api=call_api or AsyncMock(return_value={}),
    )


@pytest.mark.parametrize(
    ("data", "suffix"),
    [
        (b"RIFF1234WAVE", ".wav"),
        (b"RIFF1234WEBP", ".webp"),
        (b"RIFF1234AVI ", ".avi"),
        (b"1234ftypqt  ", ".mov"),
        (b"1234ftypM4A ", ".m4a"),
        (b"#!AMR\nvoice", ".amr"),
    ],
)
def test_magic_byte_suffixes(data: bytes, suffix: str):
    assert _suffix_from_bytes(data) == suffix


def test_magic_bytes_take_priority_over_content_type():
    assert (
        _download_suffix(
            "image/jpeg",
            b"\x89PNG\r\n\x1a\ncontent",
            "photo.jpg",
            "image",
        )
        == ".png"
    )


def test_content_type_takes_priority_over_file_hint():
    assert (
        _download_suffix(
            "audio/mpeg",
            b"mpeg without an ID3 header",
            "voice.amr",
            "audio",
        )
        == ".mp3"
    )


def test_filename_stem_is_cross_platform_and_byte_limited():
    stem = _safe_filename_stem(
        f"C:\\incoming\\bad:name_{'界' * 100}.pdf",
        "file",
    )

    assert "\\" not in stem
    assert ":" not in stem
    assert len(stem.encode("utf-8")) <= 100


async def test_resolve_keeps_existing_local_media(tmp_path):
    image_path = tmp_path / "image.png"
    image_path.write_bytes(b"image")
    media = _make_media(tmp_path)
    media.download = AsyncMock()

    resolved = await media.resolve(
        [
            ImageContent(
                type=ContentType.IMAGE,
                image_url=image_path.as_uri(),
            ),
        ],
        [{"type": "image", "data": {"file": image_path.as_uri()}}],
        "private",
        {},
    )

    assert resolved[0].image_url == str(image_path.resolve())
    media.download.assert_not_awaited()


async def test_resolve_group_file_url_and_download(tmp_path):
    call_api = AsyncMock(
        return_value={"data": {"url": "https://cdn.example/report.pdf"}},
    )
    media = _make_media(tmp_path, call_api=call_api)
    local_path = str(tmp_path / "report.pdf")
    media.download = AsyncMock(return_value=local_path)

    resolved = await media.resolve(
        [
            TextContent(type=ContentType.TEXT, text="report"),
            FileContent(
                type=ContentType.FILE,
                file_url="report.pdf",
                filename="report.pdf",
            ),
        ],
        [
            {
                "type": "file",
                "data": {
                    "file": "report.pdf",
                    "file_id": "file-id",
                },
            },
        ],
        "group",
        {"group_id": "12345"},
    )

    call_api.assert_awaited_once_with(
        "get_group_file_url",
        {"group_id": 12345, "file_id": "file-id"},
    )
    media.download.assert_awaited_once_with(
        "https://cdn.example/report.pdf",
        "file",
        0,
        "report.pdf",
    )
    assert resolved[0].text == "report"
    assert resolved[1].file_url == local_path


@pytest.mark.parametrize(
    ("kind", "segment_data", "action", "params"),
    [
        ("image", {"file": "image-id"}, "get_image", {"file": "image-id"}),
        (
            "audio",
            {"file": "voice-id"},
            "get_record",
            {"file": "voice-id", "out_format": "mp3"},
        ),
        (
            "file",
            {"file_id": "file-id"},
            "get_private_file_url",
            {"file_id": "file-id"},
        ),
    ],
)
async def test_resolve_media_url_from_api(
    tmp_path,
    kind: str,
    segment_data: dict[str, str],
    action: str,
    params: dict[str, str],
):
    call_api = AsyncMock(
        return_value={"data": {"file": "https://cdn.example/media"}},
    )
    media = _make_media(tmp_path, call_api=call_api)

    result = await media._resolve_from_api(
        kind,
        segment_data,
        "private",
        {},
    )

    assert result == "https://cdn.example/media"
    call_api.assert_awaited_once_with(action, params)


async def test_resolve_failure_becomes_text_placeholder(tmp_path):
    media = _make_media(tmp_path)

    resolved = await media.resolve(
        [
            FileContent(
                type=ContentType.FILE,
                file_url="missing.bin",
                filename="missing.bin",
            ),
        ],
        [{"type": "file", "data": {"file_id": "missing"}}],
        "private",
        {},
    )

    assert resolved[0].type == ContentType.TEXT
    assert resolved[0].text == "[file: download failed]"


async def test_download_streams_to_atomic_local_file(tmp_path):
    payload = b"\x89PNG\r\n\x1a\nimage"
    response = _FakeResponse(
        [payload[:5], payload[5:]],
        content_type="image/jpeg",
        content_length=len(payload),
    )
    session = _FakeSession(response)
    media = _make_media(tmp_path)
    media._session = session

    result = await media.download(
        "https://cdn.example/image",
        "image",
        2,
        r"C:\incoming\bad:name.jpg",
    )

    assert result is not None
    path = Path(result)
    assert path.parent == tmp_path.resolve()
    assert path.suffix == ".png"
    assert path.read_bytes() == payload
    assert not list(tmp_path.glob("*.part"))
    assert session.requests[0][1] == {
        "allow_redirects": True,
        "max_redirects": 3,
    }


async def test_download_uses_mime_when_magic_is_unknown(tmp_path):
    session = _FakeSession(
        _FakeResponse([b"mpeg"], content_type="audio/mpeg"),
    )
    media = _make_media(tmp_path)
    media._session = session

    result = await media.download(
        "https://cdn.example/voice",
        "audio",
        0,
        "voice.amr",
    )

    assert result is not None
    assert Path(result).suffix == ".mp3"


async def test_download_rejects_mismatched_content_type(tmp_path):
    session = _FakeSession(
        _FakeResponse(
            [b"<html>not an image</html>"],
            content_type="text/html",
        ),
    )
    media = _make_media(tmp_path)
    media._session = session

    result = await media.download(
        "https://cdn.example/image",
        "image",
        0,
        "image.png",
    )

    assert result is None
    assert not list(tmp_path.iterdir())


async def test_magic_bytes_allow_mislabeled_media(tmp_path):
    payload = b"\x89PNG\r\n\x1a\nimage"
    session = _FakeSession(
        _FakeResponse([payload], content_type="text/plain"),
    )
    media = _make_media(tmp_path)
    media._session = session

    result = await media.download(
        "https://cdn.example/image",
        "image",
        0,
        "image",
    )

    assert result is not None
    assert Path(result).suffix == ".png"


async def test_content_length_limit_rejects_before_writing(tmp_path):
    session = _FakeSession(
        _FakeResponse([b"123456"], content_length=6),
    )
    media = _make_media(tmp_path, max_download_bytes=5)
    media._session = session

    result = await media.download(
        "https://cdn.example/file",
        "file",
        0,
        "file.bin",
    )

    assert result is None
    assert not list(tmp_path.iterdir())


async def test_stream_limit_removes_partial_file(tmp_path):
    session = _FakeSession(_FakeResponse([b"123", b"456"]))
    media = _make_media(tmp_path, max_download_bytes=5)
    media._session = session

    result = await media.download(
        "https://cdn.example/file",
        "file",
        0,
        "file.bin",
    )

    assert result is None
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    "response",
    [
        _FakeResponse([]),
        _FakeResponse([], error=aiohttp.ClientError("request failed")),
    ],
)
async def test_empty_or_failed_download_leaves_no_file(tmp_path, response):
    media = _make_media(tmp_path)
    media._session = _FakeSession(response)

    result = await media.download(
        "https://cdn.example/file",
        "file",
        0,
        "file.bin",
    )

    assert result is None
    assert not tmp_path.exists() or not list(tmp_path.iterdir())


class _ConcurrencyState:
    def __init__(self) -> None:
        self.active = 0
        self.maximum = 0
        self.four_started = asyncio.Event()
        self.release = asyncio.Event()


class _GatedResponse(_FakeResponse):
    def __init__(self, state: _ConcurrencyState) -> None:
        super().__init__([b"content"])
        self._state = state

    async def __aenter__(self):
        self._state.active += 1
        self._state.maximum = max(
            self._state.maximum,
            self._state.active,
        )
        if self._state.active == 4:
            self._state.four_started.set()
        await self._state.release.wait()
        return self

    async def __aexit__(self, *_args):
        self._state.active -= 1
        return False


class _GatedSession:
    def __init__(self, state: _ConcurrencyState) -> None:
        self.closed = False
        self._state = state
        self.request_count = 0

    def get(self, _url: str, **_kwargs: Any) -> _GatedResponse:
        self.request_count += 1
        return _GatedResponse(self._state)

    async def close(self) -> None:
        self.closed = True


async def test_download_concurrency_is_bounded(tmp_path):
    state = _ConcurrencyState()
    session = _GatedSession(state)
    media = _make_media(tmp_path)
    media._session = session
    tasks = [
        asyncio.create_task(
            media.download(
                f"https://cdn.example/{index}",
                "file",
                index,
                f"file-{index}.bin",
            ),
        )
        for index in range(5)
    ]

    await asyncio.wait_for(state.four_started.wait(), timeout=1)
    assert state.maximum == 4
    assert session.request_count == 4
    state.release.set()
    results = await asyncio.gather(*tasks)

    assert all(results)
    assert session.request_count == 5
