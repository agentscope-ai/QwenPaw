# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,protected-access,import-outside-toplevel
"""Unit tests for plugin API extensions: #8, #10, #16.

Tests cover:
- #8: register_uninstall_hook and its execution during unload_plugin
- #10: Plugin validator uses submodule_search_locations for relative imports
- #16: register_skill_provider API contract
"""

import logging
import sys
import tempfile
import types
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Stub missing agentscope 2.0 modules so MultiAgentManager can be imported
# in environments where agentscope 2.0 is not installed.
# ---------------------------------------------------------------------------
_AGENTSCOPE_STUBS = [
    "agentscope.state",
]

for _mod_name in _AGENTSCOPE_STUBS:
    if _mod_name not in sys.modules:
        _stub = types.ModuleType(_mod_name)
        # Provide placeholder attributes that downstream imports expect.
        # type: ignore[attr-defined]
        _stub.AgentState = type("AgentState", (), {})
        sys.modules[_mod_name] = _stub


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def fresh_registry():
    """Create a fresh PluginRegistry (bypass singleton for test isolation).

    .. warning::
        This fixture is NOT safe for parallel test execution (e.g.
        ``pytest-xdist``).  It mutates the class-level ``_instance``
        attribute without locking.  Only use with sequential test runs.
    """
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


