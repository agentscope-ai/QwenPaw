# -*- coding: utf-8 -*-
"""Plugin router lifecycle wiring: post-load / unload bookkeeping.

The helpers covered here run *around* the loader: registering providers
and control commands, executing startup hooks, syncing plugin tools into
every agent config, and cleaning the same registrations up again on
uninstall.  They are exercised through stub loader / app objects so no
real plugin module is ever imported.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
# pylint: disable=use-implicit-booleaness-not-comparison
from __future__ import annotations

import io
import json
import tempfile
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from qwenpaw.app.routers import plugins as plugins_module
from qwenpaw.app.routers.plugins import (
    _DOWNLOAD_TIMEOUT,
    _async_download,
    _collect_plugin_runtime_ids,
    _load_plugin_with_optional_force_reinstall,
    _extract_downloaded_plugin_zip,
    _extract_plugin_zip_bytes,
    _post_load_setup,
    _post_unload_cleanup,
    _remove_named_tools_from_agents,
    _remove_plugin_tools_from_agents,
    _schedule_all_agents_reload,
    _sync_plugin_tools_to_agents,
    install_plugin,
    install_plugin_source,
    search_market_plugins,
    uninstall_plugin_source,
    upload_plugin,
)


# Patch targets longer than the 79-column limit are hoisted so each stays a
# single string literal (pylint W1404 implicit-str-concat).
_FINISH_INSTALL = (
    "qwenpaw.app.routers.plugins._finish_plugin_install_after_load"
)
_CMD_HANDLER_REGISTER = "qwenpaw.runtime.commands.control.register_command"
_CMD_HANDLER_UNREGISTER = "qwenpaw.runtime.commands.control.unregister_command"
_PRIORITY_REGISTER = (
    "qwenpaw.app.channels.command_registry.CommandRegistry.register_command"
)
_PRIORITY_UNREGISTER = (
    "qwenpaw.app.channels.command_registry.CommandRegistry.unregister_command"
)
_SYNC_TOOLS = "qwenpaw.app.routers.plugins._sync_plugin_tools_to_agents"


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


def _zip_bytes(entries: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
    return buffer.getvalue()


def _record(plugin_id: str = "plug", meta: dict | None = None) -> Any:
    """A loaded-plugin record stand-in (only the fields routes read)."""
    manifest = SimpleNamespace(
        id=plugin_id,
        name=f"{plugin_id} display name",
        version="1.2.3",
        description="desc",
        author="auth",
        plugin_type="general",
        entry=SimpleNamespace(frontend="ui/index.js"),
        meta=meta if meta is not None else {},
    )
    return SimpleNamespace(
        manifest=manifest,
        source_path=Path("/nonexistent/plugin"),
        enabled=True,
    )


def _app(
    loader: Any = None,
    provider_manager: Any = None,
) -> Any:
    app = MagicMock(name="App")
    app.state.plugin_loader = loader
    app.state.provider_manager = provider_manager
    return app


def _request(app: Any) -> Any:
    return SimpleNamespace(app=app)


class _LifecycleStub:
    """Async context manager recording enter/exit order."""

    def __init__(self, log: list[str], name: str) -> None:
        self._log = log
        self._name = name

    async def __aenter__(self) -> None:
        self._log.append(f"{self._name}:enter")

    async def __aexit__(self, *exc: Any) -> None:
        self._log.append(f"{self._name}:exit")


def _loader_stub(
    log: list[str],
    *,
    record: Any = None,
    registry: Any = None,
    load_result: Any = "LOADED",
) -> MagicMock:
    """A PluginLoader stand-in recording lifecycle and load calls."""
    loader = MagicMock(name="PluginLoader")
    loader.get_loaded_plugin.return_value = record
    loader.get_all_loaded_plugins.return_value = (
        {record.manifest.id: record} if record is not None else {}
    )
    loader.registry = registry if registry is not None else MagicMock()
    loader.plugin_lifecycle.side_effect = lambda plugin_id: _LifecycleStub(
        log,
        f"lifecycle({plugin_id})",
    )
    loader.unload_plugin = AsyncMock(
        side_effect=lambda *a, **k: log.append("unload_plugin"),
    )

    def _load(**kwargs):
        log.append(
            "load_plugin_from_path:"
            f"force={kwargs.get('force')}:"
            f"before={kwargs.get('before_force_unload') is not None}:"
            f"after={kwargs.get('after_force_unload') is not None}",
        )
        return load_result

    loader.load_plugin_from_path = AsyncMock(side_effect=_load)
    return loader


class _AgentCfg:
    """Agent config stand-in carrying a mutable builtin_tools dict."""

    def __init__(self, tools: dict[str, Any]) -> None:
        self.tools = SimpleNamespace(builtin_tools=tools)


class _ConfigLayer:
    """Patch ``load_config`` / ``load_agent_config`` / ``save_agent_config``.

    Records every call so assertions target observable effects (which
    agents were read, which were written, with what payload) rather than
    mock internals.
    """

    def __init__(
        self,
        profiles: dict[str, Any] | None,
        agent_cfgs: dict[str, Any] | None = None,
        *,
        load_config_error: Exception | None = None,
        failing_agents: tuple[str, ...] = (),
    ) -> None:
        self.profiles = profiles
        self.agent_cfgs = dict(agent_cfgs or {})
        self.load_config_error = load_config_error
        self.failing_agents = set(failing_agents)
        self.loaded_agents: list[str] = []
        self.saved: list[tuple[str, Any]] = []
        self._patches = (
            patch(
                "qwenpaw.config.utils.load_config",
                side_effect=self._load_config,
            ),
            patch(
                "qwenpaw.config.config.load_agent_config",
                side_effect=self._load_agent_config,
            ),
            patch(
                "qwenpaw.config.config.save_agent_config",
                side_effect=self._save_agent_config,
            ),
        )

    # -- stub behaviour ----------------------------------------------------
    def _load_config(self):
        if self.load_config_error is not None:
            raise self.load_config_error
        agents = (
            SimpleNamespace(profiles=self.profiles)
            if self.profiles is not None
            else None
        )
        return SimpleNamespace(agents=agents)

    def _load_agent_config(self, agent_id: str):
        self.loaded_agents.append(agent_id)
        if agent_id in self.failing_agents:
            raise RuntimeError(f"boom-{agent_id}")
        cfg = self.agent_cfgs.get(agent_id)
        if cfg is None:
            raise KeyError(agent_id)
        return cfg

    def _save_agent_config(self, agent_id: str, cfg: Any) -> None:
        self.saved.append((agent_id, cfg))

    # -- context manager ---------------------------------------------------
    def __enter__(self) -> "_ConfigLayer":
        for item in self._patches:
            item.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        for item in reversed(self._patches):
            item.stop()


def _provider_reg(plugin_id: str, provider_id: str) -> Any:
    return SimpleNamespace(
        plugin_id=plugin_id,
        provider_id=provider_id,
        provider_class=type("StubProvider", (), {}),
        label="Stub",
        base_url="https://stub.invalid",
        metadata={"k": "v"},
    )


def _cmd_reg(plugin_id: str, command_name: str) -> Any:
    return SimpleNamespace(
        plugin_id=plugin_id,
        handler=SimpleNamespace(command_name=command_name),
        priority_level=7,
    )


def _hook_reg(plugin_id: str, hook_name: str, callback: Any) -> Any:
    return SimpleNamespace(
        plugin_id=plugin_id,
        hook_name=hook_name,
        callback=callback,
    )


def _registry(
    providers: dict | None = None,
    commands: list | None = None,
    hooks: list | None = None,
) -> Any:
    registry = MagicMock(name="PluginRegistry")
    registry.get_all_providers.return_value = providers or {}
    registry.get_control_commands.return_value = commands or []
    registry.get_startup_hooks.return_value = hooks or []
    return registry


# ---------------------------------------------------------------------------
# _sync_plugin_tools_to_agents
# ---------------------------------------------------------------------------


class TestSyncPluginToolsToAgents:
    def test_unknown_plugin_touches_no_config(self):
        loader = MagicMock()
        loader.get_loaded_plugin.return_value = None
        with _ConfigLayer({"a": object()}) as layer:
            _sync_plugin_tools_to_agents(loader, "ghost")
        assert layer.loaded_agents == []
        assert layer.saved == []

    def test_manifest_without_tools_touches_no_config(self):
        loader = MagicMock()
        loader.get_loaded_plugin.return_value = _record(meta={})
        with _ConfigLayer({"a": object()}) as layer:
            _sync_plugin_tools_to_agents(loader, "plug")
        assert layer.loaded_agents == []
        assert layer.saved == []

    def test_no_configured_agents_saves_nothing(self):
        loader = MagicMock()
        loader.get_loaded_plugin.return_value = _record(
            meta={"tool_name": "alpha"},
        )
        with _ConfigLayer({}) as layer:
            _sync_plugin_tools_to_agents(loader, "plug")
        assert layer.loaded_agents == []
        assert layer.saved == []

    def test_adds_missing_tools_disabled(self):
        loader = MagicMock()
        loader.get_loaded_plugin.return_value = _record(
            meta={"tools": [{"name": "alpha"}, {"name": "beta"}]},
        )
        cfg_a = _AgentCfg({"alpha": object()})
        cfg_b = _AgentCfg({})
        with _ConfigLayer(
            {"a": object(), "b": object()},
            {"a": cfg_a, "b": cfg_b},
        ) as layer:
            _sync_plugin_tools_to_agents(loader, "plug")
        assert [name for name, _ in layer.saved] == ["a", "b"]
        # already-present tool is left alone, the new one is added disabled
        assert cfg_a.tools.builtin_tools["alpha"] is not None
        beta = cfg_a.tools.builtin_tools["beta"]
        assert (beta.name, beta.enabled, beta.config) == ("beta", False, {})
        assert set(cfg_b.tools.builtin_tools) == {"alpha", "beta"}
        assert cfg_b.tools.builtin_tools["alpha"].enabled is False

    def test_second_call_is_a_no_op(self):
        loader = MagicMock()
        loader.get_loaded_plugin.return_value = _record(
            meta={"tool_name": "alpha"},
        )
        cfg = _AgentCfg({})
        with _ConfigLayer({"a": object()}, {"a": cfg}) as layer:
            _sync_plugin_tools_to_agents(loader, "plug")
            _sync_plugin_tools_to_agents(loader, "plug")
        assert len(layer.saved) == 1

    def test_one_bad_agent_does_not_block_the_other(self, caplog):
        loader = MagicMock()
        loader.get_loaded_plugin.return_value = _record(
            meta={"tool_name": "alpha"},
        )
        cfg_b = _AgentCfg({})
        with _ConfigLayer(
            {"a": object(), "b": object()},
            {"b": cfg_b},
            failing_agents=("a",),
        ) as layer:
            _sync_plugin_tools_to_agents(loader, "plug")
        assert [name for name, _ in layer.saved] == ["b"]
        assert "boom-a" in caplog.text

    def test_load_config_failure_is_swallowed(self, caplog):
        loader = MagicMock()
        loader.get_loaded_plugin.return_value = _record(
            meta={"tool_name": "alpha"},
        )
        with _ConfigLayer(
            None,
            load_config_error=RuntimeError("cfg-down"),
        ) as layer:
            _sync_plugin_tools_to_agents(loader, "plug")
        assert layer.loaded_agents == []
        assert layer.saved == []
        assert "Tool sync skipped" in caplog.text
        assert "cfg-down" in caplog.text


# ---------------------------------------------------------------------------
# _remove_named_tools_from_agents / _remove_plugin_tools_from_agents
# ---------------------------------------------------------------------------


class TestRemoveToolsFromAgents:
    def test_empty_tool_list_short_circuits(self):
        with _ConfigLayer({"a": object()}) as layer:
            _remove_named_tools_from_agents("plug", [])
        assert layer.loaded_agents == []
        assert layer.saved == []

    def test_removes_only_the_named_tools(self):
        cfg = _AgentCfg({"alpha": object(), "keep": object()})
        with _ConfigLayer({"a": object()}, {"a": cfg}) as layer:
            _remove_named_tools_from_agents("plug", ["alpha", "ghost"])
        assert list(cfg.tools.builtin_tools) == ["keep"]
        assert [name for name, _ in layer.saved] == ["a"]

    def test_absent_tool_saves_nothing(self):
        cfg = _AgentCfg({"keep": object()})
        with _ConfigLayer({"a": object()}, {"a": cfg}) as layer:
            _remove_named_tools_from_agents("plug", ["alpha"])
        assert layer.saved == []
        assert list(cfg.tools.builtin_tools) == ["keep"]

    def test_one_bad_agent_does_not_block_the_other(self, caplog):
        cfg_b = _AgentCfg({"alpha": object()})
        with _ConfigLayer(
            {"a": object(), "b": object()},
            {"b": cfg_b},
            failing_agents=("a",),
        ) as layer:
            _remove_named_tools_from_agents("plug", ["alpha"])
        assert [name for name, _ in layer.saved] == ["b"]
        assert cfg_b.tools.builtin_tools == {}
        assert "boom-a" in caplog.text

    def test_load_config_failure_logs_and_returns(self, caplog):
        with _ConfigLayer(
            None,
            load_config_error=RuntimeError("cfg-down"),
        ) as layer:
            _remove_named_tools_from_agents("plug", ["alpha"])
        assert layer.saved == []
        assert "Tool removal from agents skipped" in caplog.text

    def test_newlines_in_ids_are_stripped_from_the_log(self, caplog):
        """``_log_safe`` must keep request-derived text out of log lines."""
        with _ConfigLayer(
            None,
            load_config_error=RuntimeError("bad\nvalue"),
        ) as layer:
            _remove_named_tools_from_agents("plug\nid", ["alpha"])
        assert layer.saved == []
        assert "bad\nvalue" not in caplog.text
        assert "badvalue" in caplog.text

    def test_remove_plugin_tools_reads_the_manifest(self):
        cfg = _AgentCfg({"alpha": object(), "legacy": object()})
        meta = {
            "tool_name": "legacy",
            "tools": [{"name": "alpha"}, "not-a-dict"],
        }
        with _ConfigLayer({"a": object()}, {"a": cfg}) as layer:
            _remove_plugin_tools_from_agents("plug", meta)
        assert cfg.tools.builtin_tools == {}
        assert [name for name, _ in layer.saved] == ["a"]

    def test_remove_plugin_tools_with_empty_meta(self):
        with _ConfigLayer({"a": object()}) as layer:
            _remove_plugin_tools_from_agents("plug", {})
        assert layer.loaded_agents == []
        assert layer.saved == []


# ---------------------------------------------------------------------------
# _post_unload_cleanup
# ---------------------------------------------------------------------------


class TestPostUnloadCleanup:
    def test_providers_and_commands_are_unregistered(self):
        provider_manager = MagicMock()
        calls: list[str] = []
        with patch(
            _CMD_HANDLER_UNREGISTER,
            side_effect=lambda name: calls.append(f"handler:{name}"),
        ), patch(
            _PRIORITY_UNREGISTER,
            side_effect=lambda prefix: calls.append(f"priority:{prefix}"),
        ):
            _post_unload_cleanup(
                _request(_app(None, provider_manager)),
                "plug",
                ["prov-a", "prov-b"],
                ["mycmd"],
            )
        assert provider_manager.unregister_plugin_provider.call_args_list[
            0
        ].args == ("prov-a",)
        assert provider_manager.unregister_plugin_provider.call_count == 2
        assert calls == ["handler:mycmd", "priority:/mycmd"]

    def test_provider_failure_does_not_skip_remaining_providers(
        self,
        caplog,
    ):
        provider_manager = MagicMock()
        provider_manager.unregister_plugin_provider.side_effect = [
            RuntimeError("boom-prov"),
            None,
        ]
        with patch(
            _CMD_HANDLER_UNREGISTER,
        ), patch(
            _PRIORITY_UNREGISTER,
        ):
            _post_unload_cleanup(
                _request(_app(None, provider_manager)),
                "plug",
                ["prov-a", "prov-b"],
                [],
            )
        assert provider_manager.unregister_plugin_provider.call_count == 2
        assert "boom-prov" in caplog.text

    def test_command_failure_does_not_skip_priority_unregister(self, caplog):
        calls: list[str] = []
        with patch(
            _CMD_HANDLER_UNREGISTER,
            side_effect=RuntimeError("boom-handler"),
        ), patch(
            _PRIORITY_UNREGISTER,
            side_effect=calls.append,
        ):
            _post_unload_cleanup(
                _request(_app(None, None)),
                "plug",
                [],
                ["mycmd"],
            )
        assert calls == ["/mycmd"]
        assert "boom-handler" in caplog.text

    def test_handler_unimportable_is_swallowed(self, caplog):
        provider_manager = MagicMock()
        with patch.dict(
            "sys.modules",
            {"qwenpaw.runtime.commands.control": None},
        ):
            _post_unload_cleanup(
                _request(_app(None, provider_manager)),
                "plug",
                ["prov-a"],
                ["mycmd"],
            )
        # providers are cleaned up before the command block runs
        provider_manager.unregister_plugin_provider.assert_called_once_with(
            "prov-a",
        )
        assert "Command cleanup skipped" in caplog.text

    def test_no_provider_manager_and_no_commands_is_a_no_op(self):
        _post_unload_cleanup(_request(_app(None, None)), "plug", [], [])

    def test_newlines_in_ids_are_stripped_from_the_log(self, caplog):
        provider_manager = MagicMock()
        provider_manager.unregister_plugin_provider.side_effect = RuntimeError(
            "boom",
        )
        with patch(
            _CMD_HANDLER_UNREGISTER,
        ), patch(
            _PRIORITY_UNREGISTER,
        ):
            _post_unload_cleanup(
                _request(_app(None, provider_manager)),
                "pl\nug",
                ["pr\nov"],
                [],
            )
        assert "pl\nug" not in caplog.text
        assert "pr\nov" not in caplog.text
        assert "pl" "ug" in caplog.text


# ---------------------------------------------------------------------------
# _post_load_setup
# ---------------------------------------------------------------------------


class TestPostLoadSetup:
    async def test_without_loader_returns_immediately(self):
        registry = _registry()
        await _post_load_setup(_request(_app(None, None)), "plug")
        registry.get_all_providers.assert_not_called()

    async def test_registers_only_this_plugins_provider(self):
        provider_manager = MagicMock()
        provider_manager.register_plugin_provider_async = AsyncMock()
        registry = _registry(
            providers={
                "mine": _provider_reg("plug", "mine"),
                "other": _provider_reg("other-plugin", "other"),
            },
        )
        loader = MagicMock()
        loader.registry = registry
        with patch(
            _SYNC_TOOLS,
        ) as sync:
            await _post_load_setup(
                _request(_app(loader, provider_manager)),
                "plug",
            )
        kwargs = provider_manager.register_plugin_provider_async.call_args
        assert kwargs.kwargs["provider_id"] == "mine"
        assert kwargs.kwargs["label"] == "Stub"
        assert kwargs.kwargs["base_url"] == "https://stub.invalid"
        assert kwargs.kwargs["metadata"] == {"k": "v"}
        assert provider_manager.register_plugin_provider_async.call_count == 1
        sync.assert_called_once_with(loader, "plug")

    async def test_provider_failure_is_logged_not_raised(self, caplog):
        provider_manager = MagicMock()
        provider_manager.register_plugin_provider_async = AsyncMock(
            side_effect=RuntimeError("boom-provider"),
        )
        registry = _registry(
            providers={"mine": _provider_reg("plug", "mine")},
        )
        loader = MagicMock()
        loader.registry = registry
        with patch(
            _SYNC_TOOLS,
        ):
            await _post_load_setup(
                _request(_app(loader, provider_manager)),
                "plug",
            )
        assert "Could not register provider 'mine'" in caplog.text
        assert "boom-provider" in caplog.text

    async def test_registers_control_command_with_its_priority(self):
        registry = _registry(
            commands=[
                _cmd_reg("plug", "mycmd"),
                _cmd_reg("other-plugin", "theirs"),
            ],
        )
        loader = MagicMock()
        loader.registry = registry
        handlers: list[str] = []
        # Patch the whole class: instantiating the real one would run its
        # own default registrations and drown the assertions.
        with patch(
            _CMD_HANDLER_REGISTER,
            side_effect=lambda handler: handlers.append(handler.command_name),
        ), patch(
            "qwenpaw.app.channels.command_registry.CommandRegistry",
        ) as registry_cls, patch(
            _SYNC_TOOLS,
        ):
            await _post_load_setup(_request(_app(loader, None)), "plug")
        assert handlers == ["mycmd"]
        registry_cls.return_value.register_command.assert_called_once_with(
            "/mycmd",
            priority_level=7,
        )

    async def test_command_failure_is_logged_not_raised(self, caplog):
        registry = _registry(commands=[_cmd_reg("plug", "mycmd")])
        loader = MagicMock()
        loader.registry = registry
        with patch(
            _CMD_HANDLER_REGISTER,
            side_effect=ValueError("already registered"),
        ), patch(
            "qwenpaw.app.channels.command_registry.CommandRegistry",
        ), patch(
            _SYNC_TOOLS,
        ):
            await _post_load_setup(_request(_app(loader, None)), "plug")
        assert "Could not register control command 'mycmd'" in caplog.text
        assert "already registered" in caplog.text

    async def test_command_registry_unimportable_is_swallowed(self, caplog):
        registry = _registry()
        loader = MagicMock()
        loader.registry = registry
        with patch.dict(
            "sys.modules",
            {"qwenpaw.app.channels.command_registry": None},
        ), patch(
            _SYNC_TOOLS,
        ):
            await _post_load_setup(_request(_app(loader, None)), "plug")
        assert "Control command setup skipped" in caplog.text

    async def test_sync_and_async_startup_hooks_are_both_awaited(self):
        order: list[str] = []

        def _sync_hook():
            order.append("sync")

        async def _async_hook():
            order.append("async")

        registry = _registry(
            hooks=[
                _hook_reg(
                    "other-plugin",
                    "theirs",
                    lambda: order.append(
                        "wrong-plugin",
                    ),
                ),
                _hook_reg("plug", "sync-hook", _sync_hook),
                _hook_reg("plug", "async-hook", _async_hook),
            ],
        )
        loader = MagicMock()
        loader.registry = registry
        with patch(
            _SYNC_TOOLS,
        ):
            await _post_load_setup(_request(_app(loader, None)), "plug")
        assert order == ["sync", "async"]

    async def test_startup_hook_failure_is_logged_not_raised(self, caplog):
        def _bad_hook():
            raise RuntimeError("boom-hook")

        registry = _registry(
            hooks=[_hook_reg("plug", "bad-hook", _bad_hook)],
        )
        loader = MagicMock()
        loader.registry = registry
        with patch(
            _SYNC_TOOLS,
        ) as sync:
            await _post_load_setup(_request(_app(loader, None)), "plug")
        assert "Startup hook 'bad-hook' failed" in caplog.text
        assert "boom-hook" in caplog.text
        # tool sync still runs after a failing hook
        sync.assert_called_once_with(loader, "plug")

    async def test_tool_sync_runs_off_the_event_loop(self):
        """Config file I/O must be dispatched to a worker thread."""
        registry = _registry()
        loader = MagicMock()
        loader.registry = registry
        calls: list[tuple[Any, ...]] = []

        async def _to_thread(fn, *args):
            calls.append((fn, args))
            return fn(*args)

        with patch(
            "qwenpaw.app.routers.plugins.asyncio.to_thread",
            new=_to_thread,
        ):
            await _post_load_setup(_request(_app(loader, None)), "plug")
        assert len(calls) == 1
        assert calls[0][0] is _sync_plugin_tools_to_agents
        assert calls[0][1] == (loader, "plug")


# ---------------------------------------------------------------------------
# _collect_plugin_runtime_ids
# ---------------------------------------------------------------------------


class TestCollectPluginRuntimeIds:
    def test_filters_by_plugin_id(self):
        registry = _registry(
            providers={
                "mine": _provider_reg("plug", "mine"),
                "theirs": _provider_reg("other-plugin", "theirs"),
            },
            commands=[
                _cmd_reg("plug", "mycmd"),
                _cmd_reg("other-plugin", "theirs"),
            ],
        )
        assert _collect_plugin_runtime_ids(registry, "plug") == (
            ["mine"],
            ["mycmd"],
        )

    def test_empty_registry_yields_empty_lists(self):
        assert _collect_plugin_runtime_ids(_registry(), "plug") == ([], [])


# ---------------------------------------------------------------------------
# _schedule_all_agents_reload
# ---------------------------------------------------------------------------


class TestScheduleAllAgentsReload:
    async def test_schedules_every_configured_agent(self):
        scheduled: list[str] = []
        with _ConfigLayer({"a": object(), "b": object()}), patch(
            "qwenpaw.app.routers.plugins.schedule_agent_reload",
            side_effect=lambda request, agent_id: scheduled.append(agent_id),
        ):
            await _schedule_all_agents_reload(_request(_app()))
        assert scheduled == ["a", "b"]

    async def test_no_profiles_schedules_nothing(self):
        with _ConfigLayer({}), patch(
            "qwenpaw.app.routers.plugins.schedule_agent_reload",
        ) as schedule:
            await _schedule_all_agents_reload(_request(_app()))
        schedule.assert_not_called()

    async def test_load_config_failure_is_swallowed(self, caplog):
        with _ConfigLayer(
            None,
            load_config_error=RuntimeError("cfg-down"),
        ), patch(
            "qwenpaw.app.routers.plugins.schedule_agent_reload",
        ):
            await _schedule_all_agents_reload(_request(_app()))
        assert "Could not schedule agent reloads" in caplog.text


# ---------------------------------------------------------------------------
# zip extraction helpers
# ---------------------------------------------------------------------------


class TestZipExtractionHelpers:
    def test_extract_bytes_returns_plugin_dir_and_removes_zip(self, tmp_path):
        content = _zip_bytes({"plugin.json": '{"id": "p"}', "a.txt": "A"})
        result = _extract_plugin_zip_bytes(content, tmp_path)
        assert result == tmp_path
        assert (tmp_path / "plugin.json").exists()
        assert not (tmp_path / "plugin.zip").exists()

    def test_extract_bytes_finds_nested_plugin_dir(self, tmp_path):
        content = _zip_bytes({"inner/plugin.json": '{"id": "p"}'})
        assert _extract_plugin_zip_bytes(content, tmp_path) == (
            tmp_path / "inner"
        )

    def test_extract_bytes_rejects_zip_slip(self, tmp_path):
        content = _zip_bytes({"../escape.txt": "evil"})
        with pytest.raises(ValueError, match="Zip Slip"):
            _extract_plugin_zip_bytes(content, tmp_path)
        assert not (tmp_path.parent / "escape.txt").exists()

    def test_extract_bytes_without_manifest_raises(self, tmp_path):
        with pytest.raises(ValueError, match="No plugin.json"):
            _extract_plugin_zip_bytes(_zip_bytes({"a.txt": "A"}), tmp_path)

    def test_extract_downloaded_removes_the_zip(self, tmp_path):
        zip_path = tmp_path / "downloaded.zip"
        zip_path.write_bytes(_zip_bytes({"plugin.json": '{"id": "p"}'}))
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        assert _extract_downloaded_plugin_zip(zip_path, out_dir) == out_dir
        assert not zip_path.exists()
        assert (out_dir / "plugin.json").exists()

    def test_extract_downloaded_propagates_zip_slip(self, tmp_path):
        zip_path = tmp_path / "downloaded.zip"
        zip_path.write_bytes(_zip_bytes({"../escape.txt": "evil"}))
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        with pytest.raises(ValueError, match="Zip Slip"):
            _extract_downloaded_plugin_zip(zip_path, out_dir)


# ---------------------------------------------------------------------------
# _async_download
# ---------------------------------------------------------------------------


class _FakeResponse:
    """urlopen() stand-in: a context manager yielding sized chunks."""

    def __init__(self, payload: bytes, chunk: int = 4) -> None:
        self._payload = payload
        self._chunk = chunk
        self._pos = 0
        self.read_sizes: list[int] = []

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def read(self, size: int) -> bytes:
        self.read_sizes.append(size)
        data = self._payload[self._pos : self._pos + min(size, self._chunk)]
        self._pos += len(data)
        return data


class TestAsyncDownload:
    async def test_writes_the_full_payload(self, tmp_path):
        dest = tmp_path / "out.bin"
        response = _FakeResponse(b"hello world")
        seen: dict[str, Any] = {}

        def _urlopen(url, timeout=None):
            seen["url"] = url
            seen["timeout"] = timeout
            return response

        with patch(
            "qwenpaw.app.routers.plugins.urllib.request.urlopen",
            side_effect=_urlopen,
        ):
            await _async_download("https://example.test/p.zip", dest)
        assert dest.read_bytes() == b"hello world"
        assert seen["url"] == "https://example.test/p.zip"
        assert seen["timeout"] == _DOWNLOAD_TIMEOUT
        assert response.read_sizes and response.read_sizes[0] == 65536

    async def test_size_cap_aborts_the_download(
        self,
        tmp_path,
        monkeypatch,
    ):
        dest = tmp_path / "out.bin"
        monkeypatch.setattr(plugins_module, "_MAX_DOWNLOAD_BYTES", 4)
        with patch(
            "qwenpaw.app.routers.plugins.urllib.request.urlopen",
            side_effect=lambda url, timeout=None: _FakeResponse(b"x" * 64),
        ):
            with pytest.raises(RuntimeError, match="Download aborted"):
                await _async_download("https://example.test/big.zip", dest)
        # only what fit under the cap was written; the rest is dropped
        assert dest.stat().st_size == 4

    async def test_urlopen_failure_propagates(self, tmp_path):
        dest = tmp_path / "out.bin"
        with patch(
            "qwenpaw.app.routers.plugins.urllib.request.urlopen",
            side_effect=OSError("network down"),
        ):
            with pytest.raises(OSError, match="network down"):
                await _async_download("https://example.test/p.zip", dest)
        assert not dest.exists()


# ---------------------------------------------------------------------------
# HTTP routes
# ---------------------------------------------------------------------------


def _client(loader: Any = None, provider_manager: Any = None):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from qwenpaw.app.routers.plugins import router as plugins_router

    app = FastAPI()
    app.state.plugin_loader = loader
    app.state.provider_manager = provider_manager
    app.include_router(plugins_router, prefix="/api")
    return TestClient(app)


class TestListPluginsRoute:
    def test_without_loader_falls_back_to_disk_scan(self, tmp_path):
        monkey = tmp_path / "plugins"
        monkey.mkdir()
        (monkey / "on-disk").mkdir()
        (monkey / "on-disk" / "plugin.json").write_text(
            json.dumps({"id": "on-disk", "name": "Disk", "version": "9.9"}),
            encoding="utf-8",
        )
        with patch(
            "qwenpaw.config.utils.get_plugins_dir",
            return_value=monkey,
        ):
            response = _client(None).get("/api/plugins")
        assert response.status_code == 200
        assert response.json() == [
            {
                "id": "on-disk",
                "name": "Disk",
                "version": "9.9",
                "description": "",
                "author": "",
                "enabled": True,
                "loaded": False,
                "plugin_type": "general",
                "frontend_entry": None,
            },
        ]

    def test_with_loader_reports_loaded_records(self):
        record = _record("plug", meta={"tool_name": "alpha"})
        loader = MagicMock()
        loader.get_all_loaded_plugins.return_value = {"plug": record}
        response = _client(loader).get("/api/plugins")
        assert response.status_code == 200
        assert response.json() == [
            {
                "id": "plug",
                "name": "plug display name",
                "version": "1.2.3",
                "description": "desc",
                "author": "auth",
                "enabled": True,
                "loaded": True,
                "plugin_type": "general",
                "frontend_entry": "ui/index.js",
            },
        ]

    def test_empty_loader_returns_empty_list(self):
        loader = MagicMock()
        loader.get_all_loaded_plugins.return_value = {}
        assert _client(loader).get("/api/plugins").json() == []


class TestGetPluginStatusRoute:
    def test_loaded_plugin_reports_runtime_state(self):
        loader = MagicMock()
        loader.get_loaded_plugin.return_value = _record("plug")
        response = _client(loader).get("/api/plugins/plug/status")
        assert response.status_code == 200
        assert response.json() == {
            "id": "plug",
            "loaded": True,
            "enabled": True,
            "version": "1.2.3",
        }

    def test_on_disk_but_not_loaded(self, tmp_path):
        plugins_dir = tmp_path / "plugins"
        (plugins_dir / "plug").mkdir(parents=True)
        (plugins_dir / "plug" / "plugin.json").write_text(
            "{}",
            encoding="utf-8",
        )
        loader = MagicMock()
        loader.get_loaded_plugin.return_value = None
        with patch(
            "qwenpaw.config.utils.get_plugins_dir",
            return_value=plugins_dir,
        ):
            response = _client(loader).get("/api/plugins/plug/status")
        assert response.json() == {
            "id": "plug",
            "loaded": False,
            "enabled": False,
        }

    def test_unknown_plugin_is_404(self, tmp_path):
        loader = MagicMock()
        loader.get_loaded_plugin.return_value = None
        with patch(
            "qwenpaw.config.utils.get_plugins_dir",
            return_value=tmp_path / "plugins",
        ):
            response = _client(loader).get("/api/plugins/ghost/status")
        assert response.status_code == 404
        assert "ghost" in response.json()["detail"]

    def test_dir_without_manifest_is_404(self, tmp_path):
        plugins_dir = tmp_path / "plugins"
        (plugins_dir / "plug").mkdir(parents=True)
        loader = MagicMock()
        loader.get_loaded_plugin.return_value = None
        with patch(
            "qwenpaw.config.utils.get_plugins_dir",
            return_value=plugins_dir,
        ):
            response = _client(loader).get("/api/plugins/plug/status")
        assert response.status_code == 404


class TestLoaderNotReady:
    """Every mutating route must 503 before the loader exists."""

    def test_install_is_503(self):
        response = _client(None).post(
            "/api/plugins/install",
            json={"source": "/tmp/x"},
        )
        assert response.status_code == 503
        assert "not ready" in response.json()["detail"]

    def test_uninstall_is_503(self):
        response = _client(None).delete("/api/plugins/plug")
        assert response.status_code == 503

    def test_upload_is_503(self):
        response = _client(None).post(
            "/api/plugins/upload",
            files={"file": ("p.zip", _zip_bytes({"plugin.json": "{}"}))},
        )
        assert response.status_code == 503

    async def test_install_source_raises_runtime_error(self):
        with pytest.raises(RuntimeError, match="not ready"):
            await install_plugin_source("/tmp/x", app=_app(None))

    async def test_uninstall_source_raises_runtime_error(self):
        with pytest.raises(RuntimeError, match="not ready"):
            await uninstall_plugin_source("plug", app=_app(None))


# ---------------------------------------------------------------------------
# _load_plugin_with_optional_force_reinstall
# ---------------------------------------------------------------------------


class TestLoadPluginWithOptionalForceReinstall:
    async def test_non_force_passes_no_unload_hooks(self, tmp_path):
        log: list[str] = []
        loader = _loader_stub(log)
        with patch(
            "qwenpaw.config.utils.get_plugins_dir",
            return_value=tmp_path,
        ), patch(
            _FINISH_INSTALL,
            new=AsyncMock(side_effect=lambda *a, **k: log.append("finish")),
        ):
            result = await _load_plugin_with_optional_force_reinstall(
                loader,
                _request(_app(loader)),
                tmp_path,
                force=False,
            )
        assert result == "LOADED"
        kwargs = loader.load_plugin_from_path.call_args.kwargs
        assert kwargs["force"] is False
        assert kwargs["before_force_unload"] is None
        assert kwargs["after_force_unload"] is None
        assert kwargs["install_dir"] == tmp_path
        assert kwargs["pawport_owner"] is None
        assert kwargs["recover_incomplete"] is False
        assert log == [
            "load_plugin_from_path:force=False:before=False:after=False",
        ]

    async def test_force_runs_unload_hooks_and_passes_flags(
        self,
        tmp_path,
    ):
        log: list[str] = []
        old_record = _record("plug", meta={"tool_name": "old_tool"})
        registry = _registry(
            providers={"prov": _provider_reg("plug", "prov")},
            commands=[_cmd_reg("plug", "mycmd")],
        )
        loader = _loader_stub(log, record=old_record, registry=registry)
        captured: dict[str, Any] = {}

        def _fake_cleanup(request, plugin_id, provider_ids, command_names):
            log.append("cleanup")
            captured["ids"] = (plugin_id, provider_ids, command_names)

        finish_calls: list[Any] = []

        async def _capture_load(**kwargs):
            captured["kwargs"] = kwargs
            # the real loader calls these inside the lifecycle lock
            kwargs["before_force_unload"]("plug")
            log.append("load")
            kwargs["after_force_unload"]("plug")
            await kwargs["after_load"]("RECORD")
            return "LOADED"

        loader.load_plugin_from_path = AsyncMock(side_effect=_capture_load)

        with patch(
            "qwenpaw.config.utils.get_plugins_dir",
            return_value=tmp_path,
        ), patch(
            "qwenpaw.app.routers.plugins._post_unload_cleanup",
            side_effect=_fake_cleanup,
        ), patch(
            _FINISH_INSTALL,
            new=AsyncMock(
                side_effect=lambda *a, **k: finish_calls.append((a, k)),
            ),
        ):
            result = await _load_plugin_with_optional_force_reinstall(
                loader,
                _request(_app(loader)),
                tmp_path,
                force=True,
                reload_agents=False,
                pawport_owner={"id": "owner"},
                recover_incomplete=True,
            )
        assert result == "LOADED"
        assert captured["ids"] == ("plug", ["prov"], ["mycmd"])
        kwargs = captured["kwargs"]
        assert kwargs["force"] is True
        assert kwargs["pawport_owner"] == {"id": "owner"}
        assert kwargs["recover_incomplete"] is True
        # before_force_unload ran and snapshotted the old tool set
        _, finish_kwargs = finish_calls[0]
        assert finish_kwargs["force"] is True
        assert finish_kwargs["old_tools"] == {"old_tool"}
        assert finish_kwargs["reload_agents"] is False

    async def test_force_without_old_record_snapshots_no_tools(
        self,
        tmp_path,
    ):
        loader = _loader_stub([], record=None)
        captured: dict[str, Any] = {}

        async def _capture_load(**kwargs):
            kwargs["before_force_unload"]("plug")
            captured["kwargs"] = kwargs
            await kwargs["after_load"]("RECORD")
            return "LOADED"

        loader.load_plugin_from_path = AsyncMock(side_effect=_capture_load)
        with patch(
            "qwenpaw.config.utils.get_plugins_dir",
            return_value=tmp_path,
        ), patch(
            "qwenpaw.app.routers.plugins._post_unload_cleanup",
        ), patch(
            _FINISH_INSTALL,
            new=AsyncMock(),
        ) as finish:
            await _load_plugin_with_optional_force_reinstall(
                loader,
                _request(_app(loader)),
                tmp_path,
                force=True,
            )
        assert finish.call_args.kwargs["old_tools"] == set()


# ---------------------------------------------------------------------------
# install_plugin_source / uninstall_plugin_source
# ---------------------------------------------------------------------------


class TestInstallPluginSource:
    async def test_local_path_is_resolved_and_loaded(self, tmp_path):
        log: list[str] = []
        loader = _loader_stub(log)
        app = _app(loader)
        with patch(
            "qwenpaw.config.utils.get_plugins_dir",
            return_value=tmp_path,
        ), patch(
            _FINISH_INSTALL,
            new=AsyncMock(),
        ):
            result = await install_plugin_source(
                f"  {tmp_path}  ",
                app=app,
                force=True,
                reload_agents=False,
            )
        assert result == "LOADED"
        kwargs = loader.load_plugin_from_path.call_args.kwargs
        assert kwargs["source_path"] == tmp_path
        assert kwargs["force"] is True
        assert kwargs["recover_incomplete"] is False

    async def test_missing_path_raises_file_not_found(self, tmp_path):
        loader = _loader_stub([])
        with pytest.raises(FileNotFoundError, match="Path not found"):
            await install_plugin_source(
                str(tmp_path / "ghost"),
                app=_app(loader),
            )
        loader.load_plugin_from_path.assert_not_called()

    async def test_http_url_downloads_then_extracts(self, tmp_path):
        log: list[str] = []
        loader = _loader_stub(log)
        urls: list[str] = []
        made: list[Path] = []

        async def _fake_download(url, dest):
            urls.append(url)
            dest.write_bytes(_zip_bytes({"plugin.json": '{"id": "p"}'}))

        real_mkdtemp = tempfile.mkdtemp
        seen_at_load: dict[str, Any] = {}

        def _mkdtemp(*args, **kwargs):
            path = Path(real_mkdtemp(*args, **kwargs))
            made.append(path)
            return str(path)

        async def _capture_load(**kwargs):
            source = kwargs["source_path"]
            seen_at_load["path"] = source
            seen_at_load["manifest"] = (source / "plugin.json").read_text(
                encoding="utf-8",
            )
            return "LOADED"

        loader.load_plugin_from_path = AsyncMock(side_effect=_capture_load)
        with patch(
            "qwenpaw.config.utils.get_plugins_dir",
            return_value=tmp_path,
        ), patch(
            "qwenpaw.app.routers.plugins._async_download",
            new=_fake_download,
        ), patch(
            "qwenpaw.app.routers.plugins.tempfile.mkdtemp",
            side_effect=_mkdtemp,
        ):
            await install_plugin_source(
                "https://example.test/p.zip",
                app=_app(loader),
            )
        assert urls == ["https://example.test/p.zip"]
        # the ZIP was extracted into the temp dir and that dir handed to
        # the loader as the install source
        assert seen_at_load["path"] == made[0]
        assert seen_at_load["manifest"] == '{"id": "p"}'
        # the temporary download directory is removed afterwards
        assert not made[0].exists()

    async def test_temp_dir_is_removed_even_when_load_fails(
        self,
        tmp_path,
    ):
        loader = _loader_stub([])

        async def _fake_download(url, dest):
            dest.write_bytes(_zip_bytes({"plugin.json": '{"id": "p"}'}))

        holder: dict[str, Any] = {}

        async def _failing_load(**kwargs):
            holder["source_path"] = kwargs["source_path"]
            raise RuntimeError("load failed")

        loader.load_plugin_from_path = AsyncMock(side_effect=_failing_load)
        made: list[Path] = []
        real_mkdtemp = tempfile.mkdtemp

        def _mkdtemp(*args, **kwargs):
            path = Path(real_mkdtemp(*args, **kwargs))
            made.append(path)
            return str(path)

        with patch(
            "qwenpaw.config.utils.get_plugins_dir",
            return_value=tmp_path,
        ), patch(
            "qwenpaw.app.routers.plugins._async_download",
            new=_fake_download,
        ), patch(
            "qwenpaw.app.routers.plugins.tempfile.mkdtemp",
            side_effect=_mkdtemp,
        ):
            with pytest.raises(RuntimeError, match="load failed"):
                await install_plugin_source(
                    "https://example.test/p.zip",
                    app=_app(loader),
                )
        assert holder["source_path"] == made[0]
        assert not made[0].exists()


class TestUninstallPluginSource:
    async def test_unloads_cleans_up_and_reloads(self):
        log: list[str] = []
        record = _record("plug", meta={"tool_name": "alpha"})
        registry = _registry(
            providers={"prov": _provider_reg("plug", "prov")},
            commands=[_cmd_reg("plug", "mycmd")],
        )
        loader = _loader_stub(log, record=record, registry=registry)
        cleanup: list[Any] = []
        removed: list[Any] = []
        with patch(
            "qwenpaw.app.routers.plugins._post_unload_cleanup",
            side_effect=lambda *a: cleanup.append(a),
        ), patch(
            "qwenpaw.app.routers.plugins._remove_plugin_tools_from_agents",
            side_effect=lambda *a: removed.append(a),
        ), patch(
            "qwenpaw.app.routers.plugins._schedule_all_agents_reload",
            new=AsyncMock(side_effect=lambda request: log.append("reload")),
        ):
            await uninstall_plugin_source(
                "plug",
                app=_app(loader),
                reload_agents=True,
            )
        assert log == [
            "lifecycle(plug):enter",
            "unload_plugin",
            "reload",
            "lifecycle(plug):exit",
        ]
        assert cleanup[0][1:] == ("plug", ["prov"], ["mycmd"])
        assert removed == [("plug", {"tool_name": "alpha"})]
        loader.unload_plugin.assert_awaited_once_with(
            "plug",
            delete_files=True,
        )

    async def test_unknown_plugin_raises_key_error(self):
        log: list[str] = []
        loader = _loader_stub(log, record=None)
        with pytest.raises(KeyError, match="is not loaded"):
            await uninstall_plugin_source("ghost", app=_app(loader))
        loader.unload_plugin.assert_not_called()
        assert log == ["lifecycle(ghost):enter", "lifecycle(ghost):exit"]

    async def test_reload_can_be_skipped(self):
        log: list[str] = []
        loader = _loader_stub(log, record=_record("plug"))
        with patch(
            "qwenpaw.app.routers.plugins._post_unload_cleanup",
        ), patch(
            "qwenpaw.app.routers.plugins._remove_plugin_tools_from_agents",
        ), patch(
            "qwenpaw.app.routers.plugins._schedule_all_agents_reload",
            new=AsyncMock(side_effect=lambda request: log.append("reload")),
        ):
            await uninstall_plugin_source(
                "plug",
                app=_app(loader),
                reload_agents=False,
            )
        assert "reload" not in log


# ---------------------------------------------------------------------------
# install / uninstall / upload routes
# ---------------------------------------------------------------------------


class TestInstallPluginRoute:
    def test_success_payload(self, tmp_path):
        loader = _loader_stub([])
        with patch(
            "qwenpaw.app.routers.plugins.install_plugin_source",
            new=AsyncMock(return_value=_record("plug")),
        ):
            response = _client(loader).post(
                "/api/plugins/install",
                json={"source": str(tmp_path), "force": True},
            )
        assert response.status_code == 200
        assert response.json() == {
            "id": "plug",
            "name": "plug display name",
            "version": "1.2.3",
            "description": "desc",
            "author": "auth",
            "loaded": True,
            "message": "Plugin 'plug display name' installed successfully.",
        }

    @pytest.mark.parametrize(
        "error,status",
        [
            (ValueError("dup"), 409),
            (FileNotFoundError("gone"), 400),
            (RuntimeError("not ready"), 400),
            (OSError("disk"), 500),
        ],
    )
    def test_error_mapping(self, error, status):
        loader = _loader_stub([])
        with patch(
            "qwenpaw.app.routers.plugins.install_plugin_source",
            new=AsyncMock(side_effect=error),
        ):
            response = _client(loader).post(
                "/api/plugins/install",
                json={"source": "/tmp/x"},
            )
        assert response.status_code == status
        assert str(error) in response.json()["detail"]

    def test_http_exception_is_reraised_unchanged(self):
        loader = _loader_stub([])
        with patch(
            "qwenpaw.app.routers.plugins.install_plugin_source",
            new=AsyncMock(
                side_effect=HTTPException(status_code=418, detail="teapot"),
            ),
        ):
            response = _client(loader).post(
                "/api/plugins/install",
                json={"source": "/tmp/x"},
            )
        assert response.status_code == 418
        assert response.json()["detail"] == "teapot"

    async def test_source_helper_is_called_with_request_app(self):
        app = _app(_loader_stub([]))
        seen: dict[str, Any] = {}

        async def _fake(source, *, app, **kwargs):
            seen["source"] = source
            seen["app"] = app
            seen.update(kwargs)
            return _record("plug")

        with patch(
            "qwenpaw.app.routers.plugins.install_plugin_source",
            new=_fake,
        ):
            await install_plugin(
                plugins_module.InstallPluginRequest(
                    source="/tmp/x",
                    force=True,
                ),
                _request(app),
            )
        assert seen["source"] == "/tmp/x"
        assert seen["force"] is True
        assert seen["app"] is app
        assert sorted(seen) == ["app", "force", "source"]


class TestUninstallPluginRoute:
    def test_success_payload(self):
        loader = _loader_stub([])
        with patch(
            "qwenpaw.app.routers.plugins.uninstall_plugin_source",
            new=AsyncMock(return_value=None),
        ):
            response = _client(loader).delete("/api/plugins/plug")
        assert response.status_code == 200
        assert response.json() == {
            "id": "plug",
            "message": "Plugin 'plug' uninstalled successfully.",
        }

    def test_unknown_plugin_is_404(self):
        loader = _loader_stub([])
        with patch(
            "qwenpaw.app.routers.plugins.uninstall_plugin_source",
            new=AsyncMock(
                side_effect=KeyError("Plugin 'ghost' is not loaded."),
            ),
        ):
            response = _client(loader).delete("/api/plugins/ghost")
        assert response.status_code == 404
        assert "ghost" in response.json()["detail"]

    def test_unexpected_error_is_500(self, caplog):
        loader = _loader_stub([])
        with patch(
            "qwenpaw.app.routers.plugins.uninstall_plugin_source",
            new=AsyncMock(side_effect=RuntimeError("disk on fire")),
        ):
            response = _client(loader).delete("/api/plugins/plug")
        assert response.status_code == 500
        assert "disk on fire" in response.json()["detail"]


class TestUploadPluginRoute:
    def test_success_payload(self):
        loader = _loader_stub([])
        payload = _zip_bytes({"plugin.json": '{"id": "p"}'})
        with patch(
            "qwenpaw.app.routers.plugins."
            "_load_plugin_with_optional_force_reinstall",
            new=AsyncMock(return_value=_record("plug")),
        ):
            response = _client(loader).post(
                "/api/plugins/upload?force=true",
                files={"file": ("plug.zip", payload, "application/zip")},
            )
        assert response.status_code == 200
        assert response.json()["id"] == "plug"
        assert response.json()["loaded"] is True

    def test_non_zip_filename_is_400(self):
        loader = _loader_stub([])
        response = _client(loader).post(
            "/api/plugins/upload",
            files={"file": ("plug.tar", b"nope")},
        )
        assert response.status_code == 400
        assert ".zip" in response.json()["detail"]

    async def test_empty_filename_is_rejected(self):
        """Probed at the handler: the multipart layer answers 422 for an
        empty filename before ``upload_plugin`` ever runs."""
        loader = _loader_stub([])
        upload = MagicMock()
        upload.filename = ""
        with pytest.raises(HTTPException) as exc_info:
            await upload_plugin(_request(_app(loader)), upload)
        assert exc_info.value.status_code == 400
        assert ".zip" in exc_info.value.detail

    def test_zip_slip_is_409(self):
        loader = _loader_stub([])
        payload = _zip_bytes({"../escape.txt": "evil"})
        with patch(
            "qwenpaw.app.routers.plugins._extract_plugin_zip_bytes",
            side_effect=ValueError("Zip Slip detected"),
        ):
            response = _client(loader).post(
                "/api/plugins/upload",
                files={"file": ("plug.zip", payload)},
            )
        assert response.status_code == 409
        assert "Zip Slip" in response.json()["detail"]

    def test_missing_manifest_is_400(self):
        loader = _loader_stub([])
        with patch(
            "qwenpaw.app.routers.plugins._extract_plugin_zip_bytes",
            side_effect=FileNotFoundError("no plugin.json"),
        ):
            response = _client(loader).post(
                "/api/plugins/upload",
                files={"file": ("plug.zip", _zip_bytes({"a.txt": "A"}))},
            )
        assert response.status_code == 400

    def test_unexpected_error_is_500(self):
        loader = _loader_stub([])
        with patch(
            "qwenpaw.app.routers.plugins._extract_plugin_zip_bytes",
            side_effect=OSError("disk full"),
        ):
            response = _client(loader).post(
                "/api/plugins/upload",
                files={"file": ("plug.zip", _zip_bytes({"a.txt": "A"}))},
            )
        assert response.status_code == 500
        assert "disk full" in response.json()["detail"]

    def test_http_exception_is_reraised_unchanged(self):
        loader = _loader_stub([])
        with patch(
            "qwenpaw.app.routers.plugins._extract_plugin_zip_bytes",
            side_effect=HTTPException(status_code=418, detail="teapot"),
        ):
            response = _client(loader).post(
                "/api/plugins/upload",
                files={"file": ("plug.zip", _zip_bytes({"a.txt": "A"}))},
            )
        assert response.status_code == 418


# ---------------------------------------------------------------------------
# search_market_plugins
# ---------------------------------------------------------------------------


class _FakeHttpxResponse:
    def __init__(self, payload: Any = None, status_error: Exception = None):
        self._payload = payload
        self._status_error = status_error

    def raise_for_status(self) -> None:
        if self._status_error is not None:
            raise self._status_error

    def json(self) -> Any:
        return self._payload


class _FakeAsyncClient:
    last: dict[str, Any] = {}

    def __init__(self, timeout=None):
        _FakeAsyncClient.last["timeout"] = timeout
        self._response = _FakeAsyncClient.response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> None:
        return None

    async def get(self, url, params=None):
        _FakeAsyncClient.last["url"] = url
        _FakeAsyncClient.last["params"] = params
        return self._response


class TestSearchMarketPlugins:
    def setup_method(self):
        _FakeAsyncClient.last = {}
        _FakeAsyncClient.response = _FakeHttpxResponse(payload={"ok": True})

    async def test_defaults_only_send_paging(self):
        with patch("httpx.AsyncClient", _FakeAsyncClient):
            result = await search_market_plugins()
        assert result == {"ok": True}
        assert _FakeAsyncClient.last["timeout"] == 15
        assert _FakeAsyncClient.last["url"] == (
            "https://platform.agentscope.io/openapi/v1/plugins"
        )
        assert _FakeAsyncClient.last["params"] == {
            "page_number": 1,
            "page_size": 20,
        }

    async def test_all_filters_are_forwarded(self):
        with patch("httpx.AsyncClient", _FakeAsyncClient):
            await search_market_plugins(
                page_number=3,
                page_size=5,
                search="git",
                category="dev",
                sort_by="stars",
                is_featured=True,
                is_trending=False,
            )
        assert _FakeAsyncClient.last["params"] == {
            "page_number": 3,
            "page_size": 5,
            "search": "git",
            "category": "dev",
            "sort_by": "stars",
            "is_featured": True,
            "is_trending": False,
        }

    async def test_empty_strings_are_not_forwarded(self):
        with patch("httpx.AsyncClient", _FakeAsyncClient):
            await search_market_plugins(search="", category="", sort_by="")
        assert _FakeAsyncClient.last["params"] == {
            "page_number": 1,
            "page_size": 20,
        }

    async def test_upstream_error_status_is_502(self, caplog):
        _FakeAsyncClient.response = _FakeHttpxResponse(
            status_error=RuntimeError("500 Server Error"),
        )
        with patch("httpx.AsyncClient", _FakeAsyncClient):
            with pytest.raises(HTTPException) as exc_info:
                await search_market_plugins()
        assert exc_info.value.status_code == 502
        assert "500 Server Error" in exc_info.value.detail
        assert "Plugin market search failed" in caplog.text

    async def test_transport_failure_is_502(self):
        class _Boom:
            def __init__(self, timeout=None):
                pass

            async def __aenter__(self):
                raise OSError("connection refused")

            async def __aexit__(self, *exc):
                return None

        with patch("httpx.AsyncClient", _Boom):
            with pytest.raises(HTTPException) as exc_info:
                await search_market_plugins()
        assert exc_info.value.status_code == 502
        assert "connection refused" in exc_info.value.detail


# ---------------------------------------------------------------------------
# remaining branches
# ---------------------------------------------------------------------------


class TestResidualBranches:
    def test_remove_tools_without_profiles_saves_nothing(self):
        with _ConfigLayer({}) as layer:
            _remove_named_tools_from_agents("plug", ["alpha"])
        assert layer.loaded_agents == []
        assert layer.saved == []

    def test_priority_unregister_failure_is_logged(self, caplog):
        with patch(
            _CMD_HANDLER_UNREGISTER,
            return_value=True,
        ), patch(
            _PRIORITY_UNREGISTER,
            side_effect=RuntimeError("boom-priority"),
        ):
            _post_unload_cleanup(
                _request(_app(None, None)),
                "plug",
                [],
                ["mycmd"],
            )
        assert "Could not unregister priority for '/mycmd'" in caplog.text
        assert "boom-priority" in caplog.text

    async def test_catalog_route_proxies_the_fetcher(self):
        with patch(
            "qwenpaw.plugins.download_catalog.fetch_plugin_catalog_async",
            new=AsyncMock(return_value={"plugins": [{"id": "a"}]}),
        ) as fetch:
            assert await plugins_module.get_plugin_catalog() == {
                "plugins": [{"id": "a"}],
            }
        fetch.assert_awaited_once_with()

    async def test_ui_file_uses_the_loaded_record_source_path(
        self,
        tmp_path,
    ):
        (tmp_path / "ui").mkdir()
        asset = tmp_path / "ui" / "app.js"
        asset.write_text("console.log(1)", encoding="utf-8")
        loader = MagicMock()
        loader.get_loaded_plugin.return_value = _record("plug")
        loader.get_loaded_plugin.return_value.source_path = tmp_path
        response = await plugins_module.serve_plugin_ui_file(
            "plug",
            "ui/app.js",
            _request(_app(loader)),
        )
        assert Path(response.path) == asset
        assert response.media_type == "application/javascript"
        assert response.headers["Cache-Control"] == "no-cache"

    async def test_ui_file_without_guessable_type_omits_media_type(
        self,
        tmp_path,
    ):
        asset = tmp_path / "data.unknownext"
        asset.write_bytes(b"\x00\x01")
        loader = MagicMock()
        record = _record("plug")
        record.source_path = tmp_path
        loader.get_loaded_plugin.return_value = record
        response = await plugins_module.serve_plugin_ui_file(
            "plug",
            "data.unknownext",
            _request(_app(loader)),
        )
        assert Path(response.path) == asset
        # guess_type() found nothing, so FileResponse falls back to its
        # own default instead of a caller-supplied media_type
        assert response.media_type == "application/octet-stream"
        assert response.headers["Cache-Control"] == "no-cache"
