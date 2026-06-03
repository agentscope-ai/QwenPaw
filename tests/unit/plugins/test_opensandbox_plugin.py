# -*- coding: utf-8 -*-
"""Tests for the OpenSandbox plugin."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import types
from pathlib import Path
from typing import Any

from qwenpaw.config import config as config_module
from qwenpaw.config import utils as config_utils


REPO_ROOT = Path(__file__).resolve().parents[3]
PLUGIN_DIR = REPO_ROOT / "plugins" / "tool" / "opensandbox"


def _load_module(module_name: str, path: Path):
    """Load a plugin module from a repository path for isolated tests."""
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _call_private(module: Any, name: str, *args: Any) -> Any:
    """Call a private module helper by name when the unit test targets it."""
    return getattr(module, name)(*args)


def _parse_launcher_args(launcher_module: Any, argv: list[str]) -> Any:
    """Parse launcher arguments through the launcher's private parser."""
    return _call_private(launcher_module, "_build_parser").parse_args(argv)


def _constant(value: Any):
    """Build a no-argument callable that returns a fixed value."""

    def get_value() -> Any:
        """Return the captured value."""
        return value

    return get_value


def _agent_config_loader(agent_config: Any):
    """Build a load_agent_config replacement for one agent config."""

    def load_agent_config(_agent_id: str) -> Any:
        """Return the captured agent config."""
        return agent_config

    return load_agent_config


def _agent_config_recorder(saved: list[tuple[str, Any]]):
    """Build a save_agent_config replacement that records calls."""

    def save_agent_config(agent_id: str, config: Any) -> None:
        """Record the saved agent config."""
        saved.append((agent_id, config))

    return save_agent_config


def _install_fake_launcher_dependencies(monkeypatch):
    """Install fake OpenSandbox modules used by launcher tests."""
    opensandbox_mod = types.ModuleType("opensandbox")
    config_mod = types.ModuleType("opensandbox.config")
    mcp_mod = types.ModuleType("opensandbox_mcp")
    server_mod = types.ModuleType("opensandbox_mcp.server")

    connection_config_state = types.SimpleNamespace(last_kwargs={})

    def fake_connection_config(**kwargs: Any):
        """Capture connection config keyword arguments."""
        connection_config_state.last_kwargs = kwargs
        return types.SimpleNamespace(**kwargs)

    def fake_run(**_run_kwargs):
        """Accept MCP server run calls."""

    def fake_create_server(**_kwargs):
        """Return a minimal MCP server test double."""
        return types.SimpleNamespace(run=fake_run)

    fake_sandbox = types.SimpleNamespace(last_image=None)

    async def fake_sandbox_create(image=None, **_kwargs):
        """Capture sandbox image and return a fake sandbox."""
        fake_sandbox.last_image = image
        return types.SimpleNamespace(id="fake-sandbox", image=image)

    fake_sandbox.create = fake_sandbox_create

    config_mod.ConnectionConfig = fake_connection_config
    server_mod.Sandbox = fake_sandbox
    server_mod.create_server = fake_create_server
    mcp_mod.server = server_mod

    monkeypatch.setitem(sys.modules, "opensandbox", opensandbox_mod)
    monkeypatch.setitem(sys.modules, "opensandbox.config", config_mod)
    monkeypatch.setitem(sys.modules, "opensandbox_mcp", mcp_mod)
    monkeypatch.setitem(sys.modules, "opensandbox_mcp.server", server_mod)

    return connection_config_state, fake_sandbox


def test_manifest_declares_mcp_only_plugin():
    """Manifest declares OpenSandbox as an MCP-only plugin."""
    manifest = json.loads(
        (PLUGIN_DIR / "plugin.json").read_text(encoding="utf-8"),
    )

    assert manifest["id"] == "opensandbox"
    assert manifest["description"].startswith("Register the official")
    assert manifest["dependencies"] == ["opensandbox-mcp>=0.1.1"]
    assert manifest["meta"]["tools"] == []