class TestSlashCommandLifecycle:
    """Plugin slash commands use successful registration identities."""

    @staticmethod
    def _workspace(agent_id="ws-1"):
        from qwenpaw.runtime.slash_command_registry import SlashCommandRegistry

        return SimpleNamespace(
            agent_id=agent_id,
            plugins=SimpleNamespace(
                slash_command_registry=SlashCommandRegistry(),
            ),
        )

    @pytest.mark.asyncio
    async def test_plugin_api_stamps_command_owner(
        self,
        plugin_api,
        fresh_registry,
    ):
        workspace = self._workspace()
        fresh_registry.set_workspace_manager(
            SimpleNamespace(agents={workspace.agent_id: workspace}),
        )
        plugin_api.register_slash_command("owned", MagicMock())
        await fresh_registry.projector.project(
            "slash_command",
            "owned",
            "test-plugin",
        )
        spec, _args = workspace.plugins.slash_command_registry.resolve(
            "/owned",
        )
        assert spec.owner_plugin_id == "test-plugin"

    @pytest.mark.asyncio
    async def test_plugin_collision_is_error_logged_and_propagated(
        self,
        plugin_api,
        fresh_registry,
        caplog,
    ):
        from qwenpaw.runtime.slash_command_registry import CommandSpec
        from qwenpaw.plugins.workspace_projector import ProjectionError

        workspace = self._workspace()
        original = CommandSpec(name="reserved", handler=MagicMock())
        workspace.plugins.slash_command_registry.register(original)
        fresh_registry.set_workspace_manager(
            SimpleNamespace(agents={workspace.agent_id: workspace}),
        )
        plugin_api.register_slash_command("reserved", MagicMock())
        with caplog.at_level(logging.ERROR, logger="qwenpaw.plugins.api"):
            with pytest.raises(ProjectionError):
                await fresh_registry.projector.project(
                    "slash_command",
                    "reserved",
                    "test-plugin",
                )
        assert "Projection slash_command failed" in caplog.text
        await fresh_registry.projector.revoke(
            "slash_command",
            "reserved",
            "test-plugin",
        )
        assert (
            workspace.plugins.slash_command_registry.resolve("/reserved")[0]
            is original
        )

    @pytest.mark.asyncio
    async def test_failed_projection_can_revoke_only_successful_bindings(
        self,
        plugin_api,
        fresh_registry,
    ):
        from qwenpaw.runtime.slash_command_registry import CommandSpec
        from qwenpaw.plugins.workspace_projector import ProjectionError

        first = self._workspace("ws-1")
        second = self._workspace("ws-2")
        occupant = CommandSpec(name="reserved", handler=MagicMock())
        second.plugins.slash_command_registry.register(occupant)
        fresh_registry.set_workspace_manager(
            SimpleNamespace(agents={"ws-1": first, "ws-2": second}),
        )
        plugin_api.register_slash_command("reserved", MagicMock())
        with pytest.raises(ProjectionError):
            await fresh_registry.projector.project(
                "slash_command",
                "reserved",
                "test-plugin",
            )
        await fresh_registry.projector.revoke(
            "slash_command",
            "reserved",
            "test-plugin",
        )
        assert (
            first.plugins.slash_command_registry.resolve("/reserved") is None
        )
        assert (
            second.plugins.slash_command_registry.resolve("/reserved")[0]
            is occupant
        )

    @pytest.mark.asyncio
    async def test_unload_revokes_bindings_and_reports_untracked_rows(
        self,
        plugin_api,
        fresh_registry,
        tmp_path,
    ):
        from qwenpaw.plugins.architecture import (
            PluginEntryPoints,
            PluginManifest,
            PluginRecord,
        )
        from qwenpaw.plugins.loader import PluginLoader
        from qwenpaw.runtime.slash_command_registry import CommandSpec

        workspace = self._workspace()
        commands = workspace.plugins.slash_command_registry
        builtin = CommandSpec(name="builtin", handler=MagicMock())
        untracked = CommandSpec(
            name="untracked",
            handler=MagicMock(),
            owner_plugin_id="test-plugin",
        )
        commands.register(builtin)
        commands.register(untracked)
        fresh_registry.set_workspace_manager(
            SimpleNamespace(agents={workspace.agent_id: workspace}),
        )
        loader = PluginLoader(plugin_dirs=[])
        instance = loader.lifecycle.ensure_instance("test-plugin")
        plugin_api.bind_instance(instance)
        plugin_api.register_slash_command(
            "reloadable",
            MagicMock(),
            aliases=("stale",),
        )
        await fresh_registry.projector.project(
            "slash_command",
            "reloadable",
            "test-plugin",
        )
        loader._loaded_plugins["test-plugin"] = PluginRecord(
            manifest=PluginManifest(
                id="test-plugin",
                name="Test",
                version="1.0.0",
                entry=PluginEntryPoints(backend="plugin.py"),
            ),
            source_path=tmp_path,
            enabled=True,
            instance=None,
            status="active",
        )
        report = await loader.unload_plugin("test-plugin")
        assert commands.names() == ["builtin", "untracked"]
        assert commands.resolve("/builtin")[0] is builtin
        assert commands.resolve("/untracked")[0] is untracked
        assert not report.clean
        assert report.workspace_leaks
        replacement = CommandSpec(
            name="reloadable",
            aliases=("fresh",),
            handler=MagicMock(),
            owner_plugin_id="test-plugin",
        )
        commands.register(replacement)
        assert commands.resolve("/reloadable")[0] is replacement
        assert commands.resolve("/stale") is None


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
        with pytest.warns(DeprecationWarning, match="register_uninstall_hook"):
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

    def test_legacy_hooks_are_deprecated(self, plugin_api):
        with pytest.warns(DeprecationWarning, match="register_uninstall_hook"):
            plugin_api.register_uninstall_hook("u", lambda: None)
        with pytest.warns(DeprecationWarning, match="register_shutdown_hook"):
            plugin_api.register_shutdown_hook("s", lambda: None)

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
        """register_skill_provider uses install-layer teardown, not hooks."""
        from qwenpaw.plugins.lifecycle import PluginInstance

        inst = PluginInstance("test-plugin")
        plugin_api.bind_instance(inst)
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

        uninstall_hooks = fresh_registry.get_uninstall_hooks()
        assert uninstall_hooks == []
        assert any(
            entry.desc.startswith("skill_provider:") for entry in inst._install
        )

    def test_register_skill_provider_registers_workspace_created_hook(
        self,
        plugin_api,
        fresh_registry,
    ):
        """register_skill_provider also registers a workspace_created hook."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skills_dir = Path(tmpdir)
            skill_dir = skills_dir / "auto-skill"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text(
                "---\nname: Auto Skill\n---\nAuto.",
                encoding="utf-8",
            )

            plugin_api.register_skill_provider(
                skills_dir=skills_dir,
                enabled_by_default=True,
                channels=["all"],
            )

        hooks = fresh_registry.get_workspace_created_hooks()
        hook_names = [h.hook_name for h in hooks]
        assert "provision_skills_test-plugin" in hook_names

    def test_skill_install_records_provision_inventory(
        self,
        plugin_api,
        tmp_path: Path,
        monkeypatch,
    ):
        """Skill copy goes through provision_files (hash / create branch)."""
        from qwenpaw.plugins.lifecycle import PluginInstance
        from qwenpaw.plugins.provision import load_inventory

        monkeypatch.setattr(
            "qwenpaw.constant.WORKING_DIR",
            tmp_path / "work",
        )
        inst = PluginInstance("test-plugin")
        plugin_api.bind_instance(inst)
        plugin_api.manifest = {
            "id": "test-plugin",
            "version": "3.1.0",
        }
        skills_dir = tmp_path / "skills"
        skill_dir = skills_dir / "hashed-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: hashed\n---\nHi.",
            encoding="utf-8",
        )
        workspace = tmp_path / "ws"
        workspace.mkdir()
        plugin_api._install_skills_into_workspace(
            {"workspace_dir": str(workspace), "agent_id": "a"},
            skills_dir,
            "plugin:test-plugin",
            True,
            ["all"],
        )
        dest = workspace / "skills" / "hashed-skill"
        data = load_inventory("test-plugin")
        loc = data["locations"][str(dest)]
        assert loc["owned"] is True
        assert "branch" not in loc
        assert loc["version"] == "3.1.0"
        assert loc["files"]["SKILL.md"]["factory_hash"]


# ---------------------------------------------------------------------------
# workspace_created hook infrastructure
# ---------------------------------------------------------------------------


class TestWorkspaceCreatedHook:
    """Tests for workspace_created hook registration and dispatch."""

    def test_register_workspace_created_hook_stores_in_registry(
        self,
        plugin_api,
        fresh_registry,
    ):
        """workspace_created hooks are stored in registry."""
        callback = MagicMock()
        plugin_api.register_workspace_created_hook(
            hook_name="on_ws_created",
            callback=callback,
            priority=50,
        )

        hooks = fresh_registry.get_workspace_created_hooks()
        assert len(hooks) == 1
        assert hooks[0].plugin_id == "test-plugin"
        assert hooks[0].hook_name == "on_ws_created"
        assert hooks[0].callback is callback
        assert hooks[0].priority == 50


# ---------------------------------------------------------------------------
# _fire_workspace_created_hooks: sync / async dispatch
# ---------------------------------------------------------------------------


class TestFireWorkspaceCreatedHooks:
    """Tests for async _fire_workspace_created_hooks dispatch logic."""

    @pytest.mark.asyncio
    async def test_sync_callback_offloaded_to_thread(
        self,
        plugin_api,
    ):
        """Sync callbacks are executed via asyncio.to_thread (non-blocking)."""
        invoked_with = {}

        def sync_hook(workspace_info: dict) -> None:
            invoked_with.update(workspace_info)

        plugin_api.register_workspace_created_hook(
            hook_name="sync_hook",
            callback=sync_hook,
        )

        from qwenpaw.app.multi_agent_manager import MultiAgentManager

        await MultiAgentManager._fire_workspace_created_hooks(
            {"agent_id": "a1", "workspace_dir": "/tmp/ws"},
        )

        assert invoked_with == {
            "agent_id": "a1",
            "workspace_dir": "/tmp/ws",
        }

    @pytest.mark.asyncio
    async def test_async_callback_awaited(
        self,
        plugin_api,
    ):
        """Async callbacks are directly awaited."""
        invoked_with = {}

        async def async_hook(workspace_info: dict) -> None:
            invoked_with.update(workspace_info)

        plugin_api.register_workspace_created_hook(
            hook_name="async_hook",
            callback=async_hook,
        )

        from qwenpaw.app.multi_agent_manager import MultiAgentManager

        await MultiAgentManager._fire_workspace_created_hooks(
            {"agent_id": "a2", "workspace_dir": "/tmp/ws2"},
        )

        assert invoked_with == {
            "agent_id": "a2",
            "workspace_dir": "/tmp/ws2",
        }

    @pytest.mark.asyncio
    async def test_hook_error_does_not_block_subsequent_hooks(
        self,
        plugin_api,
    ):
        """A failing hook does not prevent later hooks from running."""
        results = []

        def failing_hook(_info: dict) -> None:
            raise RuntimeError("boom")

        def good_hook(_info: dict) -> None:
            results.append("ok")

        plugin_api.register_workspace_created_hook(
            hook_name="fail_first",
            callback=failing_hook,
            priority=10,
        )
        plugin_api.register_workspace_created_hook(
            hook_name="succeed_second",
            callback=good_hook,
            priority=20,
        )

        from qwenpaw.app.multi_agent_manager import MultiAgentManager

        await MultiAgentManager._fire_workspace_created_hooks(
            {"agent_id": "a3", "workspace_dir": "/tmp/ws3"},
        )

        assert results == ["ok"]

    def test_workspace_created_hooks_sorted_by_priority(
        self,
        plugin_api,
        fresh_registry,
    ):
        """Multiple workspace_created hooks are sorted by priority."""
        plugin_api.register_workspace_created_hook(
            hook_name="low_prio",
            callback=MagicMock(),
            priority=200,
        )
        plugin_api.register_workspace_created_hook(
            hook_name="high_prio",
            callback=MagicMock(),
            priority=10,
        )

        hooks = fresh_registry.get_workspace_created_hooks()
        assert hooks[0].hook_name == "high_prio"
        assert hooks[1].hook_name == "low_prio"

    def test_workspace_created_hooks_cleaned_on_unregister(
        self,
        plugin_api,
        fresh_registry,
    ):
        """workspace_created hooks are removed when plugin is unregistered."""
        plugin_api.register_workspace_created_hook(
            hook_name="provision",
            callback=MagicMock(),
        )
        assert len(fresh_registry.get_workspace_created_hooks()) == 1

        fresh_registry.unregister_plugin("test-plugin")
        assert len(fresh_registry.get_workspace_created_hooks()) == 0
