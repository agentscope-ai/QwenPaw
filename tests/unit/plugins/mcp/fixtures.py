# -*- coding: utf-8 -*-
"""Offline peer endpoints; never substitute the host's policy or adapter."""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import httpx
import yaml
from mcp.types import CallToolResult, Tool

PLUGIN = Path(__file__).resolve().parents[4] / "plugins/protocol/mcp"
PLUGIN_ID = "qwenpaw-mcp"


def card(name="same", transport="stdio", **values):
    endpoint = (
        {"command": "synthetic-mcp", "args": ["--offline"]}
        if transport == "stdio"
        else {"url": "https://peer.invalid/mcp"}
    )
    return {
        "name": name,
        "protocol": "mcp",
        "endpoint": {"transport": transport, **endpoint},
        "policy": {"default_effect": "allow"},
        **values,
    }


def seed_card(root, source, workspace="test"):
    path = (
        root
        / "workspaces"
        / workspace
        / "drivers"
        / "mcp"
        / (source["name"] + ".yaml")
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(source))
    return path


async def seed_record(
    root,
    *,
    workspace="test",
    kind="oauth2_auth_code",
    public=None,
    secrets=None,
    ref="synthetic-oauth",
):
    # Store setup is test-only; the actual plugin only sees scoped SDK aliases.
    from qwenpaw.drivers.credentials.store import AsyncCredentialStore
    from qwenpaw.drivers.credentials.types import CredentialRecord

    store = AsyncCredentialStore(
        root / "workspaces" / workspace / "credentials.yaml",
    )
    await store.put(
        CredentialRecord(
            ref=ref,
            kind=kind,
            public=public or {},
            secrets=secrets or {},
            meta={"synthetic": True},
        ),
    )
    return store


class Peer:
    """Thirdparty MCP session and transport endpoints with observable I/O."""

    def __init__(self):
        self.tools = [Tool(name="echo", description="Echo", inputSchema={})]
        self.result = CallToolResult(content=[{"type": "text", "text": "ok"}])
        self.opens = []
        self.closes = []
        self.calls = []
        self.lists = 0
        self.initialize_started = asyncio.Event()
        self.initialize_gate = None
        self.exit_started = asyncio.Event()
        self.exit_gate = None
        self.rpc_started = asyncio.Event()
        self.rpc_gate = None
        self.rpc_tasks = []

    def install(self, monkeypatch):
        import mcp
        import mcp.client.stdio
        import mcp.client.sse

        peer = self

        @asynccontextmanager
        async def stdio(parameters, **_):
            owner = asyncio.current_task()
            peer.opens.append(("stdio", parameters))
            try:
                yield object(), object()
            finally:
                assert asyncio.current_task() is owner
                peer.closes.append("stdio")

        @asynccontextmanager
        async def sse(url, **kwargs):
            owner = asyncio.current_task()
            peer.opens.append(("sse", {"url": url, **kwargs}))
            try:
                yield object(), object()
            finally:
                assert asyncio.current_task() is owner
                peer.closes.append("sse")

        class Session:
            def __init__(self, *_args, **_kwargs):
                self.owner = None

            async def __aenter__(self):
                self.owner = asyncio.current_task()
                return self

            async def __aexit__(self, *_):
                assert asyncio.current_task() is self.owner
                peer.exit_started.set()
                if peer.exit_gate is not None:
                    while not peer.exit_gate.is_set():
                        try:
                            await peer.exit_gate.wait()
                        except asyncio.CancelledError:
                            continue

            async def initialize(self):
                peer.initialize_started.set()
                if peer.initialize_gate is not None:
                    await peer.initialize_gate.wait()

            async def list_tools(self, *_args, **_kwargs):
                peer.lists += 1
                return SimpleNamespace(tools=list(peer.tools))

            async def call_tool(self, name, arguments, **_):
                peer.calls.append((name, arguments))
                if peer.rpc_gate is not None:
                    peer.rpc_tasks.append(asyncio.current_task())
                    peer.rpc_started.set()
                    while not peer.rpc_gate.is_set():
                        try:
                            await peer.rpc_gate.wait()
                        except asyncio.CancelledError:
                            continue
                return peer.result

        monkeypatch.setattr(mcp, "ClientSession", Session)
        monkeypatch.setattr(mcp.client.stdio, "stdio_client", stdio)
        monkeypatch.setattr(mcp.client.sse, "sse_client", sse)


def mock_http(monkeypatch, handler):
    """Inject external network endpoints; preserve explicit ASGI transports."""
    original = httpx.AsyncClient.__init__

    def initialize(client, *args, **kwargs):
        if kwargs.get("transport") is None:
            kwargs["transport"] = httpx.MockTransport(handler)
        original(client, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", initialize)