def test_plugin_registers_startup_hook_without_legacy_tools():
    """Plugin registration installs startup hooks without legacy tools."""
    plugin_module = _load_module(
        "_opensandbox_plugin_test",
        PLUGIN_DIR / "plugin.py",
    )
    calls: list[tuple] = []

    def register_startup_hook(**kwargs):
        """Record startup hook registration."""
        calls.append(("hook", kwargs["hook_name"]))

    def register_tool(**kwargs):
        """Record legacy tool registration if it happens."""
        calls.append(
            (
                "tool",
                kwargs["tool_name"],
                callable(kwargs["tool_func"]),
            ),
        )

    plugin_module.plugin.register(
        types.SimpleNamespace(
            register_startup_hook=register_startup_hook,
            register_tool=register_tool,
        ),
    )

    assert ("hook", "opensandbox_install_skills") in calls
    assert not [item for item in calls if item[0] == "tool"]


def test_plugin_syncs_disabled_mcp_client_to_agents(monkeypatch):
    """Sync creates a disabled OpenSandbox MCP client for agents."""
    plugin_module = _load_module(
        "_opensandbox_plugin_sync_test",
        PLUGIN_DIR / "plugin.py",
    )

    agent_config = config_module.AgentProfileConfig(
        id="agent-1",
        name="Agent 1",
        workspace_dir=str(PLUGIN_DIR),
    )
    root_config = types.SimpleNamespace(
        agents=types.SimpleNamespace(
            profiles={
                "agent-1": types.SimpleNamespace(
                    workspace_dir=str(PLUGIN_DIR),
                ),
            },
        ),
    )
    saved: list[tuple[str, Any]] = []

    monkeypatch.setattr(config_utils, "load_config", _constant(root_config))
    monkeypatch.setattr(
        config_module,
        "load_agent_config",
        _agent_config_loader(agent_config),
    )
    monkeypatch.setattr(
        config_module,
        "save_agent_config",
        _agent_config_recorder(saved),
    )

    _call_private(plugin_module, "_sync_opensandbox_mcp_client_to_agents")

    assert len(saved) == 1
    assert saved[0][0] == "agent-1"
    clients = getattr(agent_config.mcp, "clients")
    client = clients["opensandbox"]
    assert client.enabled is False
    assert client.transport == "stdio"
    assert client.command == (sys.executable or "python")
    assert client.args == [
        str(PLUGIN_DIR / "opensandbox_mcp_launcher.py"),
        "--domain",
        "127.0.0.1:8080",
        "--protocol",
        "http",
        "--use-server-proxy",
    ]
    assert client.cwd == str(PLUGIN_DIR)
    assert client.env == {
        "OPEN_SANDBOX_API_KEY": "",
    }


def test_plugin_migrates_old_bundled_mcp_client(monkeypatch):
    """Sync migrates the removed bundled MCP wrapper to the launcher."""
    plugin_module = _load_module(
        "_opensandbox_plugin_migrate_mcp_test",
        PLUGIN_DIR / "plugin.py",
    )

    existing = config_module.MCPClientConfig(
        name="Old OpenSandbox",
        enabled=True,
        transport="stdio",
        command="python",
        args=[str(PLUGIN_DIR / "mcp_server.py")],
        cwd=str(PLUGIN_DIR),
    )
    agent_config = config_module.AgentProfileConfig(
        id="agent-1",
        name="Agent 1",
        workspace_dir=str(PLUGIN_DIR),
        mcp=config_module.MCPConfig(clients={"opensandbox": existing}),
    )
    root_config = types.SimpleNamespace(
        agents=types.SimpleNamespace(
            profiles={
                "agent-1": types.SimpleNamespace(
                    workspace_dir=str(PLUGIN_DIR),
                ),
            },
        ),
    )
    saved: list[tuple[str, Any]] = []

    monkeypatch.setattr(config_utils, "load_config", _constant(root_config))
    monkeypatch.setattr(
        config_module,
        "load_agent_config",
        _agent_config_loader(agent_config),
    )
    monkeypatch.setattr(
        config_module,
        "save_agent_config",
        _agent_config_recorder(saved),
    )

    _call_private(plugin_module, "_sync_opensandbox_mcp_client_to_agents")

    assert len(saved) == 1
    clients = getattr(agent_config.mcp, "clients")
    migrated = clients["opensandbox"]
    assert migrated.enabled is True
    assert migrated.command == (sys.executable or "python")
    assert str(PLUGIN_DIR / "opensandbox_mcp_launcher.py") in migrated.args
    assert "mcp_server.py" not in " ".join(migrated.args)


