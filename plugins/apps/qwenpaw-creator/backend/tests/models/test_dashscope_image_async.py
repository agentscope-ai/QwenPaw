# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=protected-access,unused-argument
"""DashScope image async-task transport: submit, poll, decode.

The provider submits with ``X-DashScope-Async: enable`` and polls the task
endpoint, so no HTTP call ever spans a render. A sync answer (proxy that
ignores the header) must pass through untouched, and poll hiccups must not
kill a render that is still running server-side.
"""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest

import models.image.dashscope_provider as dashscope_provider  # noqa: PLR0402  pylint: disable=consider-using-from-import
from models.image.dashscope_provider import DashScopeImageModel
from utils.exceptions import ModelError


pytestmark = pytest.mark.unit


def _model(
    base_url: str = dashscope_provider.DEFAULT_BASE_URL,
    timeout: int = 240,
) -> DashScopeImageModel:
    return DashScopeImageModel(
        model_name="qwen-image-3.0-pro",
        api_key="test-key",
        base_url=base_url,
        timeout=timeout,
    )


def _response(status_code: int, payload: dict) -> httpx.Response:
    return httpx.Response(
        status_code,
        request=httpx.Request(
            "POST",
            "https://dashscope.aliyuncs.com/api/v1/x",
        ),
        content=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )


# ── the poll root derives from whatever host the user configured ─────────


def test_task_root_derives_from_the_default_generation_endpoint() -> None:
    assert _model().api_root == "https://dashscope.aliyuncs.com/api/v1"


def test_task_root_follows_intl_and_proxy_hosts() -> None:
    intl = _model("https://dashscope-intl.aliyuncs.com/api/v1")
    assert intl.api_root == "https://dashscope-intl.aliyuncs.com/api/v1"


# ── submit acknowledgement parsing ─────────────────────────────────────────


def test_async_submit_yields_the_task_id() -> None:
    ack = _response(
        200,
        {"output": {"task_id": "t-1", "task_status": "PENDING"}},
    )
    assert DashScopeImageModel._submitted_task_id(ack) == "t-1"


def test_sync_answer_and_errors_pass_through_without_polling() -> None:
    sync = _response(200, {"output": {"choices": [{"message": {}}]}})
    assert DashScopeImageModel._submitted_task_id(sync) is None
    rate_limited = _response(429, {})
    assert DashScopeImageModel._submitted_task_id(rate_limited) is None


# ── async-rejected accounts fall back to the sync transport ───────────────


def test_async_rejection_falls_back_to_sync_and_caches(monkeypatch) -> None:
    """403 'does not support asynchronous calls' → sync resubmit, cached.

    Observed live on 2026-08-06: the account-level API rejected the async
    header outright, so the transport must retry without it and remember
    the discovery instead of probing on every image.
    """
    monkeypatch.setattr(DashScopeImageModel, "_async_unsupported", False)
    model = _model()
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(dict(request.headers))
        if request.headers.get("x-dashscope-async") == "enable":
            return httpx.Response(
                403,
                text="current user api does not support asynchronous calls",
            )
        return httpx.Response(
            200,
            json={"output": {"choices": [{"message": {}}]}},
        )

    async def scenario() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
        ) as client:
            return await model._request(client, "p", "16:9", [])

    first = asyncio.run(scenario())
    assert first.status_code == 200
    assert len(calls) == 2  # async probe + sync resubmit
    assert DashScopeImageModel._async_unsupported is True

    second = asyncio.run(scenario())
    assert second.status_code == 200
    assert len(calls) == 3  # cached: straight to sync, no probe


def test_unrelated_403_is_not_mistaken_for_async_rejection() -> None:
    denied = _response(403, {"message": "invalid api key"})
    assert DashScopeImageModel._async_rejected(denied) is False


# ── poll loop ──────────────────────────────────────────────────────────────


def _succeeded_payload() -> dict:
    return {
        "output": {
            "task_id": "t-1",
            "task_status": "SUCCEEDED",
            "results": {
                "choices": [
                    {
                        "message": {
                            "content": [{"image": "https://oss/img.png"}],
                        },
                    },
                ],
            },
        },
    }


