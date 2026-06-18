from __future__ import annotations

import asyncio
import importlib
import sys
import time
import types
from pathlib import Path
from typing import Any

import pytest

PLUGIN_DIR = Path(__file__).resolve().parents[1]
if str(PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(PLUGIN_DIR))


@pytest.fixture
def launcher_module(monkeypatch: pytest.MonkeyPatch):
    """Import the launcher against small stubs for the OpenSandbox SDK."""

    class ConnectionConfig:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

    class Sandbox:
        calls: list[tuple[object, tuple[Any, ...], dict[str, Any]]] = []

        async def create(
            image: object | None = None,
            *args: Any,
            **kwargs: Any,
        ) -> dict[str, object]:
            Sandbox.calls.append((image, args, kwargs))
            return {"image": image}

    opensandbox = types.ModuleType("opensandbox")
    opensandbox_config = types.ModuleType("opensandbox.config")
    opensandbox_config.ConnectionConfig = ConnectionConfig
    opensandbox.config = opensandbox_config

    opensandbox_mcp = types.ModuleType("opensandbox_mcp")
    opensandbox_mcp_server = types.ModuleType("opensandbox_mcp.server")
    opensandbox_mcp_server.Sandbox = Sandbox
    opensandbox_mcp_server.create_server = lambda **_: object()
    opensandbox_mcp.server = opensandbox_mcp_server

    monkeypatch.setitem(sys.modules, "opensandbox", opensandbox)
    monkeypatch.setitem(sys.modules, "opensandbox.config", opensandbox_config)
    monkeypatch.setitem(sys.modules, "opensandbox_mcp", opensandbox_mcp)
    monkeypatch.setitem(
        sys.modules,
        "opensandbox_mcp.server",
        opensandbox_mcp_server,
    )
    monkeypatch.delitem(sys.modules, "opensandbox_mcp_launcher", raising=False)

    return importlib.import_module("opensandbox_mcp_launcher")


def test_guard_injects_recommended_image_by_default(
    launcher_module,
) -> None:
    launcher_module._install_image_allowlist_guard()

    result = asyncio.run(
        launcher_module.opensandbox_mcp_server.Sandbox.create(),
    )

    assert result == {
        "image": "docker.io/library/python:3.10-alpine",
    }


def test_guard_accepts_recommended_and_compatible_images(
    launcher_module,
) -> None:
    launcher_module._install_image_allowlist_guard()
    sandbox_cls = launcher_module.opensandbox_mcp_server.Sandbox

    result = asyncio.run(
        sandbox_cls.create("docker.io/library/python:3.10-alpine"),
    )
    slim_result = asyncio.run(
        sandbox_cls.create("docker.io/library/python:3.10-slim"),
    )
    compatible_result = asyncio.run(
        sandbox_cls.create("docker.io/opensandbox/execd:v1.0.16"),
    )

    assert result == {
        "image": "docker.io/library/python:3.10-alpine",
    }
    assert slim_result == {
        "image": "docker.io/library/python:3.10-slim",
    }
    assert compatible_result == {
        "image": "docker.io/opensandbox/execd:v1.0.16",
    }


def test_guard_rejects_legacy_code_interpreter_image(
    launcher_module,
) -> None:
    launcher_module._install_image_allowlist_guard()
    sandbox_cls = launcher_module.opensandbox_mcp_server.Sandbox

    with pytest.raises(
        ValueError,
        match='docker.io/library/python:3.10-alpine',
    ):
        asyncio.run(sandbox_cls.create("opensandbox/code-interpreter:v1.0.2"))


def test_schema_annotation_exposes_recommended_image_and_timeout(
    launcher_module,
) -> None:
    class Tool:
        description = "Create a sandbox."
        parameters = {"properties": {"image": {}, "timeout_seconds": {}}}

    tool = Tool()

    class ToolManager:
        def get_tool(self, name: str) -> object | None:
            if name == "sandbox_create":
                return tool
            return None

    class MCP:
        _tool_manager = ToolManager()

    launcher_module._annotate_sandbox_create_defaults(MCP(), 300)

    image_schema = tool.parameters["properties"]["image"]
    assert image_schema["enum"] == [
        "docker.io/library/python:3.10-alpine",
        "docker.io/library/python:3.10-slim",
        "docker.io/opensandbox/execd:v1.0.16",
    ]
    assert image_schema["default"] == "docker.io/library/python:3.10-alpine"
    assert tool.parameters["properties"]["timeout_seconds"]["default"] == 300
    assert "Recommended and default image" in tool.description


