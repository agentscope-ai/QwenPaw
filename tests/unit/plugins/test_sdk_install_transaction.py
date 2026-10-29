# -*- coding: utf-8 -*-
"""SDK opt-in packages use real install/update/recovery transactions."""

import json

import pytest

from .sdk_author_fixture import make_plugin

SOURCE = """
from qwenpaw.plugins.tools import ToolSpec, ToolResult


class Plugin:
    def register(self, plugin):
        async def tool(call, args):
            count = plugin.storage.read_json("count.json", 0) + 1
            plugin.storage.write_json("count.json", count)
            return ToolResult.text(
                "__VERSION__:"
                + plugin.config.get("label", "")
                + ":"
                + str(count)
            )

        plugin.register_tool(
            ToolSpec(
                "transaction_tool",
                "Transaction probe",
                {"type": "object"},
                tool,
                enabled=True,
            )
        )


plugin = Plugin()
"""


def package(tmp_path, version):
    root = tmp_path / version
    root.mkdir()
    plugin = make_plugin(
        root,
        SOURCE.replace("__VERSION__", version),
        ["tools", "storage", "config"],
    )
    manifest = json.loads((plugin / "plugin.json").read_text())
    manifest["version"] = version
    (plugin / "plugin.json").write_text(json.dumps(manifest))
    return plugin


async def text_result(host):
    return (await host.call_tool("transaction_tool", {})).content[0].text


async def test_install_config_disable_upgrade_uninstall_preserves_user_data(
    tmp_path,
):
    from qwenpaw.plugins import SDKError
    from qwenpaw.plugins.testing import PluginTestHost

    one, two = package(tmp_path, "1.0.0"), package(tmp_path, "2.0.0")
    root = tmp_path / "host"
    async with PluginTestHost(root) as host:
        assert (await host.install(one, config={"label": "initial"})).ok
        assert await text_result(host) == "1.0.0:initial:1"
        assert (
            await host.update_config(
                "extension-contract",
                {"label": "updated"},
            )
        ).ok
        assert (await host.set_enabled("extension-contract", False)).ok
        with pytest.raises(SDKError):
            await host.call_tool("transaction_tool", {})
        assert (await host.set_enabled("extension-contract", True)).ok
        assert await text_result(host) == "1.0.0:updated:2"
        upgraded = await host.install(two, replace=True)
        assert upgraded.ok and upgraded.version == "2.0.0"
        assert await text_result(host) == "2.0.0:updated:3"
        assert (
            json.loads(
                (root / "plugins/extension-contract/plugin.json").read_text(),
            )["version"]
            == "2.0.0"
        )
        result = await host.uninstall("extension-contract")
        assert result.clean and result.quiescent and not result.needs_restart
        assert not (root / "plugins/extension-contract").exists()
        assert (
            json.loads(
                (
                    root / "plugin-data/extension-contract/count.json"
                ).read_text(),
            )
            == 3
        )


@pytest.mark.parametrize("point", ["before_commit", "post_commit_cleanup"])
async def test_sdk_transaction_commit_boundary_retains_correct_code_and_data(
    tmp_path,
    point,
):
    from qwenpaw.plugins import SDKError
    from qwenpaw.plugins.testing import PluginTestHost

    one, two = package(tmp_path, "1.0.0"), package(tmp_path, "2.0.0")
    root = tmp_path / "host"
    async with PluginTestHost(root) as host:
        await host.install(one, config={"label": "persist"})
        assert await text_result(host) == "1.0.0:persist:1"
        with host.inject_failure(point) as fault:
            if point == "before_commit":
                with pytest.raises(SDKError):
                    await host.install(two, replace=True)
            else:
                result = await host.install(two, replace=True)
                assert result.ok and result.errors
        assert fault.hits == 1
        expected = "1.0.0" if point == "before_commit" else "2.0.0"
        assert (
            json.loads(
                (root / "plugins/extension-contract/plugin.json").read_text(),
            )["version"]
            == expected
        )
        assert await text_result(host) == expected + ":persist:2"
        assert (await host.reload("extension-contract")).ok
        assert await text_result(host) == expected + ":persist:3"


