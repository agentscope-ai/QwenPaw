"""Outbound deadlines through the real host, worker and native SDK."""

import base64
import os
from pathlib import Path
import time

import psutil

import pytest

from telegram_business_suite import forbid_host_sdk
from telegram_support import eventually, push, rows, telegram

pytest_plugins = ["telegram_support"]


def controlled_effect(sdk, *, endpoint="sendPhoto", delay=6):
    """Delay the local HTTP service; native SDK/request behavior stays real."""
    boundary = sdk.site / "qwenpaw_telegram_test_boundary.py"
    with boundary.open("a") as stream:
        stream.write(f"""
_budget_original_effect = effect
async def effect(kind, token, request, arguments=None):
    if kind == {endpoint!r}:
        record("budget-upload-start", token, endpoint=kind)
        try:
            await asyncio.sleep({delay!r})
        except asyncio.CancelledError:
            record("budget-upload-cancelled", token, endpoint=kind)
            raise
        record("budget-upload-complete", token, endpoint=kind)
    return await _budget_original_effect(kind, token, request, arguments)
""")


@pytest.mark.asyncio
async def test_default_native_media_upload_exceeding_control_rpc_is_acked(
    runtime,
    telegram_sdk,
):
    controlled_effect(telegram_sdk)
    rt = await telegram(runtime, telegram_sdk)
    media = rt.ws.workspace_dir / "upload.png"
    media.write_bytes(b"controlled-upload-bytes")
    meta = {}
    started = time.monotonic()
    await rt.channel.send_media(
        "12345", {"type": "image", "image_url": media.as_uri()}, meta
    )
    elapsed = time.monotonic() - started
    assert 6 <= elapsed < 12
    assert len(rows(telegram_sdk.work, "budget-upload-complete")) == 1
    assert rows(telegram_sdk.work, "budget-upload-cancelled") == []
    assert len(rows(telegram_sdk.work, "message-effect")) == 1
    assert len(rows(telegram_sdk.work, "sendPhoto-success")) == 1
    upload = rows(telegram_sdk.work, "sendPhoto")[0]
    assert base64.b64decode(upload["files"]["photo"]["bytes_b64"]) == (
        b"controlled-upload-bytes"
    )
    assert upload["read_timeout"] == 5
    assert upload["pid"] == rt.process.health_snapshot()["pid"] != os.getpid()
    assert Path(upload["sdk_source"]).is_relative_to(telegram_sdk.site)
    assert not meta.get("_reply_unknown")
    assert not meta.get("_pending_delivery")


@pytest.mark.asyncio
@pytest.mark.parametrize("chunks", [False, True])
async def test_native_deadline_is_total_and_unknown_never_replays(
    runtime,
    telegram_sdk,
    chunks,
):
    from qwenpaw.app.channels.isolated_proxy import ChannelDeliveryError

    controlled_effect(
        telegram_sdk,
        endpoint="sendMessage" if chunks else "sendPhoto",
        delay=0.22 if chunks else 1,
    )
    rt = await telegram(
        runtime,
        telegram_sdk,
        runtime_settings={"send_timeouts": {"telegram": 0.35}},
    )
    assert rt.channel._launch_spec.send_timeout == 0.35
    meta = {}

    async def deliver():
        if chunks:
            await rt.channel.send("12345", "A" * 8000, meta)
        else:
            media = rt.ws.workspace_dir / "deadline.png"
            media.write_bytes(b"controlled-upload-bytes")
            await rt.channel.send_media(
                "12345", {"type": "image", "image_url": media.as_uri()}, meta
            )

    started = time.monotonic()
    with pytest.raises(ChannelDeliveryError) as caught:
        await deliver()
    assert caught.value.state == "unknown"
    assert 0.25 <= time.monotonic() - started < 1.5
    assert meta["_reply_unknown"] is True
    assert len(rows(telegram_sdk.work, "budget-upload-cancelled")) == 1
    assert len(rows(telegram_sdk.work, "message-effect")) == int(chunks)
    attempts = rows(telegram_sdk.work, "budget-upload-start")
    assert len(attempts) == (2 if chunks else 1)
    pending = dict(meta["_pending_delivery"])
    with pytest.raises(ChannelDeliveryError) as replay:
        await deliver()
    assert replay.value.state == "unknown"
    assert meta["_pending_delivery"] == pending
    assert rows(telegram_sdk.work, "budget-upload-start") == attempts


