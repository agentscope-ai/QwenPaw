# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=protected-access,unused-argument
"""OpenAI image background mode: Responses API submit, poll, decode.

Background mode is opt-in via ``background_model``; empty keeps the classic
synchronous Images API untouched. Both transports share the base URL.
"""
from __future__ import annotations

import asyncio
import base64
import json

import httpx
import pytest

import models.image.openai_provider as openai_provider  # noqa: PLR0402  pylint: disable=consider-using-from-import
from models.image.openai_provider import build_reference_image_files
from models.image.openai_provider import OpenAIImageModel
from utils.exceptions import ModelError


pytestmark = pytest.mark.unit

_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"x" * 20000


def _model(
    background_model: str = "gpt-5.2",
    base_url: str = "https://api.openai.com/v1",
    timeout: int = 240,
) -> OpenAIImageModel:
    return OpenAIImageModel(
        model_name="gpt-image-2",
        api_key="test-key",
        base_url=base_url,
        quality="low",
        timeout=timeout,
        background_model=background_model,
    )


def _request(model: OpenAIImageModel, handler) -> httpx.Response:
    async def scenario() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
        ) as client:
            return await model._request(client, "p", "16:9", [])

    return asyncio.run(scenario())


# ── background submit + poll ───────────────────────────────────────────────


def _completed_payload() -> dict:
    return {
        "id": "resp_1",
        "status": "completed",
        "output": [
            {
                "type": "image_generation_call",
                "result": base64.b64encode(_PNG_BYTES).decode("ascii"),
            },
        ],
    }


def test_background_submits_then_rides_out_transient_polls(
    monkeypatch,
) -> None:
    monkeypatch.setattr(openai_provider, "RESPONSES_POLL_INTERVAL_SECONDS", 0)
    submits: list[str] = []
    steps = iter(["in_progress", "boom", "503", "completed"])

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            body = json.loads(request.content.decode("utf-8"))
            assert body["background"] is True
            assert body["model"] == "gpt-5.2"
            assert body["tools"][0]["type"] == "image_generation"
            assert body["tools"][0]["model"] == "gpt-image-2"
            submits.append("submit")
            return httpx.Response(
                200,
                json={"id": "resp_1", "status": "queued"},
            )
        step = next(steps)
        if step == "boom":
            raise httpx.ReadTimeout("poll hiccup", request=request)
        if step == "503":
            return httpx.Response(503, json={})
        if step == "completed":
            return httpx.Response(200, json=_completed_payload())
        return httpx.Response(200, json={"id": "resp_1", "status": step})

    response = _request(_model(), handler)
    assert response.json()["status"] == "completed"
    assert submits == ["submit"]  # transient poll errors never resubmit


def test_background_failure_raises_with_the_provider_detail(
    monkeypatch,
) -> None:
    monkeypatch.setattr(openai_provider, "RESPONSES_POLL_INTERVAL_SECONDS", 0)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                200,
                json={"id": "resp_1", "status": "queued"},
            )
        return httpx.Response(
            200,
            json={
                "id": "resp_1",
                "status": "failed",
                "error": {"message": "moderation_blocked"},
            },
        )

    with pytest.raises(ModelError) as caught:
        _request(_model(), handler)
    assert "moderation_blocked" in str(caught.value)
    # Deterministic wording: must NOT look transient to the scheduler.
    assert "timed out" not in str(caught.value).lower()


def test_background_deadline_reads_as_a_transient_timeout(monkeypatch) -> None:
    monkeypatch.setattr(openai_provider, "RESPONSES_POLL_INTERVAL_SECONDS", 0)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                200,
                json={"id": "resp_1", "status": "queued"},
            )
        return httpx.Response(
            200,
            json={"id": "resp_1", "status": "in_progress"},
        )

    with pytest.raises(ModelError) as caught:
        _request(_model(timeout=0), handler)
    # The scheduler's transient classifier keys on this wording.
    assert "timed out" in str(caught.value)


# ── decode handles both payload shapes ─────────────────────────────────────


def test_decode_unwraps_background_and_classic_payloads(monkeypatch) -> None:
    model = _model()
    saved: dict = {}

    def fake_persist(img_bytes: bytes, model_name: str, source: str) -> str:
        saved["bytes"] = img_bytes
        return "/generated/bg.png"

    monkeypatch.setattr(openai_provider, "persist_image_bytes", fake_persist)
    assert asyncio.run(model._decode(_completed_payload())) == {
        "url": "/generated/bg.png",
        "source_url": "",
    }
    assert saved["bytes"] == _PNG_BYTES
    classic = {
        "data": [{"b64_json": base64.b64encode(_PNG_BYTES).decode("ascii")}],
    }
    assert asyncio.run(model._decode(classic)) == {
        "url": "/generated/bg.png",
        "source_url": "",
    }


# ---------------------------------------------------------------------------
# URL construction and reference upload fields (classic Images API)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("endpoint", "prefix"),
    [
        # Both endpoint styles must resolve to a single /v1/images/...
        # path — never /v1/v1/images/....
        ("https://api.openai.com/v1", "https://api.openai.com/v1"),
        (
            "https://routify.alibaba-inc.com/protocol/openai",
            "https://routify.alibaba-inc.com/protocol/openai/v1",
        ),
    ],
)
def test_image_urls_gain_exactly_one_v1_segment(
    endpoint: str,
    prefix: str,
) -> None:
    model = _model(base_url=endpoint)
    assert model.generation_url == f"{prefix}/images/generations"
    assert model._url(["ref.png"]) == f"{prefix}/images/edits"


def test_reference_files_use_the_array_field_for_multiple_images(
    tmp_path,
) -> None:
    """Two or more references upload as image[]; a single one stays image.

    The gateway rejects a repeated bare ``image`` field with 400
    "Duplicate parameter: 'image'" (storyboard incident regression).
    """

    first = tmp_path / "ref-a.png"
    second = tmp_path / "ref-b.png"
    first.write_bytes(b"\x89PNG\r\n\x1a\na")
    second.write_bytes(b"\x89PNG\r\n\x1a\nb")

    multiple = asyncio.run(
        build_reference_image_files(
            [first.as_uri(), second.as_uri(), first.as_uri(), " "],
        ),
    )
    assert [name for name, _ in multiple] == ["image[]", "image[]"]

    single = asyncio.run(build_reference_image_files([first.as_uri()]))
    assert [name for name, _ in single] == ["image"]
