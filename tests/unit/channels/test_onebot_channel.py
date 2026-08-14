# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Unit tests for OneBot v11 channel."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from agentscope.message import TextBlock
from aiohttp import web
from aiohttp.test_utils import make_mocked_request
from aiohttp.web import TCPSite
from pydantic import ValidationError
from qwenpaw.agents.utils.message_processing import (
    process_file_and_media_blocks_in_message,
)
from qwenpaw.config.config import OneBotConfig
from qwenpaw.runtime.message_convert import _request_input_to_msgs
from qwenpaw.schemas import (
    AudioContent,
    ContentType,
    FileContent,
    ImageContent,
    Message,
    Role,
    TextContent,
    VideoContent,
)

from qwenpaw.app.channels.onebot import channel as onebot_channel_module
from qwenpaw.app.channels.onebot.channel import (
    OneBotChannel,
    _normalize_media_ref_sync,
)
from qwenpaw.app.channels.renderer import ChannelDisplayConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_channel(**overrides: Any) -> OneBotChannel:
    """Create an OneBotChannel with dummy process handler."""

    async def _noop_process(_request):
        yield  # pragma: no cover

    defaults = {
        "process": _noop_process,
        "enabled": True,
        "ws_host": "127.0.0.1",
        "ws_port": 6199,
        "access_token": "",
        "bot_prefix": "",
    }
    defaults.update(overrides)
    return OneBotChannel(**defaults)


def test_media_base64_config():
    async def _noop_process(_request):
        yield  # pragma: no cover

    config = OneBotConfig(
        enabled=True,
        media_base64=True,
        media_base64_max_mb=3,
    )
    ch = OneBotChannel.from_config(
        _noop_process,
        config,
    )

    assert OneBotConfig().model_dump()["media_base64_max_mb"] == 10
    assert config.model_dump()["media_base64_max_mb"] == 3
    assert ch._media_base64 is True
    assert ch._media_base64_max_bytes == 3_000_000
    with pytest.raises(ValidationError):
        OneBotConfig(media_base64_max_mb=0)


def test_media_download_max_mb_config():
    """Inbound download limit is independent of the base64 limit."""

    async def _noop_process(_request):
        yield  # pragma: no cover

    config = OneBotConfig(enabled=True, media_download_max_mb=5)
    ch = OneBotChannel.from_config(_noop_process, config)

    assert OneBotConfig().model_dump()["media_download_max_mb"] == 50
    assert config.model_dump()["media_download_max_mb"] == 5
    assert ch._media_download_max_bytes == 5_000_000
    # A large-but-under-download-limit file must not be rejected just
    # because base64 inlining is disabled/small by default.
    assert ch._media_download_max_bytes != ch._media_base64_max_bytes
    with pytest.raises(ValidationError):
        OneBotConfig(media_download_max_mb=0)


def test_media_dir_config(tmp_path):
    async def _noop_process(_request):
        yield  # pragma: no cover

    explicit = tmp_path / "onebot-media"
    config = OneBotConfig(enabled=True, media_dir=str(explicit))
    ch = OneBotChannel.from_config(_noop_process, config)
    assert ch._media_dir == explicit

    workspace = tmp_path / "workspace"
    ch = OneBotChannel.from_config(
        _noop_process,
        OneBotConfig(enabled=True),
        workspace_dir=workspace,
    )
    assert ch._media_dir == workspace / "media" / "onebot"


def _make_message_event(
    message_type: str = "private",
    user_id: int = 12345,
    group_id: int = 0,
    message_id: int = 1001,
    segments: list | None = None,
    sender: dict | None = None,
) -> dict:
    """Build a minimal OneBot v11 message event."""
    if segments is None:
        segments = [{"type": "text", "data": {"text": "hello"}}]
    if sender is None:
        sender = {"nickname": "TestUser", "card": ""}
    event = {
        "post_type": "message",
        "message_type": message_type,
        "user_id": user_id,
        "message_id": message_id,
        "message": segments,
        "sender": sender,
    }
    if group_id:
        event["group_id"] = group_id
    return event


# ===================================================================
# Message segment parsing
# ===================================================================


class TestParseMessageSegments:
    def test_text_only(self):
        ch = _make_channel()
        parts, mentioned = ch._parse_message_segments(
            [{"type": "text", "data": {"text": "hello world"}}],
        )
        assert len(parts) == 1
        assert parts[0].type == ContentType.TEXT
        assert parts[0].text == "hello world"
        assert mentioned is False

    def test_empty_text_skipped(self):
        ch = _make_channel()
        parts, _ = ch._parse_message_segments(
            [{"type": "text", "data": {"text": "  "}}],
        )
        assert len(parts) == 0

    def test_image_segment(self):
        ch = _make_channel()
        parts, _ = ch._parse_message_segments(
            [
                {
                    "type": "image",
                    "data": {"url": "https://img.example.com/1.jpg"},
                },
            ],
        )
        assert len(parts) == 1
        assert parts[0].type == ContentType.IMAGE
        assert parts[0].image_url == "https://img.example.com/1.jpg"

    def test_image_file_fallback(self):
        ch = _make_channel()
        parts, _ = ch._parse_message_segments(
            [{"type": "image", "data": {"file": "file:///tmp/1.jpg"}}],
        )
        assert len(parts) == 1
        assert parts[0].image_url == "file:///tmp/1.jpg"

    def test_record_segment(self):
        ch = _make_channel()
        parts, _ = ch._parse_message_segments(
            [
                {
                    "type": "record",
                    "data": {"url": "https://audio.example.com/a.mp3"},
                },
            ],
        )
        assert len(parts) == 1
        assert parts[0].type == ContentType.AUDIO

    def test_video_segment(self):
        ch = _make_channel()
        parts, _ = ch._parse_message_segments(
            [
                {
                    "type": "video",
                    "data": {"url": "https://video.example.com/v.mp4"},
                },
            ],
        )
        assert len(parts) == 1
        assert parts[0].type == ContentType.VIDEO

    def test_file_segment(self):
        ch = _make_channel()
        parts, _ = ch._parse_message_segments(
            [
                {
                    "type": "file",
                    "data": {
                        "url": "https://files.example.com/doc.pdf",
                        "name": "doc.pdf",
                    },
                },
            ],
        )
        assert len(parts) == 1
        assert parts[0].type == ContentType.FILE

    def test_at_bot_detected(self):
        ch = _make_channel()
        ch._self_id = 99999
        parts, mentioned = ch._parse_message_segments(
            [
                {"type": "at", "data": {"qq": "99999"}},
                {"type": "text", "data": {"text": "hello bot"}},
            ],
        )
        assert mentioned is True
        assert len(parts) == 1
        assert parts[0].text == "hello bot"

    def test_at_other_user_not_mentioned(self):
        ch = _make_channel()
        ch._self_id = 99999
        _, mentioned = ch._parse_message_segments(
            [
                {"type": "at", "data": {"qq": "11111"}},
                {"type": "text", "data": {"text": "hello"}},
            ],
        )
        assert mentioned is False

    def test_mixed_segments(self):
        ch = _make_channel()
        parts, _ = ch._parse_message_segments(
            [
                {"type": "text", "data": {"text": "look at this"}},
                {
                    "type": "image",
                    "data": {"url": "https://img.example.com/pic.png"},
                },
                {"type": "reply", "data": {"id": "123"}},
                {"type": "face", "data": {"id": "178"}},
            ],
        )
        assert len(parts) == 2
        assert parts[0].type == ContentType.TEXT
        assert parts[1].type == ContentType.IMAGE

    def test_unknown_segment_ignored(self):
        ch = _make_channel()
        parts, _ = ch._parse_message_segments(
            [{"type": "unknown_type", "data": {}}],
        )
        assert len(parts) == 0

    def test_normalize_cq_code_message(self):
        segments = OneBotChannel._normalize_onebot_segments(
            "hello [CQ:image,file=pic.jpg,"
            "url=https://img.example.com/pic.jpg]",
        )

        assert segments == [
            {"type": "text", "data": {"text": "hello"}},
            {
                "type": "image",
                "data": {
                    "file": "pic.jpg",
                    "url": "https://img.example.com/pic.jpg",
                },
            },
        ]

    def test_normalize_cq_code_decodes_escaped_parameters(self):
        segments = OneBotChannel._normalize_onebot_segments(
            "[CQ:image,file=a&#44;b&#91;c&#93;.jpg,"
            "title=&lt;literal&gt;,"
            "url=https://cdn.example/a?x=1&#38;y=2]",
        )

        assert segments == [
            {
                "type": "image",
                "data": {
                    "file": "a,b[c].jpg",
                    "title": "&lt;literal&gt;",
                    "url": "https://cdn.example/a?x=1&y=2",
                },
            },
        ]

    def test_message_preview_bounds_fields_before_serializing(
        self,
        monkeypatch,
    ):
        captured: list = []
        real_dumps = onebot_channel_module.json.dumps

        def capture_dumps(value, *args, **kwargs):
            captured.append(value)
            return real_dumps(value, *args, **kwargs)

        monkeypatch.setattr(onebot_channel_module.json, "dumps", capture_dumps)
        preview = OneBotChannel._message_preview(
            [
                {
                    "type": "image",
                    "data": {
                        "url": "x" * 1_000_000,
                        "nested": {"payload": "y" * 1_000_000},
                    },
                },
            ],
        )

        assert len(preview) <= 200
        assert len(captured[0][0]["data"]["url"]) == 80
        assert captured[0][0]["data"]["nested"] == "<dict>"


