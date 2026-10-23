"""Prepared G3 regressions; external HTTP only, no official-owner fiction."""

import json
import os
from pathlib import Path

import psutil
import pytest

from g3fd_dd_session_support import (
    g3_host_import_boundary,
    g3_qr,
    local_management_http,
    management_runtime,
)

ROOT = Path(__file__).resolve().parents[3]
__all__ = [
    "g3_host_import_boundary",
    "g3_qr",
    "local_management_http",
    "management_runtime",
]


@pytest.mark.parametrize("channel", ["feishu", "dingtalk"])
def test_official_descriptor_declares_explicit_qrcode_management(channel):
    descriptor = json.loads(
        (ROOT / "plugins/channel" / channel / "channel.json").read_text()
    )
    assert "channel.management.qrcode.v1" in descriptor["capabilities"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["success", "confirmed"])
async def test_terminal_credentials_survive_actual_session_and_are_cached(
    g3_qr, status
):
    qr = g3_qr
    scope = qr.scope()
    fetched = await qr.sessions.fetch(scope, {})
    credentials = {"api_token": "fixture-issued-token"}
    qr.http.response = {"status": status, "credentials": credentials}
    result = await qr.sessions.poll(scope, fetched.poll_token)
    assert len(qr.http.requests) == 2
    assert all(
        row["pid"] != os.getpid() and not psutil.pid_exists(row["pid"])
        for row in qr.http.requests
    )
    assert result.status == status
    assert result.credentials == credentials
    again = await qr.sessions.poll(scope, fetched.poll_token)
    assert again.status == status
    assert again.credentials == credentials
    assert len(qr.http.requests) == 2
    async with qr.sessions.authorize_save(
        scope, fetched.poll_token, credentials
    ):
        pass


@pytest.mark.asyncio
async def test_nullable_media_default_reaches_real_management_worker(g3_qr):
    qr = g3_qr
    scope = qr.scope(media_dir=None)
    assert scope.config["media_dir"] is None
    # Match the shipped model-default shape without claiming official owner.
    for channel in ("feishu", "dingtalk"):
        descriptor = json.loads(
            (ROOT / "plugins/channel" / channel / "channel.json").read_text()
        )
        field = descriptor["config_schema"]["properties"]["media_dir"]
        assert field["default"] is None
    result = await qr.sessions.fetch(scope, {})
    assert result.scan_url == "https://fixture.invalid/scan"
    assert len(qr.http.requests) == 1
    assert qr.http.requests[0]["pid"] != os.getpid()
    assert not psutil.pid_exists(qr.http.requests[0]["pid"])
    assert qr.http.requests[0]["config"].get("media_dir") is None
