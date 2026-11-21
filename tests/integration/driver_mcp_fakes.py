# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any
from pathlib import Path
import sys

import pytest

from qwenpaw.plugins.testing import PluginTestHost


class Tool:
    def __init__(self, name: str) -> None:
        self.name = name
        self.description = f"{name} description"
        self.inputSchema = {"type": "object"}

    def model_dump(self, **_kwargs):
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.inputSchema,
        }


class FakeStdIOClient:
    instances: list["FakeStdIOClient"] = []

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.is_connected = False
        self.calls: list[tuple[str, dict[str, Any]]] = []
        FakeStdIOClient.instances.append(self)

    async def connect(self, **_kwargs: Any) -> None:
        self.is_connected = True

    async def close(self, ignore_errors: bool = True) -> None:
        del ignore_errors
        self.is_connected = False

    async def list_tools(self) -> list[Tool]:
        return [Tool("echo"), Tool("get_secret_status")]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        self.calls.append((name, arguments))
        if name == "get_secret_status":
            return {
                "structuredContent": {
                    "has_secret": bool(
                        self.kwargs.get("env", {}).get("ECHO_SECRET"),
                    ),
                },
            }
        return {"structuredContent": {"echo": arguments}}


class FakeHttpClient(FakeStdIOClient):
    instances: list["FakeHttpClient"] = []

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.is_connected = False
        self.calls: list[tuple[str, dict[str, Any]]] = []
        FakeHttpClient.instances.append(self)

    async def list_tools(self) -> list[Tool]:
        return [Tool("echo_http"), Tool("inspect_headers"), Tool("oauth_echo")]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        self.calls.append((name, arguments))
        if name == "inspect_headers":
            return {
                "structuredContent": {
                    "headers": dict(self.kwargs.get("headers") or {}),
                },
            }
        return {"structuredContent": {"echo": arguments}}


def patch_mcp_runtime_clients(monkeypatch) -> None:
    FakeStdIOClient.instances.clear()
    FakeHttpClient.instances.clear()
    modules = [
        module
        for module in tuple(sys.modules.values())
        if getattr(module, "__file__", None)
        and Path(str(module.__file__)).resolve() == PLUGIN / "connection.py"
    ]
    assert modules, "Load the actual SDK MCP plugin before patching endpoints"
    for module in modules:
        monkeypatch.setattr(module, "StdIOStatefulClient", FakeStdIOClient)
        monkeypatch.setattr(module, "HttpStatefulClient", FakeHttpClient)
        monkeypatch.setattr(module, "HttpAutoClient", FakeHttpClient)


# Test-only bridge setup keeps old host governance assertions independent of
# a removed concrete core handler. The plugin itself imports public SDK only.
PLUGIN = Path(__file__).resolve().parents[2] / "plugins/protocol/mcp"


@pytest.fixture
async def mcp_runtime_host(tmp_path):
    async with PluginTestHost(tmp_path / "plugin-host") as host:
        await host.load(PLUGIN)
        await host._workspace("test")  # pylint: disable=protected-access
        host.test_driver_managers = []
        try:
            yield host
        finally:
            for manager in host.test_driver_managers:
                await manager.shutdown_all()


async def sdk_mcp_manager(
    host,
    workspace_dir,
    store=None,
    *,
    approval_gate=None,
):
    # pylint: disable=protected-access
    from qwenpaw.drivers.credentials.store import AsyncCredentialStore
    from qwenpaw.drivers.manager import DriverManager
    from qwenpaw.plugins._drivers import attach_driver_protocols

    workspace = host._workspaces["test"]
    workspace.workspace_dir = workspace_dir
    manager = DriverManager(
        workspace_dir / "drivers",
        store or AsyncCredentialStore(workspace_dir / "credentials.yaml"),
        approval_gate=approval_gate,
    )
    workspace._service_manager.services["driver_manager"] = manager
    attach_driver_protocols(manager, host._loader.registry, workspace)
    host.test_driver_managers.append(manager)
    return manager