class TestInboundMediaResolution:
    async def test_resolve_downloads_all_media_to_local_paths(self, tmp_path):
        config = OneBotConfig(enabled=True, media_dir=str(tmp_path))

        async def _noop_process(_request):
            yield  # pragma: no cover

        ch = OneBotChannel.from_config(_noop_process, config)
        assert ch._media_base64 is False
        parts = [
            TextContent(type=ContentType.TEXT, text="see files"),
            ImageContent(
                type=ContentType.IMAGE,
                image_url="https://cdn.example.com/pic.png",
            ),
            AudioContent(
                type=ContentType.AUDIO,
                data="https://cdn.example.com/voice.amr",
            ),
            VideoContent(
                type=ContentType.VIDEO,
                video_url="https://cdn.example.com/video.mp4",
            ),
            FileContent(
                type=ContentType.FILE,
                file_url="https://cdn.example.com/doc.pdf",
                filename="doc.pdf",
            ),
        ]
        local_paths = [
            str(tmp_path / "pic.png"),
            str(tmp_path / "voice.amr"),
            str(tmp_path / "video.mp4"),
            str(tmp_path / "doc.pdf"),
        ]
        ch._download_remote_media = AsyncMock(side_effect=local_paths)

        resolved = await ch._resolve_inbound_media(
            parts,
            [
                {"type": "image", "data": {"url": parts[1].image_url}},
                {"type": "record", "data": {"url": parts[2].data}},
                {"type": "video", "data": {"url": parts[3].video_url}},
                {
                    "type": "file",
                    "data": {"url": parts[4].file_url, "name": "doc.pdf"},
                },
            ],
            "private",
            {},
        )

        assert [part.type for part in resolved] == [
            ContentType.TEXT,
            ContentType.IMAGE,
            ContentType.AUDIO,
            ContentType.VIDEO,
            ContentType.FILE,
        ]
        assert resolved[1].image_url == local_paths[0]
        assert resolved[2].data == local_paths[1]
        assert resolved[3].video_url == local_paths[2]
        assert resolved[4].file_url == local_paths[3]
        assert ch._download_remote_media.await_count == 4
        assert [
            call.args[1] for call in ch._download_remote_media.await_args_list
        ] == [
            "image",
            "audio",
            "video",
            "file",
        ]

        messages = _request_input_to_msgs(
            [Message(role=Role.USER, content=resolved)],
        )
        media_blocks = messages[0].content[1:]
        assert [str(block.source.url) for block in media_blocks] == [
            Path(path).resolve().as_uri() for path in local_paths
        ]
        media_types = [block.source.media_type for block in media_blocks]
        assert media_types[0] == "image/png"
        assert media_types[1].startswith("audio/")
        assert media_types[2:] == [
            "video/mp4",
            "application/octet-stream",
        ]

    async def test_existing_local_media_is_not_downloaded(self, tmp_path):
        media_file = tmp_path / "pic.png"
        media_file.write_bytes(b"image")
        ch = _make_channel(media_base64=True)
        ch._download_remote_media = AsyncMock()
        part = ImageContent(
            type=ContentType.IMAGE,
            image_url=str(media_file),
        )

        resolved = await ch._resolve_inbound_media(
            [part],
            [{"type": "image", "data": {"file": str(media_file)}}],
            "private",
            {},
        )

        assert resolved[0].image_url == str(media_file.resolve())
        ch._download_remote_media.assert_not_awaited()

    async def test_file_ids_are_resolved_per_segment(self, tmp_path):
        ch = _make_channel(media_base64=True, media_dir=str(tmp_path))
        ch._call_api = AsyncMock(
            side_effect=[
                {"data": {"url": "https://cdn.example.com/a.pdf"}},
                {"data": {"url": "https://cdn.example.com/b.pdf"}},
            ],
        )
        ch._download_remote_media = AsyncMock(
            side_effect=[str(tmp_path / "a.pdf"), str(tmp_path / "b.pdf")],
        )
        parts = [
            FileContent(type=ContentType.FILE, file_url="a.pdf"),
            FileContent(type=ContentType.FILE, file_url="b.pdf"),
        ]

        resolved = await ch._resolve_inbound_media(
            parts,
            [
                {"type": "file", "data": {"file_id": "id-a"}},
                {"type": "file", "data": {"file_id": "id-b"}},
            ],
            "group",
            {"group_id": "67890"},
        )

        assert resolved[0].file_url.endswith("a.pdf")
        assert resolved[1].file_url.endswith("b.pdf")
        assert ch._call_api.await_args_list[0].args[1]["file_id"] == "id-a"
        assert ch._call_api.await_args_list[1].args[1]["file_id"] == "id-b"

    async def test_skipped_media_segment_does_not_shift_source_mapping(
        self,
        tmp_path,
    ):
        ch = _make_channel(media_dir=str(tmp_path))
        ch._download_remote_media = AsyncMock(
            return_value=str(tmp_path / "visible.png"),
        )
        part = ImageContent(
            type=ContentType.IMAGE,
            image_url="https://cdn.example.com/visible.png",
        )

        resolved = await ch._resolve_inbound_media(
            [part],
            [
                {"type": "image", "data": {"file_id": "skipped"}},
                {
                    "type": "image",
                    "data": {
                        "url": part.image_url,
                        "name": "visible.png",
                    },
                },
            ],
            "private",
            {},
        )

        assert resolved[0].image_url.endswith("visible.png")
        assert ch._download_remote_media.await_args.args[2] == 1
        assert ch._download_remote_media.await_args.args[3] == "visible.png"

    async def test_local_media_path_handles_spaces_and_unicode(self, tmp_path):
        media_file = tmp_path / "媒体 file.png"
        media_file.write_bytes(b"image")
        ch = _make_channel()

        assert await ch._local_media_path(str(media_file)) == str(
            media_file.resolve(),
        )

    async def test_api_failure_becomes_placeholder(self):
        ch = _make_channel(media_base64=True)
        ch._call_api = AsyncMock(return_value={"data": {"url": ""}})
        part = FileContent(
            type=ContentType.FILE,
            file_url="missing-onebot-file.bin",
        )

        resolved = await ch._resolve_inbound_media(
            [part],
            [{"type": "file", "data": {"file_id": "missing"}}],
            "private",
            {},
        )

        assert resolved[0].type == ContentType.TEXT
        assert resolved[0].text == "[file: download failed]"


def _make_download_response(
    chunks: list,
    content_type: str = "application/octet-stream",
    content_length: int | None = None,
) -> MagicMock:
    """Build a mocked aiohttp response for ``_download_remote_media``."""
    response = MagicMock()
    response.content_length = content_length
    response.headers = {"Content-Type": content_type}
    response.raise_for_status = MagicMock()

    async def _chunks():
        for chunk in chunks:
            yield chunk

    response.content.iter_chunked.return_value = _chunks()
    return response


def _make_get_context(response: MagicMock) -> MagicMock:
    """Wrap a mocked response as an ``async with session.get(...)`` value."""
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=response)
    ctx.__aexit__ = AsyncMock(return_value=None)
    return ctx


