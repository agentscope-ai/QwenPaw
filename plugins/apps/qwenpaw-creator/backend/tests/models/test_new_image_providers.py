# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=protected-access
"""New image providers (Gemini / Ark Seedream / BFL FLUX / Ideogram).

Request bodies are captured through fake httpx clients; every asserted
parameter mirrors the official API references quoted in the providers.
"""

from __future__ import annotations

import asyncio
import base64

import pytest

from models.image import (
    ArkImageModel,
    BFLImageModel,
    GeminiImageModel,
    IdeogramImageModel,
    MiniMaxImageModel,
    _detect_backend_from_names,
    image_backend_for_protocol,
)
from models.image import ark_provider, bfl_provider, gemini_provider
from models.image import ideogram_provider
from models.image import minimax_provider
from utils.exceptions import ModelError

pytestmark = pytest.mark.unit

_PNG = b"\x89PNG fake image bytes"


class _StubResponse:
    status_code = 200

    def __init__(self, payload: dict):
        self._payload = payload

    def json(self) -> dict:
        return self._payload


class _CapturingClient:
    def __init__(self, captured: dict, payload: dict | None = None):
        self._captured = captured
        self._payload = payload or {}

    async def post(self, url, headers=None, json=None, data=None, files=None):
        self._captured.update(
            {
                "url": url,
                "headers": headers,
                "json": json,
                "data": data,
                "files": files,
            },
        )
        return _StubResponse(self._payload)


def _stub_reference_reading(monkeypatch, module) -> None:
    async def fake_read(_url, **_kwargs):
        return _PNG, "ref.png"

    monkeypatch.setattr(module, "read_reference_media", fake_read)
    monkeypatch.setattr(
        module,
        "validate_reference_image_bytes",
        lambda content: None,
    )


def _model(cls, name, base_url):
    return cls(model_name=name, api_key="k", base_url=base_url, timeout=30)


# ── backend detection ────────────────────────────────────


def test_backend_detection() -> None:
    assert image_backend_for_protocol("google gemini") == "GEMINI"
    assert image_backend_for_protocol("volcano engine（火山引擎）") == "ARK"
    assert image_backend_for_protocol("black forest labs（flux）") == "BFL"
    assert image_backend_for_protocol("ideogram") == "IDEOGRAM"
    # Labels reach the matcher exactly as the UI stores them; it casefolds
    # internally, so the request-scoped writer and the persisted-config
    # fallback can both pass one through untouched.
    assert image_backend_for_protocol("MiniMax（国内站）") == "MINIMAX"
    assert image_backend_for_protocol("MiniMax（国际站）") == "MINIMAX"
    assert _detect_backend_from_names("image-01", "") == "MINIMAX"
    assert (
        _detect_backend_from_names("", "https://api.minimax.io") == "MINIMAX"
    )
    assert (
        _detect_backend_from_names("", "https://api.minimax.cn") == "MINIMAX"
    )
    assert _detect_backend_from_names("gemini-3-pro-image", "") == "GEMINI"
    assert _detect_backend_from_names("", "https://api.bfl.ai") == "BFL"


@pytest.mark.parametrize(
    ("cls", "name", "base", "count"),
    [
        (GeminiImageModel, "gemini-2.5-flash-image", "https://g", 4),
        (ArkImageModel, "doubao-seedream-5-0-pro-260628", "https://a", 11),
        (BFLImageModel, "flux-2-pro", "https://b", 9),
        (IdeogramImageModel, "ideogram-v4", "https://i", 1),
        (MiniMaxImageModel, "image-01", "https://m", 2),
    ],
)
def test_over_budget_references_are_rejected(cls, name, base, count) -> None:
    with pytest.raises(ModelError, match="reference images"):
        _model(cls, name, base)._enforce_reference_budget(count)


# ── request shapes ───────────────────────────────────────────────────────────


