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


@pytest.fixture()
def working_dir(tmp_path, monkeypatch):
    wd = tmp_path / "wd"
    wd.mkdir()
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", wd)
    return wd


class TestIsFrozen:
    def test_not_frozen(self):
        assert pl._is_frozen() is False

    def test_frozen_flag(self, monkeypatch):
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        assert pl._is_frozen() is True


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
    def test_runtime_dir_under_working_dir(self, working_dir):
        assert pl._plugin_runtime_dir() == working_dir / "plugin_runtime"

    def test_site_dir_bucketed_and_created(self, working_dir):
        site = pl._plugin_site_dir()
        assert site.is_dir()
        assert site.name == "site"
        assert f"py{sys.version_info.major}.{sys.version_info.minor}" in (
            str(site)
        )

    def test_install_lock_path_sanitised(self, working_dir):
        lock = pl._install_lock_path("my plugin/id")
        assert lock.name == "my_plugin_id.lock"
        assert lock.parent == working_dir / "plugin_runtime" / "install-locks"

    def test_install_lock_path_simple(self, working_dir):
        lock = pl._install_lock_path("demo-1.0")
        assert lock.name == "demo-1.0.lock"


class TestNormRealpath:
    def test_normalises(self, tmp_path):
        assert pl._norm_realpath(tmp_path) == pl._norm_realpath(str(tmp_path))


class TestResolvedPluginManifestPath:
    def test_returns_manifest(self, tmp_path):
        (tmp_path / "plugin.json").write_text("{}")
        result = pl.resolved_plugin_manifest_path(tmp_path)
        assert result.name == "plugin.json"

    def test_missing_dir_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            pl.resolved_plugin_manifest_path(tmp_path / "nope")

    def test_missing_manifest_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            pl.resolved_plugin_manifest_path(tmp_path)

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


