"""Native retry/state/typing shutdown. No SDK class or auth path replacement."""
import asyncio
import json
from pathlib import Path

import pytest
from matrix_native_support import (
    BOT, ROOM, hs, platform_factory, sync_payload, text_event, until,
)
from qwenpaw_channel_matrix import platform as matrix_module


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["password", "token"])
async def test_unparseable_502_retries_exactly_once_then_connects(hs, platform_factory, monkeypatch, kind):
    # Same zero delay override as the legacy retry oracle; actual nio parses HTTP.
    monkeypatch.setattr(matrix_module, "_LOGIN_RETRY_INITIAL_DELAY", 0.0)
    responses = hs.login if kind == "password" else hs.whoami
    responses.append(({"unexpected": "proxy response"}, 502))
    platform = platform_factory(password="test_password" if kind == "password" else "")
    await platform.start()
    assert platform.observed_states == ["connected"]
    assert len(hs.calls("/login" if kind == "password" else "/whoami")) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["stop", "cancel"])
async def test_native_auth_backoff_is_interruptible_without_next_attempt(hs, platform_factory, monkeypatch, action):
    monkeypatch.setattr(matrix_module, "_LOGIN_RETRY_INITIAL_DELAY", 100.0)
    hs.whoami.append(({"unexpected": "proxy response"}, 502))
    platform = platform_factory()
    entered = asyncio.Event()
    original = platform._wait_backoff_or_stop
    async def observed(delay):
        entered.set()
        return await original(delay)
    monkeypatch.setattr(platform, "_wait_backoff_or_stop", observed)
    start = asyncio.create_task(platform.start())
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        if action == "stop":
            await platform.stop()
        else:
            start.cancel()
        with pytest.raises(asyncio.CancelledError):
            await start
        assert len(hs.calls("/whoami")) == 1
        assert "connected" not in platform.observed_states
    finally:
        start.cancel()
        await asyncio.gather(start, return_exceptions=True)


@pytest.mark.asyncio
async def test_saved_sync_token_processes_offline_event_and_closes_only_owned_typing(hs, platform_factory):
    first = platform_factory()
    await first.start()
    first._state.save_sync("saved-batch")
    await first.stop()
    hs.sync.put_nowait((sync_payload("offline-batch", [text_event("offline", "$offline")]), 200))
    second = platform_factory()
    before = len(hs.calls("/sync"))
    await second.start()
    await until(lambda: len(second.observed_events) == 1)
    assert second.observed_events[0]["content_parts"][0].text == "offline"
    assert hs.calls("/sync")[before]["query"]["since"] == "saved-batch"
    assert hs.calls("/sync")[before]["query"]["full_state"] == "true"
    await second.start_typing("reply-A", {"room_id": ROOM})
    await second.start_typing("reply-B", {"room_id": ROOM})
    typing = [r for r in hs.requests if "/typing/" in r["path"]]
    assert [r["body"] for r in typing] == [{"typing": True, "timeout": 30000}]
    task = second._typing_tasks[ROOM]
    await second.stop_typing("reply-A")
    assert not task.done() and second._typing_owners == {"reply-B": ROOM}
    assert len([r for r in hs.requests if "/typing/" in r["path"]]) == 1
    await second.stop()
    assert task.done() and not second._typing_owners and not second._typing_tasks
    assert [r["body"]["typing"] for r in hs.requests if "/typing/" in r["path"]] == [True, False]


@pytest.mark.asyncio
async def test_legacy_explicit_token_adopts_without_copying_or_overwriting_crypto(hs, platform_factory, tmp_path):
    legacy = tmp_path / "legacy"
    crypto = legacy / "matrix_crypto_store"
    crypto.mkdir(parents=True)
    original = {"matrix_auth_state.json": json.dumps({"user_id": BOT, "device_id": "SERVER-DEVICE", "access_token": "explicit-token"}).encode(),
                "matrix_sync_token": b"legacy-batch"}
    for name, raw in original.items():
        (legacy / name).write_bytes(raw)
    database = crypto / (BOT + "_SERVER-DEVICE.db")
    database.write_bytes(b"opaque-real-crypto-sentinel-no-olm-claim")
    platform = platform_factory()
    await platform.start()
    assert platform._state.crypto_dir == crypto
    assert database.read_bytes() == b"opaque-real-crypto-sentinel-no-olm-claim"
    assert not (platform._state.directory / "crypto_store").exists()
    assert all((legacy / name).read_bytes() == raw for name, raw in original.items())
    await until(lambda: len(hs.calls("/sync")) == 1)
    assert hs.calls("/sync")[0]["query"]["since"] == "legacy-batch"


@pytest.mark.asyncio
async def test_unclaimed_legacy_password_state_is_retained_and_not_transmitted(hs, platform_factory, tmp_path):
    # Safety witness for the known compatibility gap, not a migration completion claim.
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    raw = json.dumps({"user_id": BOT, "device_id": "SERVER-DEVICE", "access_token": "unrelated-cached-token"}).encode()
    (legacy / "matrix_auth_state.json").write_bytes(raw)
    platform = platform_factory(password="password", access_token="")
    with pytest.raises(RuntimeError, match="MATRIX_LEGACY_OWNER_UNVERIFIED"):
        await platform.start()
    assert (legacy / "matrix_auth_state.json").read_bytes() == raw
    assert not (legacy / "matrix_plugin_owner.json").exists()
    assert not hs.calls("/whoami")
    assert "unrelated-cached-token" not in json.dumps(hs.requests)
    assert platform.observed_states == ["failed"]


@pytest.mark.asyncio
async def test_stop_awaits_owned_http_operation_before_releasing_state(hs, platform_factory):
    platform = platform_factory()
    await platform.start()
    entered, cancelled, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    async def active_operation():
        async with platform.operation():
            entered.set()
            try:
                await platform._client.sync(timeout=30000)
            except asyncio.CancelledError:
                cancelled.set()
                await release.wait()
                raise
    task = asyncio.create_task(active_operation())
    stopping = None
    try:
        await entered.wait()
        stopping = asyncio.create_task(platform.stop())
        await asyncio.wait_for(cancelled.wait(), timeout=2)
        assert not stopping.done() and platform._client is not None and platform._state._begun
        release.set()
        await asyncio.wait_for(stopping, timeout=2)
        assert task.done() and not platform._operations and not platform._state._begun
    finally:
        release.set()
        await asyncio.gather(task, *([stopping] if stopping else []), return_exceptions=True)