class TestDownloadRemoteMedia:
    """Covers streaming download: session reuse, concurrency limit, atomic
    rename and cleanup of aborted/oversized downloads.  These behaviors
    replace the old ``_inline_remote_images``/``_download_image_data_url``
    path, which is now dead production code and has been removed.
    """

    @pytest.mark.parametrize(
        ("payload", "expected"),
        [
            (b"RIFF\x00\x00\x00\x00WAVE", ".wav"),
            (b"RIFF\x00\x00\x00\x00WEBP", ".webp"),
            (b"RIFF\x00\x00\x00\x00AVI ", ".avi"),
            (b"RIFF\x00\x00\x00\x00JUNK", None),
        ],
    )
    def test_riff_subtype_suffix_detection(self, payload, expected):
        assert OneBotChannel._suffix_from_bytes(payload) == expected

    async def test_download_remote_media_writes_local_file(self, tmp_path):
        ch = _make_channel(media_dir=str(tmp_path))
        response = _make_download_response(
            [b"image"],
            content_type="image/png",
            content_length=5,
        )
        session = MagicMock()
        session.get.return_value = _make_get_context(response)
        session.close = AsyncMock()

        with patch(
            "qwenpaw.app.channels.onebot.channel.aiohttp.ClientSession",
            return_value=session,
        ) as session_cls:
            result = await ch._download_remote_media(
                "https://img.example.com/pic",
                "image",
                0,
                "pic",
            )

        assert result is not None
        path = Path(result)
        assert path.suffix == ".png"
        assert path.read_bytes() == b"image"
        assert not path.name.endswith(".part")
        session.get.assert_called_once_with(
            "https://img.example.com/pic",
            allow_redirects=True,
            max_redirects=3,
        )
        # No channel-level session was running, so a scratch session was
        # created (and must be closed) for this one-off download.
        session_cls.assert_called_once()
        session.close.assert_awaited_once()

    async def test_download_reuses_channel_http_session(self, tmp_path):
        ch = _make_channel(media_dir=str(tmp_path))
        response = _make_download_response([b"%PDF-data"], "application/pdf")
        session = MagicMock()
        session.closed = False
        session.get.return_value = _make_get_context(response)
        session.close = AsyncMock()
        ch._http_session = session

        with patch(
            "qwenpaw.app.channels.onebot.channel.aiohttp.ClientSession",
        ) as session_cls:
            result = await ch._download_remote_media(
                "https://cdn.example.com/doc.pdf",
                "file",
                0,
                "doc.pdf",
            )

        assert result is not None
        session_cls.assert_not_called()
        session.close.assert_not_awaited()

    async def test_download_rejects_oversized_content_length(self, tmp_path):
        ch = _make_channel(media_dir=str(tmp_path), media_download_max_mb=1)
        response = _make_download_response(
            [],
            content_length=ch._media_download_max_bytes + 1,
        )
        session = MagicMock()
        session.closed = False
        session.get.return_value = _make_get_context(response)
        ch._http_session = session

        result = await ch._download_remote_media(
            "https://img.example.com/huge.png",
            "image",
            0,
            "huge.png",
        )

        assert result is None

    async def test_download_aborts_and_cleans_up_when_oversized(
        self,
        tmp_path,
    ):
        ch = _make_channel(media_dir=str(tmp_path))
        ch._media_download_max_bytes = 4
        response = _make_download_response([b"x" * 10])
        session = MagicMock()
        session.closed = False
        session.get.return_value = _make_get_context(response)
        ch._http_session = session

        result = await ch._download_remote_media(
            "https://cdn.example.com/big.bin",
            "file",
            0,
            "big.bin",
        )

        assert result is None
        assert not list(tmp_path.iterdir())

    async def test_download_rejects_empty_body(self, tmp_path):
        ch = _make_channel(media_dir=str(tmp_path))
        response = _make_download_response([], content_type="image/png")
        session = MagicMock()
        session.closed = False
        session.get.return_value = _make_get_context(response)
        ch._http_session = session

        result = await ch._download_remote_media(
            "https://img.example.com/empty.png",
            "image",
            0,
            "empty.png",
        )

        assert result is None
        assert not list(tmp_path.iterdir())

    async def test_download_rejects_mismatched_content_type(self, tmp_path):
        ch = _make_channel(media_dir=str(tmp_path))
        response = _make_download_response(
            [b"<html>not an image</html>"],
            content_type="text/html",
        )
        session = MagicMock()
        session.closed = False
        session.get.return_value = _make_get_context(response)
        ch._http_session = session

        result = await ch._download_remote_media(
            "https://img.example.com/pic.png",
            "image",
            0,
            "pic.png",
        )

        assert result is None
        assert not list(tmp_path.iterdir())

    async def test_download_uses_deterministic_content_type_suffix(
        self,
        tmp_path,
    ):
        ch = _make_channel(media_dir=str(tmp_path))
        response = _make_download_response(
            [b"RIFF\x00\x00\x00\x00WEBP"],
            content_type="image/webp",
        )
        session = MagicMock()
        session.closed = False
        session.get.return_value = _make_get_context(response)
        ch._http_session = session

        result = await ch._download_remote_media(
            "https://img.example.com/download",
            "image",
            0,
            "image",
        )

        assert result is not None
        assert Path(result).suffix == ".webp"

    async def test_download_http_error_returns_none(self, tmp_path):
        ch = _make_channel(media_dir=str(tmp_path))
        session = MagicMock()
        session.closed = False
        request_context = MagicMock()
        request_context.__aenter__ = AsyncMock(
            side_effect=aiohttp.ClientError("boom"),
        )
        request_context.__aexit__ = AsyncMock(return_value=None)
        session.get.return_value = request_context
        ch._http_session = session

        result = await ch._download_remote_media(
            "https://img.example.com/error.png",
            "image",
            0,
            "error.png",
        )

        assert result is None

    async def test_download_enforces_concurrency_limit(self, tmp_path):
        ch = _make_channel(media_dir=str(tmp_path))
        ch._download_semaphore = asyncio.Semaphore(1)
        active = 0
        max_active = 0

        async def _chunks():
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            try:
                await asyncio.sleep(0.05)
                yield b"data"
            finally:
                active -= 1

        def _new_response():
            response = MagicMock()
            response.content_length = None
            response.headers = {"Content-Type": "application/octet-stream"}
            response.raise_for_status = MagicMock()
            response.content.iter_chunked.return_value = _chunks()
            return response

        session = MagicMock()
        session.closed = False
        session.get.side_effect = lambda *a, **k: _make_get_context(
            _new_response(),
        )
        ch._http_session = session

        await asyncio.gather(
            ch._download_remote_media(
                "https://cdn.example.com/a",
                "file",
                0,
                "a",
            ),
            ch._download_remote_media(
                "https://cdn.example.com/b",
                "file",
                1,
                "b",
            ),
        )

        assert max_active == 1


class TestAudioTranscriptionIntegration:
    """End-to-end: a remote OneBot voice message is downloaded/localized
    and reaches transcription through the shared message-processing
    pipeline.  Migrated from ``test_message_processing.py`` so OneBot's
    own download/localization behavior is covered alongside the rest of
    this channel's tests.
    """

    async def test_remote_audio_reaches_transcription(self, tmp_path):
        ch = _make_channel(media_dir=str(tmp_path))
        assert ch._media_base64 is False

        local_audio = tmp_path / "voice.mp3"
        local_audio.write_bytes(b"ID3")
        ch._download_remote_media = AsyncMock(return_value=str(local_audio))
        remote_audio = AudioContent(
            type=ContentType.AUDIO,
            data="https://cdn.example.com/voice.amr",
        )

        resolved = await ch._resolve_inbound_media(
            [remote_audio],
            [{"type": "record", "data": {"url": remote_audio.data}}],
            "private",
            {},
        )

        assert resolved[0].data == str(local_audio)
        ch._download_remote_media.assert_awaited_once()

        messages = _request_input_to_msgs(
            [Message(role=Role.USER, content=resolved)],
        )
        block = messages[0].content[0]
        assert str(block.source.url) == local_audio.resolve().as_uri()

        audio_config = MagicMock()
        audio_config.agents.audio_mode = "auto"
        audio_config.agents.language = "en"
        with patch(
            "qwenpaw.agents.utils.message_processing.load_config",
            return_value=audio_config,
        ), patch(
            "qwenpaw.agents.utils.audio_transcription.transcribe_audio",
            new=AsyncMock(return_value="hello from OneBot"),
        ) as transcribe:
            await process_file_and_media_blocks_in_message(messages[0])

        transcribe.assert_awaited_once_with(str(local_audio.resolve()))
        assert len(messages[0].content) == 1
        assert isinstance(messages[0].content[0], TextBlock)
        assert messages[0].content[0].text == (
            "[Voice message]: hello from OneBot"
        )


# ===================================================================
# Message event handling
# ===================================================================


