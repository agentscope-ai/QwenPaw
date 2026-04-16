# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name
"""Unit tests for get_backend_debug_logs in the console router.

Verifies that the endpoint prefers WORKING_DIR/qwenpaw.log when the file
exists, and falls back to WORKING_DIR/copaw.log for legacy installations.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from qwenpaw.app.routers.console import router

app = FastAPI()
app.include_router(router, prefix="/api")


@pytest.fixture
def api_client():
    """Async test client for the console router."""
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


# ── helpers ──────────────────────────────────────────────────────────


def _patch_working_dir(tmp_path: Path):
    """Patch WORKING_DIR in the console router module to *tmp_path*."""
    return patch("qwenpaw.app.routers.console.WORKING_DIR", tmp_path)


# ── tests: qwenpaw.log present ───────────────────────────────────────


async def test_prefers_qwenpaw_log_when_present(
    api_client,
    tmp_path: Path,
):
    """When qwenpaw.log exists, the endpoint should read from it."""
    qwen_log = tmp_path / "qwenpaw.log"
    qwen_log.write_text("line from qwenpaw\n", encoding="utf-8")

    with _patch_working_dir(tmp_path):
        async with api_client:
            resp = await api_client.get(
                "/api/console/debug/backend-logs",
                params={"lines": 20},
            )

    assert resp.status_code == 200
    data = resp.json()
    assert data["exists"] is True
    assert "qwenpaw.log" in data["path"]
    assert "line from qwenpaw" in data["content"]


async def test_qwenpaw_log_returns_correct_metadata(
    api_client,
    tmp_path: Path,
):
    """Metadata fields (size, lines) are populated from qwenpaw.log."""
    qwen_log = tmp_path / "qwenpaw.log"
    content = "alpha\nbeta\ngamma\n"
    qwen_log.write_text(content, encoding="utf-8")

    with _patch_working_dir(tmp_path):
        async with api_client:
            resp = await api_client.get(
                "/api/console/debug/backend-logs",
                params={"lines": 20},
            )

    data = resp.json()
    assert data["size"] == qwen_log.stat().st_size
    assert data["lines"] == 20
    assert data["updated_at"] is not None


# ── tests: qwenpaw.log absent, copaw.log present ─────────────────────


async def test_falls_back_to_copaw_log(api_client, tmp_path: Path):
    """When qwenpaw.log is absent, the endpoint falls back to copaw.log."""
    copa_log = tmp_path / "copaw.log"
    copa_log.write_text("line from copaw\n", encoding="utf-8")

    with _patch_working_dir(tmp_path):
        async with api_client:
            resp = await api_client.get(
                "/api/console/debug/backend-logs",
                params={"lines": 20},
            )

    assert resp.status_code == 200
    data = resp.json()
    assert data["exists"] is True
    assert "copaw.log" in data["path"]
    assert "line from copaw" in data["content"]


async def test_copaw_log_metadata(api_client, tmp_path: Path):
    """Metadata is read from copaw.log when qwenpaw.log is absent."""
    copa_log = tmp_path / "copaw.log"
    copa_log.write_text("x\ny\nz\n", encoding="utf-8")

    with _patch_working_dir(tmp_path):
        async with api_client:
            resp = await api_client.get(
                "/api/console/debug/backend-logs",
                params={"lines": 20},
            )

    data = resp.json()
    assert data["size"] == copa_log.stat().st_size
    assert data["updated_at"] is not None


# ── tests: neither log present ────────────────────────────────────────


async def test_returns_not_found_when_no_log_exists(
    api_client,
    tmp_path: Path,
):
    """When neither log file exists, exists=False is returned."""
    with _patch_working_dir(tmp_path):
        async with api_client:
            resp = await api_client.get(
                "/api/console/debug/backend-logs",
                params={"lines": 20},
            )

    assert resp.status_code == 200
    data = resp.json()
    assert data["exists"] is False
    assert data["content"] == ""
    assert data["size"] == 0
    assert data["updated_at"] is None


async def test_not_found_path_is_copaw_fallback(api_client, tmp_path: Path):
    """When no log file exists, the reported path is the copaw.log fallback."""
    with _patch_working_dir(tmp_path):
        async with api_client:
            resp = await api_client.get(
                "/api/console/debug/backend-logs",
                params={"lines": 20},
            )

    data = resp.json()
    assert "copaw.log" in data["path"]


# ── tests: qwenpaw.log takes priority over copaw.log ─────────────────


async def test_qwenpaw_log_wins_when_both_exist(
    api_client,
    tmp_path: Path,
):
    """qwenpaw.log must win even when copaw.log also exists."""
    (tmp_path / "qwenpaw.log").write_text("from qwenpaw\n", encoding="utf-8")
    (tmp_path / "copaw.log").write_text("from copaw\n", encoding="utf-8")

    with _patch_working_dir(tmp_path):
        async with api_client:
            resp = await api_client.get(
                "/api/console/debug/backend-logs",
                params={"lines": 20},
            )

    data = resp.json()
    assert "qwenpaw.log" in data["path"]
    assert "from qwenpaw" in data["content"]
    assert "from copaw" not in data["content"]


# ── tests: query parameter validation ────────────────────────────────


async def test_lines_param_too_small_rejected(api_client, tmp_path: Path):
    """lines < 20 should return 422."""
    with _patch_working_dir(tmp_path):
        async with api_client:
            resp = await api_client.get(
                "/api/console/debug/backend-logs",
                params={"lines": 5},
            )
    assert resp.status_code == 422


async def test_lines_param_too_large_rejected(api_client, tmp_path: Path):
    """lines > MAX_DEBUG_LOG_LINES should return 422."""
    with _patch_working_dir(tmp_path):
        async with api_client:
            resp = await api_client.get(
                "/api/console/debug/backend-logs",
                params={"lines": 9999},
            )
    assert resp.status_code == 422
