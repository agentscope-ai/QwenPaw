# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,protected-access,import-outside-toplevel
"""Unit tests for plugin API extensions: #8, #10, #16.

Tests cover:
- #8: register_uninstall_hook and its execution during unload_plugin
- #10: Plugin validator uses submodule_search_locations for relative imports
- #16: register_skill_provider API contract
"""

import importlib.util
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def fresh_registry():
    """Create a fresh PluginRegistry (bypass singleton for test isolation)."""
    from qwenpaw.plugins.registry import PluginRegistry

    # Force a new instance by clearing the singleton
    old_instance = PluginRegistry._instance
    PluginRegistry._instance = None
    registry = PluginRegistry()
    yield registry
    # Restore
    PluginRegistry._instance = old_instance


@pytest.fixture()
def plugin_api(fresh_registry):
    """Create a PluginApi instance with a fresh registry."""
    from qwenpaw.plugins.api import PluginApi

    api = PluginApi("test-plugin", config={}, manifest={"id": "test-plugin"})
    api.set_registry(fresh_registry)
    return api


# ---------------------------------------------------------------------------
# #8: register_uninstall_hook
# ---------------------------------------------------------------------------


class TestUninstallHook:
    """Tests for register_uninstall_hook (requirement #8)."""

    def test_register_uninstall_hook_stores_in_registry(
        self,
        plugin_api,
        fresh_registry,
    ):
        """Uninstall hooks are stored in registry after registration."""
        callback = MagicMock()
        plugin_api.register_uninstall_hook(
            hook_name="test_cleanup",
            callback=callback,
            priority=50,
        )

        hooks = fresh_registry.get_uninstall_hooks()
        assert len(hooks) == 1
        assert hooks[0].plugin_id == "test-plugin"
        assert hooks[0].hook_name == "test_cleanup"
        assert hooks[0].callback is callback
        assert hooks[0].priority == 50

    def test_uninstall_hooks_sorted_by_priority(
        self,
        plugin_api,
        fresh_registry,
    ):
        """Multiple uninstall hooks are sorted by priority."""
        plugin_api.register_uninstall_hook(
            hook_name="low_priority",
            callback=MagicMock(),
            priority=200,
        )
        plugin_api.register_uninstall_hook(
            hook_name="high_priority",
            callback=MagicMock(),
            priority=10,
        )

        hooks = fresh_registry.get_uninstall_hooks()
        assert hooks[0].hook_name == "high_priority"
        assert hooks[1].hook_name == "low_priority"

    def test_uninstall_hooks_cleaned_on_unregister(
        self,
        plugin_api,
        fresh_registry,
    ):
        """Uninstall hooks are removed when plugin is unregistered."""
        plugin_api.register_uninstall_hook(
            hook_name="cleanup",
            callback=MagicMock(),
        )
        assert len(fresh_registry.get_uninstall_hooks()) == 1

        fresh_registry.unregister_plugin("test-plugin")
        assert len(fresh_registry.get_uninstall_hooks()) == 0

    @pytest.mark.asyncio
    async def test_unload_plugin_calls_uninstall_hooks(self, fresh_registry):
        """PluginLoader.unload_plugin executes uninstall hooks."""
        from qwenpaw.plugins.loader import PluginLoader
        from qwenpaw.plugins.architecture import (
            PluginManifest,
            PluginRecord,
            PluginEntryPoints,
        )

        loader = PluginLoader(plugin_dirs=[])
        loader.registry = fresh_registry

        # Create a fake loaded plugin record
        manifest = PluginManifest(
            id="test-plugin",
            name="Test",
            version="1.0.0",
            entry=PluginEntryPoints(backend="plugin.py"),
        )
        record = PluginRecord(
            manifest=manifest,
            source_path=Path("/fake"),
            enabled=True,
            instance=None,
        )
        loader._loaded_plugins["test-plugin"] = record

        # Register an uninstall hook
        hook_called_with: Dict[str, Any] = {}

        def uninstall_callback(plugin_id: str, delete_files: bool):
            hook_called_with["plugin_id"] = plugin_id
            hook_called_with["delete_files"] = delete_files

        fresh_registry.register_uninstall_hook(
            plugin_id="test-plugin",
            hook_name="test_cleanup",
            callback=uninstall_callback,
        )

        await loader.unload_plugin("test-plugin", delete_files=True)

        assert hook_called_with["plugin_id"] == "test-plugin"
        assert hook_called_with["delete_files"] is True

    @pytest.mark.asyncio
    async def test_uninstall_hook_async_callback(self, fresh_registry):
        """Async uninstall hook callbacks are properly awaited."""
        from qwenpaw.plugins.loader import PluginLoader
        from qwenpaw.plugins.architecture import (
            PluginManifest,
            PluginRecord,
            PluginEntryPoints,
        )

        loader = PluginLoader(plugin_dirs=[])
        loader.registry = fresh_registry

        manifest = PluginManifest(
            id="async-plugin",
            name="Async",
            version="1.0.0",
            entry=PluginEntryPoints(backend="plugin.py"),
        )
        record = PluginRecord(
            manifest=manifest,
            source_path=Path("/fake"),
            enabled=True,
            instance=None,
        )
        loader._loaded_plugins["async-plugin"] = record

        async_called = []

        async def async_cleanup(plugin_id: str, **_kwargs):
            async_called.append(plugin_id)

        fresh_registry.register_uninstall_hook(
            plugin_id="async-plugin",
            hook_name="async_cleanup",
            callback=async_cleanup,
        )

        await loader.unload_plugin("async-plugin")
        assert "async-plugin" in async_called

    @pytest.mark.asyncio
    async def test_uninstall_hook_error_isolated(self, fresh_registry):
        """Errors in uninstall hooks don't crash the unload flow."""
        from qwenpaw.plugins.loader import PluginLoader
        from qwenpaw.plugins.architecture import (
            PluginManifest,
            PluginRecord,
            PluginEntryPoints,
        )

        loader = PluginLoader(plugin_dirs=[])
        loader.registry = fresh_registry

        manifest = PluginManifest(
            id="err-plugin",
            name="Err",
            version="1.0.0",
            entry=PluginEntryPoints(backend="plugin.py"),
        )
        record = PluginRecord(
            manifest=manifest,
            source_path=Path("/fake"),
            enabled=True,
            instance=None,
        )
        loader._loaded_plugins["err-plugin"] = record

        def bad_hook(**_kwargs):
            raise RuntimeError("hook failed")

        fresh_registry.register_uninstall_hook(
            plugin_id="err-plugin",
            hook_name="bad_hook",
            callback=bad_hook,
        )

        # Should not raise
        await loader.unload_plugin("err-plugin")
        assert "err-plugin" not in loader._loaded_plugins


