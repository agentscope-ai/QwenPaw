# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name
"""Unit tests for the global settings router (/api/settings/language)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from qwenpaw.app.routers.settings import router

app = FastAPI()
app.include_router(router, prefix="/api")


@pytest.fixture(autouse=True)
def _use_tmp_settings(tmp_path: Path):
    """Redirect settings file to a temp directory for every test."""
    settings_file = tmp_path / "settings.json"
    with patch("qwenpaw.app.routers.settings._SETTINGS_FILE", settings_file):
        yield settings_file


@pytest.fixture
def api_client():
    """Create an async test client."""
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


# ── GET /settings/language ───────────────────────────────────────────


async def test_get_language_default(api_client):
    """Should return 'en' when no settings file exists."""
    async with api_client:
        resp = await api_client.get("/api/settings/language")
    assert resp.status_code == 200
    assert resp.json() == {"language": "en"}


async def test_get_language_persisted(api_client, _use_tmp_settings):
    """Should return the persisted language value."""
    _use_tmp_settings.write_text(json.dumps({"language": "ja"}), "utf-8")
    async with api_client:
        resp = await api_client.get("/api/settings/language")
    assert resp.status_code == 200
    assert resp.json() == {"language": "ja"}


# ── PUT /settings/language ───────────────────────────────────────────


@pytest.mark.parametrize("lang", ["en", "zh", "ja", "ru"])
async def test_put_language_valid(
    api_client,
    lang,
    _use_tmp_settings,
):
    """Should accept all valid languages and persist them."""
    async with api_client:
        resp = await api_client.put(
            "/api/settings/language",
            json={"language": lang},
        )
    assert resp.status_code == 200
    assert resp.json() == {"language": lang}

    data = json.loads(_use_tmp_settings.read_text("utf-8"))
    assert data["language"] == lang


async def test_put_language_invalid(api_client):
    """Should reject invalid language with 400."""
    async with api_client:
        resp = await api_client.put(
            "/api/settings/language",
            json={"language": "xx"},
        )
    assert resp.status_code == 400
    assert "Invalid language" in resp.json()["detail"]


async def test_put_language_empty(api_client):
    """Should reject empty language with 400."""
    async with api_client:
        resp = await api_client.put(
            "/api/settings/language",
            json={"language": ""},
        )
    assert resp.status_code == 400


async def test_put_language_missing_key(api_client):
    """Should reject body without 'language' key with 400."""
    async with api_client:
        resp = await api_client.put(
            "/api/settings/language",
            json={"lang": "zh"},
        )
    assert resp.status_code == 400


async def test_put_then_get_roundtrip(api_client):
    """PUT then GET should return the updated language."""
    async with api_client:
        await api_client.put(
            "/api/settings/language",
            json={"language": "ru"},
        )
        resp = await api_client.get("/api/settings/language")
    assert resp.json() == {"language": "ru"}


async def test_put_language_preserves_other_settings(
    api_client,
    _use_tmp_settings,
):
    """PUT should not overwrite other keys in settings.json."""
    _use_tmp_settings.write_text(
        json.dumps({"theme": "dark", "language": "en"}),
        "utf-8",
    )
    async with api_client:
        await api_client.put(
            "/api/settings/language",
            json={"language": "zh"},
        )

    data = json.loads(_use_tmp_settings.read_text("utf-8"))
    assert data["language"] == "zh"
    assert data["theme"] == "dark"