class TestHandleMessageEvent:
    async def test_private_message_enqueues(self):
        ch = _make_channel()
        enqueued: list = []
        ch._enqueue = enqueued.append

        event = _make_message_event(message_type="private", user_id=12345)
        await ch._handle_message_event(event)

        assert len(enqueued) == 1
        req = enqueued[0]
        assert req.session_id == "onebot:12345"
        assert req.channel_meta["message_type"] == "private"
        assert req.channel_meta["sender_id"] == "12345"

    async def test_group_message_enqueues(self):
        ch = _make_channel()
        enqueued: list = []
        ch._enqueue = enqueued.append

        event = _make_message_event(
            message_type="group",
            user_id=12345,
            group_id=67890,
        )
        await ch._handle_message_event(event)

        assert len(enqueued) == 1
        req = enqueued[0]
        assert req.session_id == "onebot:67890:12345"
        assert req.channel_meta["is_group"] is True
        assert req.channel_meta["group_id"] == "67890"

    async def test_empty_message_ignored(self):
        ch = _make_channel()
        enqueued: list = []
        ch._enqueue = enqueued.append

        event = _make_message_event(segments=[])
        await ch._handle_message_event(event)
        assert len(enqueued) == 0

    async def test_string_message_wrapped(self):
        """OneBot implementations may send message as plain string."""
        ch = _make_channel()
        enqueued: list = []
        ch._enqueue = enqueued.append

        event = _make_message_event()
        event["message"] = "plain text message"
        await ch._handle_message_event(event)

        assert len(enqueued) == 1

    async def test_access_control_dm_flag(self):
        ch = _make_channel(
            access_control_dm=True,
        )
        # access_control_dm=True should enable access control
        assert ch.access_control_dm is True
        assert ch.access_control_enabled is True

    async def test_allowlist_allows_permitted_user(self):
        ch = _make_channel(
            dm_policy="allowlist",
            allow_from=["12345"],
        )
        enqueued: list = []
        ch._enqueue = enqueued.append

        event = _make_message_event(user_id=12345)
        await ch._handle_message_event(event)
        assert len(enqueued) == 1

    async def test_require_mention_blocks_without_at(self):
        ch = _make_channel(require_mention=True)
        ch._self_id = 99999
        enqueued: list = []
        ch._enqueue = enqueued.append

        event = _make_message_event(
            message_type="group",
            group_id=67890,
            segments=[{"type": "text", "data": {"text": "hello"}}],
        )
        await ch._handle_message_event(event)
        assert len(enqueued) == 0

    async def test_require_mention_blocks_before_remote_image_download(self):
        ch = _make_channel(require_mention=True, media_base64=True)
        ch._self_id = 99999
        ch._download_remote_media = AsyncMock(
            return_value="/tmp/onebot-media/pic.png",
        )
        enqueued: list = []
        ch._enqueue = enqueued.append

        event = _make_message_event(
            message_type="group",
            group_id=67890,
            segments=[
                {
                    "type": "image",
                    "data": {"url": "https://img.example.com/pic.png"},
                },
            ],
        )
        await ch._handle_message_event(event)

        assert len(enqueued) == 0
        ch._download_remote_media.assert_not_called()

    async def test_require_mention_allows_with_at(self):
        ch = _make_channel(require_mention=True)
        ch._self_id = 99999
        enqueued: list = []
        ch._enqueue = enqueued.append

        event = _make_message_event(
            message_type="group",
            group_id=67890,
            segments=[
                {"type": "at", "data": {"qq": "99999"}},
                {"type": "text", "data": {"text": "hello"}},
            ],
        )
        await ch._handle_message_event(event)
        assert len(enqueued) == 1

    async def test_require_mention_allows_with_event_self_id(self):
        ch = _make_channel(require_mention=True)
        enqueued: list = []
        ch._enqueue = enqueued.append

        event = _make_message_event(
            message_type="group",
            group_id=67890,
            segments=[
                {"type": "at", "data": {"qq": "99999"}},
                {"type": "text", "data": {"text": "hello"}},
            ],
        )
        event["self_id"] = 99999
        await ch._handle_message_event(event)

        assert len(enqueued) == 1
        assert ch._self_id == 99999

    async def test_quoted_text_is_fetched_after_mention(self):
        ch = _make_channel(require_mention=True)
        ch._self_id = 99999
        ch._call_api = AsyncMock(
            return_value={
                "data": {
                    "message": [
                        {"type": "text", "data": {"text": "quoted text"}},
                    ],
                },
            },
        )
        enqueued: list = []
        ch._enqueue = enqueued.append

        event = _make_message_event(
            message_type="group",
            group_id=67890,
            segments=[
                {"type": "reply", "data": {"id": "321"}},
                {"type": "at", "data": {"qq": "99999"}},
                {"type": "text", "data": {"text": "please answer"}},
            ],
        )
        await ch._handle_message_event(event)

        ch._call_api.assert_awaited_once_with("get_msg", {"message_id": 321})
        assert len(enqueued) == 1
        content = enqueued[0].input[0].content
        assert len(content) == 1
        assert content[0].text == (
            "[Quoted message]\nquoted text\n\n"
            "[Current message]\nplease answer"
        )

    async def test_quoted_cq_image_is_marked_as_quoted_content(self):
        ch = _make_channel(require_mention=True)
        ch._self_id = 99999
        ch._call_api = AsyncMock(
            return_value={
                "data": {
                    "message": (
                        "[CQ:image,file=pic.jpg,"
                        "url=https://img.example.com/pic.jpg]"
                    ),
                },
            },
        )
        ch._download_remote_media = AsyncMock(
            return_value="C:/media/quoted-pic.jpg",
        )
        enqueued: list = []
        ch._enqueue = enqueued.append

        event = _make_message_event(
            message_type="group",
            group_id=67890,
            segments=[
                {"type": "reply", "data": {"id": "321"}},
                {"type": "at", "data": {"qq": "99999"}},
                {"type": "text", "data": {"text": "describe it"}},
            ],
        )
        await ch._handle_message_event(event)

        content = enqueued[0].input[0].content
        assert content[0].text == "[Quoted message]"
        assert content[1].text == "[Quoted image message]"
        assert content[2].type == ContentType.IMAGE
        assert content[2].image_url == "C:/media/quoted-pic.jpg"
        assert content[3].text == "[Current message]"
        assert content[4].text == "describe it"

    async def test_quoted_raw_message_is_used_when_message_is_text(self):
        ch = _make_channel(require_mention=True)
        ch._self_id = 99999
        ch._call_api = AsyncMock(
            return_value={
                "data": {
                    "message": "[图片]",
                    "raw_message": (
                        "[CQ:image,file=pic.jpg,"
                        "url=https://img.example.com/pic.jpg]"
                    ),
                },
            },
        )
        ch._download_remote_media = AsyncMock(
            return_value="C:/media/quoted-raw-pic.jpg",
        )
        enqueued: list = []
        ch._enqueue = enqueued.append

        event = _make_message_event(
            message_type="group",
            group_id=67890,
            segments=[
                {"type": "reply", "data": {"id": "321"}},
                {"type": "at", "data": {"qq": "99999"}},
                {"type": "text", "data": {"text": "describe it"}},
            ],
        )
        await ch._handle_message_event(event)

        content = enqueued[0].input[0].content
        assert content[0].text == "[Quoted message]"
        assert content[1].text == "[Quoted image message]"
        assert content[2].type == ContentType.IMAGE
        assert content[2].image_url == "C:/media/quoted-raw-pic.jpg"
        assert content[3].text == "[Current message]"
        assert content[4].text == "describe it"

    async def test_quoted_record_is_marked_as_voice_content(self):
        ch = _make_channel(require_mention=True)
        ch._self_id = 99999
        ch._call_api = AsyncMock(
            return_value={
                "data": {
                    "message": [
                        {
                            "type": "record",
                            "data": {
                                "file": "voice.amr",
                                "url": (
                                    "https://qq.example/" "download?file=voice"
                                ),
                            },
                        },
                    ],
                },
            },
        )
        ch._download_remote_media = AsyncMock(
            return_value="C:/media/quoted-voice.amr",
        )
        enqueued: list = []
        ch._enqueue = enqueued.append

        event = _make_message_event(
            message_type="group",
            group_id=67890,
            segments=[
                {"type": "reply", "data": {"id": "321"}},
                {"type": "at", "data": {"qq": "99999"}},
                {"type": "text", "data": {"text": "what is it"}},
            ],
        )
        await ch._handle_message_event(event)

        content = enqueued[0].input[0].content
        assert content[1].text == "[Quoted voice message]"
        assert content[2].type == ContentType.AUDIO
        assert content[2].data == "C:/media/quoted-voice.amr"
        assert content[3].text == "[Current message]"
        assert content[4].text == "what is it"

    async def test_quoted_file_uses_existing_file_url_resolution(self):
        ch = _make_channel(require_mention=True)
        ch._self_id = 99999
        ch._call_api = AsyncMock(
            side_effect=[
                {
                    "data": {
                        "message": [
                            {
                                "type": "file",
                                "data": {
                                    "file": "doc.pdf",
                                    "file_id": "quoted-file-id",
                                    "name": "doc.pdf",
                                },
                            },
                        ],
                    },
                },
                {"data": {"url": "https://files.example.com/doc.pdf"}},
            ],
        )
        ch._download_remote_media = AsyncMock(
            return_value="C:/media/quoted-doc.pdf",
        )
        enqueued: list = []
        ch._enqueue = enqueued.append

        event = _make_message_event(
            message_type="group",
            group_id=67890,
            segments=[
                {"type": "reply", "data": {"id": "321"}},
                {"type": "at", "data": {"qq": "99999"}},
            ],
        )
        await ch._handle_message_event(event)

        assert ch._call_api.await_args_list[0].args == (
            "get_msg",
            {"message_id": 321},
        )
        assert ch._call_api.await_args_list[1].args == (
            "get_group_file_url",
            {"group_id": 67890, "file_id": "quoted-file-id"},
        )
        assert len(enqueued) == 1
        assert enqueued[0].input[0].content[2].file_url == (
            "C:/media/quoted-doc.pdf"
        )
        assert enqueued[0].input[0].content[1].text == (
            "[Quoted file message: doc.pdf]"
        )

    async def test_quoted_and_current_files_keep_their_own_file_ids(self):
        ch = _make_channel(require_mention=True)
        ch._self_id = 99999
        ch._call_api = AsyncMock(
            side_effect=[
                {
                    "data": {
                        "message": [
                            {
                                "type": "file",
                                "data": {
                                    "file": "quoted.pdf",
                                    "file_id": "quoted-file-id",
                                    "name": "quoted.pdf",
                                },
                            },
                        ],
                    },
                },
                {"data": {"url": "https://files.example/quoted.pdf"}},
                {"data": {"url": "https://files.example/current.pdf"}},
            ],
        )
        ch._download_remote_media = AsyncMock(
            side_effect=[
                "C:/media/quoted.pdf",
                "C:/media/current.pdf",
            ],
        )
        enqueued: list = []
        ch._enqueue = enqueued.append

        event = _make_message_event(
            message_type="group",
            group_id=67890,
            segments=[
                {"type": "reply", "data": {"id": "321"}},
                {"type": "at", "data": {"qq": "99999"}},
                {
                    "type": "file",
                    "data": {
                        "file": "current.pdf",
                        "file_id": "current-file-id",
                        "name": "current.pdf",
                    },
                },
            ],
        )
        await ch._handle_message_event(event)

        assert ch._call_api.await_args_list[1].args == (
            "get_group_file_url",
            {"group_id": 67890, "file_id": "quoted-file-id"},
        )
        assert ch._call_api.await_args_list[2].args == (
            "get_group_file_url",
            {"group_id": 67890, "file_id": "current-file-id"},
        )
        content = enqueued[0].input[0].content
        assert content[2].file_url == "C:/media/quoted.pdf"
        assert content[4].file_url == "C:/media/current.pdf"

    async def test_unmentioned_reply_does_not_call_get_msg(self):
        ch = _make_channel(require_mention=True)
        ch._self_id = 99999
        ch._call_api = AsyncMock()
        enqueued: list = []
        ch._enqueue = enqueued.append

        event = _make_message_event(
            message_type="group",
            group_id=67890,
            segments=[{"type": "reply", "data": {"id": "321"}}],
        )
        await ch._handle_message_event(event)

        ch._call_api.assert_not_awaited()
        assert not enqueued

    async def test_access_control_blocks_before_quoted_message_lookup(self):
        """ACL must run before any reply-quote lookup or media I/O so a
        blocked sender never triggers OneBot API calls or downloads."""
        ch = _make_channel(access_control_dm=True)
        ch._access_control_gate = AsyncMock(return_value=True)
        ch._get_quoted_message_segments = AsyncMock()
        ch._resolve_inbound_media = AsyncMock()
        enqueued: list = []
        ch._enqueue = enqueued.append

        event = _make_message_event(
            segments=[
                {"type": "reply", "data": {"id": "321"}},
                {"type": "text", "data": {"text": "hello"}},
            ],
        )
        await ch._handle_message_event(event)

        ch._access_control_gate.assert_awaited_once()
        gate_payload = ch._access_control_gate.await_args.args[0]
        assert gate_payload["acl_sender_id"] == "12345"
        ch._get_quoted_message_segments.assert_not_awaited()
        ch._resolve_inbound_media.assert_not_awaited()
        assert len(enqueued) == 0

    async def test_access_control_blocks_before_media_download(self):
        ch = _make_channel(access_control_dm=True)
        ch._access_control_gate = AsyncMock(return_value=True)
        ch._download_remote_media = AsyncMock()
        enqueued: list = []
        ch._enqueue = enqueued.append

        event = _make_message_event(
            segments=[
                {
                    "type": "image",
                    "data": {"url": "https://img.example.com/pic.png"},
                },
            ],
        )
        await ch._handle_message_event(event)

        ch._access_control_gate.assert_awaited_once()
        ch._download_remote_media.assert_not_awaited()
        assert len(enqueued) == 0

    async def test_access_control_allows_when_gate_passes(self):
        ch = _make_channel(access_control_dm=True)
        ch._access_control_gate = AsyncMock(return_value=False)
        enqueued: list = []
        ch._enqueue = enqueued.append

        event = _make_message_event()
        await ch._handle_message_event(event)

        ch._access_control_gate.assert_awaited_once()
        assert len(enqueued) == 1