class TestEnsurePluginSiteOnPath:
    def test_noop_when_not_frozen(self, monkeypatch):
        monkeypatch.setattr(pl, "_is_frozen", lambda: False)
        pl._ensure_plugin_site_on_path()  # must not raise or modify path

    def test_adds_site_when_frozen(self, working_dir, monkeypatch):
        monkeypatch.setattr(pl, "_is_frozen", lambda: True)
        site_dir = pl._plugin_site_dir()
        # clean the dir from sys.path so the insertion path is exercised
        monkeypatch.setattr(
            pl.sys,
            "path",
            [p for p in pl.sys.path if p != str(site_dir)],
        )
        import site as _site

        adds = []
        monkeypatch.setattr(_site, "addsitedir", lambda d: adds.append(d))
        pl._ensure_plugin_site_on_path()
        assert str(site_dir) in pl.sys.path
        assert pl.os.environ.get("QWENPAW_PLUGIN_SITE") == str(site_dir)


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
        from types import SimpleNamespace
        from qwenpaw.plugins.registry import PluginRegistry

        monkeypatch.setattr(PluginRegistry, "_instance", None)
        monkeypatch.setattr(
            "qwenpaw.config.load_config",
            lambda: SimpleNamespace(
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

    @pytest.mark.parametrize("legacy_adapter", [False, True])
    @pytest.mark.asyncio
    async def test_defaults_unload_restart_and_reinstall(
        self,
        tmp_path,
        monkeypatch,
        legacy_adapter,
    ):
        import importlib
        from qwenpaw.market import builtin, market_registry
        from qwenpaw.market.registry import MarketProviderBusyError
        from qwenpaw.plugins.registry import PluginRegistry

        monkeypatch.setattr(PluginRegistry, "_instance", None)
        plugins_dir = tmp_path / "plugins"
        builtin.seed_builtin_hub_plugins(plugins_dir)
        if legacy_adapter:
            for entry in plugins_dir.glob("*/plugin.py"):
                key = entry.parent.name.removesuffix("-hub")
                entry.write_text(
                    "from qwenpaw.agents.skill_system.hub import PROVIDERS\n"
                    "handlers = {key: (match, fetch) "
                    "for key, match, fetch in PROVIDERS}\n"
                    + entry.read_text().replace(
                        "Provider()),",
                        f"Provider(), *handlers[{key!r}]),",
                    ),
                )
        loader = pl.PluginLoader([plugins_dir])
        try:
            loaded = await loader.load_all_plugins(types=["hub"])
            assert len(loaded) == 4
            assert all(record.enabled for record in loaded.values())
            assert list(market_registry.snapshot()) == [
                "qwenpaw",
                "clawhub",
                "modelscope",
                "aliyun",
            ]
            # Built-in plugins retain the existing search, availability,
            # URL matching and download implementations.
            from qwenpaw.agents.skill_system import hub

            legacy = {
                key: (matcher, fetcher)
                for key, matcher, fetcher in hub.PROVIDERS
            }
            for key, provider in market_registry.snapshot().items():
                original = importlib.import_module(
                    f"qwenpaw.market.providers.{key}",
                ).provider
                assert provider.label == original.label
                assert provider.supports_browse == original.supports_browse
                assert provider.available() == original.available()
                assert provider.search.__func__ is original.search.__func__
                assert provider._matcher is legacy[key][0]
                assert provider.fetch_bundle is legacy[key][1]
            with market_registry.use("qwenpaw"):
                with pytest.raises(MarketProviderBusyError):
                    await loader.unload_plugin(
                        "qwenpaw-hub",
                        delete_files=True,
                    )
            assert (plugins_dir / "qwenpaw-hub/plugin.json").exists()
            await loader.unload_plugin("qwenpaw-hub", delete_files=True)
            assert "qwenpaw" not in market_registry.snapshot()
            # Direct URL imports remain independent of the market registry.
            assert (
                hub._match_provider(
                    "https://platform.agentscope.io/skills/o/n",
                )[0]
                == "qwenpaw"
            )
            for plugin_id in list(loaded):
                await loader.unload_plugin(plugin_id)
            builtin.seed_builtin_hub_plugins(plugins_dir)
            assert not (plugins_dir / "qwenpaw-hub").exists()
            await loader.load_all_plugins(types=["hub"])
            assert "qwenpaw" not in market_registry.snapshot()
            source = builtin.get_builtin_hub_plugins_dir() / "qwenpaw-hub"
            await loader.load_plugin_from_path(source)
            assert "qwenpaw" in market_registry.snapshot()
            # A force update replaces the old registration, not duplicates it.
            await loader.load_plugin_from_path(source, force=True)
            assert list(market_registry.snapshot()).count("qwenpaw") == 1
            # Removing every default Hub remains effective on a fresh start.
            for plugin_id in list(loader.get_all_loaded_plugins()):
                await loader.unload_plugin(plugin_id, delete_files=True)
            builtin.seed_builtin_hub_plugins(plugins_dir)
            restarted = pl.PluginLoader([plugins_dir])
            assert await restarted.load_all_plugins(types=["hub"]) == {}
            assert market_registry.snapshot() == {}
            assert not list(plugins_dir.glob("*/plugin.json"))
        finally:
            for plugin_id in list(loader.get_all_loaded_plugins()):
                await loader.unload_plugin(plugin_id)

    @pytest.mark.asyncio
    async def test_catalog_waits_for_default_hubs(self, tmp_path, monkeypatch):
        import asyncio
        from fastapi import FastAPI, Request
        from qwenpaw.app.routers.market import get_market_providers
        from qwenpaw.market import builtin
        from qwenpaw.plugins.registry import PluginRegistry

        monkeypatch.setattr(PluginRegistry, "_instance", None)
        builtin.seed_builtin_hub_plugins(tmp_path)
        loader = pl.PluginLoader([tmp_path])
        app = FastAPI()
        app.state.market_ready = asyncio.Event()
        catalog_request = asyncio.create_task(
            get_market_providers(Request({"type": "http", "app": app})),
        )
        try:
            await asyncio.sleep(0)
            assert not catalog_request.done()
            await loader.load_all_plugins(types=["hub"])
            app.state.market_ready.set()
            catalog = await asyncio.wait_for(catalog_request, timeout=1)
            assert [provider.key for provider in catalog] == [
                "qwenpaw",
                "clawhub",
                "modelscope",
                "aliyun",
            ]
        finally:
            catalog_request.cancel()
            for plugin_id in list(loader.get_all_loaded_plugins()):
                await loader.unload_plugin(plugin_id)

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
        await asyncio.wait_for(registered.wait(), timeout=5)
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
        assert "broken-hub" not in loader.get_all_loaded_plugins()
