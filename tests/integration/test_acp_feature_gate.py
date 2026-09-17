# -*- coding: utf-8 -*-
"""ACP 产品关闭后的路由与兼容契约。"""

from __future__ import annotations

from qwenpaw.app._app import _without_retired_acp_product_tools, app
from qwenpaw.app.routers.tools import _is_tool_published


def _route_methods(path: str) -> set[str]:
    operation = app.openapi()["paths"].get(path, {})
    return {method.upper() for method in operation}


def test_acp_product_writes_are_not_published() -> None:
    """ACP 历史配置只读可用，但不再发布任何修改入口。"""
    paths = (
        "/api/config/acp",
        "/api/config/acp/node-runtime",
        "/api/config/acp/{agent_name}",
        "/api/agents/{agentId}/config/acp",
        "/api/agents/{agentId}/config/acp/node-runtime",
        "/api/agents/{agentId}/config/acp/{agent_name}",
    )

    for path in paths:
        methods = _route_methods(path)
        assert "GET" in methods, path
        assert methods.isdisjoint({"POST", "PUT", "PATCH", "DELETE"}), path


def test_harness_and_mcp_compatibility_routes_remain_published() -> None:
    """关闭 ACP 产品不能移除历史 Harness/MCP 的兼容读取。"""
    assert "GET" in _route_methods("/api/harnesses")
    assert "GET" in _route_methods("/api/harnesses/{provider_id}/mcp")
    assert "GET" in _route_methods("/api/mcp")
    assert "GET" in _route_methods("/api/agents/{agentId}/mcp")


def test_new_workspaces_do_not_register_acp_product_tool() -> None:
    """历史实现仍可导入，但 Web 应用的新调用链不注册 ACP 工具。"""

    def delegate_external_agent() -> None:
        pass

    def regular_tool() -> None:
        pass

    assert _without_retired_acp_product_tools(
        [delegate_external_agent, regular_tool],
    ) == [regular_tool]
    assert _is_tool_published("delegate_external_agent") is False
    assert _is_tool_published("regular_tool") is True
