# -*- coding: utf-8 -*-
"""Internal production TaskTracker boundary for public Channel callbacks."""

# Inspect host ownership and cleanup state at the tested bridge boundary.
# pylint: disable=protected-access

import asyncio

import pytest

from .sdk_author_fixture import make_plugin

from .timing import WAIT_TIMEOUT


async def wait_flag(ctx, name):
    async with asyncio.timeout(WAIT_TIMEOUT):
        while True:
            if ctx.storage.read_json(name, False):
                return
            await asyncio.sleep(0.01)
    pytest.fail(f"Channel callback did not reach {name}")


async def test_sync_channel_send_observes_current_call_cancellation(tmp_path):
    from qwenpaw.plugins.channels import ChannelMessage
    from qwenpaw.plugins.messages import ContentBlock
    from qwenpaw.plugins.testing import PluginTestHost

    source = """
import time
from pathlib import Path
from qwenpaw.plugins.channels import ChannelSpec
from qwenpaw.plugins.commands import CommandSpec, CommandResult
from qwenpaw.plugins.messages import Message, ContentBlock


class Plugin:
    def register(self, plugin):
        class Transport:
            async def start(self, call):
                pass

            async def stop(self, call):
                return True

            def send(self, call, message):
                plugin.storage.write_json("entered.json", True)
                try:
                    while (
                        not call.cancelled
                        and not Path(
                            plugin.config.get("release")
                        ).exists()
                    ):
                        time.sleep(0.01)
                    plugin.storage.write_json(
                        "observed-cancel.json", call.cancelled
                    )
                finally:
                    plugin.storage.write_json("stopped.json", True)

        async def reply(call, args):
            return CommandResult(
                "reply",
                Message("assistant", (ContentBlock(text="reply"),)),
            )

        plugin.register_command(CommandSpec("syncsend", reply))
        plugin.register_channel(
            ChannelSpec("sync-send", "Sync send", Transport)
        )


plugin = Plugin()
"""
    release = tmp_path / "release"
    async with PluginTestHost(tmp_path / "host") as host:
        ctx = await host.load(
            make_plugin(
                tmp_path,
                source,
                ["channels", "commands", "storage", "config"],
            ),
            config={"release": str(release)},
        )
        await host.start_channel("sync-send")
        workspace = await host._workspace("test")
        await host.receive_channel(
            "sync-send",
            ChannelMessage("sender", (ContentBlock(text="/syncsend"),)),
        )
        cancellation = None
        try:
            await wait_flag(ctx, "entered.json")
            runs = await workspace.task_tracker.list_active_tasks()
            assert len(runs) == 1
            cancellation = asyncio.create_task(
                workspace.task_tracker.request_stop(runs[0]),
            )
            done, _ = await asyncio.wait({cancellation}, timeout=WAIT_TIMEOUT)
            assert (
                cancellation in done
            ), "Synchronous sender never observed cancellation"
            assert await cancellation is True
            assert ctx.storage.read_json("observed-cancel.json") is True
            assert ctx.storage.read_json("stopped.json") is True
            assert not await workspace.task_tracker.has_active_tasks()
        finally:
            release.touch()
            if cancellation is not None:
                await asyncio.wait_for(cancellation, WAIT_TIMEOUT)
            await host.stop_channel("sync-send")


async def test_cancelled_channel_stream_emits_one_cancelled_terminal(tmp_path):
    from qwenpaw.plugins.channels import ChannelMessage
    from qwenpaw.plugins.messages import ContentBlock
    from qwenpaw.plugins.testing import PluginTestHost

    source = """
import asyncio
from qwenpaw.plugins.channels import ChannelSpec
from qwenpaw.plugins.providers import (
    ProviderSpec,
    ModelInfo,
    ModelChunk,
)
from qwenpaw.plugins.messages import ContentBlock


class Plugin:
    def register(self, plugin):
        class Transport:
            async def start(self, call):
                pass

            async def stop(self, call):
                return True

            async def send(self, call, message):
                pass

            async def on_stream(self, call, event):
                rows = plugin.storage.read_json("events.json", [])
                rows.append(
                    {
                        "phase": event.phase,
                        "status": event.event.status,
                    }
                )
                plugin.storage.write_json("events.json", rows)
                if event.phase == "delta":
                    plugin.storage.write_json("delta.json", True)

        async def generate(call, request):
            try:
                yield ModelChunk((ContentBlock(text="first"),))
                await asyncio.sleep(100)
            finally:
                plugin.storage.write_json(
                    "model-stopped.json", True
                )

        plugin.register_channel(
            ChannelSpec(
                "cancel-stream",
                "Cancel stream",
                Transport,
                streaming=True,
            )
        )
        plugin.register_provider(
            ProviderSpec(
                "cancel-provider",
                "Cancel provider",
                generate,
                models=(ModelInfo("cancel-model", "Cancel model"),),
                require_api_key=False,
            )
        )


plugin = Plugin()
"""
    async with PluginTestHost(tmp_path / "host") as host:
        ctx = await host.load(
            make_plugin(
                tmp_path,
                source,
                ["channels", "providers", "storage"],
            ),
        )
        await host.configure_chat_model("cancel-provider", "cancel-model")
        await host.start_channel("cancel-stream")
        workspace = await host._workspace("test")
        await host.receive_channel(
            "cancel-stream",
            ChannelMessage("sender", (ContentBlock(text="hello"),)),
        )
        try:
            await wait_flag(ctx, "delta.json")
            runs = await workspace.task_tracker.list_active_tasks()
            assert len(runs) == 1
            assert await workspace.task_tracker.request_stop(runs[0])
            assert ctx.storage.read_json("model-stopped.json") is True
            rows = ctx.storage.read_json("events.json")
            assert [row["phase"] for row in rows].count("end") == 1
            assert rows[-1] == {"phase": "end", "status": "cancelled"}
            assert not await workspace.task_tracker.has_active_tasks()
        finally:
            for run in await workspace.task_tracker.list_active_tasks():
                await workspace.task_tracker.request_stop(run)
            await host.stop_channel("cancel-stream")


