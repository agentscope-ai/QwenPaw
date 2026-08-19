# -*- coding: utf-8 -*-
"""Unit tests for provider OAuth router registration."""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.app.routers import router as api_router


def _callback_url(authorize_url: str) -> str:
    return parse_qs(urlsplit(authorize_url).query)["callback_url"][0]


def test_openrouter_oauth_start_is_registered() -> None:
    """POST /api/providers/openrouter/oauth/start must not 405."""
    app = FastAPI()
    app.include_router(api_router, prefix="/api")
    client = TestClient(app)

    response = client.post("/api/providers/openrouter/oauth/start")

    assert response.status_code == 200
    payload = response.json()
    assert payload["flow_type"] == "browser_redirect"
    assert payload["authorize_url"].startswith("https://openrouter.ai/auth")
    assert _callback_url(payload["authorize_url"]) == (
        "http://testserver/api/providers/openrouter/oauth/callback"
    )
    assert payload["state"]


def test_openrouter_uses_managed_callback_when_injected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QWENPAW_RUNTIME_INTERNAL_TOKEN", "runtime-token")
    app = FastAPI()
    app.include_router(api_router, prefix="/api")
    client = TestClient(app)

    response = client.post(
        "/api/providers/openrouter/oauth/start",
        headers={
            "X-QwenPaw-Hub-OAuth-Callback-Url": (
                "https://qwenpaw.example.com/api/hub/oauth/callback/relay"
            ),
        },
    )

    assert response.status_code == 200
    assert _callback_url(response.json()["authorize_url"]) == (
        "https://qwenpaw.example.com/api/hub/oauth/callback/relay"
    )


def test_openrouter_ignores_managed_callback_header_in_standalone() -> None:
    app = FastAPI()
    app.include_router(api_router, prefix="/api")
    client = TestClient(app)

    response = client.post(
        "/api/providers/openrouter/oauth/start",
        headers={
            "X-QwenPaw-Hub-OAuth-Callback-Url": (
                "https://attacker.example/callback"
            ),
        },
    )

    assert _callback_url(response.json()["authorize_url"]) == (
        "http://testserver/api/providers/openrouter/oauth/callback"
    )


def test_openrouter_rejects_public_http_managed_callback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QWENPAW_RUNTIME_INTERNAL_TOKEN", "runtime-token")
    app = FastAPI()
    app.include_router(api_router, prefix="/api")
    client = TestClient(app)

    response = client.post(
        "/api/providers/openrouter/oauth/start",
        headers={
            "X-QwenPaw-Hub-OAuth-Callback-Url": (
                "http://192.0.2.4/api/hub/oauth/callback/runtime/openrouter"
            ),
        },
    )

    assert response.status_code == 422
    assert "requires HTTPS" in response.json()["detail"]