# ===================================================================
# Session ID resolution
# ===================================================================


class TestResolveSessionId:
    def test_private_session(self):
        ch = _make_channel()
        sid = ch.resolve_session_id("12345", {"is_group": False})
        assert sid == "onebot:12345"

    def test_group_per_user(self):
        ch = _make_channel(share_session_in_group=False)
        sid = ch.resolve_session_id(
            "12345",
            {"is_group": True, "group_id": "67890"},
        )
        assert sid == "onebot:67890:12345"

    def test_group_shared(self):
        ch = _make_channel(share_session_in_group=True)
        sid = ch.resolve_session_id(
            "12345",
            {"is_group": True, "group_id": "67890"},
        )
        assert sid == "onebot:g:67890"


# ===================================================================
# get_to_handle_from_request
# ===================================================================


class TestGetToHandle:
    def test_group_message(self):
        ch = _make_channel()
        req = MagicMock()
        req.channel_meta = {"is_group": True, "group_id": "67890"}
        assert ch.get_to_handle_from_request(req) == "group:67890"

    def test_private_message(self):
        ch = _make_channel()
        req = MagicMock()
        req.channel_meta = {"is_group": False, "sender_id": "12345"}
        assert ch.get_to_handle_from_request(req) == "12345"


# ===================================================================
# Send methods
# ===================================================================