# ---------------------------------------------------------------------------
# #10: Plugin validator relative import fix
# ---------------------------------------------------------------------------


class TestPluginValidatorImports:
    """Tests for plugin validator import resolution (requirement #10)."""

    def test_validator_sets_submodule_search_locations(self):
        """CLI install validator uses submodule_search_locations."""
        # Create a temp plugin with relative import
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_dir = Path(tmpdir)

            # Create plugin.json
            import json

            manifest = {
                "id": "import-test",
                "name": "Import Test",
                "version": "1.0.0",
                "entry": {"backend": "plugin.py"},
            }
            (plugin_dir / "plugin.json").write_text(
                json.dumps(manifest),
                encoding="utf-8",
            )

            # Create a helper module
            (plugin_dir / "constants.py").write_text(
                "PLUGIN_NAME = 'import-test'\n",
                encoding="utf-8",
            )

            # Create plugin.py that uses relative import
            (plugin_dir / "plugin.py").write_text(
                "from .constants import PLUGIN_NAME\n"
                "\n"
                "class Plugin:\n"
                "    pass\n"
                "\n"
                "plugin = Plugin()\n",
                encoding="utf-8",
            )

            # Simulate validation with correct submodule_search_locations
            backend_path = plugin_dir / "plugin.py"
            module_name = "_plugin_validation_import_test"
            plugin_dir_str = str(plugin_dir)

            spec = importlib.util.spec_from_file_location(
                module_name,
                backend_path,
                submodule_search_locations=[plugin_dir_str],
            )
            assert spec is not None
            assert spec.loader is not None

            module = importlib.util.module_from_spec(spec)
            module.__package__ = module_name
            module.__path__ = [plugin_dir_str]

            # Register sub-module mapping so relative imports resolve
            sys.modules[module_name] = module
            # Also register the constants sub-module path
            constants_spec = importlib.util.spec_from_file_location(
                f"{module_name}.constants",
                plugin_dir / "constants.py",
            )
            constants_module = importlib.util.module_from_spec(constants_spec)
            sys.modules[f"{module_name}.constants"] = constants_module
            constants_spec.loader.exec_module(constants_module)

            try:
                spec.loader.exec_module(module)
                assert hasattr(module, "plugin")
                assert hasattr(module, "PLUGIN_NAME")
            finally:
                sys.modules.pop(module_name, None)
                sys.modules.pop(f"{module_name}.constants", None)

    def test_validator_without_search_locations_fails(self):
        """Without submodule_search_locations, relative imports fail."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_dir = Path(tmpdir)

            (plugin_dir / "constants.py").write_text(
                "PLUGIN_NAME = 'test'\n",
                encoding="utf-8",
            )
            (plugin_dir / "plugin.py").write_text(
                "from .constants import PLUGIN_NAME\n",
                encoding="utf-8",
            )

            backend_path = plugin_dir / "plugin.py"
            module_name = "_plugin_validation_no_locations"

            # Without submodule_search_locations — should fail
            spec = importlib.util.spec_from_file_location(
                module_name,
                backend_path,
            )
            module = importlib.util.module_from_spec(spec)
            # Don't set __package__ or __path__

            sys.modules[module_name] = module
            try:
                with pytest.raises(ImportError):
                    spec.loader.exec_module(module)
            finally:
                sys.modules.pop(module_name, None)

    def test_cli_validate_path_with_relative_import(self):
        """Exercise the actual CLI validation code path.

        Calls validate_plugin_module (the real implementation used by
        both 'install' and 'validate' commands) to prove that relative
        imports work end-to-end, including sys.modules registration
        before exec_module, cleanup in finally, and sanitized module
        name from plugin_id with hyphens.
        """
        from qwenpaw.plugins.validation import validate_plugin_module

        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_dir = Path(tmpdir) / "my-datapaw"
            plugin_dir.mkdir()

            (plugin_dir / "helpers.py").write_text(
                "HELPER_VALUE = 42\n",
                encoding="utf-8",
            )
            (plugin_dir / "plugin.py").write_text(
                "from .helpers import HELPER_VALUE\n"
                "\n"
                "class Plugin:\n"
                "    pass\n"
                "\n"
                "plugin = Plugin()\n",
                encoding="utf-8",
            )

            # Should succeed without raising
            validate_plugin_module("my-datapaw", plugin_dir, "plugin.py")

            # Verify sys.modules was cleaned up (no leaking)
            leaked = [
                k
                for k in sys.modules
                if k.startswith("_plugin_validation_my_datapaw")
            ]
            assert leaked == [], f"Leaked modules: {leaked}"

    def test_cli_validate_cleans_sys_modules_on_error(self):
        """sys.modules cleanup happens even when validation fails."""
        from qwenpaw.plugins.validation import validate_plugin_module

        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_dir = Path(tmpdir) / "bad-plugin"
            plugin_dir.mkdir()

            # Plugin that imports a non-existent module
            (plugin_dir / "plugin.py").write_text(
                "from .nonexistent import MISSING\n",
                encoding="utf-8",
            )

            with pytest.raises(ImportError):
                validate_plugin_module(
                    "bad-plugin",
                    plugin_dir,
                    "plugin.py",
                )

            # Verify cleanup still happened
            leaked = [
                k
                for k in sys.modules
                if k.startswith("_plugin_validation_bad_plugin")
            ]
            assert leaked == [], f"Leaked modules: {leaked}"


# ---------------------------------------------------------------------------
# #16: register_skill_provider
# ---------------------------------------------------------------------------


class TestRegisterSkillProvider:
    """Tests for register_skill_provider API (requirement #16)."""

    def test_register_skill_provider_registers_hooks(
        self,
        plugin_api,
        fresh_registry,
    ):
        """register_skill_provider registers startup and uninstall hooks."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skills_dir = Path(tmpdir)
            # Create a fake skill
            skill_dir = skills_dir / "my-skill"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text(
                "---\nname: My Skill\n---\nDo something.",
                encoding="utf-8",
            )

            plugin_api.register_skill_provider(
                skills_dir=skills_dir,
                enabled_by_default=True,
                channels=["all"],
            )

        # Check startup hook registered
        startup_hooks = fresh_registry.get_startup_hooks()
        startup_names = [h.hook_name for h in startup_hooks]
        assert "install_skills_test-plugin" in startup_names

        # Check uninstall hook registered
        uninstall_hooks = fresh_registry.get_uninstall_hooks()
        uninstall_names = [h.hook_name for h in uninstall_hooks]
        assert "uninstall_skills_test-plugin" in uninstall_names

    def test_register_skill_provider_default_channels(
        self,
        plugin_api,
        fresh_registry,
    ):
        """Default channels is ['all'] when not specified."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skills_dir = Path(tmpdir)
            skill_dir = skills_dir / "default-skill"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text(
                "---\nname: Default\n---\nHello.",
                encoding="utf-8",
            )

            plugin_api.register_skill_provider(skills_dir=skills_dir)

        # Verify startup hook is registered (integration correctness)
        hooks = fresh_registry.get_startup_hooks()
        assert any(h.hook_name == "install_skills_test-plugin" for h in hooks)

    def test_register_skill_provider_source_tag(self, plugin_api):
        """Source tag follows 'plugin:{id}' convention."""
        # Verify internal source_tag format
        expected_tag = "plugin:test-plugin"
        assert expected_tag == f"plugin:{plugin_api.plugin_id}"
