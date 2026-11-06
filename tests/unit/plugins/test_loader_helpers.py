# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name,unnecessary-lambda,unused-argument  # noqa: E501
"""Unit tests for plugins/loader.py helper functions.

Coverage-driven backfill (batch 4, coverage-first per the 2026-08-24
instruction: upstream PRs are only considered after backend_unit coverage
rises by at least 5 percentage points). Target: the plugin loader path /
runtime-dir helpers which previously sat at ~53% coverage.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

import qwenpaw.plugins.loader as pl

from .timing import WAIT_TIMEOUT


@pytest.fixture()
def working_dir(tmp_path, monkeypatch):
    wd = tmp_path / "wd"
    wd.mkdir()
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", wd)
    return wd


class TestDesktopPython:
    def test_unset_returns_none(self, monkeypatch):
        monkeypatch.delenv("QWENPAW_DESKTOP_PY_RUNTIME", raising=False)
        assert pl._desktop_python() is None

    def test_blank_returns_none(self, monkeypatch):
        monkeypatch.setenv("QWENPAW_DESKTOP_PY_RUNTIME", "   ")
        assert pl._desktop_python() is None

    def test_missing_file_returns_none(self, monkeypatch):
        monkeypatch.setenv("QWENPAW_DESKTOP_PY_RUNTIME", "/no/such/python")
        assert pl._desktop_python() is None

    def test_existing_file_returned(self, tmp_path, monkeypatch):
        py = tmp_path / "python"
        py.write_text("")
        monkeypatch.setenv("QWENPAW_DESKTOP_PY_RUNTIME", str(py))
        assert pl._desktop_python() == str(py)


class TestPluginRuntimeDirs:
    def test_site_dir_bucketed_without_creating_environment(self, working_dir):
        site = pl._plugin_site_dir()
        assert not site.exists()
        assert not (working_dir / "plugin_runtime").exists()
        assert site.name == "site"
        assert f"py{sys.version_info.major}.{sys.version_info.minor}" in (
            str(site)
        )


class TestResolvedPluginManifestPath:
    def test_missing_dir_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            pl.resolved_plugin_manifest_path(tmp_path / "nope")

    def test_symlink_escape_rejected(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        outside = tmp_path / "outside" / "plugin.json"
        outside.parent.mkdir()
        outside.write_text("{}")
        (src / "plugin.json").symlink_to(outside)
        with pytest.raises(ValueError, match="escapes"):
            pl.resolved_plugin_manifest_path(src)


class TestIsDisabledPluginDir:
    def test_hidden_dir_disabled(self):
        assert pl._is_disabled_plugin_dir(Path("/x/.git")) is True

    def test_disabled_suffix(self):
        assert pl._is_disabled_plugin_dir(Path("/x/remote.disabled")) is True

    def test_normal_dir_enabled(self):
        assert pl._is_disabled_plugin_dir(Path("/x/remote")) is False


class TestHubPluginLifecycle:
    @pytest.mark.parametrize("plugin_type", ["hub", "general"])
    @pytest.mark.parametrize(
        "config, expected",
        [
            (None, {"endpoint": "saved"}),
            ({}, {}),
            ({"endpoint": "explicit"}, {"endpoint": "explicit"}),
        ],
    )
    @pytest.mark.asyncio
    async def test_hot_load_config_matches_startup(
        self,
        tmp_path,
        monkeypatch,
        plugin_type,
        config,
        expected,
    ):
        import json
        from qwenpaw.config.config import Config
        from qwenpaw.plugins.registry import PluginRegistry

        monkeypatch.setattr(PluginRegistry, "_instance", None)
        monkeypatch.setattr(
            "qwenpaw.config.load_config",
            lambda: Config(
                plugins={"config-plugin": {"endpoint": "saved"}},
            ),
        )
        source = tmp_path / "source"
        source.mkdir()
        (source / "plugin.json").write_text(
            json.dumps(
                {
                    "id": "config-plugin",
                    "version": "1.0.0",
                    "type": plugin_type,
                    "entry": {"backend": "plugin.py"},
                },
            ),
        )
        (source / "plugin.py").write_text(
            "class Plugin:\n"
            "    def register(self, api):\n"
            "        self.config = api.config\n"
            "plugin = Plugin()\n",
        )
        loader = pl.PluginLoader([tmp_path / "plugins"])
        record = await loader.load_plugin_from_path(source, config=config)
        try:
            assert record.instance.config == expected
        finally:
            await loader.unload_plugin("config-plugin")

    @pytest.mark.parametrize(
        "plugin_id",
        ["qwenpaw-hub", "clawhub-hub", "modelscope-hub", "aliyun-hub"],
    )
    @pytest.mark.parametrize(
        "host_version, compatible",
        [
            ("2.2.1", False),
            ("2.2.2b4", True),
            ("2.2.2", True),
            ("2.2.3", True),
        ],
    )
    def test_hub_uses_existing_version_compatibility(
        self,
        monkeypatch,
        plugin_id,
        host_version,
        compatible,
    ):
        from qwenpaw.market import builtin
        from qwenpaw.plugins.download_catalog import _is_entry_compatible

        monkeypatch.setattr("qwenpaw.__version__.__version__", host_version)
        source = builtin.get_builtin_hub_plugins_dir()
        loader = pl.PluginLoader([])
        manifest = loader._load_manifest(source / plugin_id / "plugin.json")
        assert manifest.qwenpaw_version.min == "2.2.2"
        assert loader._check_version_compatibility(manifest)[0] is compatible
        assert (
            _is_entry_compatible(
                {
                    "plugin_id": plugin_id,
                    "version": manifest.version,
                    "platform": "hub",
                    "qwenpaw_version": manifest.qwenpaw_version.model_dump(
                        exclude_none=True,
                    ),
                },
            )
            is compatible
        )

        # Hubs follow the same version rules as existing plugin types.
        assert (
            _is_entry_compatible(
                {
                    "plugin_id": "existing-tool",
                    "version": "1.0.0",
                    "kind": "tool",
                    "qwenpaw_version": {"min": "2.2.2"},
                },
            )
            is compatible
        )

    @pytest.mark.asyncio
    async def test_catalog_waits_for_default_hubs(self, monkeypatch):
        import asyncio
        from fastapi import FastAPI, Request
        from qwenpaw.app.routers.market import get_market_providers
        from qwenpaw.market.schema import ProviderInfo

        providers = [
            ProviderInfo(key, key, True, None)
            for key in ("qwenpaw", "clawhub", "modelscope", "aliyun")
        ]
        monkeypatch.setattr(
            "qwenpaw.app.routers.market.list_providers",
            lambda: providers,
        )
        app = FastAPI()
        app.state.market_ready = asyncio.Event()
        catalog_request = asyncio.create_task(
            get_market_providers(Request({"type": "http", "app": app})),
        )
        try:
            await asyncio.sleep(0)
            assert not catalog_request.done()
            app.state.market_ready.set()
            catalog = await asyncio.wait_for(
                catalog_request,
                timeout=WAIT_TIMEOUT,
            )
            assert [provider.key for provider in catalog] == [
                "qwenpaw",
                "clawhub",
                "modelscope",
                "aliyun",
            ]
        finally:
            catalog_request.cancel()
            await asyncio.gather(catalog_request, return_exceptions=True)

    def test_seeding_preserves_existing_files_and_rejects_bad_marker(
        self,
        tmp_path,
    ):
        from qwenpaw.market.builtin import seed_builtin_hub_plugins

        existing = tmp_path / "qwenpaw-hub"
        existing.mkdir()
        (existing / "plugin.json").write_text('{"custom": true}')
        seed_builtin_hub_plugins(tmp_path)
        assert (existing / "plugin.json").read_text() == '{"custom": true}'
        (tmp_path / ".hub-defaults.json").write_text("{broken")
        with pytest.raises(ValueError):
            seed_builtin_hub_plugins(tmp_path)

    @pytest.mark.asyncio
    async def test_failed_registration_leaves_no_hub(
        self,
        tmp_path,
        monkeypatch,
    ):
        import asyncio
        import json
        from textwrap import dedent
        from qwenpaw.market import market_registry
        from qwenpaw.plugins.registry import PluginRegistry

        monkeypatch.setattr(PluginRegistry, "_instance", None)
        source = tmp_path / "broken-hub"
        source.mkdir()
        (source / "plugin.json").write_text(
            json.dumps(
                {
                    "id": "broken-hub",
                    "name": "Broken Hub",
                    "version": "1.0.0",
                    "type": "hub",
                    "entry": {"backend": "plugin.py"},
                },
            ),
        )
        (source / "plugin.py").write_text(
            dedent(
                """
        from qwenpaw.market.builtin import BuiltinMarketProvider
        from qwenpaw.market.providers.qwenpaw import QwenPawProvider
        class HubPlugin:
            async def register(self, api):
                api.register_market_provider(
                    BuiltinMarketProvider(QwenPawProvider()))
                api.config["registered"].set()
                await api.config["release"].wait()
                raise RuntimeError("registration failed")
        plugin = HubPlugin()
        """,
            ),
        )
        loader = pl.PluginLoader([tmp_path])
        registered, release = asyncio.Event(), asyncio.Event()
        loading = asyncio.create_task(
            loader.load_plugin_from_path(
                source,
                config={"registered": registered, "release": release},
            ),
        )
        await asyncio.wait_for(registered.wait(), timeout=WAIT_TIMEOUT)
        try:
            assert "qwenpaw" not in market_registry.snapshot()
            with pytest.raises(ValueError, match="not loaded"):
                with market_registry.use("qwenpaw"):
                    pytest.fail("A partially loaded Hub must not be usable")
        finally:
            release.set()
        with pytest.raises(RuntimeError, match="registration failed"):
            await loading
        assert "qwenpaw" not in market_registry.snapshot()
        record = loader.get_loaded_plugin("broken-hub")
        assert record.status == "failed"
        instance = loader.lifecycle.get_instance("broken-hub")
        assert not instance.has_runtime_ledger()

    @pytest.mark.asyncio
    async def test_hub_config_rebuild_replaces_provider(
        self,
        tmp_path,
        monkeypatch,
    ):
        from qwenpaw.market import builtin, market_registry
        from qwenpaw.plugins.registry import PluginRegistry

        monkeypatch.setattr(PluginRegistry, "_instance", None)
        monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
        loader = pl.PluginLoader([tmp_path / "plugins"])
        source = builtin.get_builtin_hub_plugins_dir() / "qwenpaw-hub"
        await loader.load_plugin_from_path(source)
        original = market_registry.snapshot()["qwenpaw"]
        try:
            report = await loader.lifecycle.update_config("qwenpaw-hub", {})
            assert report.ok
            replacement = market_registry.snapshot()["qwenpaw"]
            assert replacement is not original
            assert replacement.key == original.key
        finally:
            await loader.unload_plugin("qwenpaw-hub")
        assert "qwenpaw" not in market_registry.snapshot()