async def test_sdk_busy_stream_in_other_workspace_prevents_install_commit(
    tmp_path,
):
    import asyncio
    from qwenpaw.plugins import PluginBusyError
    from qwenpaw.plugins.testing import PluginTestHost

    one, two = package(tmp_path, "1.0.0"), package(tmp_path, "2.0.0")
    (one / "main.py").write_text(
        """
import asyncio
from qwenpaw.plugins.tools import ToolSpec, ToolEvent, ToolResult
from qwenpaw.plugins.messages import ContentBlock


class Plugin:
    def register(self, ctx):
        async def tool(call, args):
            try:
                yield ToolEvent(
                    "delta",
                    (
                        ContentBlock(
                            text="old:" + call.workspace_id
                        ),
                    ),
                )
                await asyncio.sleep(100)
            finally:
                ctx.storage.write_json("closed.json", True)

        ctx.register_tool(
            ToolSpec(
                "transaction_tool",
                "Busy",
                {"type": "object"},
                tool,
                enabled=True,
            )
        )


plugin = Plugin()
""",
    )
    root = tmp_path / "host"
    async with PluginTestHost(root) as host:
        await host.install(one)
        old = host.context("extension-contract")
        stream = host.stream_tool(
            "transaction_tool",
            {},
            workspace_id="other-workspace",
        )
        assert (await asyncio.create_task(anext(stream))).content[
            0
        ].text == "old:other-workspace"
        try:
            with pytest.raises(PluginBusyError):
                await host.install(two, replace=True)
            assert (
                json.loads(
                    (
                        root / "plugins/extension-contract/plugin.json"
                    ).read_text(),
                )["version"]
                == "1.0.0"
            )
            assert not old.storage.read_json("closed.json", False)
        finally:
            await stream.aclose()
        assert old.storage.read_json("closed.json") is True
        assert (await host.install(two, replace=True)).ok
        assert await text_result(host) == "2.0.0::1"


async def test_sdk_upgrade_partial_activation_stops_new_task_and_restores_old(
    tmp_path,
):
    from qwenpaw.plugins import SDKError
    from qwenpaw.plugins.testing import PluginTestHost

    one, two = package(tmp_path, "1.0.0"), package(tmp_path, "2.0.0")
    marker = tmp_path / "new-task-stopped"
    entry = two / "main.py"
    entry.write_text(
        """
import asyncio
from pathlib import Path
class Plugin:
    def register(self, plugin):
        async def activate(ctx):
            async def worker():
                try:
                    await asyncio.sleep(100)
                finally:
                    Path(__MARKER__).touch()
            ctx.resources.task(worker(), description="partial-new-start")
            await asyncio.sleep(0)
            raise RuntimeError("partial new activation failed")
        plugin.on_activate(activate)
plugin = Plugin()
""".replace(
            "__MARKER__",
            repr(str(marker)),
        ),
    )
    manifest = json.loads((two / "plugin.json").read_text())
    manifest["sdk"]["capabilities"].append("resources")
    (two / "plugin.json").write_text(json.dumps(manifest))
    root = tmp_path / "host"
    async with PluginTestHost(root) as host:
        await host.install(one, config={"label": "original"})
        assert await text_result(host) == "1.0.0:original:1"
        with pytest.raises(SDKError):
            await host.install(two, replace=True)
        assert (
            marker.exists()
        ), "Partially started new generation kept its task alive"
        assert await text_result(host) == "1.0.0:original:2"
        assert (
            json.loads(
                (root / "plugins/extension-contract/plugin.json").read_text(),
            )["version"]
            == "1.0.0"
        )
        assert (await host.reload("extension-contract")).ok
