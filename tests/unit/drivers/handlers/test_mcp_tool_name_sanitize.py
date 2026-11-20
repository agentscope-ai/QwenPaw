# -*- coding: utf-8 -*-
# Imported pytest fixtures are explicit re-exports for fixture discovery.
# pylint: disable=redefined-outer-name

import re

import pytest

from qwenpaw.drivers.capabilities import parse_capability_id
from qwenpaw.drivers.contracts import DriverCard
from tests.integration.driver_mcp_fakes import (
    FakeStdIOClient,
    Tool,
    mcp_runtime_host as _mcp_runtime_host,
    patch_mcp_runtime_clients,
    sdk_mcp_manager,
)

mcp_runtime_host = _mcp_runtime_host


async def discover(host, tmp_path, monkeypatch, driver, names, display=""):
    patch_mcp_runtime_clients(monkeypatch)

    async def tools(_self):
        return [Tool(name) for name in names]

    monkeypatch.setattr(FakeStdIOClient, "list_tools", tools)
    manager = await sdk_mcp_manager(host, tmp_path)
    await manager.upsert_driver(
        DriverCard(
            name=driver,
            protocol="mcp",
            endpoint={"transport": "stdio", "command": "synthetic"},
            config={"display_name": display},
        ),
    )
    return await manager.list_capabilities()


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        (
            "-MCP__get_consensus_forecast",
            "-MCP__get_consensus_forecast",
        ),
        ("-A__get_esg_data", "-A__get_esg_data"),
        ("-__bond_basic_info", "-__bond_basic_info"),
        ("_get_esg_data", "_get_esg_data"),
        ("get_esg_data", "get_esg_data"),
        ("pat.batch_plan", "pat_batch_plan"),
        ("123", "123"),
        ("", "tool"),
    ],
)
async def test_sanitize_tool_name(
    name: str,
    expected: str,
    tmp_path,
    monkeypatch,
    mcp_runtime_host,
) -> None:
    capability = (
        await discover(
            mcp_runtime_host,
            tmp_path,
            monkeypatch,
            "source",
            [name],
        )
    )[0]
    assert capability.exposure.tool_name == "source__" + expected


@pytest.mark.parametrize(
    ("display_name", "fallback", "expected"),
    [
        ("MCP", "fallback", "MCP"),
        ("-MCP", "fallback", "tool_-MCP"),
        ("123MCP", "fallback", "tool_123MCP"),
        ("_MCP", "fallback", "tool__MCP"),
        ("-123-MCP", "fallback", "tool_-123-MCP"),
        ("123", "fallback", "tool_123"),
        ("---", "fallback", "tool_---"),
        ("", "-driver", "tool_-driver"),
        ("...", "client.with.dot", "client_with_dot"),
    ],
)
async def test_tool_namespace_starts_with_letter(
    display_name: str,
    fallback: str,
    expected: str,
    tmp_path,
    monkeypatch,
    mcp_runtime_host,
) -> None:
    capability = (
        await discover(
            mcp_runtime_host,
            tmp_path,
            monkeypatch,
            fallback,
            ["echo"],
            display_name,
        )
    )[0]
    assert capability.exposure.namespace == expected


async def test_mcp_capability_sanitizes_only_exposed_tool_name(
    tmp_path,
    monkeypatch,
    mcp_runtime_host,
) -> None:
    original_name = "-__bond_basic_info"
    capability = (
        await discover(
            mcp_runtime_host,
            tmp_path,
            monkeypatch,
            "bond-driver",
            [original_name],
            "-MCP",
        )
    )[0]

    assert capability.name == original_name
    assert parse_capability_id(capability.capability_id)[-1] == original_name
    assert capability.exposure.namespace == "tool_-MCP"
    assert capability.exposure.tool_name == "tool_-MCP__-__bond_basic_info"
    assert re.fullmatch(
        r"[A-Za-z][A-Za-z0-9_-]*",
        capability.exposure.tool_name,
    )


async def test_exposed_tool_names_remain_unique(
    tmp_path,
    monkeypatch,
    mcp_runtime_host,
) -> None:
    original_names = ["foo", "-foo", "_foo", "123foo"]
    discovered = await discover(
        mcp_runtime_host,
        tmp_path,
        monkeypatch,
        "test-driver",
        original_names,
        "-MCP",
    )
    capabilities = sorted(
        discovered,
        key=lambda cap: original_names.index(cap.name),
    )

    exposed_names = [
        capability.exposure.tool_name for capability in capabilities
    ]
    assert exposed_names == [
        "tool_-MCP__foo",
        "tool_-MCP__-foo",
        "tool_-MCP___foo",
        "tool_-MCP__123foo",
    ]
    assert len(set(exposed_names)) == len(original_names)
    assert all(
        re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", name) for name in exposed_names
    )
    assert [capability.name for capability in capabilities] == original_names
    assert [
        parse_capability_id(capability.capability_id)[-1]
        for capability in capabilities
    ] == original_names


async def test_exposed_tool_names_are_unique_across_driver_namespaces(
    tmp_path,
    monkeypatch,
    mcp_runtime_host,
) -> None:
    driver_names = ["mcp-driver", "dash-mcp-driver", "numeric-mcp-driver"]
    display_names = ["MCP", "-MCP", "123MCP"]
    original_name = "shared_tool"
    capabilities = []
    for driver_name, display_name in zip(driver_names, display_names):
        capabilities.extend(
            await discover(
                mcp_runtime_host,
                tmp_path,
                monkeypatch,
                driver_name,
                [original_name],
                display_name,
            ),
        )

    assert [capability.exposure.namespace for capability in capabilities] == [
        "MCP",
        "tool_-MCP",
        "tool_123MCP",
    ]
    exposed_names = [
        capability.exposure.tool_name for capability in capabilities
    ]
    assert len(set(exposed_names)) == len(capabilities)
    assert all(
        re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", name) for name in exposed_names
    )
    assert [capability.name for capability in capabilities] == [
        original_name,
    ] * len(capabilities)
    parsed_ids = [
        parse_capability_id(capability.capability_id)
        for capability in capabilities
    ]
    assert [parsed_id[1] for parsed_id in parsed_ids] == driver_names
    assert [parsed_id[-1] for parsed_id in parsed_ids] == [
        original_name,
    ] * len(capabilities)
