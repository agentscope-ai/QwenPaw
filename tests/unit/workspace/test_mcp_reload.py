# -*- coding: utf-8 -*-
"""Tests for MCP hot-reload safety handling."""
# pylint: disable=protected-access

from types import SimpleNamespace

import pytest

from copaw.app.exceptions import AgentReloadRequiresRestartError
from copaw.app.multi_agent_manager import MultiAgentManager
from copaw.app.runner.daemon_commands import (
    DaemonContext,
    run_daemon_restart,
)
from copaw.config.config import MCPClientConfig, MCPConfig


def test_requires_serial_reload_when_any_client_is_unsafe():
    """Agents with unsafe MCP clients should avoid zero-downtime reload."""
    agent_config = SimpleNamespace(
        mcp=MCPConfig(
            clients={
                "chrome-mcp-stdio": MCPClientConfig(
                    name="chrome-mcp-stdio",
                    transport="stdio",
                    command="npx",
                    args=["node", "mcp-server-stdio.js"],
                    hot_reload_safe=False,
                ),
            },
        ),
    )

    assert MultiAgentManager._requires_serial_reload(agent_config) is True


def test_requires_serial_reload_ignores_disabled_or_safe_clients():
    """Disabled or default-safe MCP clients should not force serial reload."""
    agent_config = SimpleNamespace(
        mcp=MCPConfig(
            clients={
                "chrome-mcp-stdio": MCPClientConfig(
                    name="chrome-mcp-stdio",
                    enabled=False,
                    transport="stdio",
                    command="npx",
                    args=["node", "mcp-server-stdio.js"],
                    hot_reload_safe=False,
                ),
                "playwright": MCPClientConfig(
                    name="playwright",
                    transport="stdio",
                    command="npx",
                    args=["@playwright/mcp@latest"],
                ),
            },
        ),
    )

    assert MultiAgentManager._requires_serial_reload(agent_config) is False


@pytest.mark.asyncio
async def test_daemon_restart_reports_process_restart_when_reload_is_unsafe():
    """Unsafe reloads should return a restart-required message."""

    class FakeManager:
        async def reload_agent(self, _agent_id):
            raise AgentReloadRequiresRestartError(
                "Restart CoPaw to apply changes safely.",
            )

    context = DaemonContext(manager=FakeManager(), agent_id="default")

    result = await run_daemon_restart(context)

    assert result.startswith("**Restart requires process restart**")
