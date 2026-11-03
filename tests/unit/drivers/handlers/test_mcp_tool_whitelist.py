# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""MCP per-tool whitelist: discovery tags, assembly filters, invoke rejects."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from qwenpaw.app.mcp.config_service import MCPConfigService
from qwenpaw.drivers.adapters.agentscope_tool import build_driver_agent_tools
from qwenpaw.drivers.capabilities import (
    CapabilityExposure,
    DriverCapability,
    DriverInvocation,
    DriverInvocationResult,
    format_capability_id,
    mcp_tool_is_enabled,
    mcp_tool_whitelist,
)
from qwenpaw.drivers.contracts import DriverCard
from qwenpaw.drivers.credentials.providers import NoneProvider
from qwenpaw.drivers.handlers.mcp import (
    MCPDriverHandler,
    _mcp_tool_to_capability,
)


def _tool(name: str) -> SimpleNamespace:
    return SimpleNamespace(name=name, description="", inputSchema={})


def _handler(tools_config: Any) -> MCPDriverHandler:
    card = DriverCard(
        name="fs",
        protocol="mcp",
        endpoint={"transport": "stdio", "command": "true"},
        config={"tools": tools_config},
    )
    return MCPDriverHandler(card, NoneProvider())


@pytest.mark.parametrize(
    ("whitelist", "name", "expected"),
    [
        (None, "write", True),
        ([], "write", False),
        (["read"], "read", True),
        (["read"], "write", False),
        ("read", "write", True),
    ],
)
def test_mcp_tool_is_enabled(
    whitelist: Any,
    name: str,
    expected: bool,
) -> None:
    assert mcp_tool_is_enabled(mcp_tool_whitelist(whitelist), name) is expected


@pytest.mark.parametrize(
    ("whitelist", "expected"),
    [
        (None, True),
        (["read"], True),
        (["write"], False),
        ([], False),
    ],
)
def test_mcp_capability_enabled_from_whitelist(
    whitelist: list[str] | None,
    expected: bool,
) -> None:
    capability = _mcp_tool_to_capability(
        "fs",
        _tool("read"),
        whitelist=mcp_tool_whitelist(whitelist),
    )
    assert capability.name == "read"
    assert capability.enabled is expected
    assert capability.exposure.as_tool is True


def test_mcp_prefixed_tool_name_uses_raw_whitelist_key() -> None:
    capability = _mcp_tool_to_capability(
        "fs",
        _tool("mcp__fs__read"),
        whitelist=mcp_tool_whitelist(["read"]),
    )
    assert capability.name == "read"
    assert capability.enabled is True


@pytest.mark.asyncio
async def test_build_driver_agent_tools_omits_disabled() -> None:
    enabled = DriverCapability(
        capability_id="on",
        driver_name="fs",
        protocol="mcp",
        kind="tool",
        action="invoke",
        name="read",
        exposure=CapabilityExposure(as_tool=True, tool_name="fs__read"),
        enabled=True,
    )
    disabled = DriverCapability(
        capability_id="off",
        driver_name="fs",
        protocol="mcp",
        kind="tool",
        action="invoke",
        name="write",
        exposure=CapabilityExposure(as_tool=True, tool_name="fs__write"),
        enabled=False,
    )

    class _Manager:
        async def list_capabilities(
            self,
            **_kwargs: Any,
        ) -> list[DriverCapability]:
            return [enabled, disabled]

        async def invoke_capability(self, *_args: Any, **_kwargs: Any) -> Any:
            return DriverInvocationResult(ok=True)

    tools, _hints = await build_driver_agent_tools(_Manager(), {})
    assert [tool.name for tool in tools] == ["fs__read"]


@pytest.mark.asyncio
async def test_build_driver_agent_tools_missing_enabled_stays_open() -> None:
    cap = SimpleNamespace(
        exposure=CapabilityExposure(as_tool=True, tool_name="fs__read"),
        name="read",
        description="",
        input_schema={},
    )

    class _Manager:
        async def list_capabilities(self, **_kwargs: Any) -> list[Any]:
            return [cap]

        async def invoke_capability(self, *_args: Any, **_kwargs: Any) -> Any:
            return DriverInvocationResult(ok=True)

    tools, _hints = await build_driver_agent_tools(_Manager(), {})
    assert [tool.name for tool in tools] == ["fs__read"]


@pytest.mark.asyncio
async def test_list_capabilities_reads_card_config_tools() -> None:
    handler = _handler(["read"])

    async def _list_tools() -> list[SimpleNamespace]:
        return [_tool("read"), _tool("write")]

    handler.list_tools = _list_tools  # type: ignore[method-assign]
    capabilities = await handler.list_capabilities()
    assert {item.name: item.enabled for item in capabilities} == {
        "read": True,
        "write": False,
    }


