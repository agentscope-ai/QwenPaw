# -*- coding: utf-8 -*-
"""Controlled commands bypass the busy ordinary queue, using its real owner."""

import json
import pytest

from qwenpaw.plugins.errors import SDKError
from qwenpaw.plugins.testing import PluginTestHost
from .sdk_author_fixture import make_plugin
from .test_sdk_channel_routing_contract import (
    SOURCE,
    CHANNEL,
    incoming,
    wait_for,
)

DECLARATION = """
        from qwenpaw.plugins.commands import CommandSpec, CommandResult
        from qwenpaw.plugins.messages import Message
        async def command(call, args):
            plugin.storage.write_json('control.json', {
                'argument': args,
                'user': call.identity.user_id,
                'channel': call.identity.channel,
            })
            return CommandResult('reply', Message('assistant', (ContentBlock(text='control:' + args),)))
        plugin.register_command(CommandSpec('sdkcontrol', command, aliases=('sc',), control=True))
        plugin.register_command(CommandSpec('normalcommand', command))
"""


async def test_control_uses_live_declaration_and_runs_while_model_busy(
    tmp_path,
):
    async with PluginTestHost(tmp_path / "host") as host:
        source = make_plugin(
            tmp_path,
            SOURCE.replace(
                "        callback_lock =",
                DECLARATION + "        callback_lock =",
            ),
            ["channels", "providers", "storage", "commands"],
        )
        manifest = json.loads((source / "plugin.json").read_text())
        manifest["sdk"]["version"] = "1.2.0"
        (source / "plugin.json").write_text(json.dumps(manifest))
        assert (await host.install(source)).ok
        ctx = host.context("extension-contract")
        await host.configure_chat_model("routing-provider", "routing-model")
        await host.start_channel(CHANNEL, {})
        manager = (await host._workspace("test")).channel_manager
        assert manager.is_control_command("/sc immediate")
        assert not manager.is_control_command("/sc-other")
        with pytest.raises(SDKError, match="Not a registered"):
            await host.call_control_command("/normalcommand wrong")
        result = await host.call_control_command(
            "/sc helper",
            user_id="helper-user",
        )
        assert result.content[0].text == "control:helper"
        assert ctx.storage.read_json("control.json")["user"] == "helper-user"
        await host.receive_channel(CHANNEL, incoming("hold-first", "one"))
        await wait_for(lambda: bool(ctx.storage.read_json("model.json", [])))
        try:
            await host.receive_channel(
                CHANNEL,
                incoming("/sc immediate", "two"),
            )
            await wait_for(
                lambda: ctx.storage.read_json("control.json").get("argument")
                == "immediate",
            )
            assert not ctx.storage.read_json("model-finished.json", [])
            assert len(ctx.storage.read_json("model.json", [])) == 1
            assert ctx.storage.read_json("control.json")["channel"] == CHANNEL
        finally:
            ctx.storage.write_json("release.json", True)
        await wait_for(
            lambda: bool(ctx.storage.read_json("model-finished.json", [])),
        )
        await host.stop_channel(CHANNEL)
        assert (await host.update_config("extension-contract", {})).ok
        assert (await host.reload("extension-contract")).ok
        assert manager.is_control_command("/sc immediate")
        assert (await host.set_enabled("extension-contract", False)).ok
        assert not manager.is_control_command("/sc immediate")
        assert (await host.set_enabled("extension-contract", True)).ok
        assert manager.is_control_command("/sc immediate")
        assert (await host.uninstall("extension-contract")).clean
        assert not manager.is_control_command("/sc immediate")


async def test_control_cannot_continue_into_model_turn(sdk_component):
    from qwenpaw.plugins.commands import CommandSpec, CommandResult

    def declare(ctx):
        ctx.register_command(
            CommandSpec(
                "invalidcontrol",
                lambda call, args: CommandResult(),
                control=True,
            ),
        )

    async with sdk_component(declare, capabilities=("commands",)) as (host, _):
        with pytest.raises(SDKError, match="must reply"):
            await host.call_control_command("/invalidcontrol")
