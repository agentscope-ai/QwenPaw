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
    _backend_for_protocol,
    _detect_backend_from_names,
)
from models.image import ark_provider, bfl_provider, gemini_provider
from models.image import ideogram_provider
from models.image.base import image_reference_limit
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


# ── capability table & backend detection ────────────────────────────────────


@pytest.mark.parametrize(
    ("model_name", "limit"),
    [
        ("gemini-3-pro-image", 14),
        ("gemini-3.1-flash-image", 14),
        ("gemini-2.5-flash-image", 3),
        ("doubao-seedream-5-0-pro-260628", 10),
        ("doubao-seedream-4-5-251128", 14),
        ("flux-2-pro", 8),
        ("flux-2-klein-4b", 8),
        ("ideogram-v3", 1),
        ("ideogram-v4", 0),
        ("gemini-42-image", None),  # unknown aliases stay unregistered
    ],
)
def test_reference_limits_follow_official_docs(model_name, limit) -> None:
    assert image_reference_limit(model_name) == limit


def test_backend_detection() -> None:
    assert _backend_for_protocol("google gemini") == "GEMINI"
    assert _backend_for_protocol("volcano engine（火山引擎）") == "ARK"
    assert _backend_for_protocol("black forest labs（flux）") == "BFL"
    assert _backend_for_protocol("ideogram") == "IDEOGRAM"
    assert _detect_backend_from_names("gemini-3-pro-image", "") == "GEMINI"
    assert _detect_backend_from_names("", "https://api.bfl.ai") == "BFL"


@pytest.mark.parametrize(
    ("cls", "name", "base", "count"),
    [
        (GeminiImageModel, "gemini-2.5-flash-image", "https://g", 4),
        (ArkImageModel, "doubao-seedream-5-0-pro-260628", "https://a", 11),
        (BFLImageModel, "flux-2-pro", "https://b", 9),
        (IdeogramImageModel, "ideogram-v4", "https://i", 1),
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
