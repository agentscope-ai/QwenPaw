# -*- coding: utf-8 -*-
"""Gemini VLM content conversion and remote media transport.

Gemini's ``file_data.file_uri`` only accepts Files API resources
(``https://generativelanguage.googleapis.com/v1beta/files/…``) or GCS
URIs — arbitrary public URLs are rejected with INVALID_ARGUMENT. Remote
media must therefore be downloaded and inlined before the request.
"""

# pylint: disable=protected-access,unused-argument

from __future__ import annotations

import asyncio
import base64
from contextlib import asynccontextmanager

import pytest

from models import vlm_model
from services.runtime_files.safe_remote_download import SafeRemoteDownloadError
from utils.exceptions import ModelError

pytestmark = pytest.mark.unit


def test_data_url_becomes_inline_data() -> None:
    parts = vlm_model._convert_to_gemini_content(
        [
            {
                "type": "image_url",
                "image_url": {
                    "url": "data:image/jpeg;base64,QUJD",
                },
            },
        ],
    )
    assert parts == [
        {"inline_data": {"mime_type": "image/jpeg", "data": "QUJD"}},
    ]


def test_gemini_files_api_uri_passes_through_as_file_data() -> None:
    file_uri = "https://generativelanguage.googleapis.com/v1beta/files/abc123"
    parts = vlm_model._convert_to_gemini_content(
        [
            {"type": "image_url", "image_url": {"url": file_uri}},
            {
                "type": "video_url",
                "video_url": {"url": "gs://bucket/clip.mp4"},
            },
        ],
    )
    assert parts[0]["file_data"]["file_uri"] == file_uri
    assert parts[1]["file_data"]["file_uri"] == "gs://bucket/clip.mp4"


def test_plain_remote_url_is_rejected_by_converter() -> None:
    with pytest.raises(ModelError):
        vlm_model._convert_to_gemini_content(
            [
                {
                    "type": "image_url",
                    "image_url": {"url": "https://cdn.example.com/ref.png"},
                },
            ],
        )


def test_gemini_caller_downloads_remote_media_and_inlines_it(
    monkeypatch,
) -> None:
    media_bytes = b"fake-image-bytes"
    captured: dict = {}

    class FakeResponse:
        def __init__(self, method: str):
            self._method = method
            self.status_code = 200
            self.headers = {}

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "candidates": [
                    {
                        "content": {"parts": [{"text": "red"}]},
                        "finishReason": "STOP",
                    },
                ],
            }

    class FakeAsyncClient:
        def __init__(self, *, timeout, follow_redirects=False):
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, _exc_type, _exc, _tb):
            return False

        async def post(self, url, *, headers, json):
            captured.update(post_url=url, headers=headers, body=json)
            return FakeResponse("POST")

    async def fake_download(url, fallback_mime, timeout):
        captured.update(
            get_url=url,
            download_fallback=fallback_mime,
            download_timeout=timeout,
        )
        return "image/png", base64.b64encode(media_bytes).decode("ascii")

    @asynccontextmanager
    async def fake_model_slot(_kind):
        yield

    monkeypatch.setattr(vlm_model.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(vlm_model, "model_slot", fake_model_slot)
    monkeypatch.setattr(vlm_model, "_download_remote_media", fake_download)
    monkeypatch.setattr(
        vlm_model.model_config,
        "get_vlm_max_inline_bytes",
        lambda: 20 * 1024 * 1024,
    )

    result = asyncio.run(
        vlm_model._call_gemini_vlm(
            [
                {"type": "text", "text": "描述图片"},
                {
                    "type": "image_url",
                    "image_url": {"url": "https://cdn.example.com/ref.png"},
                },
            ],
            system_prompt="",
            temperature=0.2,
            max_tokens=100,
            timeout=30.0,
            api_key="gm-test-key",
            base_url="https://generativelanguage.googleapis.com",
            model_name="gemini-2.5-pro",
        ),
    )

    assert result is not None
    assert captured["get_url"] == "https://cdn.example.com/ref.png"
    # Authenticated Gemini calls transport the key as a query parameter.
    assert captured["post_url"] == (
        "https://generativelanguage.googleapis.com"
        "/v1beta/models/gemini-2.5-pro:generateContent?key=gm-test-key"
    )
    parts = captured["body"]["contents"][0]["parts"]
    assert parts[0] == {"text": "描述图片"}
    inline = parts[1]["inline_data"]
    assert inline["mime_type"] == "image/png"
    assert base64.b64decode(inline["data"]) == media_bytes


def test_gemini_remote_downloader_rejects_loopback_before_connecting() -> None:
    with pytest.raises(SafeRemoteDownloadError, match="本机|私有|保留"):
        asyncio.run(
            vlm_model._download_remote_media(
                "http://127.0.0.1:65535/private",
                "image/png",
                1.0,
            ),
        )


def test_gemini_caller_omits_key_param_when_keyless(monkeypatch) -> None:
    captured: dict = {}

    class FakeResponse:
        status_code = 200
        content = b""
        headers: dict = {}

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}

    class FakeAsyncClient:
        def __init__(self, *, timeout, follow_redirects=False):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, _exc_type, _exc, _tb):
            return False

        async def post(self, url, *, headers, json):
            captured["post_url"] = url
            return FakeResponse()

    @asynccontextmanager
    async def fake_model_slot(_kind):
        yield

    monkeypatch.setattr(vlm_model.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(vlm_model, "model_slot", fake_model_slot)

    asyncio.run(
        vlm_model._call_gemini_vlm(
            [{"type": "text", "text": "ping"}],
            system_prompt="",
            temperature=0.2,
            max_tokens=100,
            timeout=30.0,
            api_key="",
            base_url="https://generativelanguage.googleapis.com",
            model_name="gemini-2.5-pro",
        ),
    )

    assert "key=" not in captured["post_url"]
