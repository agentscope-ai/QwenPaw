# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name
"""Unit tests for PluginLoader runtime install / unload methods."""

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from qwenpaw.plugins.loader import PluginLoader
from qwenpaw.plugins.registry import PluginRegistry


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_registry():
    """Reset the PluginRegistry singleton before each test."""
    PluginRegistry._instance = None
    yield
    PluginRegistry._instance = None


@pytest.fixture()
def plugin_dir(tmp_path: Path) -> Path:
    """Return a directory acting as the top-level plugins store."""
    d = tmp_path / "plugins"
    d.mkdir()
    return d


def _make_plugin_src(
    base: Path,
    plugin_id: str,
    has_backend: bool = True,
    has_requirements: bool = False,
    tool_name: str | None = None,
) -> Path:
    """Create a minimal plugin directory inside *base*.

    Args:
        base: Parent directory
        plugin_id: Plugin identifier
        has_backend: Whether to create a plugin.py
        has_requirements: Whether to create requirements.txt
        tool_name: Optional tool name to add to meta

    Returns:
        Path to the created plugin source directory
    """
    src = base / plugin_id
    src.mkdir(parents=True)

    meta: dict[str, Any] = {}
    if tool_name:
        meta["tool_name"] = tool_name

    manifest: dict[str, Any] = {
        "id": plugin_id,
        "name": f"Test Plugin {plugin_id}",
        "version": "1.0.0",
        "description": "A test plugin",
        "author": "Tester",
        "entry": {},
        "meta": meta,
    }
    if has_backend:
        manifest["entry"]["backend"] = "plugin.py"

    (src / "plugin.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )

    if has_backend:
        # Minimal valid plugin module
        (src / "plugin.py").write_text(
            "class _Plugin:\n"
            "    def register(self, api):\n"
            "        pass\n\n"
            "plugin = _Plugin()\n",
            encoding="utf-8",
        )

    if has_requirements:
        (src / "requirements.txt").write_text(
            "# no real deps\n",
            encoding="utf-8",
        )

    return src


# ── load_plugin_from_path ─────────────────────────────────────────────────


class TestLoadPluginFromPath:
    """Tests for PluginLoader.load_plugin_from_path."""

    @pytest.mark.asyncio
    async def test_copies_files_and_loads_plugin(
        self,
        plugin_dir: Path,
        tmp_path: Path,
    ):
        """Plugin files should be copied into install_dir and loaded."""
        src = _make_plugin_src(tmp_path / "src", "my-plugin")
        loader = PluginLoader([plugin_dir])

        record = await loader.load_plugin_from_path(
            source_path=src,
            install_dir=plugin_dir,
        )

        assert record.manifest.id == "my-plugin"
        assert (plugin_dir / "my-plugin" / "plugin.json").exists()
        assert "my-plugin" in loader.get_all_loaded_plugins()

    @pytest.mark.asyncio
    async def test_raises_if_no_plugin_json(
        self,
        plugin_dir: Path,
        tmp_path: Path,
    ):
        """FileNotFoundError when plugin.json is missing."""
        src = tmp_path / "bad-plugin"
        src.mkdir()
        loader = PluginLoader([plugin_dir])

        with pytest.raises(FileNotFoundError, match="plugin.json not found"):
            await loader.load_plugin_from_path(
                source_path=src,
                install_dir=plugin_dir,
            )

    @pytest.mark.asyncio
    async def test_raises_if_already_loaded(
        self,
        plugin_dir: Path,
        tmp_path: Path,
    ):
        """ValueError when the plugin is already in the loaded set."""
        src = _make_plugin_src(tmp_path / "src", "dup-plugin")
        loader = PluginLoader([plugin_dir])

        await loader.load_plugin_from_path(
            source_path=src,
            install_dir=plugin_dir,
        )

        src2 = _make_plugin_src(tmp_path / "src2", "dup-plugin")
        with pytest.raises(ValueError, match="already loaded"):
            await loader.load_plugin_from_path(
                source_path=src2,
                install_dir=plugin_dir,
            )

    @pytest.mark.asyncio
    async def test_installs_requirements(
        self,
        plugin_dir: Path,
        tmp_path: Path,
    ):
        """_install_requirements is called when requirements.txt exists."""
        src = _make_plugin_src(
            tmp_path / "src",
            "req-plugin",
            has_requirements=True,
        )
        loader = PluginLoader([plugin_dir])

        with patch.object(
            loader,
            "_install_requirements",
            wraps=lambda *_: None,
        ) as mock_install:
            await loader.load_plugin_from_path(
                source_path=src,
                install_dir=plugin_dir,
            )
            mock_install.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_install_requirements_when_absent(
        self,
        plugin_dir: Path,
        tmp_path: Path,
    ):
        """_install_requirements is NOT called when no requirements.txt."""
        src = _make_plugin_src(
            tmp_path / "src",
            "no-req-plugin",
            has_requirements=False,
        )
        loader = PluginLoader([plugin_dir])

        with patch.object(
            loader,
            "_install_requirements",
        ) as mock_install:
            await loader.load_plugin_from_path(
                source_path=src,
                install_dir=plugin_dir,
            )
            mock_install.assert_not_called()


# ── unload_plugin ─────────────────────────────────────────────────────────


class TestUnloadPlugin:
    """Tests for PluginLoader.unload_plugin."""

    @pytest.mark.asyncio
    async def test_removes_from_loaded_plugins(
        self,
        plugin_dir: Path,
        tmp_path: Path,
    ):
        """Plugin should not appear in get_all_loaded_plugins after unload."""
        src = _make_plugin_src(tmp_path / "src", "rm-plugin")
        loader = PluginLoader([plugin_dir])
        await loader.load_plugin_from_path(
            source_path=src,
            install_dir=plugin_dir,
        )
        assert "rm-plugin" in loader.get_all_loaded_plugins()

        await loader.unload_plugin("rm-plugin")

        assert "rm-plugin" not in loader.get_all_loaded_plugins()

    @pytest.mark.asyncio
    async def test_raises_if_not_loaded(self, plugin_dir: Path):
        """KeyError when trying to unload a plugin that is not loaded."""
        loader = PluginLoader([plugin_dir])

        with pytest.raises(KeyError, match="not loaded"):
            await loader.unload_plugin("ghost-plugin")

    @pytest.mark.asyncio
    async def test_deletes_files_when_requested(
        self,
        plugin_dir: Path,
        tmp_path: Path,
    ):
        """Plugin directory should be deleted when delete_files=True."""
        src = _make_plugin_src(tmp_path / "src", "del-plugin")
        loader = PluginLoader([plugin_dir])
        await loader.load_plugin_from_path(
            source_path=src,
            install_dir=plugin_dir,
        )
        installed = plugin_dir / "del-plugin"
        assert installed.exists()

        await loader.unload_plugin("del-plugin", delete_files=True)

        assert not installed.exists()

    @pytest.mark.asyncio
    async def test_keeps_files_when_not_requested(
        self,
        plugin_dir: Path,
        tmp_path: Path,
    ):
        """Plugin directory should NOT be deleted when delete_files=False."""
        src = _make_plugin_src(tmp_path / "src", "keep-plugin")
        loader = PluginLoader([plugin_dir])
        await loader.load_plugin_from_path(
            source_path=src,
            install_dir=plugin_dir,
        )
        installed = plugin_dir / "keep-plugin"
        assert installed.exists()

        await loader.unload_plugin("keep-plugin", delete_files=False)

        assert installed.exists()

    @pytest.mark.asyncio
    async def test_removes_from_sys_modules(
        self,
        plugin_dir: Path,
        tmp_path: Path,
    ):
        """Plugin module should be removed from sys.modules on unload."""
        src = _make_plugin_src(tmp_path / "src", "sysmod-plugin")
        loader = PluginLoader([plugin_dir])
        await loader.load_plugin_from_path(
            source_path=src,
            install_dir=plugin_dir,
        )
        module_name = "plugin_sysmod_plugin"
        assert module_name in sys.modules

        await loader.unload_plugin("sysmod-plugin")

        assert module_name not in sys.modules

    @pytest.mark.asyncio
    async def test_unregisters_from_registry(
        self,
        plugin_dir: Path,
        tmp_path: Path,
    ):
        """Registry should not contain the plugin manifest after unload."""
        src = _make_plugin_src(tmp_path / "src", "reg-plugin")
        loader = PluginLoader([plugin_dir])
        await loader.load_plugin_from_path(
            source_path=src,
            install_dir=plugin_dir,
        )
        assert "reg-plugin" in loader.registry.get_all_plugin_manifests()

        await loader.unload_plugin("reg-plugin")

        assert "reg-plugin" not in loader.registry.get_all_plugin_manifests()

    @pytest.mark.asyncio
    async def test_cleans_up_agent_tools(
        self,
        plugin_dir: Path,
        tmp_path: Path,
    ):
        """_cleanup_plugin_tools is invoked and removes the tool entry.

        We patch the method directly and verify that it was called with
        the correct plugin_id and record on unload.  The internal import
        path is exercised in the synchronous unit test below.
        """
        src = _make_plugin_src(
            tmp_path / "src",
            "tool-plugin",
            tool_name="my_test_tool",
        )
        loader = PluginLoader([plugin_dir])
        await loader.load_plugin_from_path(
            source_path=src,
            install_dir=plugin_dir,
        )

        cleanup_calls: list = []

        original_cleanup = loader._cleanup_plugin_tools

        def _mock_cleanup(pid, record):
            cleanup_calls.append((pid, record.manifest.id))

        loader._cleanup_plugin_tools = (  # type: ignore[method-assign]
            _mock_cleanup
        )
        try:
            await loader.unload_plugin("tool-plugin")
        finally:
            loader._cleanup_plugin_tools = (  # type: ignore[method-assign]
                original_cleanup
            )

        assert len(cleanup_calls) == 1
        assert cleanup_calls[0] == ("tool-plugin", "tool-plugin")


# ── PluginRegistry.unregister_plugin ──────────────────────────────────────


class TestRegistryUnregisterPlugin:
    """Tests for PluginRegistry.unregister_plugin."""

    def test_removes_manifest(self):
        registry = PluginRegistry()
        registry.register_plugin_manifest("p1", {"id": "p1"})
        registry.unregister_plugin("p1")
        assert "p1" not in registry.get_all_plugin_manifests()

    def test_removes_startup_hooks(self):
        registry = PluginRegistry()
        registry.register_startup_hook("p1", "boot", lambda: None)
        registry.unregister_plugin("p1")
        hooks = [
            h for h in registry.get_startup_hooks() if h.plugin_id == "p1"
        ]
        assert not hooks

    def test_removes_shutdown_hooks(self):
        registry = PluginRegistry()
        registry.register_shutdown_hook("p1", "shutdown", lambda: None)
        registry.unregister_plugin("p1")
        hooks = [
            h for h in registry.get_shutdown_hooks() if h.plugin_id == "p1"
        ]
        assert not hooks

    def test_idempotent_on_unknown_id(self):
        registry = PluginRegistry()
        # Should not raise
        registry.unregister_plugin("nonexistent")


# ── _cleanup_plugin_tools (sync logic) ───────────────────────────────────


class TestCleanupPluginTools:
    """Tests for PluginLoader._cleanup_plugin_tools."""

    def _make_record(self, plugin_id: str, tool_name: str):
        """Return a minimal PluginRecord with a tool in meta."""
        from qwenpaw.plugins.architecture import (
            PluginManifest,
            PluginRecord,
        )

        manifest = PluginManifest(
            id=plugin_id,
            name=plugin_id,
            version="1.0.0",
            meta={"tool_name": tool_name},
        )
        return PluginRecord(
            manifest=manifest,
            source_path=Path("/tmp"),
            enabled=True,
        )

    def test_removes_tool_attribute_and_all_entry(self, tmp_path: Path):
        """Tool attribute and __all__ entry are removed from the module.

        _cleanup_plugin_tools uses sys.modules.get, so we set the key
        directly to bypass parent-package attribute caching.
        """
        import types

        loader = PluginLoader([tmp_path])
        record = self._make_record("p", "the_tool")

        fake_tools = types.ModuleType("qwenpaw.agents.tools")
        fake_tools.__all__ = ["the_tool", "other_tool"]
        fake_tools.the_tool = lambda: None  # type: ignore[attr-defined]

        prev = sys.modules.get("qwenpaw.agents.tools")
        sys.modules["qwenpaw.agents.tools"] = fake_tools
        try:
            loader._cleanup_plugin_tools("p", record)
        finally:
            if prev is None:
                sys.modules.pop("qwenpaw.agents.tools", None)
            else:
                sys.modules["qwenpaw.agents.tools"] = prev

        assert "the_tool" not in fake_tools.__all__
        assert "other_tool" in fake_tools.__all__
        assert not hasattr(fake_tools, "the_tool")

    def test_no_error_when_tool_absent(self, tmp_path: Path):
        """No error if the tool is not present in the module."""
        import types

        loader = PluginLoader([tmp_path])
        record = self._make_record("p", "missing_tool")

        fake_tools = types.ModuleType("qwenpaw.agents.tools")
        fake_tools.__all__ = []

        prev = sys.modules.get("qwenpaw.agents.tools")
        sys.modules["qwenpaw.agents.tools"] = fake_tools
        try:
            loader._cleanup_plugin_tools("p", record)  # must not raise
        finally:
            if prev is None:
                sys.modules.pop("qwenpaw.agents.tools", None)
            else:
                sys.modules["qwenpaw.agents.tools"] = prev