class TestSend:
    async def test_disabled_channel_noop(self):
        ch = _make_channel(enabled=False)
        ch._call_api = AsyncMock()
        await ch.send("12345", "hello")
        ch._call_api.assert_not_called()

    async def test_empty_text_noop(self):
        ch = _make_channel()
        ch._call_api = AsyncMock()
        await ch.send("12345", "   ")
        ch._call_api.assert_not_called()

    async def test_private_message_send(self):
        ch = _make_channel()
        ch._call_api = AsyncMock(return_value={"retcode": 0})
        await ch.send("12345", "hello", {"sender_id": "12345"})
        ch._call_api.assert_called_once_with(
            "send_private_msg",
            {
                "user_id": 12345,
                "message": [{"type": "text", "data": {"text": "hello"}}],
            },
        )

    async def test_group_message_send_via_meta(self):
        ch = _make_channel()
        ch._call_api = AsyncMock(return_value={"retcode": 0})
        await ch.send(
            "group:67890",
            "hello group",
            {"is_group": True, "group_id": "67890"},
        )
        ch._call_api.assert_called_once_with(
            "send_group_msg",
            {
                "group_id": 67890,
                "message": [{"type": "text", "data": {"text": "hello group"}}],
            },
        )

    async def test_group_message_send_via_to_handle(self):
        ch = _make_channel()
        ch._call_api = AsyncMock(return_value={"retcode": 0})
        await ch.send("group:67890", "hi")
        ch._call_api.assert_called_once()
        args = ch._call_api.call_args
        assert args[0][0] == "send_group_msg"
        assert args[0][1]["group_id"] == 67890

    async def test_send_cleans_link_markup_and_preserves_comments(self):
        ch = _make_channel()
        ch._call_api = AsyncMock(return_value={"retcode": 0})

        await ch.send(
            "12345",
            "为你找到了链接：\n**https://example.com/profile**\n"
            "[profile](https://example.com/card)\n"
            "`[inline](https://example.com/inline)`\n"
            "```\n**https://example.com/code**\n```\n"
            "<!-- internal lookup note -->",
            {"sender_id": "12345"},
        )

        args = ch._call_api.call_args[0]
        assert args[0] == "send_private_msg"
        assert args[1]["message"] == [
            {
                "type": "text",
                "data": {
                    "text": "为你找到了链接：\n"
                    "https://example.com/profile\n"
                    "profile: https://example.com/card\n"
                    "`[inline](https://example.com/inline)`\n"
                    "```\n**https://example.com/code**\n```\n"
                    "<!-- internal lookup note -->",
                },
            },
        ]

    def test_outbound_normalize_media_ref_policy(self, tmp_path):
        image = tmp_path / "pic.png"
        image.write_bytes(b"fake")

        assert (
            _normalize_media_ref_sync(
                image.as_uri(),
                media_base64_max_bytes=10 * 1024 * 1024,
            )
            == image.as_uri()
        )
        assert (
            _normalize_media_ref_sync(
                image.as_uri(),
                media_base64=True,
                media_base64_max_bytes=10 * 1024 * 1024,
            )
            == "base64://ZmFrZQ=="
        )
        assert (
            _normalize_media_ref_sync(
                image.as_uri(),
                media_base64=True,
                media_base64_max_bytes=1,
            )
            == image.as_uri()
        )
        assert (
            _normalize_media_ref_sync(
                "data:image/png;base64,ZmFrZQ==",
                media_base64_max_bytes=10 * 1024 * 1024,
            )
            == "base64://ZmFrZQ=="
        )


class TestSendMedia:
    async def test_send_image(self):
        ch = _make_channel()
        ch._call_api = AsyncMock(return_value={"retcode": 0})
        part = ImageContent(
            type=ContentType.IMAGE,
            image_url="https://img.example.com/pic.png",
        )
        await ch.send_media("12345", part, {"sender_id": "12345"})
        ch._call_api.assert_called_once()
        args = ch._call_api.call_args[0]
        assert args[0] == "send_private_msg"
        assert args[1]["message"][0]["type"] == "image"

    async def test_send_audio(self):
        ch = _make_channel()
        ch._call_api = AsyncMock(return_value={"retcode": 0})
        part = AudioContent(type=ContentType.AUDIO, data="https://a.com/v.mp3")
        await ch.send_media("12345", part, {"sender_id": "12345"})
        ch._call_api.assert_called_once()
        args = ch._call_api.call_args[0]
        assert args[1]["message"][0]["type"] == "record"

    async def test_send_video(self):
        ch = _make_channel()
        ch._call_api = AsyncMock(return_value={"retcode": 0})
        part = VideoContent(
            type=ContentType.VIDEO,
            video_url="https://v.com/v.mp4",
        )
        await ch.send_media("12345", part, {"sender_id": "12345"})
        ch._call_api.assert_called_once()
        args = ch._call_api.call_args[0]
        assert args[1]["message"][0]["type"] == "video"

    async def test_send_file_private(self):
        ch = _make_channel()
        ch._call_api = AsyncMock(return_value={"retcode": 0})
        part = FileContent(
            type=ContentType.FILE,
            file_url="https://f.com/doc.pdf",
            filename="doc.pdf",
        )
        await ch.send_media("12345", part, {"sender_id": "12345"})
        ch._call_api.assert_called_once_with(
            "upload_private_file",
            {
                "user_id": 12345,
                "file": "https://f.com/doc.pdf",
                "name": "doc.pdf",
            },
        )

    async def test_send_file_to_group(self):
        ch = _make_channel()
        ch._call_api = AsyncMock(return_value={"retcode": 0})
        part = FileContent(
            type=ContentType.FILE,
            file_url="https://f.com/report.xlsx",
            filename="report.xlsx",
        )
        await ch.send_media(
            "group:67890",
            part,
            {"is_group": True, "group_id": "67890"},
        )
        ch._call_api.assert_called_once_with(
            "upload_group_file",
            {
                "group_id": 67890,
                "file": "https://f.com/report.xlsx",
                "name": "report.xlsx",
            },
        )

    async def test_send_file_converts_local_path_when_enabled(self, tmp_path):
        file_path = tmp_path / "report.txt"
        file_path.write_bytes(b"fake")
        ch = _make_channel(media_base64=True)
        ch._call_api = AsyncMock(return_value={"retcode": 0})

        await ch.send_media(
            "12345",
            FileContent(file_url=file_path.as_uri(), filename="report.txt"),
            {"sender_id": "12345"},
        )

        assert ch._call_api.call_args.args[1]["file"] == "base64://ZmFrZQ=="

    async def test_send_file_no_url_noop(self):
        ch = _make_channel()
        ch._call_api = AsyncMock()
        part = FileContent(type=ContentType.FILE, file_url="")
        await ch.send_media("12345", part, {"sender_id": "12345"})
        ch._call_api.assert_not_called()

    async def test_send_image_to_group(self):
        ch = _make_channel()
        ch._call_api = AsyncMock(return_value={"retcode": 0})
        part = ImageContent(
            type=ContentType.IMAGE,
            image_url="https://img.example.com/pic.png",
        )
        await ch.send_media(
            "group:67890",
            part,
            {"is_group": True, "group_id": "67890"},
        )
        args = ch._call_api.call_args[0]
        assert args[0] == "send_group_msg"
        assert args[1]["group_id"] == 67890

    async def test_send_content_parts_preserves_order_and_prefix(self):
        ch = _make_channel()
        ch._call_api = AsyncMock(return_value={"retcode": 0})

        await ch.send_content_parts(
            "12345",
            [
                TextContent(type=ContentType.TEXT, text="这是截图"),
                ImageContent(
                    type=ContentType.IMAGE,
                    image_url="https://img.example.com/pic.png",
                ),
                TextContent(type=ContentType.TEXT, text="补充说明"),
            ],
            {"sender_id": "12345", "bot_prefix": "[BOT]"},
        )

        assert ch._call_api.call_count == 3
        first = ch._call_api.call_args_list[0][0]
        second = ch._call_api.call_args_list[1][0]
        third = ch._call_api.call_args_list[2][0]
        assert first == (
            "send_private_msg",
            {
                "user_id": 12345,
                "message": [
                    {"type": "text", "data": {"text": "[BOT]  这是截图"}},
                ],
            },
        )
        assert second == (
            "send_private_msg",
            {
                "user_id": 12345,
                "message": [
                    {
                        "type": "image",
                        "data": {"file": "https://img.example.com/pic.png"},
                    },
                ],
            },
        )
        assert third == (
            "send_private_msg",
            {
                "user_id": 12345,
                "message": [
                    {"type": "text", "data": {"text": "补充说明"}},
                ],
            },
        )

    async def test_send_strips_think_blocks_when_hidden(self):
        ch = _make_channel(
            display_config=ChannelDisplayConfig(show_thinking=False),
        )
        ch._call_api = AsyncMock(return_value={"retcode": 0})

        await ch.send(
            "12345",
            "before\n<think>private reasoning</think>\nafter",
            {"sender_id": "12345"},
        )

        message = ch._call_api.call_args.args[1]["message"]
        assert message == [
            {"type": "text", "data": {"text": "before\n\nafter"}},
        ]

    async def test_send_preserves_think_blocks_inside_code_fences(self):
        ch = _make_channel(
            display_config=ChannelDisplayConfig(show_thinking=False),
        )
        ch._call_api = AsyncMock(return_value={"retcode": 0})

        await ch.send(
            "12345",
            (
                "```xml\n<think>literal</think>\n```\n"
                "<think>secret</think>\nanswer"
            ),
            {"sender_id": "12345"},
        )

        message = ch._call_api.call_args.args[1]["message"]
        assert message == [
            {
                "type": "text",
                "data": {
                    "text": "```xml\n<think>literal</think>\n```\n\nanswer",
                },
            },
        ]

    async def test_send_keeps_think_blocks_when_visible(self):
        ch = _make_channel(
            display_config=ChannelDisplayConfig(show_thinking=True),
        )
        ch._call_api = AsyncMock(return_value={"retcode": 0})

        await ch.send(
            "12345",
            "<think>visible reasoning</think>\nanswer",
            {"sender_id": "12345"},
        )

        message = ch._call_api.call_args.args[1]["message"]
        assert message == [
            {
                "type": "text",
                "data": {"text": "<think>visible reasoning</think>\nanswer"},
            },
        ]