def test_gemini_request_shape(monkeypatch) -> None:
    _stub_reference_reading(monkeypatch, gemini_provider)
    captured: dict = {}
    model = _model(
        GeminiImageModel,
        "gemini-3-pro-image",
        "https://generativelanguage.googleapis.com/v1beta",
    )
    asyncio.run(
        model._request(
            _CapturingClient(captured),
            "a cat",
            "16:9",
            ["/generated/ref.png"],
        ),
    )
    assert captured["url"] == (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        "gemini-3-pro-image:generateContent"
    )
    assert captured["headers"]["x-goog-api-key"] == "k"
    parts = captured["json"]["contents"][0]["parts"]
    assert parts[0]["inlineData"]["mimeType"] == "image/png"
    assert parts[-1] == {"text": "a cat"}
    config = captured["json"]["generationConfig"]
    assert config["responseModalities"] == ["TEXT", "IMAGE"]
    assert config["imageConfig"] == {"aspectRatio": "16:9", "imageSize": "2K"}

    # gemini-2.5-flash-image has a fixed 1024px output: no imageSize.
    model = _model(GeminiImageModel, "gemini-2.5-flash-image", "https://g")
    asyncio.run(model._request(_CapturingClient(captured), "a cat", "1:1", []))
    assert captured["json"]["generationConfig"]["imageConfig"] == {
        "aspectRatio": "1:1",
    }


def test_ark_request_shape(monkeypatch) -> None:
    _stub_reference_reading(monkeypatch, ark_provider)
    captured: dict = {}
    model = _model(
        ArkImageModel,
        "doubao-seedream-5-0-pro-260628",
        "https://ark.cn-beijing.volces.com",
    )
    asyncio.run(
        model._request(
            _CapturingClient(captured),
            "海报",
            "16:9",
            ["/generated/a.png", "https://cdn.example/b.png"],
        ),
    )
    assert captured["url"] == (
        "https://ark.cn-beijing.volces.com/api/v3/images/generations"
    )
    body = captured["json"]
    # Official 2K tier pixel example for 16:9; watermark off; url result.
    assert body["size"] == "2848x1600"
    assert body["response_format"] == "url"
    assert body["watermark"] is False
    assert "sequential_image_generation" not in body
    assert body["image"][0].startswith("data:image/png;base64,")
    assert body["image"][1] == "https://cdn.example/b.png"


def test_bfl_submit_and_poll(monkeypatch) -> None:
    _stub_reference_reading(monkeypatch, bfl_provider)
    captured: dict = {}

    class _BFLClient(_CapturingClient):
        async def post(self, url, headers=None, json=None):
            await super().post(url, headers=headers, json=json)
            return _StubResponse(
                {"id": "req-1", "polling_url": "https://api.bfl.ai/poll"},
            )

        async def get(self, _url, headers=None, **_kwargs):
            self._captured["poll_headers"] = headers
            return _StubResponse(
                {
                    "status": "Ready",
                    "result": {"sample": "https://delivery.bfl.ai/s.png"},
                },
            )

    model = _model(BFLImageModel, "flux-2-pro", "https://api.bfl.ai")
    response = asyncio.run(
        model._request(
            _BFLClient(captured),
            "an owl",
            "16:9",
            ["/generated/a.png", "https://cdn.example/b.png"],
        ),
    )
    assert captured["url"] == "https://api.bfl.ai/v1/flux-2-pro"
    assert captured["headers"]["x-key"] == "k"
    body = captured["json"]
    assert (body["width"], body["height"]) == (2048, 1152)
    # First reference is bare base64; the public URL passes through.
    assert body["input_image"] == base64.b64encode(_PNG).decode()
    assert body["input_image_2"] == "https://cdn.example/b.png"
    assert captured["poll_headers"]["x-key"] == "k"
    assert response.json()["status"] == "Ready"


