"""Public DiscordPlatform behavior with only the copied SDK controlled."""

import importlib
import sys

import pytest
import pytest_asyncio

from discord_support import discord_sdk, fault_runtime, rows
from extension_sample import ROOT
from extension_process_suite import eventually


@pytest_asyncio.fixture
async def platform(discord_sdk, tmp_path, monkeypatch):
    for name in tuple(sys.modules):
        if name == "discord" or name.startswith(
            ("discord.", "qwenpaw_channel_discord")
        ):
            monkeypatch.delitem(sys.modules, name)
    monkeypatch.syspath_prepend(str(discord_sdk.site))
    monkeypatch.syspath_prepend(str(ROOT / "plugins/channel/discord"))
    sdk = importlib.import_module("discord")
    module = importlib.import_module("qwenpaw_channel_discord.platform")
    accepted, states = [], []

    async def event(value):
        accepted.append(value)
        return True

    async def state(value):
        states.append(value)

    value = module.DiscordPlatform(
        {"bot_token": "local-A", "workspace_dir": str(tmp_path / "workspace")},
        event,
        state,
    )
    await value.start()
    await eventually(lambda: "connected" in states)
    try:
        yield value, sdk.LIVE_CLIENTS["local-A"], accepted, states
    finally:
        await value.stop()


@pytest.mark.asyncio
async def test_stable_message_id_cache_is_bounded_by_500_and_not_text(
    platform,
):
    _, client, accepted, _ = platform
    for ident in range(1, 502):
        await client.dispatch(
            "on_message", client.message({"id": ident, "text": "identical"})
        )
    assert len(accepted) == 501
    await client.dispatch(
        "on_message", client.message({"id": 501, "text": "identical"})
    )
    assert len(accepted) == 501
    await client.dispatch(
        "on_message", client.message({"id": 1, "text": "identical"})
    )
    assert len(accepted) == 502
    assert [row["message_id"] for row in accepted[-2:]] == ["501", "1"]


@pytest.mark.asyncio
async def test_missing_media_url_and_empty_parts_are_platform_noops(
    platform, discord_sdk
):
    value, _, _, _ = platform
    for parts in ([], [{"type": "image"}], [{"type": "file", "file_url": ""}]):
        receipt = await value.send_parts({"channel_id": "123"}, parts)
        assert receipt["message_id"] == ""
    assert rows(discord_sdk.work, "send") == []


@pytest.mark.asyncio
async def test_callbacks_after_stop_do_not_reconnect_or_submit(platform):
    value, client, accepted, states = platform
    await value.stop()
    await client.dispatch("on_ready")
    await client.dispatch("on_message", client.message({"id": 1}))
    await client.dispatch(
        "on_thread_create", client.message({"id": 2}).channel
    )
    assert accepted == []
    assert states == ["connected"]
    assert value.connected is False


@pytest.mark.asyncio
async def test_typing_exit_failure_is_visible_and_stop_can_retry(
    platform, discord_sdk
):
    from discord_support import set_mode

    value, _, _, _ = platform
    await value.start_typing("one", {"channel_id": "123"})
    set_mode(discord_sdk.work, "typing-exit-reject")
    with pytest.raises(Exception):
        await value.stop_typing("one")
    assert len(rows(discord_sdk.work, "typing-exit")) == 1
    set_mode(discord_sdk.work, "")
    await value.stop()
    assert rows(discord_sdk.work, "gateway-close")


@pytest.mark.asyncio
async def test_gateway_close_failure_is_visible_and_second_stop_confirms_close(
    platform, discord_sdk
):
    from discord_support import set_mode

    value, _, _, _ = platform
    set_mode(discord_sdk.work, "close-unknown")
    with pytest.raises(TimeoutError):
        await value.stop()
    assert len(rows(discord_sdk.work, "gateway-close")) == 1
    set_mode(discord_sdk.work, "")
    await value.stop()
    assert len(rows(discord_sdk.work, "gateway-close")) == 2


@pytest.mark.asyncio
async def test_uninitialized_and_disconnected_platform_sends_fail_without_effect(
    platform, discord_sdk
):
    from qwenpaw_channel_discord.platform import (
        DiscordDeliveryError,
        DiscordPlatform,
    )

    value, client, _, _ = platform

    async def event(_value):
        return True

    async def state(_value):
        pass

    unstarted = DiscordPlatform({}, event, state)
    with pytest.raises(DiscordDeliveryError, match="NOT_CONNECTED"):
        await unstarted.send_parts(
            {"channel_id": "123"}, [{"type": "text", "text": "uninitialized"}]
        )
    await client.dispatch("on_disconnect")
    with pytest.raises(DiscordDeliveryError, match="NOT_CONNECTED"):
        await value.send_parts(
            {"channel_id": "123"}, [{"type": "text", "text": "disconnected"}]
        )
    assert rows(discord_sdk.work, "send") == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "outcome", ["success", "native_failure", "cancel_retry"]
)
async def test_real_sdk_typing_shutdown_waits_for_http_cleanup_and_keeps_other_owner(
    platform, outcome
):
    import asyncio
    from types import SimpleNamespace
    from discord.context_managers import Typing

    value, client, _, _ = platform
    entered, cleanup_started, release = (
        asyncio.Event(),
        asyncio.Event(),
        asyncio.Event(),
    )

    class HTTPBoundary:
        def __init__(self):
            self.calls = {}

        async def send_typing(self, ident):
            self.calls[ident] = self.calls.get(ident, 0) + 1
            if ident != 123 or self.calls[ident] == 1:
                return
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleanup_started.set()
                await release.wait()
                if outcome == "native_failure":
                    raise RuntimeError(
                        "native HTTP cancellation cleanup failed"
                    )

    class Messageable:
        def __init__(self, ident, http):
            self.id = ident
            self._state = SimpleNamespace(
                loop=asyncio.get_running_loop(), http=http
            )
            self.context = None

        async def _get_channel(self):
            return self

        def typing(self):
            self.context = Typing(self)
            return self.context

    http = HTTPBoundary()
    first, second = Messageable(123, http), Messageable(456, http)
    client.channels.update({123: first, 456: second})
    await value.start_typing("first", {"channel_id": "123"})
    await value.start_typing("second", {"channel_id": "456"})
    stopping, retry = None, None
    try:
        await eventually(entered.is_set)
        native = first.context.task
        stopping = asyncio.create_task(value.stop_typing("first"))
        await eventually(cleanup_started.is_set)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert not stopping.done(), "stop returned before native HTTP cleanup"
        assert not native.done()
        assert not second.context.task.done()
        if outcome == "cancel_retry":
            stopping.cancel()
            with pytest.raises(asyncio.CancelledError):
                await stopping
            assert not native.done(), "caller cancellation lost native cleanup"
            retry = asyncio.create_task(value.stop_typing("first"))
            await asyncio.sleep(0)
            assert not retry.done()
        release.set()
        if outcome == "native_failure":
            with pytest.raises(RuntimeError, match="native HTTP cancellation"):
                await stopping
            await value.stop_typing("first")
        else:
            await (retry if retry is not None else stopping)
        assert native.done()
        assert not second.context.task.done()
        await value.stop_typing("second")
        assert second.context.task.done()
    finally:
        release.set()
        await asyncio.gather(
            *(task for task in (stopping, retry) if task is not None),
            return_exceptions=True,
        )
        await value.stop_typing("second")
        await asyncio.gather(
            first.context.task, second.context.task, return_exceptions=True
        )