@pytest.mark.asyncio
async def test_manager_drain_retains_long_upload_until_ack_then_stops(
    runtime,
    telegram_sdk,
    monkeypatch,
    tmp_path,
):
    from qwenpaw.plugins.registry import PluginRegistry
    from qwenpaw.schemas import ImageContent

    controlled_effect(telegram_sdk)
    media = tmp_path / "workspace-telegram" / "stop.png"
    rt = await telegram(
        runtime,
        telegram_sdk,
        agent_content=[ImageContent(image_url=media.as_uri())],
    )
    media.write_bytes(b"controlled-upload-bytes")
    push(telegram_sdk.work)
    await eventually(
        lambda: bool(rows(telegram_sdk.work, "budget-upload-start"))
    )
    monkeypatch.setattr(
        "qwenpaw.app.channels.manager._CHANNEL_DRAIN_TIMEOUT", 0.15
    )
    pid = rt.process.health_snapshot()["pid"]
    started = time.monotonic()
    receipt = await rt.manager.stop_one("telegram")
    assert time.monotonic() - started < 1.5
    assert not receipt.stopped
    assert receipt.detail == "CHANNEL_DRAIN_TIMEOUT"
    assert await rt.manager.get_channel("telegram") is rt.channel
    assert PluginRegistry().runtime_owners.leases("telegram")
    assert psutil.pid_exists(pid)
    assert not rows(telegram_sdk.work, "budget-upload-cancelled")
    await eventually(
        lambda: bool(rows(telegram_sdk.work, "sendPhoto-success"))
    )
    monkeypatch.setattr(
        "qwenpaw.app.channels.manager._CHANNEL_DRAIN_TIMEOUT", 2
    )
    stopped = await rt.manager.stop_one("telegram")
    assert stopped.stopped and stopped.exited and not stopped.residual
    assert not psutil.pid_exists(pid)
    assert await rt.manager.get_channel("telegram") is None
    assert not PluginRegistry().runtime_owners.leases("telegram")


@pytest.mark.asyncio
@pytest.mark.parametrize("budget,delay", [(None, 6), (0.35, 1)])
async def test_native_finish_cleanup_uses_outbound_receipt_budget(
    runtime,
    telegram_sdk,
    budget,
    delay,
):
    from qwenpaw.channel_protocol.errors import RpcError

    controlled_effect(telegram_sdk, endpoint="deleteMessage", delay=delay)
    rt = await telegram(
        runtime,
        telegram_sdk,
        streaming_enabled=True,
        runtime_settings={} if budget is None else {"send_timeout": budget},
    )
    meta = {}
    await rt.channel.on_streaming_start(None, "12345", None, meta, "message")
    assert len(rows(telegram_sdk.work, "sendMessage-success")) == 1
    started = time.monotonic()
    if budget is None:
        await rt.channel._finish_route(meta, "completed")
        assert 6 <= time.monotonic() - started < 12
        assert len(rows(telegram_sdk.work, "deleteMessage-success")) == 1
        assert rows(telegram_sdk.work, "budget-upload-cancelled") == []
    else:
        with pytest.raises(RpcError) as caught:
            await rt.channel._finish_route(meta, "completed")
        assert caught.value.data["reason_code"] == "RESPONSE_FINISH_FAILED"
        assert 0.25 <= time.monotonic() - started < 1.5
        assert len(rows(telegram_sdk.work, "budget-upload-cancelled")) == 1
        assert rows(telegram_sdk.work, "deleteMessage-success") == []
        with pytest.raises(RpcError):
            await rt.channel._finish_route(meta, "completed")
        assert len(rows(telegram_sdk.work, "budget-upload-start")) == 1
