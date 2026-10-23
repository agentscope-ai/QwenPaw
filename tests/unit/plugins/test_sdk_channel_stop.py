# -*- coding: utf-8 -*-
"""SDK stop preparation through the real manager and workspace barriers."""

import asyncio
import json

import pytest

from qwenpaw.plugins import SDKError
from qwenpaw.plugins.channels import ChannelMessage
from qwenpaw.plugins.lifecycle import QuiescenceError
from qwenpaw.plugins.messages import ContentBlock
from qwenpaw.plugins.testing import PluginTestHost

from .sdk_author_fixture import make_plugin

SOURCE = """
import asyncio
from qwenpaw.plugins.channels import ChannelSpec
from qwenpaw.plugins.commands import CommandSpec, CommandResult
from qwenpaw.plugins.messages import ContentBlock, Message
class Plugin:
    def register(self, plugin):
        class Transport:
            async def start(self, call): pass
            async def send(self, call, message):
                sent = plugin.storage.read_json("sent.json", [])
                plugin.storage.write_json("sent.json", [*sent, ''.join(b.text for b in message.content)])
                plugin.storage.write_json("sending.json", True)
                try:
                    while not plugin.storage.read_json("release.json", False):
                        await asyncio.sleep(.01)
                finally:
                    plugin.storage.write_json("cleanup-entered.json", True)
                    try:
                        while plugin.storage.read_json("hold-cleanup.json", False):
                            await asyncio.sleep(.01)
                    except asyncio.CancelledError:
                        plugin.storage.write_json("cleanup-cancelled.json", True)
                        raise
                    plugin.storage.write_json("finished.json", True)
            async def stop(self, call):
                plugin.storage.write_json("stopped.json",
                    plugin.storage.read_json("finished.json", False))
                return True
        async def reply(call, args):
            commands = plugin.storage.read_json("commands.json", [])
            plugin.storage.write_json("commands.json", [*commands, args])
            return CommandResult("reply", Message("assistant", (ContentBlock(text=args or "answer"),)))
        plugin.register_command(CommandSpec("stopprobe", reply))
        plugin.register_channel(ChannelSpec("stop-probe", "Stop probe", Transport))
        plugin.register_channel(ChannelSpec("other-probe", "Other probe", Transport))
plugin = Plugin()
"""


def message(text="", **kwargs):
    return ChannelMessage(
        "sender",
        (ContentBlock(text="/stopprobe " + text),),
        **kwargs,
    )


async def wait_sending(ctx):
    async with asyncio.timeout(3):
        while not ctx.storage.read_json("sending.json", False):
            await asyncio.sleep(0.01)


