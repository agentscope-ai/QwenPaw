# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,protected-access
"""Tests for plugin load-failure isolation.

Verifies that when ``_load_backend_module`` fails at any stage
(exec_module, missing ``plugin`` attribute, ``register()`` exception),
the framework cleans up:

- ``sys.modules`` (main module, sub-modules, bare-imported modules)
- ``sys.path``
- ``PluginRegistry`` (manifest, hooks, providers, middleware, etc.)
"""

import json
import os
import sys
import types
from pathlib import Path
from typing import Dict

import pytest

# ---------------------------------------------------------------------------
# Stub missing agentscope 2.0 modules (same pattern as sibling test file)
# ---------------------------------------------------------------------------
_AGENTSCOPE_STUBS = [
    "agentscope.state",
]
for _mod_name in _AGENTSCOPE_STUBS:
    if _mod_name not in sys.modules:
        _stub = types.ModuleType(_mod_name)
        _stub.AgentState = type(
            "AgentState",
            (),
            {},
        )  # type: ignore[attr-defined]
        sys.modules[_mod_name] = _stub


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def fresh_registry():
    """Create a fresh PluginRegistry (bypass singleton)."""
    from qwenpaw.plugins.registry import PluginRegistry

    old_instance = PluginRegistry._instance
    PluginRegistry._instance = None
    registry = PluginRegistry()
    yield registry
    PluginRegistry._instance = old_instance


@pytest.fixture()
def loader(fresh_registry, tmp_path):
    """Create a PluginLoader wired to the fresh registry."""
    from qwenpaw.plugins.loader import PluginLoader

    ldr = PluginLoader(plugin_dirs=[tmp_path])
    ldr.registry = fresh_registry
    return ldr