def _poll(
    model: DashScopeImageModel,
    transport: httpx.MockTransport,
) -> httpx.Response:
    async def scenario() -> httpx.Response:
        async with httpx.AsyncClient(transport=transport) as client:
            return await model._poll_task(client, "t-1")

    return asyncio.run(scenario())


def test_poll_waits_through_pending_then_returns_the_result(
    monkeypatch,
) -> None:
    monkeypatch.setattr(dashscope_provider, "POLL_INTERVAL_SECONDS", 0)
    states = iter(["PENDING", "RUNNING", "SUCCEEDED"])

    def handler(
        request: httpx.Request,
    ) -> httpx.Response:  # pylint: disable=unused-argument
        state = next(states)
        if state == "SUCCEEDED":
            return httpx.Response(200, json=_succeeded_payload())
        return httpx.Response(
            200,
            json={"output": {"task_id": "t-1", "task_status": state}},
        )

    response = _poll(_model(), httpx.MockTransport(handler))
    payload = response.json()
    assert payload["output"]["task_status"] == "SUCCEEDED"


def test_poll_survives_transient_5xx_and_transport_errors(monkeypatch) -> None:
    monkeypatch.setattr(dashscope_provider, "POLL_INTERVAL_SECONDS", 0)
    attempts = iter(["boom", "503", "SUCCEEDED"])

    def handler(request: httpx.Request) -> httpx.Response:
        step = next(attempts)
        if step == "boom":
            raise httpx.ReadTimeout("poll hiccup", request=request)
        if step == "503":
            return httpx.Response(503, json={})
        return httpx.Response(200, json=_succeeded_payload())

    response = _poll(_model(), httpx.MockTransport(handler))
    assert response.json()["output"]["task_status"] == "SUCCEEDED"


def test_failed_task_raises_a_deterministic_model_error() -> None:
    def handler(
        request: httpx.Request,
    ) -> httpx.Response:  # pylint: disable=unused-argument
        return httpx.Response(
            200,
            json={
                "output": {
                    "task_id": "t-1",
                    "task_status": "FAILED",
                    "code": "DataInspectionFailed",
                    "message": "safety rejection",
                },
            },
        )

    with pytest.raises(ModelError) as caught:
        _poll(_model(), httpx.MockTransport(handler))
    assert "FAILED" in str(caught.value)
    assert "safety rejection" in str(caught.value)
    # Deterministic wording: must NOT look transient to the scheduler.
    assert "timed out" not in str(caught.value).lower()


def test_deadline_exhaustion_reads_as_a_transient_timeout(monkeypatch) -> None:
    monkeypatch.setattr(dashscope_provider, "POLL_INTERVAL_SECONDS", 0)

    def handler(
        request: httpx.Request,
    ) -> httpx.Response:  # pylint: disable=unused-argument
        return httpx.Response(
            200,
            json={"output": {"task_id": "t-1", "task_status": "RUNNING"}},
        )

    with pytest.raises(ModelError) as caught:
        _poll(_model(timeout=0), httpx.MockTransport(handler))
    # The scheduler's transient classifier keys on this wording.
    assert "timed out" in str(caught.value)


# ── decode handles the nested async-result payload ─────────────────────────


def test_decode_unwraps_async_task_results(monkeypatch) -> None:
    model = _model()

    async def fake_download(
        url: str,
        model_name: str,
    ) -> str:  # pylint: disable=unused-argument
        return f"/generated/{url.rsplit('/', 1)[-1]}"

    monkeypatch.setattr(
        dashscope_provider,
        "download_remote_image",
        fake_download,
    )
    url = asyncio.run(model._decode(_succeeded_payload()))
    assert url == "/generated/img.png"


def test_decode_still_reads_the_synchronous_payload(monkeypatch) -> None:
    model = _model()

    async def fake_download(
        url: str,
        model_name: str,
    ) -> str:  # pylint: disable=unused-argument
        return "/generated/sync.png"

    monkeypatch.setattr(
        dashscope_provider,
        "download_remote_image",
        fake_download,
    )
    payload = {
        "output": {
            "choices": [
                {
                    "message": {
                        "content": [{"image": "https://oss/sync.png"}],
                    },
                },
            ],
        },
    }
    assert asyncio.run(model._decode(payload)) == "/generated/sync.png"
