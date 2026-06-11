# -*- coding: utf-8 -*-
"""Unit tests for ``qwenpaw.app.mcp.stateful_client`` (agentscope 2.0).

Verifies that the stateful MCP clients construct and that ``list_tools``
returns ``agentscope.tool.MCPTool`` (``ToolBase``) instances wired so the
server receives the **real** (un-sanitized) MCP tool name, while the model
sees the namespaced ``mcp__{server}__{sanitized}`` function.  This is the
contract agentscope 2.0's ``Toolkit`` relies on (it registers the returned
objects directly and reads ``tool.is_mcp`` / ``tool.name`` then calls
``tool(**kwargs)``).  No real network or subprocess is started — the session
is a fake stub.
"""

# pylint: disable=protected-access,redefined-outer-name
from __future__ import annotations

import mcp.types as mcp_types
import pytest

from agentscope.tool import MCPTool, ToolBase

from qwenpaw.app.mcp.stateful_client import (
    HttpStatefulClient,
    StdIOStatefulClient,
    _LazyClientSession,
)


def _tool(name: str) -> mcp_types.Tool:
    return mcp_types.Tool(
        name=name,
        description=f"desc for {name}",
        inputSchema={"type": "object", "properties": {}},
    )


class _FakeCallResult:
    """Minimal stand-in for mcp ``CallToolResult``."""

    def __init__(self) -> None:
        self.content = []
        self.isError = False


class _FakeSession:
    """Minimal ClientSession stub recording call_tool / list_tools."""

    def __init__(self, tools=None) -> None:
        self.calls = []
        self._tools = tools or []

    async def list_tools(self):
        return mcp_types.ListToolsResult(tools=self._tools)

    async def call_tool(self, name, arguments=None, **_kwargs):
        self.calls.append((name, arguments))
        return _FakeCallResult()


def _connect(client, session_tools, whitelist=None):
    """Put the client into a connected state served by a fake session."""
    client.session = _FakeSession(tools=session_tools)
    client.is_connected = True
    client._ready_event.set()
    client._tool_whitelist = whitelist


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_stdio_client_constructs():
    client = StdIOStatefulClient(name="srv", command="echo", args=["hi"])
    assert client.name == "srv"
    assert client.is_stateful is True
    assert client.is_connected is False


def test_http_client_constructs():
    client = HttpStatefulClient(
        name="srv",
        transport="streamable_http",
        url="https://example.test/mcp",
    )
    assert client.name == "srv"
    assert client.is_stateful is True
    assert client.transport == "streamable_http"


def test_http_client_rejects_bad_transport():
    with pytest.raises(ValueError):
        HttpStatefulClient(
            name="srv",
            transport="ftp",
            url="https://example.test/mcp",
        )


# ---------------------------------------------------------------------------
# list_tools -> list[MCPTool] (the live Toolkit path)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_tools_returns_mcptool_instances():
    """The live path: agentscope's Toolkit registers list_tools() output
    directly, so each item MUST be an MCPTool (ToolBase), not a raw
    mcp.types.Tool."""
    client = StdIOStatefulClient(name="srv", command="echo")
    _connect(client, [_tool("alpha"), _tool("beta")])

    tools = await client.list_tools()

    assert len(tools) == 2
    for t in tools:
        assert isinstance(t, MCPTool)
        assert isinstance(t, ToolBase)
        assert t.is_mcp is True
        assert t.is_state_injected is False
    names = {t.name for t in tools}
    assert names == {"mcp__srv__alpha", "mcp__srv__beta"}
    # Cache also holds MCPTool instances (served on reconnect fallback).
    assert all(isinstance(t, MCPTool) for t in client._cached_tools)


@pytest.mark.asyncio
async def test_list_tools_applies_whitelist_on_sanitized_names():
    client = StdIOStatefulClient(name="srv", command="echo")
    _connect(
        client,
        [_tool("alpha"), _tool("beta")],
        whitelist={"alpha"},
    )

    tools = await client.list_tools()

    assert [t.name for t in tools] == ["mcp__srv__alpha"]


@pytest.mark.asyncio
async def test_list_tools_sanitizes_name_but_dispatches_real_name():
    """A server tool whose name has invalid chars is exposed under a
    sanitized model-facing name, yet dispatches to the server under the real
    name."""
    client = StdIOStatefulClient(name="srv", command="echo")
    _connect(client, [_tool("weird.tool")])

    tools = await client.list_tools()

    assert len(tools) == 1
    fn = tools[0]
    # Model-facing name: namespaced + sanitized (no dot).
    assert fn.name == "mcp__srv__weird_tool"
    # Underlying tool keeps the REAL name for server dispatch.
    assert fn._tool.name == "weird.tool"

    await fn(**{})
    dispatched_name = client.session.calls[-1][0]
    assert dispatched_name == "weird.tool"


@pytest.mark.asyncio
async def test_list_tools_valid_name_dispatches_unchanged():
    client = StdIOStatefulClient(name="srv", command="echo")
    _connect(client, [_tool("alpha")])

    fn = (await client.list_tools())[0]
    await fn(**{"x": 1})

    assert client.session.calls[-1] == ("alpha", {"x": 1})


# ---------------------------------------------------------------------------
# get_callable_function (compatibility shim over the cache)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_callable_function_returns_cached_mcptool():
    client = StdIOStatefulClient(name="srv", command="echo")
    _connect(client, [_tool("alpha")])

    by_bare = await client.get_callable_function("alpha")
    by_namespaced = await client.get_callable_function("mcp__srv__alpha")

    assert isinstance(by_bare, MCPTool)
    assert by_bare.name == "mcp__srv__alpha"
    assert by_namespaced is by_bare


@pytest.mark.asyncio
async def test_get_callable_function_unknown_tool_raises():
    client = StdIOStatefulClient(name="srv", command="echo")
    _connect(client, [_tool("alpha")])

    with pytest.raises(ValueError):
        await client.get_callable_function("does-not-exist")


# ---------------------------------------------------------------------------
# _LazyClientSession — resolves the live session and translates aliases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lazy_session_resolves_live_session_after_reconnect():
    """Cached MCPTools dispatch through whatever ``client.session`` currently
    is, so they survive a reconnect that rebinds the session."""
    client = StdIOStatefulClient(name="srv", command="echo")
    _connect(client, [_tool("alpha")])
    proxy = _LazyClientSession(client)

    # Simulate a reconnect: swap in a brand-new session object.
    new_session = _FakeSession()
    client.session = new_session

    await proxy.call_tool("alpha", arguments={"x": 1})

    assert new_session.calls == [("alpha", {"x": 1})]


@pytest.mark.asyncio
async def test_lazy_session_translates_sanitized_name():
    client = StdIOStatefulClient(name="srv", command="echo")
    _connect(client, [_tool("weird_tool")])
    client._name_alias_to_real = {"weird_tool": "weird.tool"}
    proxy = _LazyClientSession(client)

    await proxy.call_tool("weird_tool", arguments={"y": 2})

    assert client.session.calls == [("weird.tool", {"y": 2})]