async def test_old_queued_channel_payload_cannot_run_on_replacement_generation(
    tmp_path,
):
    from qwenpaw.plugins.channels import ChannelMessage
    from qwenpaw.plugins.messages import ContentBlock
    from qwenpaw.plugins.testing import PluginTestHost

    source = """
from qwenpaw.plugins.channels import ChannelSpec
from qwenpaw.plugins.commands import CommandSpec, CommandResult
from qwenpaw.plugins.messages import Message, ContentBlock


class Plugin:
    def register(self, plugin):
        class Transport:
            async def start(self, call):
                pass

            async def stop(self, call):
                return True

            async def send(self, call, message):
                rows = plugin.storage.read_json("sent.json", [])
                plugin.storage.write_json(
                    "sent.json",
                    rows
                    + [
                        "".join(
                            block.text for block in message.content
                        )
                    ],
                )

        async def reply(call, args):
            rows = plugin.storage.read_json("calls.json", [])
            plugin.storage.write_json("calls.json", rows + [args])
            return CommandResult(
                "reply",
                Message("assistant", (ContentBlock(text=args),)),
            )

        plugin.register_command(CommandSpec("queueprobe", reply))
        plugin.register_channel(
            ChannelSpec(
                "queued-channel", "Queued channel", Transport
            )
        )


plugin = Plugin()
"""
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(
            make_plugin(tmp_path, source, ["channels", "commands", "storage"]),
        )
        await host.start_channel("queued-channel")
        workspace = await host._workspace("test")
        manager = workspace.channel_manager
        gate = manager._queue_manager._lock
        await gate.acquire()
        try:
            await host.receive_channel(
                "queued-channel",
                ChannelMessage(
                    "sender",
                    (ContentBlock(text="/queueprobe stale"),),
                    session_id="one-queue",
                ),
            )
            async with asyncio.timeout(WAIT_TIMEOUT):
                while True:
                    if manager._enqueue_tasks:
                        break
                    await asyncio.sleep(0)
            assert manager._enqueue_tasks and all(
                not task.done() for task in manager._enqueue_tasks
            )
            assert (await host.reload("extension-contract")).ok
            await host.receive_channel(
                "queued-channel",
                ChannelMessage(
                    "sender",
                    (ContentBlock(text="/queueprobe fresh"),),
                    session_id="one-queue",
                ),
            )
            await asyncio.sleep(0)
        finally:
            gate.release()
        ctx = host.context("extension-contract")
        async with asyncio.timeout(WAIT_TIMEOUT):
            while True:
                if ctx.storage.read_json("sent.json", []):
                    break
                await asyncio.sleep(0.01)
        assert ctx.storage.read_json("calls.json") == ["fresh"]
        assert ctx.storage.read_json("sent.json") == ["fresh"]
        await host.stop_channel("queued-channel")


async def test_channel_uses_real_sender_access_policy_before_runtime(tmp_path):
    from pathlib import Path
    from qwenpaw.app.channels.access_control import get_access_control_store
    from .test_sdk_channel_contract import SOURCE, wait_sent
    from qwenpaw.plugins.channels import ChannelMessage
    from qwenpaw.plugins.messages import ContentBlock
    from qwenpaw.plugins.testing import PluginTestHost

    source = SOURCE.replace(
        (
            "plugin.storage.write_json(\n"
            '                f"called-{call.workspace_id}.json", args\n'
            "            )"
        ),
        (
            'plugin.storage.write_json("calls.json", '
            'plugin.storage.read_json("calls.json", []) + [args])'
        ),
    )
    async with PluginTestHost(tmp_path / "host") as host:
        ctx = await host.load(
            make_plugin(tmp_path, source, ["channels", "commands", "storage"]),
        )
        await host.start_channel(
            "sdk-contract-channel",
            {
                "token": "test-channel-token",
                "access_control_dm": True,
                "dm_policy": "allowlist",
                "allow_from": ["approved"],
            },
        )
        workspace = await host._workspace("test")
        store = get_access_control_store(Path(workspace.workspace_dir))
        store.add_to_whitelist("sdk-contract-channel", "approved")
        for sender, argument in (
            ("intruder", "blocked"),
            ("approved", "allowed"),
        ):
            await host.receive_channel(
                "sdk-contract-channel",
                ChannelMessage(
                    sender,
                    (ContentBlock(text="/channelprobe " + argument),),
                    session_id="policy-" + sender,
                    reply_to="target",
                ),
            )
        await wait_sent(ctx, "test")
        async with asyncio.timeout(WAIT_TIMEOUT):
            while True:
                if ctx.storage.read_json("calls.json", []):
                    break
                await asyncio.sleep(0.01)
        assert ctx.storage.read_json("calls.json") == ["allowed"]
        await host.stop_channel("sdk-contract-channel")


