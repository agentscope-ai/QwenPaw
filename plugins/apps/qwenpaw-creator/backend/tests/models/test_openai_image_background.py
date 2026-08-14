# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=protected-access,unused-argument
"""OpenAI image background mode: Responses API submit, poll, decode.

Background mode is opt-in via ``background_model`` (the Responses-API host
model); empty keeps the classic synchronous Images API untouched, because
gpt-image-2 renders in ~40s and has no async mode on the classic endpoint.
Both transports share the configured base URL.
"""
from __future__ import annotations

import asyncio
import base64
import json

import httpx
import pytest

import models.image.openai_provider as openai_provider  # noqa: PLR0402  pylint: disable=consider-using-from-import
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


# ── the responses root derives from the same configured base URL ──────────


def test_responses_url_tolerates_v1_suffixed_and_versionless_bases() -> None:
    assert _model().responses_url == "https://api.openai.com/v1/responses"
    versionless = _model(
        base_url="https://routify.alibaba-inc.com/protocol/openai",
    )
    assert versionless.responses_url == (
        "https://routify.alibaba-inc.com/protocol/openai/v1/responses"
    )


def test_empty_background_model_keeps_the_sync_transport() -> None:
    sync_model = _model(background_model="")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/images/generations")
        return httpx.Response(200, json={"data": [{"b64_json": "x"}]})

    async def scenario() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
        ) as client:
            return await sync_model._request(client, "p", "16:9", [])

    assert asyncio.run(scenario()).status_code == 200


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


def test_background_submits_then_polls_to_completion(monkeypatch) -> None:
    monkeypatch.setattr(
        openai_provider,
        "RESPONSES_POLL_INTERVAL_SECONDS",
        0,
    )
    model = _model()
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            body = json.loads(request.content.decode("utf-8"))
            assert body["background"] is True
            assert body["model"] == "gpt-5.2"
            assert body["tools"][0]["type"] == "image_generation"
            assert body["tools"][0]["model"] == "gpt-image-2"
            seen.append("submit")
            return httpx.Response(
                200,
                json={"id": "resp_1", "status": "queued"},
            )
        seen.append("poll")
        if seen.count("poll") < 2:
            return httpx.Response(
                200,
                json={"id": "resp_1", "status": "in_progress"},
            )
        return httpx.Response(200, json=_completed_payload())

    async def scenario() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
        ) as client:
            return await model._request(client, "p", "16:9", [])

    response = asyncio.run(scenario())
    assert response.json()["status"] == "completed"
    assert seen == ["submit", "poll", "poll"]


def test_background_failure_raises_with_the_provider_detail(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        openai_provider,
        "RESPONSES_POLL_INTERVAL_SECONDS",
        0,
    )
    model = _model()

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

    async def scenario() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
        ) as client:
            return await model._request(client, "p", "16:9", [])

    with pytest.raises(ModelError) as caught:
        asyncio.run(scenario())
    assert "moderation_blocked" in str(caught.value)
    assert "timed out" not in str(caught.value).lower()


def test_background_deadline_reads_as_a_transient_timeout(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        openai_provider,
        "RESPONSES_POLL_INTERVAL_SECONDS",
        0,
    )
    model = _model(timeout=0)

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

    async def scenario() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
        ) as client:
            return await model._request(client, "p", "16:9", [])

    with pytest.raises(ModelError) as caught:
        asyncio.run(scenario())
    # The scheduler's transient classifier keys on this wording.
    assert "timed out" in str(caught.value)


def test_background_poll_survives_transient_errors(monkeypatch) -> None:
    monkeypatch.setattr(
        openai_provider,
        "RESPONSES_POLL_INTERVAL_SECONDS",
        0,
    )
    model = _model()
    steps = iter(["boom", "503", "done"])

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                200,
                json={"id": "resp_1", "status": "queued"},
            )
        step = next(steps)
        if step == "boom":
            raise httpx.ReadTimeout("poll hiccup", request=request)
        if step == "503":
            return httpx.Response(503, json={})
        return httpx.Response(200, json=_completed_payload())

    async def scenario() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
        ) as client:
            return await model._request(client, "p", "16:9", [])

    assert asyncio.run(scenario()).json()["status"] == "completed"


# ── decode handles both payload shapes ─────────────────────────────────────


def test_decode_reads_the_responses_payload(monkeypatch, tmp_path) -> None:
    model = _model()
    saved: dict = {}

    def fake_persist(img_bytes: bytes, model_name: str, source: str) -> str:
        saved["bytes"] = img_bytes
        return "/generated/bg.png"

    monkeypatch.setattr(openai_provider, "persist_image_bytes", fake_persist)
    url = asyncio.run(model._decode(_completed_payload()))
    assert url == "/generated/bg.png"
    assert saved["bytes"] == _PNG_BYTES


def test_decode_still_reads_the_classic_images_payload(monkeypatch) -> None:
    model = _model()

    def fake_persist(img_bytes: bytes, model_name: str, source: str) -> str:
        return "/generated/classic.png"

    monkeypatch.setattr(openai_provider, "persist_image_bytes", fake_persist)
    classic = {
        "data": [
            {"b64_json": base64.b64encode(_PNG_BYTES).decode("ascii")},
        ],
    }
    assert asyncio.run(model._decode(classic)) == "/generated/classic.png"


def test_decode_persists_off_the_event_loop_with_task_scope(
    monkeypatch,
    tmp_path,
) -> None:
    """The durable image write never runs on the event loop.

    The review's case: base64 decode plus the fsync-heavy persist stalled
    every other coroutine while a large image landed on a slow disk. The
    write must run in a worker thread, and contextvars must carry the Task
    scope there so the file still lands in the right scratch directory.
    """

    import threading

    # pylint: disable=no-name-in-module
    from utils.paths import media_task_scope, task_work_root

    # pylint: enable=no-name-in-module

    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path))
    (tmp_path / "project-bg" / "runtime").mkdir(parents=True)
    (tmp_path / "project-bg" / "project.json").write_text(
        "{}",
        encoding="utf-8",
    )
    model = _model()
    seen: dict = {}

    def fake_persist(img_bytes: bytes, model_name: str, source: str) -> str:
        seen["thread"] = threading.get_ident()
        seen["work_root"] = str(task_work_root())
        seen["bytes"] = img_bytes
        return "/generated/bg.png"

    monkeypatch.setattr(openai_provider, "persist_image_bytes", fake_persist)

    async def scenario() -> tuple[int, str]:
        with media_task_scope("task-bg-1", project_id="project-bg"):
            url = await model._decode(_completed_payload())
        return threading.get_ident(), url

    loop_thread, url = asyncio.run(scenario())

    assert url == "/generated/bg.png"
    assert seen["bytes"] == _PNG_BYTES
    # Off the loop, but still inside the Task's scratch scope.
    assert seen["thread"] != loop_thread
    assert "task-bg-1" in seen["work_root"]
