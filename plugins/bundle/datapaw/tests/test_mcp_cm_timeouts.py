# -*- coding: utf-8 -*-
"""Tests for CM MCP long-timeout helpers and build-client patch."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from plugin_datapaw.core.mcp_cm import (
    CM_MCP_SSE_READ_TIMEOUT,
    apply_cm_mcp_long_timeouts,
    is_cm_mcp_client,
    is_cm_mcp_config,
)
from plugin_datapaw.hooks import setup_mcp_timeout_hook
from qwenpaw.app.mcp.stateful_client import HttpStatefulClient


def test_is_cm_mcp_config_by_url():
    cfg = SimpleNamespace(
        url="http://pre-context-management.alibaba-inc.com/mcp/v1/cm",
        name="Context Manager",
    )
    assert is_cm_mcp_config(cfg) is True


def test_is_cm_mcp_config_by_name():
    cfg = SimpleNamespace(url="", name="Context Manager")
    assert is_cm_mcp_config(cfg) is True


def test_is_cm_mcp_config_rejects_other():
    cfg = SimpleNamespace(url="http://example.com/mcp", name="Other")
    assert is_cm_mcp_config(cfg) is False


def test_is_cm_mcp_client_by_rebuild_info_url():
    client = SimpleNamespace(
        url="",
        name="anything",
        _qwenpaw_rebuild_info={
            "url": "http://pre-context-management.alibaba-inc.com/mcp/v1/cm",
        },
    )
    assert is_cm_mcp_client(client) is True


def test_apply_cm_mcp_long_timeouts_on_http_client():
    client = HttpStatefulClient(
        name="Context Manager",
        transport="streamable_http",
        url="http://pre-context-management.alibaba-inc.com/mcp/v1/cm",
    )
    assert client.read_timeout_seconds == 300

    apply_cm_mcp_long_timeouts(client)

    assert client.sse_read_timeout == CM_MCP_SSE_READ_TIMEOUT
    assert client.read_timeout_seconds == CM_MCP_SSE_READ_TIMEOUT


def test_setup_mcp_timeout_hook_extends_cm_client():
    cm_cfg = SimpleNamespace(
        url="http://pre-context-management.alibaba-inc.com/mcp/v1/cm",
        name="Context Manager",
    )
    other_cfg = SimpleNamespace(url="http://example.com/mcp", name="Other")

    class FakeManager:
        @staticmethod
        def _orig_build(client_config):
            if is_cm_mcp_config(client_config):
                return HttpStatefulClient(
                    name=client_config.name,
                    transport="streamable_http",
                    url=client_config.url,
                )
            return SimpleNamespace(name=client_config.name, url=client_config.url)

    FakeManager._build_client = classmethod(
        lambda cls, cfg: FakeManager._orig_build(cfg),
    )

    setup_mcp_timeout_hook(FakeManager)

    cm_client = FakeManager._build_client(cm_cfg)
    assert isinstance(cm_client, HttpStatefulClient)
    assert cm_client.read_timeout_seconds == CM_MCP_SSE_READ_TIMEOUT

    other_client = FakeManager._build_client(other_cfg)
    assert not isinstance(other_client, HttpStatefulClient)

    setup_mcp_timeout_hook(FakeManager)


def test_register_mcp_clients_applies_timeouts_before_super():
    from plugin_datapaw.core.agents.base import DataPawAgent

    client = HttpStatefulClient(
        name="Context Manager",
        transport="streamable_http",
        url="http://pre-context-management.alibaba-inc.com/mcp/v1/cm",
    )
    assert client.read_timeout_seconds == 300

    agent = DataPawAgent.__new__(DataPawAgent)
    agent._mcp_clients = [client]

    async def fake_list_tools():
        return [SimpleNamespace(name="execute_sql")]

    client.list_tools = fake_list_tools  # type: ignore[method-assign]

    with patch(
        "qwenpaw.agents.react_agent.QwenPawAgent.register_mcp_clients",
        new=AsyncMock(),
    ) as mock_super:
        asyncio.run(agent.register_mcp_clients())

    assert client.read_timeout_seconds == CM_MCP_SSE_READ_TIMEOUT
    mock_super.assert_awaited_once()
    assert agent._cm_tool_names == {"execute_sql"}