async def test_real_channel_manager_clone_keeps_only_current_owner(tmp_path):
    from .test_sdk_channel_contract import SOURCE, wait_sent
    from qwenpaw.plugins.channels import ChannelMessage
    from qwenpaw.plugins.messages import ContentBlock
    from qwenpaw.plugins.testing import PluginTestHost

    async with PluginTestHost(tmp_path / "host") as host:
        ctx = await host.load(
            make_plugin(tmp_path, SOURCE, ["channels", "commands", "storage"]),
        )
        await host.start_channel(
            "sdk-contract-channel",
            {"token": "test-channel-token"},
        )
        workspace = await host._workspace("test")
        for count in range(3):
            if count:
                result = await workspace.channel_manager.restart_channel(
                    "sdk-contract-channel",
                )
                assert result["status"] == "restarted"
            await host.receive_channel(
                "sdk-contract-channel",
                ChannelMessage(
                    "sender",
                    (ContentBlock(text=f"/channelprobe clone-{count}"),),
                    session_id=f"clone-{count}",
                ),
            )
            rows = await wait_sent(ctx, "test", count + 1)
            assert rows[-1]["text"] == f"test:clone-{count}"
        await host.stop_channel("sdk-contract-channel")
        host.assert_quiescent("extension-contract")
        assert (await host.reload("extension-contract")).ok


async def test_stop_waits_for_invocation_not_long_lived_queue_worker(
    tmp_path,
    monkeypatch,
):
    from .test_sdk_channel_contract import SOURCE
    from qwenpaw.plugins.channels import ChannelMessage
    from qwenpaw.plugins.messages import ContentBlock
    from qwenpaw.plugins.testing import PluginTestHost

    async with PluginTestHost(tmp_path / "host") as host:
        ctx = await host.load(
            make_plugin(tmp_path, SOURCE, ["channels", "commands", "storage"]),
        )
        await host.start_channel(
            "sdk-contract-channel",
            {"token": "test-channel-token"},
        )
        workspace = await host._workspace("test")
        tracker = workspace.task_tracker
        attach = tracker.attach_or_start
        waiting = asyncio.Event()
        release = asyncio.Event()
        workers = []

        async def attach_with_queue_gate(*args, **kwargs):
            queue, fresh = await attach(*args, **kwargs)
            get = queue.get

            async def gated_get():
                workers.append(asyncio.current_task())
                waiting.set()
                await release.wait()
                return await get()

            monkeypatch.setattr(queue, "get", gated_get)
            return queue, fresh

        monkeypatch.setattr(tracker, "attach_or_start", attach_with_queue_gate)
        await host.receive_channel(
            "sdk-contract-channel",
            ChannelMessage(
                "sender",
                (ContentBlock(text="/channelprobe pending"),),
            ),
        )
        await asyncio.wait_for(waiting.wait(), WAIT_TIMEOUT)
        try:
            await asyncio.wait_for(
                host.stop_channel("sdk-contract-channel"),
                10,
            )
            assert ctx.storage.read_json("stopped-test.json", False)
            host.assert_quiescent("extension-contract")
            # Host queue workers can survive a completed plugin invocation.
            assert workers and all(not worker.done() for worker in workers)
            assert all(worker.cancelling() == 0 for worker in workers)
            assert (await host.reload("extension-contract")).ok
            # A new generation reuses the same manager queue/session safely.
            monkeypatch.setattr(tracker, "attach_or_start", attach)
            await host.start_channel(
                "sdk-contract-channel",
                {"token": "test-channel-token"},
            )
            await host.receive_channel(
                "sdk-contract-channel",
                ChannelMessage(
                    "sender",
                    (ContentBlock(text="/channelprobe replacement"),),
                ),
            )
            current = host.context("extension-contract")
            async with asyncio.timeout(WAIT_TIMEOUT):
                while True:
                    rows = current.storage.read_json("sent-test.json", [])
                    if rows and rows[-1]["text"] == "test:replacement":
                        break
                    await asyncio.sleep(0.01)
            assert rows[-1]["text"] == "test:replacement"
            assert (
                current.storage.read_json("called-test.json") == "replacement"
            )
            await host.stop_channel("sdk-contract-channel")
        finally:
            release.set()