@pytest.mark.asyncio
async def test_sync_runtime_metadata_clears_capability_cache() -> None:
    handler = _handler(["read"])

    async def _list_tools() -> list[SimpleNamespace]:
        return [_tool("read"), _tool("write")]

    handler.list_tools = _list_tools  # type: ignore[method-assign]
    await handler.list_capabilities()
    assert handler._capability_cache is not None

    handler.sync_runtime_metadata(
        DriverCard(
            name="fs",
            protocol="mcp",
            endpoint={"transport": "stdio", "command": "true"},
            config={"tools": ["read", "write"]},
        ),
    )
    assert handler._capability_cache is None
    capabilities = await handler.list_capabilities()
    assert {item.name: item.enabled for item in capabilities} == {
        "read": True,
        "write": True,
    }


@pytest.mark.asyncio
async def test_list_capabilities_disabled_tools_omitted_from_toolkit() -> None:
    handler = _handler(["read"])

    async def _list_tools() -> list[SimpleNamespace]:
        return [_tool("read"), _tool("write")]

    handler.list_tools = _list_tools  # type: ignore[method-assign]
    capabilities = await handler.list_capabilities()

    class _Manager:
        async def list_capabilities(
            self,
            **_kwargs: Any,
        ) -> list[DriverCapability]:
            return capabilities

        async def invoke_capability(self, *_args: Any, **_kwargs: Any) -> Any:
            return DriverInvocationResult(ok=True)

    tools, _hints = await build_driver_agent_tools(_Manager(), {})
    assert [tool.name for tool in tools] == ["fs__read"]


@pytest.mark.asyncio
async def test_list_capabilities_non_list_whitelist_is_open() -> None:
    handler = _handler("read")

    async def _list_tools() -> list[SimpleNamespace]:
        return [_tool("read"), _tool("write")]

    handler.list_tools = _list_tools  # type: ignore[method-assign]
    capabilities = await handler.list_capabilities()
    assert all(item.enabled for item in capabilities)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tools_config", "tool_name", "disabled"),
    [
        (["read"], "write", True),
        (["read"], "read", False),
        ([], "read", True),
    ],
)
async def test_invoke_capability_whitelist_contract(
    tools_config: list[str],
    tool_name: str,
    disabled: bool,
) -> None:
    handler = _handler(tools_config)
    result = await handler.invoke_capability(
        DriverInvocation(
            capability_id=format_capability_id(
                "mcp",
                "fs",
                "tool",
                "invoke",
                tool_name,
            ),
            payload={},
        ),
    )
    if disabled:
        assert result.ok is False
        assert result.error_type == "tool_disabled"
        assert result.metadata == {
            "driver_name": "fs",
            "tool_name": tool_name,
        }
        return
    assert result.error_type != "tool_disabled"


def _whitelist_service(*, refresh_fails: bool) -> tuple[Any, ...]:
    card = DriverCard(
        name="fs",
        protocol="mcp",
        endpoint={"transport": "stdio", "command": "true"},
        config={"tools": ["write"]},
    )
    saves: list[bool] = []
    refreshed: list[str] = []
    reloads: list[str] = []

    class _Store:
        async def load_card(self, *_args: Any, **_kwargs: Any) -> DriverCard:
            return card

        async def save_card(
            self,
            saved: DriverCard,
            *,
            reload_driver: bool = True,
        ) -> None:
            card.config = dict(saved.config)
            saves.append(reload_driver)

        async def list_driver_capabilities(
            self,
            *_args: Any,
            **_kwargs: Any,
        ) -> list[Any]:
            return []

        async def reload_driver_best_effort(self, name: str) -> None:
            reloads.append(name)

    class _Manager:
        async def refresh_driver(self, name: str) -> None:
            refreshed.append(name)
            if refresh_fails:
                raise RuntimeError("refresh failed")

        async def reload_driver(self, name: str) -> None:
            raise AssertionError("reload_driver should not run")

    service = MCPConfigService(SimpleNamespace(driver_manager=_Manager()))
    service._driver_config = _Store()
    return service, card, saves, refreshed, reloads


@pytest.mark.asyncio
async def test_update_tool_whitelist_refreshes_without_reload() -> None:
    service, card, saves, refreshed, reloads = _whitelist_service(
        refresh_fails=False,
    )
    result = await service.update_tool_whitelist("fs", ["read"])
    assert saves == [False]
    assert refreshed == ["fs"]
    assert not reloads
    assert card.config["tools"] == ["read"]
    assert result == []


@pytest.mark.asyncio
async def test_update_tool_whitelist_rejects_when_refresh_fails() -> None:
    service, card, saves, refreshed, reloads = _whitelist_service(
        refresh_fails=True,
    )
    with pytest.raises(HTTPException) as caught:
        await service.update_tool_whitelist("fs", ["read"])
    assert caught.value.status_code == 502
    assert saves == [False]
    assert refreshed == ["fs"]
    assert not reloads
    assert card.config["tools"] == ["read"]
