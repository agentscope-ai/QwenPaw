# -*- coding: utf-8 -*-
"""Synthetic transport via real ChannelManager/ACL/Runtime, no external sends.
"""

import asyncio

import pytest

from .sdk_author_fixture import make_plugin

SOURCE = """
from pathlib import Path
from qwenpaw.plugins.channels import ChannelSpec
from qwenpaw.plugins.commands import CommandSpec, CommandResult
from qwenpaw.plugins.messages import ContentBlock, Message


class Plugin:
    def register(self, plugin):
        class Transport:
            async def start(self, call):
                assert not hasattr(
                    call, "workspace"
                ) and not hasattr(call, "agent")
                assert (
                    call.config.secret("token")
                    == "test-channel-token"
                )
                plugin.storage.write_json(
                    f"started-{call.workspace_id}.json", True
                )

            async def stop(self, call):
                directory = call.config.get("directory")
                if (
                    directory
                    and not (
                        Path(directory) / "channel-stop-allowed"
                    ).exists()
                ):
                    return False
                plugin.storage.write_json(
                    f"stopped-{call.workspace_id}.json", True
                )
                return True

            async def send(self, call, message):
                key = f"sent-{call.workspace_id}.json"
                rows = plugin.storage.read_json(key, [])
                rows.append(
                    {
                        "target": message.target,
                        "text": "".join(
                            block.text for block in message.content
                        ),
                    }
                )
                plugin.storage.write_json(key, rows)

        async def reply(call, args):
            plugin.storage.write_json(
                f"called-{call.workspace_id}.json", args
            )
            return CommandResult(
                "reply",
                Message(
                    "assistant",
                    (
                        ContentBlock(
                            text=call.workspace_id + ":" + args
                        ),
                    ),
                ),
            )

        plugin.register_command(CommandSpec("channelprobe", reply))
        plugin.register_channel(
            ChannelSpec(
                "sdk-contract-channel",
                "Test transport",
                Transport,
                config_fields=(
                    {
                        "name": "token",
                        "type": "password",
                        "label": "Token",
                    },
                    {
                        "name": "directory",
                        "type": "text",
                        "label": "Directory",
                    },
                ),
            )
        )


plugin = Plugin()
"""


async def wait_sent(ctx, workspace, minimum=1):
    for _ in range(150):
        rows = ctx.storage.read_json(f"sent-{workspace}.json", [])
        if len(rows) >= minimum:
            return rows
        await asyncio.sleep(0.01)
    pytest.fail(f"Channel {workspace} did not send {minimum} messages")


async def test_channel_start_none_restores_persisted_settings_but_empty_resets(
    tmp_path,
):
    from qwenpaw.plugins.testing import PluginTestHost

    source = """
from qwenpaw.plugins.channels import ChannelSpec


class Plugin:
    def register(self, plugin):
        class Transport:
            async def start(self, call):
                plugin.storage.write_json(
                    "settings.json",
                    {
                        "label": call.config.get("label"),
                        "token": call.config.secret("token"),
                    },
                )

            async def stop(self, call):
                return True

            async def send(self, call, message):
                pass

        plugin.register_channel(
            ChannelSpec(
                "persisted-channel",
                "Persisted",
                Transport,
                config_fields=(
                    {
                        "name": "label",
                        "type": "text",
                        "label": "Label",
                    },
                    {
                        "name": "token",
                        "type": "password",
                        "label": "Token",
                    },
                ),
            )
        )


plugin = Plugin()
"""
    package = make_plugin(tmp_path, source, ["channels", "storage"])
    root = tmp_path / "host"
    expected = {"label": "persisted-value", "token": "synthetic-secret"}
    async with PluginTestHost(root) as host:
        await host.install(package)
        await host.start_channel("persisted-channel", expected)
        assert (
            host.context("extension-contract").storage.read_json(
                "settings.json",
            )
            == expected
        )
    async with PluginTestHost(root) as host:
        ctx = await host.load(root / "plugins/extension-contract")
        await host.start_channel("persisted-channel")
        assert ctx.storage.read_json("settings.json") == expected
        await host.stop_channel("persisted-channel")
        await host.start_channel("persisted-channel", {})
        assert ctx.storage.read_json("settings.json") == {
            "label": None,
            "token": None,
        }