async def wait_until(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(0.01)


@pytest.fixture
async def running_channel(tmp_path):
    async with PluginTestHost(tmp_path / "host") as host:
        ctx = await host.load(
            make_plugin(tmp_path, SOURCE, ["channels", "commands", "storage"]),
        )
        await host.start_channel("stop-probe")
        workspace = await host._workspace("test")
        try:
            yield host, ctx, workspace
        finally:
            try:
                current = host.context("extension-contract")
            except SDKError:
                current = None
            if current is ctx:
                ctx.storage.write_json("release.json", True)
                ctx.storage.write_json("hold-cleanup.json", False)


@pytest.mark.parametrize("stop_workspace", [False, True])
async def test_shutdown_prepares_hung_sdk_send(
    running_channel,
    stop_workspace,
):
    host, ctx, workspace = running_channel
    await host.receive_channel("stop-probe", message())
    await wait_sending(ctx)
    if stop_workspace:
        # PluginTestHost builds real workspaces without starting every service.
        workspace._start_attempted = True
        shutdown = workspace.stop()
    else:
        shutdown = workspace.channel_manager.stop_all()
    await asyncio.wait_for(shutdown, 3)
    assert ctx.storage.read_json("finished.json", False)
    assert ctx.storage.read_json("stopped.json", False)
    assert await workspace.channel_manager.get_channel("stop-probe") is None
    host.assert_quiescent("extension-contract")


async def test_ordinary_quiesce_does_not_cancel_sdk_send(running_channel):
    host, ctx, workspace = running_channel
    manager = workspace.channel_manager
    await host.receive_channel("stop-probe", message())
    await wait_sending(ctx)
    assert not await manager.quiesce(timeout=0.03)
    assert not ctx.storage.read_json("finished.json", False)
    assert ctx.storage.read_json("stopped.json", None) is None
    ctx.storage.write_json("release.json", True)
    assert await manager.quiesce(timeout=3)
    assert ctx.storage.read_json("finished.json", False)
    assert ctx.storage.read_json("stopped.json", None) is None
    await host.stop_channel("stop-probe")


@pytest.mark.parametrize("stop_other", [False, True])
async def test_overlapping_stops_preserve_sdk_call_cleanup(
    running_channel,
    monkeypatch,
    stop_other,
):
    host, ctx, workspace = running_channel
    manager = workspace.channel_manager
    if stop_other:
        await host.start_channel("other-probe")
    ctx.storage.write_json("hold-cleanup.json", True)
    await host.receive_channel("stop-probe", message())
    await wait_sending(ctx)
    stopping_one = asyncio.create_task(manager.stop_one("stop-probe"))
    async with asyncio.timeout(3):
        while not ctx.storage.read_json("cleanup-entered.json", False):
            await asyncio.sleep(0.01)
    channel = await manager.get_channel("stop-probe")
    prepare = channel.prepare_stop
    second_preparing = asyncio.Event()

    async def observe_prepare():
        second_preparing.set()
        return await prepare()

    monkeypatch.setattr(channel, "prepare_stop", observe_prepare)
    stopping_all = asyncio.create_task(manager.stop_all())
    try:
        await asyncio.wait_for(second_preparing.wait(), 3)
        done, _ = await asyncio.wait(
            {stopping_one, stopping_all},
            timeout=0.05,
        )
        assert not done
        assert not ctx.storage.read_json("cleanup-cancelled.json", False)
        assert ctx.storage.read_json("stopped.json", None) is None
        if stop_other:
            assert (await manager.stop_one("other-probe")).stopped
    finally:
        ctx.storage.write_json("hold-cleanup.json", False)
        results = await asyncio.wait_for(
            asyncio.gather(stopping_one, stopping_all),
            3,
        )
    assert results[0].stopped
    assert ctx.storage.read_json("finished.json", False)
    assert ctx.storage.read_json("stopped.json", False)
    if stop_other:
        await manager.start_all()
        await host.start_channel("other-probe")
        await host.stop_channel("other-probe")


@pytest.mark.parametrize("stop_all", [False, True])
async def test_prepare_failure_retains_sdk_owner_for_retry(
    running_channel,
    monkeypatch,
    stop_all,
):
    host, ctx, workspace = running_channel
    manager = workspace.channel_manager
    channel = await manager.get_channel("stop-probe")
    prepare = channel.prepare_stop
    await host.receive_channel("stop-probe", message())
    await wait_sending(ctx)

    async def fail_after_preparing():
        await prepare()
        raise SDKError("prepare interrupted")

    monkeypatch.setattr(channel, "prepare_stop", fail_after_preparing)
    if stop_all:
        with pytest.raises(QuiescenceError, match="prepare interrupted"):
            await manager.stop_all()
    else:
        receipt = await manager.stop_one("stop-probe")
        assert not receipt.stopped and "prepare interrupted" in receipt.detail
    assert await manager.get_channel("stop-probe") is channel
    assert ctx.storage.read_json("finished.json", False)
    assert ctx.storage.read_json("stopped.json", None) is None
    with pytest.raises(SDKError):
        await host.receive_channel("stop-probe", message())
    assert not (await host.reload("extension-contract")).ok
    assert host.context("extension-contract") is ctx
    monkeypatch.setattr(channel, "prepare_stop", prepare)
    assert (await manager.stop_one("stop-probe")).stopped
    assert await manager.get_channel("stop-probe") is None
    result = await host.reload("extension-contract")
    assert result.ok, result.errors


@pytest.mark.parametrize("prepare_also", [False, True])
async def test_external_consumer_cancellation_propagates(
    running_channel,
    prepare_also,
):
    _, ctx, workspace = running_channel
    channel = await workspace.channel_manager.get_channel("stop-probe")
    request = channel.build_agent_request_from_native(message())
    consumer = asyncio.create_task(channel.consume_one(request))
    try:
        await wait_sending(ctx)
        consumer.cancel()
        if prepare_also:
            await channel.prepare_stop()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(consumer, 3)
        assert consumer.cancelled()
        await channel.prepare_stop()
        assert ctx.storage.read_json("finished.json", False)
        assert ctx.storage.read_json("stopped.json", None) is None
    finally:
        if not consumer.done():
            consumer.cancel()
            await asyncio.gather(consumer, return_exceptions=True)


@pytest.mark.parametrize("operation", ["stop", "reload", "unload"])
async def test_interrupt_settles_real_queue_backlog_without_replaying(
    running_channel,
    monkeypatch,
    operation,
):
    host, ctx, workspace = running_channel
    manager = workspace.channel_manager
    await host.receive_channel("stop-probe", message("active"))
    await wait_sending(ctx)
    (state,) = manager._queue_manager._queues.values()
    queue = state.queue
    settled = []
    task_done = queue.task_done

    def record_done():
        settled.append(True)
        task_done()

    monkeypatch.setattr(queue, "task_done", record_done)
    await host.receive_channel("stop-probe", message("backlog"))
    await wait_until(lambda: queue.qsize() == 1)
    assert queue.unfinished == 2
    if operation == "stop":
        await host.stop_channel("stop-probe")
    elif operation == "reload":
        result = await host.reload("extension-contract", interrupt_tasks=True)
        assert result.ok, result.errors
    else:
        result = await host.unload("extension-contract", interrupt_tasks=True)
        assert result.clean, result
    await asyncio.wait_for(queue.join(), 0.2)
    assert queue.qsize() == queue.unfinished == 0
    assert len(settled) == 2
    data = host.root / "plugin-data/extension-contract"
    assert json.loads((data / "sent.json").read_text()) == ["active"]
    assert json.loads((data / "commands.json").read_text()) == ["active"]
    assert json.loads((data / "finished.json").read_text()) is True
    assert json.loads((data / "stopped.json").read_text()) is True
    if operation != "unload":
        ctx = host.context("extension-contract")
        ctx.storage.write_json("release.json", True)
        await host.start_channel("stop-probe")
        await host.receive_channel("stop-probe", message("after"))
        await wait_until(
            lambda: len(ctx.storage.read_json("sent.json", [])) == 2,
        )
        assert await manager.quiesce(timeout=3)
        assert ctx.storage.read_json("sent.json") == ["active", "after"]
        assert ctx.storage.read_json("commands.json") == ["active", "after"]


async def test_real_consumer_repeated_cancel_waits_for_cleanup(
    running_channel,
):
    host, ctx, workspace = running_channel
    manager = workspace.channel_manager
    ctx.storage.write_json("hold-cleanup.json", True)
    await host.receive_channel("stop-probe", message())
    await wait_sending(ctx)
    (state,) = manager._queue_manager._queues.values()
    consumer = state.consumer_task
    consumer.cancel()
    try:
        await wait_until(
            lambda: ctx.storage.read_json("cleanup-entered.json", False),
        )
        consumer.cancel()
        done, _ = await asyncio.wait({consumer}, timeout=0.03)
        assert not done
        assert not ctx.storage.read_json("cleanup-cancelled.json", False)
        assert not ctx.storage.read_json("finished.json", False)
        assert state.queue.unfinished == 1
    finally:
        ctx.storage.write_json("hold-cleanup.json", False)
        await asyncio.gather(consumer, return_exceptions=True)
    assert consumer.cancelled()
    assert ctx.storage.read_json("finished.json", False)
    assert not ctx.storage.read_json("cleanup-cancelled.json", False)
    await asyncio.wait_for(state.queue.join(), 0.2)
    assert state.queue.unfinished == 0
    # A fresh consumer must be usable for the same channel/session key.
    ctx.storage.write_json("release.json", True)
    await host.receive_channel("stop-probe", message("after"))
    await wait_until(lambda: len(ctx.storage.read_json("sent.json", [])) == 2)
    assert await manager.quiesce(timeout=3)
    assert ctx.storage.read_json("sent.json") == ["answer", "after"]


@pytest.mark.parametrize("operation", ["cancel", "reload"])
async def test_model_consumer_cancellation_owns_provider_cleanup(
    tmp_path,
    monkeypatch,
    operation,
):
    from qwenpaw.plugins import PluginBusyError, activity, custody
    from .test_sdk_channel_routing_contract import (
        CHANNEL,
        SOURCE as model_source,
        incoming,
    )

    monkeypatch.setattr(activity, "INTERRUPT_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(custody, "TASK_STOP_SECONDS", 0.02)
    finalizer = '                append("model-finished.json", text)'
    assert model_source.count(finalizer) == 1
    source = model_source.replace(
        finalizer,
        """                plugin.storage.write_json('cleanup-entered.json',True)
                try:
                    while plugin.storage.read_json('hold-cleanup.json',False):
                        await asyncio.sleep(.01)
                except asyncio.CancelledError:
                    plugin.storage.write_json('cleanup-cancelled.json',True)
                    raise
                append('model-finished.json',text)""",
    )
    async with PluginTestHost(tmp_path / "host") as host:
        ctx = await host.load(
            make_plugin(
                tmp_path,
                source,
                ["channels", "providers", "storage"],
            ),
        )
        await host.configure_chat_model("routing-provider", "routing-model")
        await host.start_channel(CHANNEL)
        ctx.storage.write_json("hold-cleanup.json", True)
        await host.receive_channel(CHANNEL, incoming("hold-first", "active"))
        await wait_until(lambda: bool(ctx.storage.read_json("model.json", [])))
        workspace = await host._workspace("test")
        manager = workspace.channel_manager
        (state,) = manager._queue_manager._queues.values()
        consumer = state.consumer_task
        try:
            if operation == "reload":
                for _ in range(2):
                    with pytest.raises(PluginBusyError):
                        await host.reload(
                            "extension-contract",
                            interrupt_tasks=True,
                        )
                    assert host.context("extension-contract") is ctx
            else:
                consumer.cancel()
            await wait_until(
                lambda: ctx.storage.read_json("cleanup-entered.json", False),
            )
            if operation == "cancel":
                consumer.cancel()
                done, _ = await asyncio.wait({consumer}, timeout=0.05)
                assert not done
            assert state.queue.unfinished == 1
            assert not ctx.storage.read_json("cleanup-cancelled.json", False)
            assert ctx.storage.read_json("model-finished.json", []) == []
            assert [
                (e["phase"], e["status"])
                for e in ctx.storage.read_json("events.json")
            ] == [("start", "running")]
        finally:
            ctx.storage.write_json("hold-cleanup.json", False)
            if operation == "cancel":
                await asyncio.gather(consumer, return_exceptions=True)
        if operation == "cancel":
            assert consumer.cancelled()
        else:
            await wait_until(
                lambda: ctx.storage.read_json("model-finished.json", [])
                == ["hold-first"],
            )
            result = await host.reload(
                "extension-contract",
                interrupt_tasks=True,
            )
            assert result.ok, result.errors
            ctx = host.context("extension-contract")
            await host.start_channel(CHANNEL)
        await asyncio.wait_for(state.queue.join(), 0.2)
        assert state.queue.unfinished == 0
        assert ctx.storage.read_json("model-finished.json") == ["hold-first"]
        assert [
            (e["phase"], e["status"])
            for e in ctx.storage.read_json("events.json")
        ] == [
            ("start", "running"),
            ("end", "cancelled"),
        ]
        await host.receive_channel(CHANNEL, incoming("after", "next"))
        await wait_until(
            lambda: len(ctx.storage.read_json("model-finished.json", [])) == 2,
        )
        assert await manager.quiesce(timeout=3)
        assert [
            item["text"] for item in ctx.storage.read_json("model.json")
        ] == ["hold-first", "after"]


async def test_cancel_after_real_queue_get_settles_message(
    running_channel,
    monkeypatch,
):
    host, ctx, workspace = running_channel
    manager = workspace.channel_manager
    channel = await manager.get_channel("stop-probe")
    get_channel = manager.get_channel
    looking_up = asyncio.Event()
    release = asyncio.Event()

    async def held_lookup(name):
        looking_up.set()
        await release.wait()
        return await get_channel(name)

    monkeypatch.setattr(manager, "get_channel", held_lookup)
    channel._sdk_context.receive(message())
    try:
        await asyncio.wait_for(looking_up.wait(), 3)
        (state,) = manager._queue_manager._queues.values()
        assert state.queue.qsize() == 0 and state.queue.unfinished == 1
        state.consumer_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await state.consumer_task
        await asyncio.wait_for(state.queue.join(), 0.2)
        assert state.queue.unfinished == 0
        assert ctx.storage.read_json("sent.json", []) == []
    finally:
        release.set()
        monkeypatch.setattr(manager, "get_channel", get_channel)


async def test_cancel_mid_batch_settles_every_dequeued_acl_message_once(
    running_channel,
    monkeypatch,
):
    _, ctx, workspace = running_channel
    manager = workspace.channel_manager
    channel = await manager.get_channel("stop-probe")
    consume = channel._consume_one_request
    observed = []

    async def observe(request):
        observed.append(
            (
                request.acl_sender_id,
                tuple(
                    block.text
                    for item in request.input
                    for block in item.content
                ),
            ),
        )
        if len(observed) == 2:
            ctx.storage.write_json("release.json", False)
            ctx.storage.write_json("hold-cleanup.json", True)
            ctx.storage.write_json("cleanup-entered.json", False)
        await consume(request)

    monkeypatch.setattr(channel, "_consume_one_request", observe)
    ctx.storage.write_json("release.json", True)
    # Synchronous SDK ingress schedules all four arrivals before a consumer
    # can dequeue; the first two share ACL identity and merge into one call.
    for identifier, acl in (("1", "a"), ("2", "a"), ("3", "b"), ("4", "a")):
        channel._sdk_context.receive(
            message(
                identifier,
                session_id="shared",
                message_id=identifier,
                acl_sender_id=acl,
                is_group=True,
            ),
        )
    await wait_until(lambda: len(ctx.storage.read_json("sent.json", [])) == 2)
    (state,) = manager._queue_manager._queues.values()
    assert state.queue.qsize() == 0 and state.queue.unfinished == 4
    settled = []
    task_done = state.queue.task_done

    def record_done():
        settled.append(True)
        task_done()

    monkeypatch.setattr(state.queue, "task_done", record_done)
    state.consumer_task.cancel()
    try:
        await wait_until(
            lambda: ctx.storage.read_json("cleanup-entered.json", False),
        )
        assert not state.consumer_task.done()
        assert state.queue.unfinished == 4
    finally:
        ctx.storage.write_json("hold-cleanup.json", False)
        await asyncio.gather(state.consumer_task, return_exceptions=True)
    assert state.consumer_task.cancelled()
    assert observed == [
        ("a", ("/stopprobe 1", "/stopprobe 2")),
        ("b", ("/stopprobe 3",)),
    ]
    assert len(ctx.storage.read_json("commands.json")) == 2
    assert len(ctx.storage.read_json("sent.json")) == 2
    assert len(settled) == 4 and state.queue.unfinished == 0
    await asyncio.wait_for(state.queue.join(), 0.2)


async def test_interrupt_retry_keeps_queue_and_cleanup_on_original_instance(
    running_channel,
    monkeypatch,
):
    from qwenpaw.plugins import PluginBusyError
    from qwenpaw.plugins import activity, custody

    monkeypatch.setattr(activity, "INTERRUPT_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(custody, "TASK_STOP_SECONDS", 0.05)
    host, ctx, workspace = running_channel
    manager = workspace.channel_manager
    channel = await manager.get_channel("stop-probe")
    ctx.storage.write_json("hold-cleanup.json", True)
    await host.receive_channel("stop-probe", message("active"))
    await wait_sending(ctx)
    (state,) = manager._queue_manager._queues.values()
    await host.receive_channel("stop-probe", message("backlog"))
    await wait_until(lambda: state.queue.qsize() == 1)
    try:
        for _ in range(2):
            with pytest.raises(PluginBusyError):
                await host.reload("extension-contract", interrupt_tasks=True)
            assert host.context("extension-contract") is ctx
            assert await manager.get_channel("stop-probe") is channel
            assert ctx.storage.read_json("cleanup-entered.json", False)
            assert not ctx.storage.read_json("cleanup-cancelled.json", False)
            assert not ctx.storage.read_json("finished.json", False)
            assert ctx.storage.read_json("stopped.json", None) is None
            assert state.queue.unfinished == 2
        receipt = await manager.stop_one("stop-probe")
        assert not receipt.stopped
        assert await manager.get_channel("stop-probe") is channel
        assert not ctx.storage.read_json("cleanup-cancelled.json", False)
        assert ctx.storage.read_json("stopped.json", None) is None
    finally:
        ctx.storage.write_json("hold-cleanup.json", False)
    await wait_until(lambda: ctx.storage.read_json("finished.json", False))
    result = await host.reload("extension-contract", interrupt_tasks=True)
    assert result.ok, result.errors
    await asyncio.wait_for(state.queue.join(), 0.2)
    assert state.queue.qsize() == state.queue.unfinished == 0
    assert host.context("extension-contract") is not ctx
    data = host.root / "plugin-data/extension-contract"
    assert json.loads((data / "sent.json").read_text()) == ["active"]
