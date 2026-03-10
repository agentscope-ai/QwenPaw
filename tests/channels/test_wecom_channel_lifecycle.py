# -*- coding: utf-8 -*-

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
for candidate in (ROOT, SRC):
    path_str = str(candidate)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from copaw.app.channels.wecom.channel import WeComChannel


async def _empty_process(_request):
    if False:
        yield _request


class _FakeRuntimeClient:
    def __init__(self):
        self.started = 0
        self.stopped = 0

    async def start(self):
        self.started += 1

    async def stop(self):
        self.stopped += 1


@pytest.mark.anyio
async def test_channel_start_and_stop_manage_runtime_client():
    runtime = _FakeRuntimeClient()
    channel = WeComChannel(
        process=_empty_process,
        bot_id="bot-1",
        bot_secret="secret-1",
        runtime_client_factory=lambda **_kwargs: runtime,
    )

    await channel.start()

    assert channel._transport is runtime

    await channel.stop()

    assert runtime.started == 1
    assert runtime.stopped == 1
    assert channel._transport is None


@pytest.mark.anyio
async def test_channel_callback_enqueues_payload_when_callback_exists():
    received = []
    channel = WeComChannel(process=_empty_process)
    channel.set_enqueue(received.append)

    await channel._handle_incoming_payload({"cmd": "aibot_msg_callback"})

    assert received == [{"cmd": "aibot_msg_callback"}]


@pytest.mark.anyio
async def test_channel_callback_without_enqueue_does_not_crash():
    channel = WeComChannel(process=_empty_process)

    await channel._handle_incoming_payload({"cmd": "aibot_msg_callback"})


@pytest.mark.anyio
async def test_channel_from_env_reads_runtime_settings(monkeypatch):
    monkeypatch.setenv("WECOM_CHANNEL_ENABLED", "1")
    monkeypatch.setenv("WECOM_BOT_ID", "bot-1")
    monkeypatch.setenv("WECOM_BOT_SECRET", "secret-1")
    monkeypatch.setenv("WECOM_WS_URL", "wss://example.test/ws")
    monkeypatch.setenv("WECOM_PING_INTERVAL_SECONDS", "15")
    monkeypatch.setenv("WECOM_RECONNECT_MIN_SECONDS", "3")
    monkeypatch.setenv("WECOM_RECONNECT_MAX_SECONDS", "20")

    channel = WeComChannel.from_env(_empty_process)

    assert channel.enabled is True
    assert channel.bot_id == "bot-1"
    assert channel.bot_secret == "secret-1"
    assert channel.ws_url == "wss://example.test/ws"
    assert channel.ping_interval_seconds == 15
    assert channel.reconnect_min_seconds == 3
    assert channel.reconnect_max_seconds == 20


@pytest.mark.anyio
async def test_channel_start_requires_bot_id_when_runtime_enabled():
    channel = WeComChannel(
        process=_empty_process,
        enabled=True,
        bot_secret="secret-1",
    )

    with pytest.raises(ValueError, match="WECOM_BOT_ID"):
        await channel.start()


@pytest.mark.anyio
async def test_channel_start_requires_bot_secret_when_runtime_enabled():
    channel = WeComChannel(
        process=_empty_process,
        enabled=True,
        bot_id="bot-1",
    )

    with pytest.raises(ValueError, match="WECOM_BOT_SECRET"):
        await channel.start()