async def test_channel_real_queue_reply_target_and_workspace_isolation(
    tmp_path,
):
    from qwenpaw.plugins.channels import ChannelMessage
    from qwenpaw.plugins.messages import ContentBlock
    from qwenpaw.plugins.testing import PluginTestHost

    async with PluginTestHost(tmp_path / "host") as host:
        ctx = await host.load(
            make_plugin(tmp_path, SOURCE, ["channels", "commands", "storage"]),
        )
        for workspace in ("one", "two"):
            await host.start_channel(
                "sdk-contract-channel",
                {"token": "test-channel-token"},
                workspace_id=workspace,
            )
            await host.receive_channel(
                "sdk-contract-channel",
                ChannelMessage(
                    "sender",
                    (ContentBlock(text="/channelprobe hello"),),
                    session_id="same-session",
                    reply_to="target-" + workspace,
                ),
                workspace_id=workspace,
            )
        for workspace in ("one", "two"):
            rows = await wait_sent(ctx, workspace)
            assert rows == [
                {
                    "target": "target-" + workspace,
                    "text": workspace + ":hello",
                },
            ]
        await host.stop_channel("sdk-contract-channel", workspace_id="one")
        assert ctx.storage.read_json("stopped-one.json") is True
        await host.receive_channel(
            "sdk-contract-channel",
            ChannelMessage(
                "sender",
                (ContentBlock(text="/channelprobe again"),),
                reply_to="target-two",
            ),
            workspace_id="two",
        )
        rows = await wait_sent(ctx, "two", 2)
        assert rows[-1]["text"] == "two:again"
        await host.stop_channel("sdk-contract-channel", workspace_id="two")


async def test_channel_failed_stop_keeps_owner_until_real_stop(tmp_path):
    from qwenpaw.plugins import SDKError
    from qwenpaw.plugins.testing import PluginTestHost

    async with PluginTestHost(tmp_path / "host") as host:
        ctx = await host.load(
            make_plugin(tmp_path, SOURCE, ["channels", "commands", "storage"]),
        )
        await host.start_channel(
            "sdk-contract-channel",
            {"token": "test-channel-token", "directory": str(tmp_path)},
        )
        try:
            with pytest.raises(SDKError):
                await host.stop_channel("sdk-contract-channel")
            result = await host.reload("extension-contract")
            assert not result.ok and result.errors
            assert ctx.storage.read_json("stopped-test.json", False) is False
        finally:
            (tmp_path / "channel-stop-allowed").touch()
            await host.stop_channel("sdk-contract-channel")
        assert ctx.storage.read_json("stopped-test.json") is True
        assert (await host.reload("extension-contract")).ok


async def test_sdk_channel_cannot_replace_builtin_dingtalk(tmp_path):
    from qwenpaw.plugins import SDKError
    from qwenpaw.plugins.testing import PluginTestHost

    source = SOURCE.replace('"sdk-contract-channel"', '"dingtalk"')
    async with PluginTestHost(tmp_path / "host") as host:
        with pytest.raises(SDKError, match="built-in"):
            await host.load(
                make_plugin(
                    tmp_path,
                    source,
                    ["channels", "commands", "storage"],
                ),
            )


