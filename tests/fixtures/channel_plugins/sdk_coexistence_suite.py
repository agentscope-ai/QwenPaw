"""SDK opt-in must not change undeclared descriptor or Python dispatch."""

import asyncio
import json

import pytest

from catalog_suite import candidate


@pytest.mark.asyncio
async def test_sdk_tool_and_undeclared_plugins_keep_independent_dispatch(
    tmp_path, monkeypatch
):
    from qwenpaw.plugins import PluginApi, PluginContext, PluginManifest
    from qwenpaw.plugins.testing import PluginTestHost

    descriptor_root, descriptor_manifest = candidate(tmp_path / "native")
    roots = {}
    for plugin_id, sdk, body in (
        (
            "sdk-coexistence",
            {"version": "1.0", "capabilities": ["tools"]},
            "from qwenpaw.plugins.tools import ToolResult, ToolSpec\n"
            "class Plugin:\n"
            "    def register(self, ctx):\n"
            "        self.api = ctx\n"
            "        async def echo(call, args):\n"
            "            return ToolResult.text(args['text'])\n"
            "        ctx.register_tool(ToolSpec('coexistence_echo', 'Echo', "
            "{'type': 'object'}, echo, enabled=True))\n"
            "plugin = Plugin()\n",
        ),
        (
            "legacy-coexistence",
            None,
            "class Plugin:\n"
            "    def register(self, api):\n"
            "        self.api = api\n"
            "plugin = Plugin()\n",
        ),
    ):
        root = tmp_path / plugin_id
        root.mkdir()
        manifest = {
            "id": plugin_id,
            "version": "1.0.0",
            "entry": {"backend": "main.py"},
        }
        if sdk is not None:
            manifest["sdk"] = sdk
        (root / "plugin.json").write_text(json.dumps(manifest))
        (root / "main.py").write_text(body)
        roots[plugin_id] = (root, PluginManifest.from_dict(manifest))

    async def no_process(*_args, **_kwargs):
        raise AssertionError("Static descriptor discovery spawned a worker")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", no_process)
    async with PluginTestHost(tmp_path / "host") as host:
        loader = host._loader
        descriptor = await loader.load_plugin(
            descriptor_manifest, descriptor_root, activate=False
        )
        ctx = await host.load(roots["sdk-coexistence"][0])
        legacy_root, legacy_manifest = roots["legacy-coexistence"]
        legacy = await loader.load_plugin(legacy_manifest, legacy_root)

        assert isinstance(ctx, PluginContext)
        assert type(legacy.instance.api) is PluginApi
        assert legacy.status == "active"
        assert descriptor.status == "catalogued" and not descriptor.enabled
        row = loader.registry.get_channel_catalog_entry("feishu")
        assert row is not None and row.plugin_id == "feishu"
        assert loader.registry.get_registered_channels() == {}
        result = await host.call_tool(
            "coexistence_echo", {"text": "both alive"}
        )
        assert [(part.type, part.text) for part in result.content] == [
            ("text", "both alive")
        ]

        report = await loader.unload_plugin("feishu")
        assert report.clean and report.quiescent
        assert loader.registry.get_channel_catalog_entry("feishu") is None
        assert loader.get_loaded_plugin("legacy-coexistence") is legacy
        result = await host.call_tool(
            "coexistence_echo", {"text": "sdk retained"}
        )
        assert result.content[0].text == "sdk retained"