def test_command_run_annotation_prefers_sandbox_execution(
    launcher_module,
) -> None:
    class Tool:
        description = "Run a command inside a sandbox."

    tool = Tool()

    class ToolManager:
        def get_tool(self, name: str) -> object | None:
            if name == "command_run":
                return tool
            return None

    class MCP:
        _tool_manager = ToolManager()

    launcher_module._annotate_command_run_preference(MCP())
    launcher_module._annotate_command_run_preference(MCP())

    assert "Preferred tool for executing shell/system commands" in (
        tool.description
    )
    assert "execute_shell_command" in tool.description
    assert tool.description.count(
        "Preferred tool for executing shell/system commands",
    ) == 1


def test_lifecycle_hook_injects_default_timeout_and_metadata(
    launcher_module,
) -> None:
    captured: list[dict[str, Any]] = []

    class ToolManager:
        async def call_tool(
            self,
            name: str,
            arguments: dict[str, Any],
            context: Any = None,
            convert_result: bool = False,
        ) -> dict[str, str]:
            captured.append({"name": name, "arguments": arguments})
            return {"sandbox_id": "sandbox-1"}

    class MCP:
        _tool_manager = ToolManager()

    async def scenario() -> None:
        launcher_module.install_sandbox_lifecycle_hook(
            MCP(),
            launcher_module.SandboxLifecycleConfig(
                default_timeout_seconds=300,
                idle_timeout_seconds=0,
                agent_id="agent-a",
            ),
        )
        await MCP._tool_manager.call_tool("sandbox_create", {})

    asyncio.run(scenario())

    assert captured[0]["name"] == "sandbox_create"
    assert captured[0]["arguments"]["timeout_seconds"] == 300
    metadata = captured[0]["arguments"]["metadata"]
    assert metadata["qwenpaw_managed"] == "true"
    assert metadata["qwenpaw_agent_id"] == "agent-a"
    assert metadata["qwenpaw_launcher_instance_id"]


def test_idle_cleanup_lists_and_kills_stale_tracked_sandbox(
    launcher_module,
) -> None:
    calls: list[dict[str, Any]] = []

    class ToolManager:
        async def call_tool(
            self,
            name: str,
            arguments: dict[str, Any],
            context: Any = None,
            convert_result: bool = False,
        ) -> dict[str, Any]:
            calls.append({"name": name, "arguments": arguments})
            if name == "sandbox_list":
                return {
                    "sandbox_infos": [
                        {
                            "id": "sandbox-1",
                            "status": {"state": "Running"},
                            "metadata": {},
                        },
                    ],
                    "pagination": {"has_next_page": False},
                }
            if name == "sandbox_kill":
                return {"status": "killed"}
            raise AssertionError(f"unexpected tool call: {name}")

    class MCP:
        _tool_manager = ToolManager()

    async def scenario() -> None:
        manager = launcher_module.install_sandbox_lifecycle_hook(
            MCP(),
            launcher_module.SandboxLifecycleConfig(
                idle_timeout_seconds=30,
                idle_scan_interval_seconds=999,
                agent_id="agent-a",
            ),
        )
        async with manager._lock:
            manager._tracked["sandbox-1"] = launcher_module._TrackedSandbox(
                last_command_at=time.monotonic() - 31,
            )
        await manager.cleanup_once()

    asyncio.run(scenario())

    assert calls == [
        {
            "name": "sandbox_list",
            "arguments": {"filter": {"page": 1, "page_size": 100}},
        },
        {
            "name": "sandbox_kill",
            "arguments": {"sandbox_id": "sandbox-1"},
        },
    ]