def test_plugin_refreshes_managed_launcher_paths(monkeypatch):
    """Sync refreshes generated launcher paths without losing user config."""
    plugin_module = _load_module(
        "_opensandbox_plugin_refresh_mcp_test",
        PLUGIN_DIR / "plugin.py",
    )

    existing = config_module.MCPClientConfig(
        name="OpenSandbox MCP",
        enabled=True,
        transport="stdio",
        command=r"C:\old\python.exe",
        args=[
            r"C:\old\plugins\opensandbox\opensandbox_mcp_launcher.py",
            "--domain",
            "10.0.0.5:8080",
            "--protocol",
            "http",
        ],
        env={
            "OPEN_SANDBOX_API_KEY": "secret",
            "OPEN_SANDBOX_DOMAIN": "10.0.0.5:8080",
            "OPEN_SANDBOX_USE_SERVER_PROXY": "false",
        },
        cwd=r"C:\old\plugins\opensandbox",
    )
    agent_config = config_module.AgentProfileConfig(
        id="agent-1",
        name="Agent 1",
        workspace_dir=str(PLUGIN_DIR),
        mcp=config_module.MCPConfig(clients={"opensandbox": existing}),
    )
    root_config = types.SimpleNamespace(
        agents=types.SimpleNamespace(
            profiles={
                "agent-1": types.SimpleNamespace(
                    workspace_dir=str(PLUGIN_DIR),
                ),
            },
        ),
    )
    saved: list[tuple[str, Any]] = []

    monkeypatch.setattr(config_utils, "load_config", _constant(root_config))
    monkeypatch.setattr(
        config_module,
        "load_agent_config",
        _agent_config_loader(agent_config),
    )
    monkeypatch.setattr(
        config_module,
        "save_agent_config",
        _agent_config_recorder(saved),
    )

    _call_private(plugin_module, "_sync_opensandbox_mcp_client_to_agents")

    assert len(saved) == 1
    clients = getattr(agent_config.mcp, "clients")
    refreshed = clients["opensandbox"]
    assert refreshed.enabled is True
    assert refreshed.command == (sys.executable or "python")
    assert refreshed.cwd == str(PLUGIN_DIR)
    assert refreshed.args == [
        str(PLUGIN_DIR / "opensandbox_mcp_launcher.py"),
        "--domain",
        "10.0.0.5:8080",
        "--protocol",
        "http",
        "--no-use-server-proxy",
    ]
    assert refreshed.env == {
        "OPEN_SANDBOX_API_KEY": "secret",
    }


def test_plugin_refreshes_literal_auto_placeholders(monkeypatch):
    """Sync replaces literal auto placeholders in managed client config."""
    plugin_module = _load_module(
        "_opensandbox_plugin_refresh_placeholder_test",
        PLUGIN_DIR / "plugin.py",
    )

    existing = config_module.MCPClientConfig(
        name="OpenSandbox MCP",
        enabled=True,
        transport="stdio",
        command="<auto: current QwenPaw Python>",
        args=[
            r"<auto: plugin_dir>\opensandbox_mcp_launcher.py",
            "--domain",
            "127.0.0.1:8080",
            "--protocol",
            "http",
        ],
        env={
            "OPEN_SANDBOX_API_KEY": "secret",
            "OPEN_SANDBOX_DOMAIN": "127.0.0.1:8080",
            "OPEN_SANDBOX_USE_SERVER_PROXY": "true",
        },
        cwd="<auto: plugin_dir>",
    )
    agent_config = config_module.AgentProfileConfig(
        id="agent-1",
        name="Agent 1",
        workspace_dir=str(PLUGIN_DIR),
        mcp=config_module.MCPConfig(clients={"opensandbox": existing}),
    )
    root_config = types.SimpleNamespace(
        agents=types.SimpleNamespace(
            profiles={
                "agent-1": types.SimpleNamespace(
                    workspace_dir=str(PLUGIN_DIR),
                ),
            },
        ),
    )
    saved: list[tuple[str, Any]] = []

    monkeypatch.setattr(config_utils, "load_config", _constant(root_config))
    monkeypatch.setattr(
        config_module,
        "load_agent_config",
        _agent_config_loader(agent_config),
    )
    monkeypatch.setattr(
        config_module,
        "save_agent_config",
        _agent_config_recorder(saved),
    )

    _call_private(plugin_module, "_sync_opensandbox_mcp_client_to_agents")

    assert len(saved) == 1
    clients = getattr(agent_config.mcp, "clients")
    refreshed = clients["opensandbox"]
    assert refreshed.command == (sys.executable or "python")
    assert refreshed.cwd == str(PLUGIN_DIR)
    assert refreshed.args[0] == str(
        PLUGIN_DIR / "opensandbox_mcp_launcher.py",
    )
    assert refreshed.args[-1] == "--use-server-proxy"
    assert set(refreshed.env) == {"OPEN_SANDBOX_API_KEY"}
    assert refreshed.env["OPEN_SANDBOX_API_KEY"] == "secret"


