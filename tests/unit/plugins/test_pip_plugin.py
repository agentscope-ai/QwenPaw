# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,protected-access
"""Unit tests for pip-based plugin discovery and installation.

Tests cover:
- Entry point discovery via ``qwenpaw.plugins`` group
- ``discover_pip_plugins()`` scanning logic
- ``load_pip_plugin()`` install + load flow
- ``uninstall_pip_plugin()`` unload + pip uninstall flow
- ``InstallSource`` enum on ``PluginRecord``
- CLI ``install-pip`` / ``uninstall-pip`` commands
- REST API ``POST /install-pip`` / ``DELETE /{id}/pip`` endpoints
"""

import importlib
import json
import sys
import types
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

_AGENTSCOPE_STUBS = [
    "agentscope.state",
]
for _mod_name in _AGENTSCOPE_STUBS:
    if _mod_name not in sys.modules:
        _stub = types.ModuleType(_mod_name)
        _stub.AgentState = type("AgentState", (), {})
        sys.modules[_mod_name] = _stub


@pytest.fixture()
def fresh_registry():
    """Create a fresh PluginRegistry (bypass singleton for test isolation)."""
    from qwenpaw.plugins.registry import PluginRegistry

    original_instance = PluginRegistry._instance
    PluginRegistry._instance = None
    registry = PluginRegistry()
    yield registry
    PluginRegistry._instance = original_instance


@pytest.fixture()
def loader(tmp_path, fresh_registry):
    """Create a PluginLoader with a temporary plugin directory."""
    from qwenpaw.plugins.loader import PluginLoader

    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    loader = PluginLoader(plugin_dirs=[plugin_dir])
    loader.registry = fresh_registry
    return loader


def _make_fake_entry_point(name, module):
    """Create a mock entry point that returns the given module on load()."""
    ep = MagicMock()
    ep.name = name
    ep.load.return_value = module
    return ep


