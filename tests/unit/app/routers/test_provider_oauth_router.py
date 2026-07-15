# -*- coding: utf-8 -*-
"""Unit tests for provider OAuth router registration."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.app.routers import router as api_router


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
    assert payload["state"]