def test_plugin_moves_connection_env_into_launcher_args(monkeypatch):
    """Sync moves non-secret OpenSandbox env config into args."""
    plugin_module = _load_module(
        "_opensandbox_plugin_env_to_args_test",
        PLUGIN_DIR / "plugin.py",
    )

    existing = config_module.MCPClientConfig(
        name="OpenSandbox MCP",
        enabled=True,
        transport="stdio",
        command="python",
        args=[
            r"C:\old\plugins\opensandbox\opensandbox_mcp_launcher.py",
            "--protocol",
            "http",
        ],
        env={
            "OPEN_SANDBOX_API_KEY": "secret",
            "OPEN_SANDBOX_DOMAIN": "10.0.0.5:8080",
            "OPEN_SANDBOX_USE_SERVER_PROXY": "true",
        },
        cwd=r"C:\old\plugins\opensandbox",
    )
    agent_config = config_module.AgentProfileConfig(
        id="agent-1",
        name="Agent 1",
        workspace_dir=str(PLUGIN_DIR),
        mcp=config_module.MCPConfig(clients={"opensandbox": existing}),
    )
    root_config = types.SimpleNamespace(
        agents=types.SimpleNamespace(
            profiles={
                "agent-1": types.SimpleNamespace(
                    workspace_dir=str(PLUGIN_DIR),
                ),
            },
        ),
    )
    saved: list[tuple[str, Any]] = []

    monkeypatch.setattr(config_utils, "load_config", _constant(root_config))
    monkeypatch.setattr(
        config_module,
        "load_agent_config",
        _agent_config_loader(agent_config),
    )
    monkeypatch.setattr(
        config_module,
        "save_agent_config",
        _agent_config_recorder(saved),
    )

    _call_private(plugin_module, "_sync_opensandbox_mcp_client_to_agents")

    assert len(saved) == 1
    clients = getattr(agent_config.mcp, "clients")
    refreshed = clients["opensandbox"]
    assert refreshed.args == [
        str(PLUGIN_DIR / "opensandbox_mcp_launcher.py"),
        "--protocol",
        "http",
        "--domain",
        "10.0.0.5:8080",
        "--use-server-proxy",
    ]
    assert refreshed.env == {"OPEN_SANDBOX_API_KEY": "secret"}


def test_launcher_maps_server_proxy_env_to_connection_config(monkeypatch):
    """Launcher maps server proxy environment into ConnectionConfig."""
    (
        fake_connection_config,
        _fake_sandbox,
    ) = _install_fake_launcher_dependencies(
        monkeypatch,
    )
    launcher_module = _load_module(
        "_opensandbox_mcp_launcher_test",
        PLUGIN_DIR / "opensandbox_mcp_launcher.py",
    )

    monkeypatch.setenv("OPEN_SANDBOX_USE_SERVER_PROXY", "true")
    args = _parse_launcher_args(
        launcher_module,
        [
            "--domain",
            "127.0.0.1:8080",
            "--protocol",
            "http",
            "--request-timeout-seconds",
            "42",
        ],
    )

    _call_private(launcher_module, "_connection_config_from_args", args)

    assert fake_connection_config.last_kwargs["domain"] == "127.0.0.1:8080"
    assert fake_connection_config.last_kwargs["protocol"] == "http"
    assert fake_connection_config.last_kwargs["use_server_proxy"] is True