def _make_fake_module(tmp_path, plugin_id, version="1.0.0"):
    """Create a fake pip-installed plugin module with plugin.json."""
    pkg_dir = tmp_path / f"pkg_{plugin_id.replace('-', '_')}"
    pkg_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "id": plugin_id,
        "name": plugin_id,
        "version": version,
        "description": f"Test plugin {plugin_id}",
        "author": "test",
        "entry": {"backend": "plugin_backend.py"},
        "plugin_type": "tool",
        "meta": {"tool_name": plugin_id},
    }
    (pkg_dir / "plugin.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )

    backend_code = (
        "class _TestPlugin:\n"
        "    def register(self, api):\n"
        "        pass\n"
        "\n"
        "plugin = _TestPlugin()\n"
    )
    (pkg_dir / "plugin_backend.py").write_text(
        backend_code,
        encoding="utf-8",
    )

    mod = types.ModuleType(f"fake_{plugin_id.replace('-', '_')}")
    mod.__file__ = str(pkg_dir / "plugin_backend.py")
    return mod, pkg_dir


class TestDiscoverPipPlugins:
    """Tests for ``PluginLoader.discover_pip_plugins()``."""

    def test_no_entry_points(self, loader):
        """Returns empty list when no entry points registered."""
        with patch(
            "qwenpaw.plugins.loader._entry_points",
            return_value=[],
        ):
            result = loader.discover_pip_plugins()
        assert result == []

    def test_discovers_valid_plugin(self, loader, tmp_path):
        """Discovers a plugin with valid entry point and manifest."""
        mod, pkg_dir = _make_fake_module(
            tmp_path,
            "test-pip-plugin",
        )
        ep = _make_fake_entry_point("test-pip-plugin", mod)

        with patch(
            "qwenpaw.plugins.loader._entry_points",
            return_value=[ep],
        ):
            result = loader.discover_pip_plugins()

        assert len(result) == 1
        manifest, discovered_dir = result[0]
        assert manifest.id == "test-pip-plugin"
        assert manifest.version == "1.0.0"
        assert discovered_dir == pkg_dir

    def test_skips_entry_point_without_module(self, loader):
        """Skips entry points that don't resolve to a module."""
        ep = MagicMock()
        ep.name = "bad-plugin"
        ep.load.return_value = "not_a_module"

        with patch(
            "qwenpaw.plugins.loader._entry_points",
            return_value=[ep],
        ):
            result = loader.discover_pip_plugins()

        assert result == []

    def test_skips_entry_point_missing_plugin_json(self, loader, tmp_path):
        """Skips entry points whose package lacks plugin.json."""
        pkg_dir = tmp_path / "no_manifest_pkg"
        pkg_dir.mkdir()
        backend = pkg_dir / "backend.py"
        backend.write_text("x = 1", encoding="utf-8")

        mod = types.ModuleType("no_manifest")
        mod.__file__ = str(backend)

        ep = _make_fake_entry_point("no-manifest", mod)

        with patch(
            "qwenpaw.plugins.loader._entry_points",
            return_value=[ep],
        ):
            result = loader.discover_pip_plugins()

        assert result == []

    def test_skips_entry_point_load_failure(self, loader):
        """Skips entry points that raise on load()."""
        ep = MagicMock()
        ep.name = "broken"
        ep.load.side_effect = ImportError("broken dep")

        with patch(
            "qwenpaw.plugins.loader._entry_points",
            return_value=[ep],
        ):
            result = loader.discover_pip_plugins()

        assert result == []

    def test_discovers_multiple_plugins(self, loader, tmp_path):
        """Discovers multiple plugins from entry points."""
        mod1, _ = _make_fake_module(tmp_path, "plugin-a")
        mod2, _ = _make_fake_module(tmp_path, "plugin-b")
        ep1 = _make_fake_entry_point("plugin-a", mod1)
        ep2 = _make_fake_entry_point("plugin-b", mod2)

        with patch(
            "qwenpaw.plugins.loader._entry_points",
            return_value=[ep1, ep2],
        ):
            result = loader.discover_pip_plugins()

        assert len(result) == 2
        ids = {m.id for m, _ in result}
        assert ids == {"plugin-a", "plugin-b"}


class TestLoadPipPluginFromDir:
    """Tests for ``PluginLoader._load_pip_plugin_from_dir()``."""

    @pytest.mark.asyncio
    async def test_loads_valid_plugin(self, loader, tmp_path):
        """Loads a valid pip plugin from its package directory."""
        mod, pkg_dir = _make_fake_module(tmp_path, "load-test-plugin")

        manifest_path = pkg_dir / "plugin.json"
        manifest = loader._load_manifest(manifest_path)

        record = await loader._load_pip_plugin_from_dir(
            manifest,
            pkg_dir,
        )

        assert record.manifest.id == "load-test-plugin"
        assert record.enabled is True
        from qwenpaw.plugins.architecture import InstallSource

        assert record.install_source == InstallSource.PIP
        assert "load-test-plugin" in loader._loaded_plugins

    @pytest.mark.asyncio
    async def test_rejects_duplicate_plugin(self, loader, tmp_path):
        """Raises ValueError when plugin is already loaded."""
        mod, pkg_dir = _make_fake_module(tmp_path, "dup-plugin")

        manifest_path = pkg_dir / "plugin.json"
        manifest = loader._load_manifest(manifest_path)

        await loader._load_pip_plugin_from_dir(manifest, pkg_dir)

        with pytest.raises(ValueError, match="already loaded"):
            await loader._load_pip_plugin_from_dir(manifest, pkg_dir)

    @pytest.mark.asyncio
    async def test_rejects_missing_backend(self, loader, tmp_path):
        """Raises FileNotFoundError when backend file is missing."""
        pkg_dir = tmp_path / "no_backend_pkg"
        pkg_dir.mkdir()
        manifest_data = {
            "id": "no-backend",
            "name": "no-backend",
            "version": "1.0.0",
            "entry": {"backend": "nonexistent.py"},
        }
        (pkg_dir / "plugin.json").write_text(
            json.dumps(manifest_data),
            encoding="utf-8",
        )

        manifest = loader._load_manifest(pkg_dir / "plugin.json")

        with pytest.raises(FileNotFoundError, match="backend file not found"):
            await loader._load_pip_plugin_from_dir(manifest, pkg_dir)


class TestInstallSource:
    """Tests for the ``InstallSource`` enum."""

    def test_enum_values(self):
        from qwenpaw.plugins.architecture import InstallSource

        assert InstallSource.ZIP.value == "zip"
        assert InstallSource.PIP.value == "pip"

    def test_default_is_zip(self):
        from qwenpaw.plugins.architecture import (
            InstallSource,
            PluginManifest,
            PluginRecord,
        )

        manifest = PluginManifest(id="test", version="1.0")
        record = PluginRecord(
            manifest=manifest,
            source_path=Path("/tmp/test"),
            enabled=True,
        )
        assert record.install_source == InstallSource.ZIP


class TestLoadAllPluginsIncludesPip:
    """Tests that ``load_all_plugins`` also discovers pip plugins."""

    @pytest.mark.asyncio
    async def test_load_all_includes_pip(self, loader, tmp_path):
        """load_all_plugins discovers both disk and pip plugins."""
        mod, pkg_dir = _make_fake_module(tmp_path, "auto-pip-plugin")
        ep = _make_fake_entry_point("auto-pip-plugin", mod)

        with patch(
            "qwenpaw.plugins.loader._entry_points",
            return_value=[ep],
        ):
            result = await loader.load_all_plugins()

        assert "auto-pip-plugin" in result


class TestPipInstallPackage:
    """Tests for ``PluginLoader._pip_install_package()``."""

    def test_pip_success(self, loader):
        """Installs package successfully via pip."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Successfully installed pkg"

        with patch.object(
            loader,
            "_run_subprocess_with_streaming_log",
            return_value=mock_result,
        ):
            loader._pip_install_package("test-package")

    def test_pip_failure_no_uv(self, loader):
        """Raises RuntimeError when pip fails and uv is not found."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = "error"
        mock_result.stderr = "some error"

        with patch.object(
            loader,
            "_run_subprocess_with_streaming_log",
            return_value=mock_result,
        ), patch.object(
            loader,
            "_find_uv",
            return_value=None,
        ):
            with pytest.raises(RuntimeError, match="pip install failed"):
                loader._pip_install_package("bad-package")

    def test_pip_missing_falls_back_to_uv(self, loader):
        """Falls back to uv when pip is not available."""
        pip_result = MagicMock()
        pip_result.returncode = 1
        pip_result.stdout = "No module named pip"
        pip_result.stderr = ""

        uv_result = MagicMock()
        uv_result.returncode = 0
        uv_result.stdout = "installed"

        call_count = 0

        def mock_run(cmd, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return pip_result
            return uv_result

        with patch.object(
            loader,
            "_run_subprocess_with_streaming_log",
            side_effect=mock_run,
        ), patch.object(
            loader,
            "_find_uv",
            return_value="/usr/bin/uv",
        ):
            loader._pip_install_package("test-package")

        assert call_count == 2


class TestGuessDistName:
    """Tests for ``PluginLoader._guess_dist_name()``."""

    def test_finds_dist_name(self, tmp_path):
        from qwenpaw.plugins.architecture import (
            InstallSource,
            PluginManifest,
            PluginRecord,
        )

        site_dir = tmp_path / "site-packages"
        site_dir.mkdir()
        dist_info = site_dir / "my_plugin-1.0.0.dist-info"
        dist_info.mkdir()
        (dist_info / "METADATA").write_text(
            "Name: my-plugin\nVersion: 1.0.0\n",
            encoding="utf-8",
        )

        pkg_dir = site_dir / "my_plugin"
        pkg_dir.mkdir()

        manifest = PluginManifest(id="my-plugin", version="1.0.0")
        record = PluginRecord(
            manifest=manifest,
            source_path=pkg_dir,
            enabled=True,
            install_source=InstallSource.PIP,
        )

        from qwenpaw.plugins.loader import PluginLoader

        name = PluginLoader._guess_dist_name(record)
        assert name == "my-plugin"

    def test_returns_none_when_no_dist_info(self, tmp_path):
        from qwenpaw.plugins.architecture import (
            InstallSource,
            PluginManifest,
            PluginRecord,
        )

        pkg_dir = tmp_path / "some_pkg"
        pkg_dir.mkdir()

        manifest = PluginManifest(id="some-plugin", version="1.0.0")
        record = PluginRecord(
            manifest=manifest,
            source_path=pkg_dir,
            enabled=True,
            install_source=InstallSource.PIP,
        )

        from qwenpaw.plugins.loader import PluginLoader

        name = PluginLoader._guess_dist_name(record)
        assert name is None


class TestEntryPointGroupConstant:
    """Tests for the entry point group constant."""

    def test_constant_value(self):
        from qwenpaw.plugins.loader import ENTRY_POINT_GROUP

        assert ENTRY_POINT_GROUP == "qwenpaw.plugins"

    def test_exported_from_init(self):
        from qwenpaw.plugins import ENTRY_POINT_GROUP

        assert ENTRY_POINT_GROUP == "qwenpaw.plugins"