async def test_channel_streaming_real_model_preserves_metadata_and_terminal(
    tmp_path,
):
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
                raise AssertionError(
                    "Streaming transport must receive stream callbacks"
                )

            async def on_stream(self, call, event):
                assert not any(
                    key.startswith("_") for key in event.metadata
                )
                rows = plugin.storage.read_json("stream.json", [])
                rows.append(
                    {
                        "phase": event.phase,
                        "text": event.text,
                        "status": event.event.status,
                        "target": event.target,
                        "metadata": dict(event.metadata),
                    }
                )
                plugin.storage.write_json("stream.json", rows)

        async def generate(call, request):
            yield ModelChunk(
                (ContentBlock(text="first"),), id="channel-answer"
            )
            await asyncio.sleep(0.2)
            yield ModelChunk(
                (ContentBlock(text=" second"),),
                id="channel-answer",
                is_last=True,
            )

        plugin.register_channel(
            ChannelSpec(
                "stream-contract",
                "Streaming contract",
                Transport,
                streaming=True,
            )
        )
        plugin.register_provider(
            ProviderSpec(
                "channel-provider",
                "Channel model",
                generate,
                models=(
                    ModelInfo("channel-model", "Channel model"),
                ),
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
        await host.configure_chat_model("channel-provider", "channel-model")
        await host.start_channel("stream-contract")
        await host.receive_channel(
            "stream-contract",
            ChannelMessage(
                "sender",
                (ContentBlock(text="hello"),),
                reply_to="original-target",
                metadata={"session_webhook": "https://example.test/reply"},
            ),
        )
        for _ in range(400):
            rows = ctx.storage.read_json("stream.json", [])
            if any(row["phase"] == "end" for row in rows):
                break
            await asyncio.sleep(0.01)
        assert rows[0]["phase"] == "start"
        assert any(row["phase"] == "delta" for row in rows)
        assert [row["phase"] for row in rows].count("end") == 1
        assert rows[-1]["phase"] == "end" and rows[-1]["status"] == "completed"
        assert rows[-1]["text"] == "first second"
        assert all(row["target"] == "original-target" for row in rows)
        assert all(
            row["metadata"]["session_webhook"] == "https://example.test/reply"
            for row in rows
        )
        await host.stop_channel("stream-contract")


async def test_channel_partial_start_failure_releases_owned_task(tmp_path):
    from qwenpaw.plugins import SDKError
    from qwenpaw.plugins.testing import PluginTestHost

    source = """
import asyncio
from pathlib import Path
from qwenpaw.plugins.channels import ChannelSpec


class Plugin:
    def register(self, plugin):
        class Transport:
            async def start(self, call):
                async def worker():
                    try:
                        await asyncio.sleep(100)
                    finally:
                        (
                            Path(plugin.config.get("directory"))
                            / "worker-stopped"
                        ).touch()

                call.resources.task(
                    worker(), description="channel-partial-worker"
                )
                await asyncio.sleep(0)
                raise RuntimeError("partial channel activation")

            async def stop(self, call):
                (
                    Path(plugin.config.get("directory"))
                    / "backend-stopped"
                ).touch()
                return True

            async def send(self, call, message):
                pass

        plugin.register_channel(
            ChannelSpec(
                "partial-channel", "Partial channel", Transport
            )
        )


plugin = Plugin()
"""
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(
            make_plugin(tmp_path, source, ["channels", "resources", "config"]),
            config={"directory": str(tmp_path)},
        )
        with pytest.raises(SDKError):
            await host.start_channel("partial-channel")
        assert (tmp_path / "backend-stopped").exists()
        assert (tmp_path / "worker-stopped").exists()
        host.assert_quiescent("extension-contract")
        with pytest.raises(SDKError, match="not running"):
            await host.stop_channel("partial-channel")


@pytest.mark.parametrize("stop_fails_once", [False, True])
async def test_stop_during_send_finishes_call_before_backend_stop(
    tmp_path,
    stop_fails_once,
):
    from qwenpaw.plugins import SDKError
    from qwenpaw.plugins.channels import ChannelMessage
    from qwenpaw.plugins.messages import ContentBlock
    from qwenpaw.plugins.testing import PluginTestHost

    source = """
import asyncio
from qwenpaw.plugins.channels import ChannelSpec
from qwenpaw.plugins.commands import CommandSpec, CommandResult
from qwenpaw.plugins.messages import ContentBlock, Message


class Plugin:
    def register(self, plugin):
        class Transport:
            async def start(self, call):
                pass

            async def send(self, call, message):
                plugin.storage.write_json("sending.json", True)
                try:
                    await asyncio.Event().wait()
                finally:
                    plugin.storage.write_json(
                        "send-finished.json", True
                    )

            async def stop(self, call):
                plugin.storage.write_json(
                    "stop-observed-finished.json",
                    plugin.storage.read_json(
                        "send-finished.json", False
                    ),
                )
                return plugin.storage.read_json(
                    "allow-stop.json", False
                )

        async def reply(call, args):
            return CommandResult(
                "reply",
                Message(
                    "assistant", (ContentBlock(text="answer"),)
                ),
            )

        plugin.register_command(CommandSpec("sendgate", reply))
        plugin.register_channel(
            ChannelSpec("send-gate", "Send gate", Transport)
        )


plugin = Plugin()
"""
    async with PluginTestHost(tmp_path / "host") as host:
        ctx = await host.load(
            make_plugin(tmp_path, source, ["channels", "commands", "storage"]),
        )
        ctx.storage.write_json("allow-stop.json", not stop_fails_once)
        await host.start_channel("send-gate")
        await host.receive_channel(
            "send-gate",
            ChannelMessage("sender", (ContentBlock(text="/sendgate"),)),
        )
        for _ in range(200):
            if ctx.storage.read_json("sending.json", False):
                break
            await asyncio.sleep(0.01)
        assert ctx.storage.read_json("sending.json", False)
        try:
            if stop_fails_once:
                with pytest.raises(SDKError):
                    await asyncio.wait_for(host.stop_channel("send-gate"), 10)
                result = await host.reload("extension-contract")
                assert not result.ok and result.errors
                assert host.context("extension-contract") is ctx
                ctx.storage.write_json("allow-stop.json", True)
            await asyncio.wait_for(host.stop_channel("send-gate"), 10)
            assert ctx.storage.read_json("send-finished.json", False)
            assert ctx.storage.read_json("stop-observed-finished.json", False)
            assert (await host.reload("extension-contract")).ok
        finally:
            if host.context("extension-contract") is ctx:
                ctx.storage.write_json("allow-stop.json", True)
                await host.stop_channel("send-gate")