def test_launcher_cli_server_proxy_overrides_env(monkeypatch):
    """Launcher CLI proxy flag overrides the environment value."""
    (
        fake_connection_config,
        _fake_sandbox,
    ) = _install_fake_launcher_dependencies(
        monkeypatch,
    )
    launcher_module = _load_module(
        "_opensandbox_mcp_launcher_cli_test",
        PLUGIN_DIR / "opensandbox_mcp_launcher.py",
    )

    monkeypatch.setenv("OPEN_SANDBOX_USE_SERVER_PROXY", "false")
    args = _parse_launcher_args(
        launcher_module,
        [
            "--domain",
            "127.0.0.1:8080",
            "--use-server-proxy",
        ],
    )

    _call_private(launcher_module, "_connection_config_from_args", args)

    assert fake_connection_config.last_kwargs["use_server_proxy"] is True


def test_launcher_allows_only_whitelisted_sandbox_image(monkeypatch):
    """Launcher allows the supported OpenSandbox image."""
    (
        _fake_connection_config,
        fake_sandbox,
    ) = _install_fake_launcher_dependencies(
        monkeypatch,
    )
    launcher_module = _load_module(
        "_opensandbox_mcp_launcher_image_allow_test",
        PLUGIN_DIR / "opensandbox_mcp_launcher.py",
    )

    _call_private(launcher_module, "_install_image_allowlist_guard")

    result = asyncio.run(
        launcher_module.opensandbox_mcp_server.Sandbox.create(
            "opensandbox/code-interpreter:v1.0.2",
        ),
    )

    assert result.id == "fake-sandbox"
    assert fake_sandbox.last_image == "opensandbox/code-interpreter:v1.0.2"


def test_launcher_rejects_unsupported_sandbox_image(monkeypatch):
    """Launcher rejects unsupported sandbox images before provisioning."""
    _install_fake_launcher_dependencies(monkeypatch)
    launcher_module = _load_module(
        "_opensandbox_mcp_launcher_image_reject_test",
        PLUGIN_DIR / "opensandbox_mcp_launcher.py",
    )

    _call_private(launcher_module, "_install_image_allowlist_guard")

    try:
        asyncio.run(
            launcher_module.opensandbox_mcp_server.Sandbox.create(
                "python:3.11",
            ),
        )
    except ValueError as exc:
        assert str(exc) == (
            'not support image, pls use "opensandbox/code-interpreter:v1.0.2" '
            "instead."
        )
    else:
        raise AssertionError("unsupported image was not rejected")


def test_launcher_annotates_sandbox_create_image_schema(monkeypatch):
    """Launcher annotates sandbox_create with the image allowlist."""
    _install_fake_launcher_dependencies(monkeypatch)
    launcher_module = _load_module(
        "_opensandbox_mcp_launcher_image_schema_test",
        PLUGIN_DIR / "opensandbox_mcp_launcher.py",
    )
    tool = types.SimpleNamespace(
        description="Create a sandbox.",
        parameters={"properties": {"image": {"type": "string"}}},
    )

    def get_tool(name: str):
        """Return the sandbox_create tool from the fake tool manager."""
        return tool if name == "sandbox_create" else None

    manager = types.SimpleNamespace(get_tool=get_tool)
    mcp = types.SimpleNamespace(_tool_manager=manager)

    _call_private(launcher_module, "_annotate_image_allowlist", mcp)

    image_schema = tool.parameters["properties"]["image"]
    assert image_schema["enum"] == ["opensandbox/code-interpreter:v1.0.2"]
    assert "not support image" in image_schema["description"]
    assert "Only supported image" in tool.description


