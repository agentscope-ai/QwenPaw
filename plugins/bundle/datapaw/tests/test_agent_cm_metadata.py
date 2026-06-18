# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Tests for DataPawAgent datasource_id -> metadata injection."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


def _make_agent(**attrs):
    """Build a DataPawAgent shell without running __init__."""
    from plugin_datapaw.core.agents.base import DataPawAgent

    agent = DataPawAgent.__new__(DataPawAgent)
    for key, value in attrs.items():
        setattr(agent, key, value)
    return agent


# ---------------------------------------------------------------------------
# _inject_datasource_metadata
# ---------------------------------------------------------------------------


def test_inject_replaces_metadata_for_cm_tool():
    agent = _make_agent(
        _cm_tool_names={"fetch_data"},
        _request_context={"datasource_id": "mysql-abc123"},
    )
    tool_call = {
        "name": "fetch_data",
        "input": {
            "query": "select 1",
            "metadata": {"datasource_id": "llm-wrong", "keep": "drop"},
        },
    }

    agent._inject_datasource_metadata(tool_call)

    assert tool_call["input"]["metadata"] == {"datasource_id": "mysql-abc123"}
    assert tool_call["input"]["query"] == "select 1"


def test_inject_skips_non_cm_tool():
    agent = _make_agent(
        _cm_tool_names={"fetch_data"},
        _request_context={"datasource_id": "mysql-abc123"},
    )
    tool_call = {"name": "other_tool", "input": {"a": 1}}

    agent._inject_datasource_metadata(tool_call)

    assert tool_call == {"name": "other_tool", "input": {"a": 1}}


def test_inject_skips_when_no_datasource_id():
    agent = _make_agent(
        _cm_tool_names={"fetch_data"},
        _request_context={},
    )
    tool_call = {"name": "fetch_data", "input": {"query": "select 1"}}

    agent._inject_datasource_metadata(tool_call)

    assert "metadata" not in tool_call["input"]


def test_inject_creates_input_when_missing():
    agent = _make_agent(
        _cm_tool_names={"fetch_data"},
        _request_context={"datasource_id": "mysql-abc123"},
    )
    tool_call = {"name": "fetch_data"}

    agent._inject_datasource_metadata(tool_call)

    assert tool_call["input"] == {"metadata": {"datasource_id": "mysql-abc123"}}


# ---------------------------------------------------------------------------
# register_mcp_clients tool-name collection
# ---------------------------------------------------------------------------


def _fake_client(name, tool_names=None, raises=False):
    async def list_tools():
        if raises:
            raise RuntimeError("boom")
        return [SimpleNamespace(name=n) for n in (tool_names or [])]

    return SimpleNamespace(name=name, list_tools=list_tools)


def test_register_collects_only_cm_tool_names():
    from plugin_datapaw.core.agents.base import CM_MCP_NAME

    cm_client = _fake_client(CM_MCP_NAME, ["fetch_data", "run_sql"])
    agent = _make_agent(
        _mcp_clients=[
            cm_client,
            _fake_client("Other MCP", ["foo"]),
        ],
    )

    with patch(
        "qwenpaw.agents.react_agent.QwenPawAgent.register_mcp_clients",
        new=AsyncMock(),
    ):
        asyncio.run(agent.register_mcp_clients())

    assert agent._cm_tool_names == {"fetch_data", "run_sql"}


def test_register_collects_context_manager_by_name():
    cm_client = _fake_client("Context Manager", ["execute_sql"])
    agent = _make_agent(_mcp_clients=[cm_client])

    with patch(
        "qwenpaw.agents.react_agent.QwenPawAgent.register_mcp_clients",
        new=AsyncMock(),
    ):
        asyncio.run(agent.register_mcp_clients())

    assert agent._cm_tool_names == {"execute_sql"}


def test_register_handles_list_tools_failure():
    from plugin_datapaw.core.agents.base import CM_MCP_NAME

    agent = _make_agent(
        _mcp_clients=[_fake_client(CM_MCP_NAME, raises=True)],
    )

    with patch(
        "qwenpaw.agents.react_agent.QwenPawAgent.register_mcp_clients",
        new=AsyncMock(),
    ):
        asyncio.run(agent.register_mcp_clients())

    assert agent._cm_tool_names == set()
