# -*- coding: utf-8 -*-
"""Integration test: MCP client disconnect → reconnect lifecycle.

Verifies the fix for GitHub issue #1308:
  RuntimeError: The MCP client is not connected to the server.

Test scenarios
--------------
1. Normal connection and tool invocation work.
2. After the MCP server process crashes, the manager detects the
   disconnected client and ``reconnect_disconnected()`` rebuilds
   a fresh client that re-connects automatically.
3. ``register_mcp_clients()`` on the agent side gracefully recovers
   (or skips) a disconnected client instead of raising RuntimeError.
"""
# pylint: disable=protected-access

from __future__ import annotations

import asyncio
import os
import signal
import sys
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, MagicMock

from anyio import ClosedResourceError
from agentscope.mcp import StdIOStatefulClient
import pytest

from copaw.app.mcp.manager import MCPClientManager

# Path to our tiny MCP server fixture
MOCK_SERVER = str(Path(__file__).with_name("fixtures") / "mock_mcp_server.py")
PYTHON = sys.executable


# ── helpers ──────────────────────────────────────────────────────────────────


def _build_test_client(name: str = "test-ping") -> StdIOStatefulClient:
    """Build a StdIOStatefulClient pointing at the mock server."""
    client = StdIOStatefulClient(
        name=name,
        command=PYTHON,
        args=[MOCK_SERVER],
    )
    # Attach rebuild metadata (same as MCPClientManager._build_client does)
    setattr(
        client,
        "_copaw_rebuild_info",
        {
            "name": name,
            "transport": "stdio",
            "command": PYTHON,
            "args": [MOCK_SERVER],
            "env": {},
            "cwd": None,
            "url": "",
            "headers": None,
        },
    )
    return client


async def _connect_client(client: StdIOStatefulClient) -> None:
    """Connect within the current task.

    AgentScope's stdio client stores anyio cleanup state on the calling task.
    Wrapping ``connect()`` in ``wait_for()``/timeout scopes moves cancellation
    into a different task/scope and makes teardown flaky, so the integration
    test keeps connection setup single-task and relies on the local fixture
    server to fail fast if startup is broken.
    """
    await client.connect()


def _get_client_process_pid(client: StdIOStatefulClient) -> int:
    """Extract the spawned stdio MCP server pid from AgentScope internals."""
    context_manager = getattr(client, "client", None)
    generator = getattr(context_manager, "gen", None)
    frame = getattr(generator, "ag_frame", None)
    if frame is None:
        pytest.skip(
            "Cannot inspect MCP stdio generator frame; "
            "AgentScope internals may have changed.",
        )

    process = frame.f_locals.get("process")
    pid = getattr(process, "pid", None)
    if not isinstance(pid, int):
        pytest.skip(
            "MCP stdio process pid is unavailable; "
            "AgentScope internals may have changed.",
        )

    return cast(int, pid)


async def _kill_client_process(client: StdIOStatefulClient) -> None:
    """Simulate a real MCP server crash by killing the child process."""
    if not hasattr(signal, "SIGKILL"):
        pytest.skip("SIGKILL is unavailable on this platform")
    os.kill(_get_client_process_pid(client), signal.SIGKILL)
    await asyncio.sleep(0.2)


# ── Test 1: basic connect → list_tools → call_tool ──────────────────────────


@pytest.mark.asyncio
async def test_normal_connect_and_call():
    """Sanity check: the mock MCP server works end-to-end."""
    client = _build_test_client()
    try:
        await _connect_client(client)
        assert client.is_connected

        tools = await client.list_tools()
        assert any(
            t.name == "ping" for t in tools
        ), f"Expected 'ping' in {tools}"

        func = await client.get_callable_function(
            "ping",
            wrap_tool_result=False,
        )
        result = await func()
        # result is CallToolResult
        assert any("pong" in str(c) for c in result.content)
    finally:
        if client.is_connected:
            await client.close()


# ── Test 2: manager.reconnect_disconnected() rebuilds after crash ────────────


@pytest.mark.asyncio
async def test_manager_reconnect_disconnected():
    """After the server crashes, reconnect_disconnected() should rebuild
    a fresh client and swap it into the manager atomically."""
    manager = MCPClientManager()

    # --- Phase 1: connect normally ---
    client = _build_test_client()
    await _connect_client(client)
    assert client.is_connected

    # Put it in the manager (simulate init_from_config)
    manager._clients["ping"] = client

    # --- Phase 2: kill the underlying stdio subprocess ---
    await _kill_client_process(client)
    assert client.is_connected
    with pytest.raises(ClosedResourceError):
        await client.list_tools()

    # The manager still holds this broken-looking client
    clients = await manager.get_clients()
    assert len(clients) == 1
    assert clients[0] is client

    # --- Phase 3: health check should rebuild and reconnect ---
    await manager.reconnect_disconnected(timeout=15)

    clients = await manager.get_clients()
    assert len(clients) == 1
    new_client = clients[0]
    assert new_client.is_connected, "Client should be reconnected"
    assert new_client is not client, "Should be a fresh instance"

    # Verify the new client actually works
    tools = await new_client.list_tools()
    assert any(t.name == "ping" for t in tools)

    # Cleanup
    await manager.close_all()


# ── Test 3: manager.reconnect_disconnected() is no-op when all healthy ───────