# ===================================================================
# Echo-based API calls
# ===================================================================


class TestCallApi:
    async def test_no_connections_returns_empty(self):
        ch = _make_channel()
        result = await ch._call_api("get_login_info", {})
        assert result == {}

    async def test_successful_call(self):
        ch = _make_channel()
        ws = AsyncMock()
        ch._connections.add(ws)

        async def simulate_response():
            await asyncio.sleep(0.01)
            # Find the pending echo and resolve it
            for echo, fut in list(ch._pending_calls.items()):
                if not fut.done():
                    fut.set_result(
                        {"retcode": 0, "data": {"user_id": 99}, "echo": echo},
                    )

        task = asyncio.create_task(simulate_response())
        result = await ch._call_api("get_login_info", {})
        await task
        assert result.get("retcode") == 0

    async def test_timeout_returns_empty(self):
        ch = _make_channel()
        ws = AsyncMock()
        ch._connections.add(ws)

        # Don't resolve the future — will timeout
        # Use a very short timeout for testing
        import unittest.mock

        with unittest.mock.patch(
            "asyncio.wait_for",
            side_effect=asyncio.TimeoutError,
        ):
            result = await ch._call_api("slow_action", {})
        assert result == {}


class TestHandleApiResponse:
    def test_matching_echo_resolves_future(self):
        ch = _make_channel()
        loop = asyncio.new_event_loop()
        fut = loop.create_future()
        ch._pending_calls["abc-123"] = fut

        ch._handle_api_response(
            {"retcode": 0, "data": {}, "echo": "abc-123"},
        )
        assert fut.done()
        assert fut.result()["retcode"] == 0
        loop.close()

    def test_unknown_echo_ignored(self):
        ch = _make_channel()
        # Should not raise
        ch._handle_api_response({"retcode": 0, "echo": "unknown"})


# ===================================================================
# Meta event handling
# ===================================================================


class TestHandleMetaEvent:
    def test_lifecycle_connect_sets_self_id(self):
        ch = _make_channel()
        ch._handle_meta_event(
            {
                "post_type": "meta_event",
                "meta_event_type": "lifecycle",
                "sub_type": "connect",
                "self_id": 99999,
            },
        )
        assert ch._self_id == 99999

    def test_heartbeat_does_not_crash(self):
        ch = _make_channel()
        ch._handle_meta_event(
            {
                "post_type": "meta_event",
                "meta_event_type": "heartbeat",
                "self_id": 99999,
            },
        )


# ===================================================================
# Event dispatch
# ===================================================================


class TestSessionEventOrdering:
    async def test_dispatch_preserves_order_and_reclaims_idle_worker(
        self,
        monkeypatch,
    ):
        monkeypatch.setattr(
            onebot_channel_module,
            "_SESSION_QUEUE_IDLE_TIMEOUT_SECONDS",
            0.01,
        )
        ch = _make_channel()
        order = []

        async def handle(data):
            order.append(data["message_id"])
            if data["message_id"] == 1:
                await asyncio.sleep(0.02)

        ch._handle_message_event = AsyncMock(side_effect=handle)
        first = _make_message_event(message_id=1)
        second = _make_message_event(message_id=2)

        ch._dispatch_message_event(first)
        key = ch._session_queue_key(first)
        queue = ch._session_queues[key]
        ch._dispatch_message_event(second)
        await queue.join()
        await asyncio.sleep(0.03)

        assert order == [1, 2]
        assert key not in ch._session_queues
        assert key not in ch._session_workers

    def test_dispatch_drops_events_while_stopping(self):
        ch = _make_channel()
        ch._stopping = True

        ch._dispatch_message_event(_make_message_event())

        assert not ch._session_queues
        assert not ch._session_workers


class TestHandleEvent:
    async def test_meta_event_dispatched(self):
        ch = _make_channel()
        await ch._handle_event(
            {
                "post_type": "meta_event",
                "meta_event_type": "lifecycle",
                "sub_type": "connect",
                "self_id": 88888,
            },
        )
        assert ch._self_id == 88888

    async def test_message_event_dispatched(self):
        ch = _make_channel()
        enqueued: list = []
        ch._enqueue = enqueued.append

        await ch._handle_event(
            _make_message_event(message_type="private", user_id=11111),
        )
        assert len(enqueued) == 1

    async def test_notice_event_ignored(self):
        ch = _make_channel()
        enqueued: list = []
        ch._enqueue = enqueued.append

        await ch._handle_event({"post_type": "notice", "notice_type": "poke"})
        assert len(enqueued) == 0


# ===================================================================
# build_agent_request_from_native
# ===================================================================


class TestBuildAgentRequest:
    def test_basic_request(self):
        ch = _make_channel()
        native = {
            "channel_id": "onebot",
            "sender_id": "12345",
            "content_parts": [
                TextContent(type=ContentType.TEXT, text="hi"),
            ],
            "meta": {"is_group": False},
        }
        req = ch.build_agent_request_from_native(native)
        assert req.session_id == "onebot:12345"
        assert req.user_id == "12345"
        assert req.channel == "onebot"
        assert len(req.input) == 1
        assert req.input[0].content[0].text == "hi"


# ===================================================================
# Lifecycle
# ===================================================================


class TestLifecycle:
    async def test_disabled_start_noop(self):
        ch = _make_channel(enabled=False)
        await ch.start()
        assert ch._app is None

    async def test_disabled_stop_noop(self):
        ch = _make_channel(enabled=False)
        await ch.stop()

    async def test_start_creates_server(self):
        ch = _make_channel(ws_port=0)  # port 0 = OS picks free port
        await ch.start()
        assert ch._app is not None
        assert ch._runner is not None
        assert ch._site is not None
        assert ch._watchdog_task is not None
        assert not ch._watchdog_task.done()
        await ch.stop()
        assert ch._site is None
        assert ch._runner is None
        assert ch._stopping is True


# ===================================================================
# Watchdog / reconnect
# ===================================================================


class TestWatchdog:
    async def test_watchdog_restarts_when_site_is_none(self):
        """Watchdog should restart the WS server if _site becomes None."""
        ch = _make_channel(ws_port=0)
        ch._watchdog_interval = 0.05  # speed up for test
        await ch.start()
        assert ch._site is not None

        # Simulate server crash: clear server state without full stop
        old_site = ch._site
        await old_site.stop()
        await ch._runner.cleanup()
        ch._site = None
        ch._runner = None
        ch._app = None

        # Wait for watchdog to detect and restart
        await asyncio.sleep(0.2)

        assert ch._site is not None, "watchdog should have restarted server"
        assert ch._app is not None
        assert ch._runner is not None

        await ch.stop()

    async def test_watchdog_restarts_when_port_unreachable(self):
        """Watchdog should restart if _site exists but port is dead."""
        ch = _make_channel(ws_port=0)
        ch._watchdog_interval = 0.05
        await ch.start()
        assert ch._site is not None

        # Simulate TCPSite still exists but underlying socket is dead:
        # stop the site but keep the Python object reference
        old_site = ch._site
        await old_site.stop()
        # _site is NOT None, but the port is no longer listening

        # Wait for watchdog to detect via TCP probe and restart
        await asyncio.sleep(0.3)

        assert ch._site is not None
        assert (
            ch._site is not old_site
        ), "watchdog should have created a new site"

        await ch.stop()

    async def test_watchdog_stops_on_channel_stop(self):
        """Watchdog task should be cancelled when channel stops."""
        ch = _make_channel(ws_port=0)
        ch._watchdog_interval = 0.05
        await ch.start()
        watchdog = ch._watchdog_task
        assert watchdog is not None

        await ch.stop()
        assert watchdog.done()

    async def test_watchdog_no_restart_when_healthy(self):
        """Watchdog should not touch a healthy server."""
        ch = _make_channel(ws_port=0)
        ch._watchdog_interval = 0.05
        await ch.start()
        original_site = ch._site

        # Wait a couple of watchdog cycles
        await asyncio.sleep(0.15)

        # Site should remain the same object (not recreated)
        assert ch._site is original_site
        await ch.stop()

    async def test_is_server_healthy_when_listening(self):
        """_is_server_healthy returns True when port is accepting."""
        ch = _make_channel(ws_port=0)
        await ch._start_ws_server()
        assert await ch._is_server_healthy() is True
        await ch._stop_ws_server()

    async def test_is_server_healthy_when_site_none(self):
        """_is_server_healthy returns False when _site is None."""
        ch = _make_channel(ws_port=0)
        assert await ch._is_server_healthy() is False