def _write_plugin(plugin_dir: Path, plugin_py_code: str) -> Dict:
    """Write a minimal plugin directory and return the manifest dict."""
    plugin_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "id": plugin_dir.name,
        "name": plugin_dir.name,
        "version": "1.0.0",
        "entry": {"backend": "plugin.py"},
        "qwenpaw_version": {"min": "0.1.0", "max": "99.0.0"},
    }
    (plugin_dir / "plugin.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    (plugin_dir / "plugin.py").write_text(plugin_py_code, encoding="utf-8")
    return manifest


# ---------------------------------------------------------------------------
# Tests: sys.modules cleanup
# ---------------------------------------------------------------------------


class TestSysModulesCleanup:
    """sys.modules must not retain entries from a failed load."""

    @pytest.mark.asyncio
    async def test_exec_module_failure_cleans_sys_modules(
        self,
        loader,
        tmp_path,
    ):
        """If exec_module raises, the module is removed from sys.modules."""
        plugin_dir = tmp_path / "bad-syntax"
        _write_plugin(plugin_dir, "raise SyntaxError('intentional')\n")

        from qwenpaw.plugins.architecture import PluginManifest

        manifest = PluginManifest.from_dict(
            json.loads(
                (plugin_dir / "plugin.json").read_text(encoding="utf-8"),
            ),
        )
        module_name = f"plugin_{manifest.id.replace('-', '_')}"

        with pytest.raises(SyntaxError):
            await loader._load_backend_module(
                manifest.id,
                plugin_dir / "plugin.py",
                plugin_dir,
                None,
                manifest,
            )

        assert module_name not in sys.modules

    @pytest.mark.asyncio
    async def test_missing_plugin_attr_cleans_sys_modules(
        self,
        loader,
        tmp_path,
    ):
        """If the module lacks a 'plugin' attribute, sys.modules is cleaned."""
        plugin_dir = tmp_path / "no-attr"
        _write_plugin(plugin_dir, "x = 42\n")

        from qwenpaw.plugins.architecture import PluginManifest

        manifest = PluginManifest.from_dict(
            json.loads(
                (plugin_dir / "plugin.json").read_text(encoding="utf-8"),
            ),
        )
        module_name = f"plugin_{manifest.id.replace('-', '_')}"

        with pytest.raises(AttributeError, match="plugin"):
            await loader._load_backend_module(
                manifest.id,
                plugin_dir / "plugin.py",
                plugin_dir,
                None,
                manifest,
            )

        assert module_name not in sys.modules

    @pytest.mark.asyncio
    async def test_register_failure_cleans_submodules(
        self,
        loader,
        tmp_path,
    ):
        """Sub-modules written by exec_module are cleaned on failure."""
        plugin_dir = tmp_path / "sub-mod"
        (plugin_dir).mkdir()
        (plugin_dir / "helper.py").write_text(
            "VALUE = 99\n",
            encoding="utf-8",
        )
        _write_plugin(
            plugin_dir,
            "from .helper import VALUE\n"
            "\n"
            "class P:\n"
            "    def register(self, api):\n"
            "        raise RuntimeError('register boom')\n"
            "\n"
            "plugin = P()\n",
        )

        from qwenpaw.plugins.architecture import PluginManifest

        manifest = PluginManifest.from_dict(
            json.loads(
                (plugin_dir / "plugin.json").read_text(encoding="utf-8"),
            ),
        )
        module_name = f"plugin_{manifest.id.replace('-', '_')}"
        sub_name = f"{module_name}.helper"

        with pytest.raises(RuntimeError, match="register boom"):
            await loader._load_backend_module(
                manifest.id,
                plugin_dir / "plugin.py",
                plugin_dir,
                None,
                manifest,
            )

        assert module_name not in sys.modules
        assert sub_name not in sys.modules

    @pytest.mark.asyncio
    async def test_bare_import_cleaned_by_file_path(
        self,
        loader,
        tmp_path,
    ):
        """Modules imported via bare ``import`` (after sys.path manipulation)
        are cleaned via __file__ path scanning."""
        plugin_dir = tmp_path / "bare-imp"
        (plugin_dir).mkdir()
        # A helper that the plugin will import via bare name
        (plugin_dir / "bare_helper_xyzzy.py").write_text(
            "MAGIC = 123\n",
            encoding="utf-8",
        )
        _write_plugin(
            plugin_dir,
            "import sys, os\n"
            "sys.path.insert(0, os.path.dirname(__file__))\n"
            "import bare_helper_xyzzy\n"
            "\n"
            "class P:\n"
            "    def register(self, api):\n"
            "        raise RuntimeError('fail after bare import')\n"
            "\n"
            "plugin = P()\n",
        )

        from qwenpaw.plugins.architecture import PluginManifest

        manifest = PluginManifest.from_dict(
            json.loads(
                (plugin_dir / "plugin.json").read_text(encoding="utf-8"),
            ),
        )

        with pytest.raises(RuntimeError, match="fail after bare import"):
            await loader._load_backend_module(
                manifest.id,
                plugin_dir / "plugin.py",
                plugin_dir,
                None,
                manifest,
            )

        assert "bare_helper_xyzzy" not in sys.modules


# ---------------------------------------------------------------------------
# Tests: sys.path cleanup
# ---------------------------------------------------------------------------


class TestSysPathCleanup:
    @pytest.mark.asyncio
    async def test_sys_path_cleaned_on_failure(self, loader, tmp_path):
        """Plugin directory inserted into sys.path is removed on failure."""
        plugin_dir = tmp_path / "path-pol"
        _write_plugin(
            plugin_dir,
            "import sys, os\n"
            "sys.path.insert(0, os.path.dirname(__file__))\n"
            "\n"
            "class P:\n"
            "    def register(self, api):\n"
            "        raise RuntimeError('path pollution test')\n"
            "\n"
            "plugin = P()\n",
        )

        from qwenpaw.plugins.architecture import PluginManifest

        manifest = PluginManifest.from_dict(
            json.loads(
                (plugin_dir / "plugin.json").read_text(encoding="utf-8"),
            ),
        )

        plugin_dir_real = os.path.realpath(str(plugin_dir))
        assert plugin_dir_real not in [os.path.realpath(p) for p in sys.path]

        with pytest.raises(RuntimeError, match="path pollution test"):
            await loader._load_backend_module(
                manifest.id,
                plugin_dir / "plugin.py",
                plugin_dir,
                None,
                manifest,
            )

        assert plugin_dir_real not in [os.path.realpath(p) for p in sys.path]


# ---------------------------------------------------------------------------
# Tests: PluginRegistry cleanup
# ---------------------------------------------------------------------------


class TestRegistryCleanup:
    @pytest.mark.asyncio
    async def test_manifest_cleaned_on_register_failure(
        self,
        loader,
        fresh_registry,
        tmp_path,
    ):
        """Manifest pre-registered before register() is cleaned on failure."""
        plugin_dir = tmp_path / "reg-fail"
        _write_plugin(
            plugin_dir,
            "class P:\n"
            "    def register(self, api):\n"
            "        raise ValueError('register failed')\n"
            "\n"
            "plugin = P()\n",
        )

        from qwenpaw.plugins.architecture import PluginManifest

        manifest = PluginManifest.from_dict(
            json.loads(
                (plugin_dir / "plugin.json").read_text(encoding="utf-8"),
            ),
        )

        with pytest.raises(ValueError, match="register failed"):
            await loader._load_backend_module(
                manifest.id,
                plugin_dir / "plugin.py",
                plugin_dir,
                None,
                manifest,
            )

        assert fresh_registry.get_plugin_manifest(manifest.id) is None

    @pytest.mark.asyncio
    async def test_partial_registrations_cleaned_on_failure(
        self,
        loader,
        fresh_registry,
        tmp_path,
    ):
        """Hooks/middleware registered before the exception are cleaned."""
        plugin_dir = tmp_path / "partial-reg"
        _write_plugin(
            plugin_dir,
            "class P:\n"
            "    def register(self, api):\n"
            "        api.register_startup_hook(\n"
            "            hook_name='orphan_hook',\n"
            "            callback=lambda: None,\n"
            "        )\n"
            "        api.register_middleware(\n"
            "            middleware_factory=lambda ctx, cfg: None,\n"
            "        )\n"
            "        raise RuntimeError('partial failure')\n"
            "\n"
            "plugin = P()\n",
        )

        from qwenpaw.plugins.architecture import PluginManifest

        manifest = PluginManifest.from_dict(
            json.loads(
                (plugin_dir / "plugin.json").read_text(encoding="utf-8"),
            ),
        )

        with pytest.raises(RuntimeError, match="partial failure"):
            await loader._load_backend_module(
                manifest.id,
                plugin_dir / "plugin.py",
                plugin_dir,
                None,
                manifest,
            )

        assert len(fresh_registry.get_startup_hooks()) == 0
        assert len(fresh_registry.get_middleware_factories()) == 0
        assert fresh_registry.get_plugin_manifest(manifest.id) is None


# ---------------------------------------------------------------------------
# Tests: load_all_plugins integration
# ---------------------------------------------------------------------------


class TestLoadAllPluginsIsolation:
    @pytest.mark.asyncio
    async def test_bad_plugin_does_not_block_good_plugin(
        self,
        loader,
        fresh_registry,
        tmp_path,
    ):
        """A failing plugin does not prevent subsequent plugins from loading,
        and leaves no residue in the registry.

        The directory names (aaa-bad, zzz-good) do NOT imply a required
        load order — Path.iterdir() order is filesystem-dependent.  The
        assertions only check presence/absence in the loaded dict and
        registry, which are order-independent.
        """
        # Plugin that fails during register()
        bad_dir = tmp_path / "aaa-bad"
        _write_plugin(
            bad_dir,
            "class P:\n"
            "    def register(self, api):\n"
            "        api.register_startup_hook(\n"
            "            hook_name='orphan',\n"
            "            callback=lambda: None,\n"
            "        )\n"
            "        raise RuntimeError('bad plugin')\n"
            "\n"
            "plugin = P()\n",
        )

        # Plugin that loads successfully
        good_dir = tmp_path / "zzz-good"
        _write_plugin(
            good_dir,
            "class P:\n"
            "    def register(self, api):\n"
            "        api.register_startup_hook(\n"
            "            hook_name='good_hook',\n"
            "            callback=lambda: None,\n"
            "        )\n"
            "\n"
            "plugin = P()\n",
        )

        loaded = await loader.load_all_plugins()

        # Good plugin loaded successfully
        assert "zzz-good" in loaded
        assert loaded["zzz-good"].enabled is True

        # Bad plugin is NOT in loaded dict
        assert "aaa-bad" not in loaded

        # Registry contains only the good plugin's hook, not the bad one
        hooks = fresh_registry.get_startup_hooks()
        hook_names = [h.hook_name for h in hooks]
        assert "good_hook" in hook_names
        assert "orphan" not in hook_names

        # No manifest residue from bad plugin
        assert fresh_registry.get_plugin_manifest("aaa-bad") is None
        assert fresh_registry.get_plugin_manifest("zzz-good") is not None
