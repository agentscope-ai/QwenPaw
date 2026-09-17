# -*- coding: utf-8 -*-

from qwenpaw.agents.slash_runtime import resolve_slash_route, route_to_prompt
from qwenpaw.config.config import (
    AgentProfileConfig,
    BuiltinToolConfig,
    MCPClientConfig,
    MCPConfig,
    ToolsConfig,
)


def _agent_config() -> AgentProfileConfig:
    config = AgentProfileConfig(id="default", name="Default")
    config.tools = ToolsConfig(
        builtin_tools={
            "get_current_time": BuiltinToolConfig(
                name="get_current_time",
                enabled=True,
            ),
            "disabled_tool": BuiltinToolConfig(
                name="disabled_tool",
                enabled=False,
            ),
        },
    )
    config.mcp = MCPConfig(
        clients={
            "search": MCPClientConfig(
                name="Search",
                enabled=True,
                command="npx",
            ),
            "disabled": MCPClientConfig(
                name="Disabled",
                enabled=False,
                command="npx",
            ),
        },
    )
    return config


def test_tool_slash_route_matches_enabled_tool():
    route = resolve_slash_route(
        "/tool get_current_time 当前时间",
        _agent_config(),
    )

    assert route is not None
    assert route.kind == "tool"
    assert route.tool_name == "get_current_time"
    assert route.args == "当前时间"
    assert route.error == ""
    assert "get_current_time" in route_to_prompt(route)


def test_tool_slash_route_rejects_disabled_tool():
    route = resolve_slash_route("/tool disabled_tool test", _agent_config())

    assert route is not None
    assert route.error


def test_mcp_tool_slash_route_matches_enabled_client():
    route = resolve_slash_route("/mcp search.web cats", _agent_config())

    assert route is not None
    assert route.kind == "mcp_tool"
    assert route.client_key == "search"
    assert route.mcp_tool_name == "web"
    assert route.args == "cats"
    assert "search.web" in route_to_prompt(route)


def test_mcp_slash_route_rejects_disabled_client():
    route = resolve_slash_route("/mcp disabled.web cats", _agent_config())

    assert route is not None
    assert route.error
