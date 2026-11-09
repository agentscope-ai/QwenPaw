# -*- coding: utf-8 -*-
"""Opt-in SDK dispatch and pre-import compatibility contracts."""

import json

import pytest

from qwenpaw.plugins import PluginApi, PluginLoader, PluginManifest


def write_plugin(root, source, **manifest_fields):
    root.mkdir(parents=True)
    manifest = {
        "id": root.name,
        "version": "1.0.0",
        "entry": {"backend": "main.py"},
        **manifest_fields,
    }
    (root / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
    (root / "main.py").write_text(source, encoding="utf-8")
    return PluginManifest.from_dict(manifest)


@pytest.fixture(name="loader")
def plugin_loader(tmp_path, monkeypatch, fresh_registry):
    work = tmp_path / "work"
    monkeypatch.setenv("QWENPAW_WORKING_DIR", str(work))
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", work)
    monkeypatch.setattr("qwenpaw.config.utils.WORKING_DIR", work)
    result = PluginLoader(plugin_dirs=[tmp_path / "plugins"])
    result.registry = fresh_registry
    return result


@pytest.mark.parametrize(
    "version_fields",
    [
        {},
        {"min_version": "0.1.0", "max_version": "0.2.0"},
        {"qwenpaw_version": {"min": "0.1.0", "max": "0.2.0"}},
    ],
)
async def test_undeclared_plugin_keeps_original_api_and_version_policy(
    tmp_path,
    loader,
    version_fields,
):
    root = tmp_path / "plugins" / "legacy-sdk-contract"
    manifest = write_plugin(
        root,
        "class Plugin:\n"
        "    def register(self, api):\n"
        "        self.api = api\n"
        "plugin = Plugin()\n",
        **version_fields,
    )
    record = await loader.load_plugin(manifest, root, {"value": 3})
    try:
        assert record.status == "active"
        assert type(record.instance.api) is PluginApi
        assert record.instance.api.config == {"value": 3}
    finally:
        await loader.unload_plugin(manifest.id)


@pytest.mark.parametrize(
    "sdk",
    [
        {"version": "999.0", "capabilities": []},
        {"version": "1.0", "capabilities": ["unknown-contract-capability"]},
    ],
)
async def test_incompatible_sdk_rejected_before_module_execution(
    tmp_path,
    loader,
    sdk,
):
    from qwenpaw.plugins import SDKCompatibilityError

    marker = tmp_path / "module-was-executed"
    root = tmp_path / "plugins" / "incompatible-sdk-contract"
    manifest = write_plugin(
        root,
        f"from pathlib import Path\nPath({str(marker)!r}).touch()\n"
        "class Plugin:\n"
        "    def register(self, ctx):\n"
        "        pass\n"
        "plugin = Plugin()\n",
        sdk=sdk,
    )
    with pytest.raises(SDKCompatibilityError):
        await loader.load_plugin(manifest, root, {})
    assert not marker.exists(), "SDK preflight must precede module execution"
    assert loader.get_loaded_plugin(manifest.id) is None


async def test_incompatible_reload_does_not_probe_or_stop_old_plugin(
    tmp_path,
    loader,
):
    root = tmp_path / "plugins" / "sdk-reload-contract"
    stopped = tmp_path / "stopped"
    manifest = write_plugin(
        root,
        "class Plugin:\n"
        "    def register(self, api):\n"
        "        self.value = 'old'\n"
        "        api.register_shutdown_hook('stop', "
        f"lambda: open({str(stopped)!r}, 'w').close())\n"
        "plugin = Plugin()\n",
    )
    old = await loader.load_plugin(manifest, root, {})
    marker = tmp_path / "incoming-probed"
    incoming = tmp_path / "incoming" / manifest.id
    write_plugin(
        incoming,
        f"from pathlib import Path\nPath({str(marker)!r}).touch()\n"
        "class Plugin:\n"
        "    def register(self, ctx):\n"
        "        pass\n"
        "plugin = Plugin()\n",
        sdk={"version": "999.0"},
    )
    try:
        report = await loader.lifecycle.reload(
            manifest.id,
            new_source=incoming,
        )
        assert not report.ok and report.unchanged
        assert (
            not marker.exists()
        ), "An incompatible candidate must not be probed"
        assert (
            not stopped.exists()
        ), "Compatibility rejection must precede teardown"
        assert loader.get_loaded_plugin(manifest.id) is old
        assert old.status == "active" and old.instance.value == "old"
    finally:
        await loader.unload_plugin(manifest.id)


@pytest.mark.parametrize(
    "plugin_id",
    ["../other", "/absolute", "a/../../other"],
)
async def test_sdk_identity_cannot_escape_owned_storage_roots(
    tmp_path,
    loader,
    plugin_id,
):
    from qwenpaw.plugins import SDKError

    marker = tmp_path / "unsafe-id-executed"
    root = tmp_path / "plugins" / "unsafe-sdk-identity"
    manifest = write_plugin(
        root,
        f"from pathlib import Path\nPath({str(marker)!r}).touch()\n"
        "class Plugin:\n"
        "    def register(self, ctx):\n"
        "        ctx.storage.write_json('proof.json', {'escaped': True})\n"
        "plugin = Plugin()\n",
        id=plugin_id,
        sdk={"version": "1.0", "capabilities": ["storage"]},
    )
    with pytest.raises(SDKError):
        await loader.load_plugin(manifest, root, {})
    assert not marker.exists()