def test_plugin_does_not_overwrite_existing_mcp_client(monkeypatch):
    """Sync leaves user-managed OpenSandbox MCP clients untouched."""
    plugin_module = _load_module(
        "_opensandbox_plugin_no_overwrite_test",
        PLUGIN_DIR / "plugin.py",
    )

    existing = config_module.MCPClientConfig(
        name="Custom OpenSandbox",
        enabled=True,
        transport="stdio",
        command="custom-opensandbox",
    )
    agent_config = config_module.AgentProfileConfig(
        id="agent-1",
        name="Agent 1",
        workspace_dir=str(PLUGIN_DIR),
        mcp=config_module.MCPConfig(clients={"opensandbox": existing}),
    )
    root_config = types.SimpleNamespace(
        agents=types.SimpleNamespace(
            profiles={
                "agent-1": types.SimpleNamespace(
                    workspace_dir=str(PLUGIN_DIR),
                ),
            },
        ),
    )
    saved: list[tuple[str, Any]] = []

    monkeypatch.setattr(config_utils, "load_config", _constant(root_config))
    monkeypatch.setattr(
        config_module,
        "load_agent_config",
        _agent_config_loader(agent_config),
    )
    monkeypatch.setattr(
        config_module,
        "save_agent_config",
        _agent_config_recorder(saved),
    )

    _call_private(plugin_module, "_sync_opensandbox_mcp_client_to_agents")

    assert not saved
    clients = getattr(agent_config.mcp, "clients")
    assert clients["opensandbox"] is existing


def test_plugin_removes_legacy_tool_entries(monkeypatch):
    """Legacy OpenSandbox tool entries are removed from root and agents."""
    plugin_module = _load_module(
        "_opensandbox_plugin_cleanup_test",
        PLUGIN_DIR / "plugin.py",
    )

    legacy_tool_names = {
        "execute_opensandbox_command",
        "check_opensandbox_status",
        "inspect_opensandbox_upload",
    }
    root_tools = {tool_name: object() for tool_name in legacy_tool_names}
    root_tools["read_file"] = object()
    root_config = types.SimpleNamespace(
        tools=types.SimpleNamespace(builtin_tools=root_tools),
        agents=types.SimpleNamespace(
            profiles={
                "agent-1": types.SimpleNamespace(
                    workspace_dir=str(PLUGIN_DIR),
                ),
            },
        ),
    )
    agent_tools = {
        tool_name: config_module.BuiltinToolConfig(name=tool_name)
        for tool_name in legacy_tool_names
    }
    agent_tools["read_file"] = config_module.BuiltinToolConfig(
        name="read_file",
    )
    agent_config = config_module.AgentProfileConfig(
        id="agent-1",
        name="Agent 1",
        workspace_dir=str(PLUGIN_DIR),
        tools=config_module.ToolsConfig(builtin_tools=agent_tools),
    )
    saved_root: list[Any] = []
    saved_agents: list[tuple[str, Any]] = []

    monkeypatch.setattr(config_utils, "load_config", _constant(root_config))
    monkeypatch.setattr(
        config_utils,
        "save_config",
        saved_root.append,
    )
    monkeypatch.setattr(
        config_module,
        "load_agent_config",
        _agent_config_loader(agent_config),
    )
    monkeypatch.setattr(
        config_module,
        "save_agent_config",
        _agent_config_recorder(saved_agents),
    )

    _call_private(plugin_module, "_remove_legacy_tool_entries_from_agents")

    assert legacy_tool_names.isdisjoint(root_tools)
    agent_builtin_tools = getattr(agent_config.tools, "builtin_tools")
    assert legacy_tool_names.isdisjoint(agent_builtin_tools)
    assert "read_file" in root_tools
    assert "read_file" in agent_builtin_tools
    assert saved_root == [root_config]
    assert saved_agents == [("agent-1", agent_config)]


def test_startup_setup_still_syncs_mcp_when_skill_install_fails(monkeypatch):
    """Startup setup keeps cleanup and MCP sync after skill install failure."""
    plugin_module = _load_module(
        "_opensandbox_plugin_startup_test",
        PLUGIN_DIR / "plugin.py",
    )
    calls: list[str] = []

    def fail_install():
        """Raise an installation failure for startup recovery testing."""
        raise RuntimeError("skill install failed")

    def record_cleanup():
        """Record legacy cleanup execution."""
        calls.append("cleanup")

    def record_mcp_sync():
        """Record MCP sync execution."""
        calls.append("mcp")

    monkeypatch.setattr(plugin_module, "_install_plugin_skills", fail_install)
    monkeypatch.setattr(
        plugin_module,
        "_remove_legacy_tool_entries_from_agents",
        record_cleanup,
    )
    monkeypatch.setattr(
        plugin_module,
        "_sync_opensandbox_mcp_client_to_agents",
        record_mcp_sync,
    )

    _call_private(plugin_module, "_startup_setup")

    assert calls == ["cleanup", "mcp"]
