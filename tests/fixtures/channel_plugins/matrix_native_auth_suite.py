"""Real nio HTTP auth, catch-up, state ownership and stop witnesses."""
import asyncio
import json
from pathlib import Path

import pytest
from nio import AsyncClient

from matrix_native_support import (
    BOT, ROOM, hs, platform_factory, sync_payload, text_event, until,
)


@pytest.mark.asyncio
async def test_password_precedes_token_and_server_identity_is_persisted(hs, platform_factory):
    platform = platform_factory(password="explicit-password", device_name="  named-device  ")
    await platform.start()
    assert isinstance(platform._client, AsyncClient)
    assert len(hs.calls("/login")) == 1 and not hs.calls("/whoami")
    request = hs.calls("/login")[0]["body"]
    assert request["password"] == "explicit-password"
    assert request["identifier"]["user"] == BOT
    assert request["device_id"] == "named-device"
    assert request["initial_device_display_name"] == "  named-device  "
    assert platform._client.access_token == "password-result-token"
    assert platform.device_id == "SERVER-DEVICE"
    assert platform.observed_states == ["connected"]
    assert json.loads((platform._state.directory / "auth.json").read_text()) == {
        "access_token": "password-result-token", "user_id": BOT, "device_id": "SERVER-DEVICE"}


@pytest.mark.asyncio
async def test_token_whoami_and_catchup_suppress_only_old_events_then_resume(hs, platform_factory):
    hs.sync.put_nowait((sync_payload("batch-old", [text_event("old", "$old")], invite=True), 200))
    platform = platform_factory()
    await platform.start()
    await until(lambda: len(hs.calls("/sync")) == 2)
    assert len(hs.calls("/whoami")) == 1 and not hs.calls("/login")
    assert platform.observed_events == []
    assert platform._client.event_callbacks
    assert hs.calls("/sync")[0]["query"]["full_state"] == "true"
    assert "since" not in hs.calls("/sync")[0]["query"]
    assert hs.calls("/sync")[1]["query"]["since"] == "batch-old"
    assert any("/join/" in r["path"] for r in hs.requests)
    hs.sync.put_nowait((sync_payload("batch-new", [text_event("Hello", "$new")]), 200))
    await until(lambda: len(platform.observed_events) == 1)
    event = platform.observed_events[0]
    assert event["sender_id"] == "@user:example.com"
    assert event["meta"]["event_id"] == "$new"
    assert event["content_parts"][0].text == "Hello"
    receipt = hs.calls("/read_markers")[0]
    assert receipt["body"] == {"m.fully_read": "$new", "m.read": "$new"}
    await until(lambda: platform._state.load_sync() == "batch-new")
    client, http, sync_task = platform._client, platform._http_client, platform._sync_task
    await platform.stop()
    assert sync_task.done() and client.client_session is None and http.is_closed
    assert platform._client is None and not platform._state._begun
    assert platform.observed_states[-1] == "disconnected"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["mismatch", "unknown-token", "forbidden-password", "404-password"])
async def test_definitive_auth_failure_has_one_attempt_and_never_connects(hs, platform_factory, mode):
    platform = platform_factory(password="password" if "password" in mode else "")
    if mode == "mismatch":
        hs.user = "@different:example.com"
    elif mode == "unknown-token":
        hs.whoami.append(({"errcode": "M_UNKNOWN_TOKEN", "error": "Unknown token"}, 401))
    else:
        hs.login.append(({"errcode": "M_FORBIDDEN" if mode == "forbidden-password" else "M_NOT_FOUND", "error": "rejected"}, 403 if mode == "forbidden-password" else 404))
    with pytest.raises(RuntimeError, match="MATRIX_AUTHENTICATION_FAILED"):
        await platform.start()
    assert len(hs.calls("/login") if "password" in mode else hs.calls("/whoami")) == 1
    assert platform.observed_states == ["failed"]
    assert platform._sync_task is None
    assert not list(Path(platform.config["workspace_dir"]).rglob("auth.json"))


@pytest.mark.asyncio
async def test_stored_token_never_becomes_startup_credential(hs, platform_factory):
    platform = platform_factory()
    await platform.start()
    await platform.stop()
    requests = len(hs.calls("/whoami"))
    restored = platform_factory(user_id="", access_token="")
    with pytest.raises(RuntimeError, match="MATRIX_CREDENTIALS_REQUIRED"):
        await restored.start()
    assert restored.matrix_user_id == BOT and restored.access_token == ""
    assert len(hs.calls("/whoami")) == requests and not hs.calls("/login")


@pytest.mark.asyncio
async def test_same_device_cannot_be_owned_by_two_workspaces(hs, platform_factory, tmp_path):
    first = platform_factory()
    await first.start()
    before = {str(p): p.read_bytes() for p in first._state.directory.rglob("*") if p.is_file()}
    second = platform_factory(workspace_dir=str(tmp_path / "B"))
    with pytest.raises(Exception):
        await second.start()
    assert second.observed_states == ["failed"]
    assert first.observed_states == ["connected"] and first._client.logged_in
    assert {str(p): p.read_bytes() for p in first._state.directory.rglob("*") if p.is_file()} == before
    assert not list((tmp_path / "B").rglob("auth.json"))
    await second.stop()
    assert first._client.logged_in and first._state._begun
    await first.stop()
    third = platform_factory(workspace_dir=str(tmp_path / "B"))
    with pytest.raises(Exception, match="MATRIX_DEVICE_WORKSPACE_CONFLICT"):
        await third.start()


@pytest.mark.asyncio
async def test_invalid_sync_token_stops_loop_and_marks_failed(hs, platform_factory):
    hs.sync.put_nowait(({"errcode": "M_UNKNOWN_TOKEN", "error": "revoked"}, 401))
    platform = platform_factory()
    await platform.start()
    await until(lambda: platform._sync_task.done())
    assert len(hs.calls("/sync")) == 1
    assert platform.access_token == platform._client.access_token == ""
    assert platform.observed_states == ["connected", "failed"]
