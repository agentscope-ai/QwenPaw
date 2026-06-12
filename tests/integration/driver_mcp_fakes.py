# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any


class Tool:
    def __init__(self, name: str) -> None:
        self.name = name
        self.description = f"{name} description"
        self.inputSchema = {"type": "object"}


class FakeStdIOClient:
    instances: list["FakeStdIOClient"] = []

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.is_connected = False
        self.calls: list[tuple[str, dict[str, Any]]] = []
        FakeStdIOClient.instances.append(self)

    async def connect(self) -> None:
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
                "has_secret": bool(
                    self.kwargs.get("env", {}).get("ECHO_SECRET"),
                ),
            }
        return {"echo": arguments}


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
            return {"headers": dict(self.kwargs.get("headers") or {})}
        return {"echo": arguments}


def patch_mcp_runtime_clients(monkeypatch) -> None:
    FakeStdIOClient.instances.clear()
    FakeHttpClient.instances.clear()
    monkeypatch.setattr(
        "qwenpaw.drivers.handlers.mcp.StdIOStatefulClient",
        FakeStdIOClient,
    )
    monkeypatch.setattr(
        "qwenpaw.drivers.handlers.mcp.HttpStatefulClient",
        FakeHttpClient,
    )