@pytest.mark.asyncio
async def test_reconnect_disconnected_noop_when_healthy():
    """reconnect_disconnected() should return immediately if all clients
    are already connected."""
    manager = MCPClientManager()

    client = _build_test_client()
    await _connect_client(client)
    manager._clients["ping"] = client

    # Should be a no-op — no rebuild needed
    await manager.reconnect_disconnected(timeout=5)

    clients = await manager.get_clients()
    assert len(clients) == 1
    assert clients[0] is client  # Same instance — not replaced
    assert clients[0].is_connected

    await manager.close_all()


# ── Test 4: register_mcp_clients pre-flight recovers disconnected client ─────


@pytest.mark.asyncio
async def test_register_mcp_clients_preflight_recovery():
    """register_mcp_clients() should detect is_connected=False and attempt
    recovery BEFORE calling toolkit.register_mcp_client(), preventing the
    RuntimeError that caused issue #1308."""
    from copaw.agents.react_agent import CoPawAgent

    # Build a client that is already disconnected (simulates post-crash state)
    client = _build_test_client()
    await _connect_client(client)
    await client.close()
    assert not client.is_connected

    # We need to mock the agent construction minimally.
    # The key test: register_mcp_clients should NOT raise RuntimeError.
    # It should either recover the client or skip it gracefully.

    # Create a mock agent-like object that has the relevant methods
    # We'll test the method in isolation by calling it on a real agent
    # with mocked dependencies.

    # Patch _recover_mcp_client to simulate successful recovery
    recovered_client = _build_test_client("recovered")
    await _connect_client(recovered_client)

    mock_toolkit = MagicMock()
    mock_toolkit.register_mcp_client = AsyncMock()

    # Create a partial agent-like harness
    class AgentHarness:
        """Minimal harness with the register_mcp_clients method."""

        def __init__(self):
            self._mcp_clients = [client]
            self.toolkit = mock_toolkit

        async def _recover_mcp_client(self, _client):
            return recovered_client

    harness = AgentHarness()
    # This should NOT raise RuntimeError
    await CoPawAgent.register_mcp_clients(harness)

    # Verify that toolkit.register_mcp_client was called with the
    # recovered client (not the broken one)
    mock_toolkit.register_mcp_client.assert_called_once()
    call_args = mock_toolkit.register_mcp_client.call_args
    assert call_args[0][0] is recovered_client
    assert harness._mcp_clients[0] is recovered_client

    # Cleanup
    await recovered_client.close()


# ── Test 5: register_mcp_clients skips when recovery fails ───────────────────


@pytest.mark.asyncio
async def test_register_mcp_clients_skips_on_failed_recovery():
    """When a client is disconnected and recovery fails, the agent should
    skip it gracefully rather than raising RuntimeError."""
    from copaw.agents.react_agent import CoPawAgent

    client = _build_test_client()
    await _connect_client(client)
    await client.close()
    assert not client.is_connected

    mock_toolkit = MagicMock()
    mock_toolkit.register_mcp_client = AsyncMock()

    class AgentHarness:
        def __init__(self):
            self._mcp_clients = [client]
            self.toolkit = mock_toolkit

        async def _recover_mcp_client(self, _client):
            return None  # Recovery fails

    harness = AgentHarness()
    # Should NOT raise — just skip the broken client
    await CoPawAgent.register_mcp_clients(harness)

    # toolkit.register_mcp_client should never be called (client was skipped)
    mock_toolkit.register_mcp_client.assert_not_called()


# ── Test 6: watcher health-check auto-recovers after server crash ────────────


@pytest.mark.asyncio
async def test_watcher_health_check_auto_recovery():
    """Simulate a real-world scenario: MCP server process is killed, then
    the watcher's periodic health check detects the broken connection and
    rebuilds the client automatically within one poll cycle."""
    from copaw.app.mcp.watcher import MCPConfigWatcher

    manager = MCPClientManager()

    # --- Phase 1: connect normally ---
    client = _build_test_client()
    await _connect_client(client)
    manager._clients["ping"] = client

    # Verify it works
    tools = await client.list_tools()
    assert any(t.name == "ping" for t in tools)

    # --- Phase 2: kill the subprocess to simulate a real crash ---
    await _kill_client_process(client)
    assert client.is_connected
    with pytest.raises(ClosedResourceError):
        await client.list_tools()

    # --- Phase 3: create watcher and run one health-check cycle ---
    watcher = MCPConfigWatcher(
        mcp_manager=manager,
        config_loader=lambda: MagicMock(mcp=MagicMock(clients={})),
        poll_interval=1.0,
    )
    # Call health check directly (don't start the full poll loop)
    await watcher._health_check()

    # --- Phase 4: verify recovery ---
    clients = await manager.get_clients()
    assert len(clients) == 1
    new_client = clients[0]
    assert (
        new_client.is_connected
    ), "Watcher should have reconnected the client"

    # Verify the rebuilt client actually works
    tools = await new_client.list_tools()
    assert any(t.name == "ping" for t in tools)

    await manager.close_all()


# ── Test 7: _build_client_from_info produces working client ──────────────────


@pytest.mark.asyncio
async def test_build_client_from_info():
    """MCPClientManager._build_client_from_info should produce a connectable
    client from rebuild metadata."""
    rebuild_info = {
        "name": "test-rebuild",
        "transport": "stdio",
        "command": PYTHON,
        "args": [MOCK_SERVER],
        "env": {},
        "cwd": None,
    }

    client = MCPClientManager._build_client_from_info(rebuild_info)
    assert client is not None
    assert not client.is_connected

    await _connect_client(client)
    assert client.is_connected

    tools = await client.list_tools()
    assert any(t.name == "ping" for t in tools)

    await client.close()