# ===================================================================
# Preview helper
# ===================================================================


class TestPreviewText:
    def test_text_content(self):
        parts = [TextContent(type=ContentType.TEXT, text="hello world")]
        assert OneBotChannel._preview_text(parts) == "hello world"

    def test_non_text_content(self):
        parts = [
            ImageContent(
                type=ContentType.IMAGE,
                image_url="https://x.com/i.png",
            ),
        ]
        assert OneBotChannel._preview_text(parts) == "<non-text>"

    def test_empty_parts(self):
        assert OneBotChannel._preview_text([]) == "<non-text>"


# ===================================================================
# Port bind retry during _start_ws_server
# ===================================================================


class TestPortBindGracefulDegradation:
    """Tests for graceful degradation when port is in use."""

    async def test_port_conflict_does_not_raise(self):
        """_start_ws_server should not raise on OSError (port in use).

        It should clean up and leave _site as None so the watchdog
        can retry later.
        """
        ch = _make_channel(ws_port=0)

        async def always_fail(self_site):
            raise OSError(98, "address already in use")

        with patch.object(TCPSite, "start", always_fail):
            # Should NOT raise
            await ch._start_ws_server()

        # State should be cleaned up for watchdog recovery
        assert ch._site is None
        assert ch._runner is None
        assert ch._app is None

    async def test_watchdog_recovers_after_port_conflict(self):
        """Watchdog should recover the server after initial port conflict."""
        ch = _make_channel(ws_port=0)
        ch._watchdog_interval = 0.05

        fail_count = 1
        original_tcp_start = TCPSite.start

        async def mock_site_start(self_site):
            nonlocal fail_count
            if fail_count > 0:
                fail_count -= 1
                raise OSError(98, "address already in use")
            return await original_tcp_start(self_site)

        with patch.object(TCPSite, "start", mock_site_start):
            await ch.start()
            # Initial start failed, _site is None
            assert ch._site is None

        # Watchdog should recover (no patch, real start succeeds)
        await asyncio.sleep(0.3)
        assert ch._site is not None

        await ch.stop()

    async def test_non_oserror_still_raises(self):
        """Non-OSError exceptions should propagate normally."""
        ch = _make_channel(ws_port=0)

        async def fail_with_runtime_error(self_site):
            raise RuntimeError("unexpected error")

        with patch.object(TCPSite, "start", fail_with_runtime_error):
            try:
                await ch._start_ws_server()
                assert False, "Should have raised RuntimeError"
            except RuntimeError:
                pass


class _ReachedAccept(Exception):
    """Sentinel proving a handshake passed every authentication guard."""


class TestConnectionAuth:
    """Tests for reverse WebSocket handshake authentication."""

    @staticmethod
    def _request(path: str = "/ws", authorization: str | None = None):
        headers = (
            {} if authorization is None else {"Authorization": authorization}
        )
        return make_mocked_request("GET", path, headers=headers)

    @staticmethod
    def _sentinel_prepare():
        """Patch ``prepare`` so reaching it raises :class:`_ReachedAccept`.

        ``prepare`` runs right after the authentication guards, so the
        sentinel distinguishes "accepted" from "rejected" without a real
        WebSocket upgrade.
        """

        async def _prepare(_self, _request):
            raise _ReachedAccept

        return patch.object(web.WebSocketResponse, "prepare", _prepare)

    async def test_non_loopback_without_token_rejects_connection(
        self,
        caplog,
    ):
        """The server keeps listening but refuses every client."""
        ch = _make_channel(ws_host="0.0.0.0", access_token="")

        with caplog.at_level(logging.ERROR):
            resp = await ch._handle_ws_connection(self._request())

        assert resp.status == 401
        assert not ch._connections
        assert "access_token is empty" in caplog.text

    async def test_loopback_without_token_accepts_connection(self):
        """Existing local setups keep working without a token."""
        ch = _make_channel(ws_host="127.0.0.1", access_token="")

        with self._sentinel_prepare():
            with pytest.raises(_ReachedAccept):
                await ch._handle_ws_connection(self._request())

    async def test_non_loopback_with_valid_token_accepts_connection(self):
        """Exposing the port is allowed once a token is configured."""
        ch = _make_channel(ws_host="0.0.0.0", access_token="s3cret-token")
        request = self._request(authorization="Bearer s3cret-token")

        with self._sentinel_prepare():
            with pytest.raises(_ReachedAccept):
                await ch._handle_ws_connection(request)

    @pytest.mark.parametrize(
        "authorization",
        [
            "Bearer s3cret-token",
            "Token s3cret-token",
            "bearer s3cret-token",
        ],
    )
    def test_accepted_authorization_schemes(self, authorization: str):
        """Bearer and Token are accepted, case-insensitively."""
        ch = _make_channel(access_token="s3cret-token")
        request = self._request(authorization=authorization)
        assert ch._token_authorized(request) is True

    @pytest.mark.parametrize(
        "authorization",
        [
            "Bearer wrong-token",
            "Basic s3cret-token",
            "s3cret-token",
            "Bearer",
            "",
        ],
    )
    def test_rejected_authorization_headers(self, authorization: str):
        ch = _make_channel(access_token="s3cret-token")
        request = self._request(authorization=authorization)
        assert ch._token_authorized(request) is False

    async def test_query_parameter_rejection_logs_migration_hint(
        self,
        caplog,
    ):
        """Query tokens are not accepted; the log explains the migration."""
        ch = _make_channel(ws_host="0.0.0.0", access_token="s3cret-token")
        request = self._request(path="/ws?access_token=s3cret-token")

        with caplog.at_level(logging.WARNING):
            resp = await ch._handle_ws_connection(request)

        assert resp.status == 401
        assert "Authorization header" in caplog.text

    def test_non_ascii_token_is_supported(self):
        """compare_digest requires bytes for non-ASCII tokens."""
        token = "密钥-abc"
        ch = _make_channel(access_token=token)
        request = self._request(authorization=f"Bearer {token}")
        assert ch._token_authorized(request) is True

    async def test_rejection_log_stays_on_one_line(self, caplog):
        """A forged newline must not become a second log record."""
        ch = _make_channel(ws_host="0.0.0.0", access_token="")
        request = self._request().clone(
            remote="1.2.3.4\nINFO onebot: client connected from 1.2.3.4",
        )

        with caplog.at_level(logging.ERROR):
            resp = await ch._handle_ws_connection(request)

        assert resp.status == 401
        assert len(caplog.records) == 1
        assert "\n" not in caplog.records[0].getMessage()


class TestDefaultBindAddress:
    """Tests for the loopback-by-default listen address."""

    def test_config_default_is_loopback(self):
        assert OneBotConfig().ws_host == "127.0.0.1"

    def test_channel_default_is_loopback(self):
        async def _noop_process(_request):
            yield  # pragma: no cover

        ch = OneBotChannel(process=_noop_process, enabled=True)

        assert ch._ws_host == "127.0.0.1"
        assert ch._auth_required is False

    @pytest.mark.parametrize("ws_host", ["", "   "])
    def test_blank_host_normalizes_to_loopback(self, ws_host: str):
        """A blank host must not fall through to every interface."""
        ch = _make_channel(ws_host=ws_host)

        assert ch._ws_host == "127.0.0.1"
        assert ch._auth_required is False

    def test_bracketed_ipv6_host_is_unwrapped(self):
        """Brackets are URL notation and make getaddrinfo fail."""
        ch = _make_channel(ws_host="[::1]")

        assert ch._ws_host == "::1"
        assert ch._auth_required is False

    def test_whitespace_token_counts_as_unset(self):
        """A whitespace token could never match a stripped request token."""
        ch = _make_channel(ws_host="0.0.0.0", access_token="   ")

        assert ch._access_token == ""
        assert ch._auth_required is True