def test_ideogram_request_shapes(monkeypatch) -> None:
    _stub_reference_reading(monkeypatch, ideogram_provider)
    captured: dict = {}
    model = _model(
        IdeogramImageModel,
        "ideogram-v3",
        "https://api.ideogram.ai",
    )
    asyncio.run(
        model._request(
            _CapturingClient(captured),
            "poster",
            "16:9",
            ["/generated/a.png"],
        ),
    )
    assert captured["url"] == "https://api.ideogram.ai/v1/ideogram-v3/generate"
    assert captured["headers"] == {"Api-Key": "k"}
    assert captured["data"] == {
        "prompt": "poster",
        "aspect_ratio": "16x9",
        "rendering_speed": "DEFAULT",
    }
    field, (_name, content, mime) = captured["files"][0]
    assert field == "character_reference_images"
    assert (content, mime) == (_PNG, "image/png")

    # ideogram-v4 documents neither aspect_ratio nor references.
    model = _model(
        IdeogramImageModel,
        "ideogram-v4",
        "https://api.ideogram.ai",
    )
    asyncio.run(
        model._request(_CapturingClient(captured), "poster", "16:9", []),
    )
    assert captured["data"] == {
        "text_prompt": "poster",
        "rendering_speed": "DEFAULT",
    }
    assert captured["files"] is None


def test_minimax_request_shape(monkeypatch) -> None:
    _stub_reference_reading(monkeypatch, minimax_provider)
    captured: dict = {}
    model = _model(MiniMaxImageModel, "image-01", "https://api.minimax.io")
    asyncio.run(
        model._request(
            _CapturingClient(captured),
            "a cat",
            "16:9",
            ["/generated/ref.png"],
        ),
    )
    assert captured["url"] == "https://api.minimax.io/v1/image_generation"
    assert captured["headers"]["Authorization"] == "Bearer k"
    body = captured["json"]
    assert body["model"] == "image-01"
    assert body["aspect_ratio"] == "16:9"
    assert body["response_format"] == "url"
    assert body["n"] == 1
    # A local reference has to reach the endpoint as a data URL: MiniMax
    # reads neither a URL nor a media type out of bare base64 and answers a
    # parameter error before generating anything.
    encoded = base64.b64encode(_PNG).decode()
    assert body["subject_reference"] == [
        {
            "type": "character",
            "image_file": f"data:image/png;base64,{encoded}",
        },
    ]


def test_minimax_keeps_a_public_reference_as_url(monkeypatch) -> None:
    # The documented form is a network URL; inlining a file MiniMax can fetch
    # itself would only inflate the request body.
    _stub_reference_reading(monkeypatch, minimax_provider)
    captured: dict = {}
    model = _model(MiniMaxImageModel, "image-01", "https://api.minimax.io")
    asyncio.run(
        model._request(
            _CapturingClient(captured),
            "a cat",
            "1:1",
            ["https://cdn.example.com/ref.jpg"],
        ),
    )
    assert captured["json"]["subject_reference"] == [
        {
            "type": "character",
            "image_file": "https://cdn.example.com/ref.jpg",
        },
    ]


def test_minimax_decode_url_base64_and_base_resp(monkeypatch) -> None:
    model = _model(MiniMaxImageModel, "image-01", "https://api.minimax.io")
    downloaded: list = []

    async def fake_download(url, _name):
        downloaded.append(url)
        return "/generated/img.png"

    monkeypatch.setattr(
        minimax_provider,
        "download_remote_image",
        fake_download,
    )
    result = asyncio.run(
        model._decode({"data": {"image_urls": ["https://cdn/x.png"]}}),
    )
    assert result == {"url": "/generated/img.png", "source_url": ""}
    assert downloaded == ["https://cdn/x.png"]

    # base64 payload path is persisted without a network fetch.
    png = base64.b64encode(_PNG).decode()
    persisted: list = []
    monkeypatch.setattr(
        minimax_provider,
        "persist_image_bytes",
        lambda content, _name, _src: persisted.append(content)
        or "/generated/img.png",
    )
    assert asyncio.run(model._decode({"data": {"image_base64": [png]}})) == {
        "url": "/generated/img.png",
        "source_url": "",
    }

    # HTTP 200 carrying a non-zero base_resp is still a failure.
    with pytest.raises(ModelError, match="1026"):
        asyncio.run(
            model._decode(
                {
                    "data": {},
                    "base_resp": {"status_code": 1026, "status_msg": "nsfw"},
                },
            ),
        )
