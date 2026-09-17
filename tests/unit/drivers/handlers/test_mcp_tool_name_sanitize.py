# -*- coding: utf-8 -*-

import re
from types import SimpleNamespace

import pytest

from qwenpaw.drivers.capabilities import parse_capability_id
from qwenpaw.drivers.handlers.mcp import (
    _mcp_tool_to_capability,
    _sanitize_tool_name,
    _tool_namespace_from_display_name,
)


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
def test_sanitize_tool_name(name: str, expected: str) -> None:
    assert _sanitize_tool_name(name) == expected


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
def test_tool_namespace_starts_with_letter(
    display_name: str,
    fallback: str,
    expected: str,
) -> None:
    assert (
        _tool_namespace_from_display_name(display_name, fallback=fallback)
        == expected
    )


def test_mcp_capability_sanitizes_only_exposed_tool_name() -> None:
    original_name = "-__bond_basic_info"
    tool = SimpleNamespace(
        name=original_name,
        description="Bond details",
        inputSchema={},
    )

    capability = _mcp_tool_to_capability(
        "bond-driver",
        tool,
        display_name="-MCP",
    )

    assert capability.name == original_name
    assert parse_capability_id(capability.capability_id)[-1] == original_name
    assert capability.exposure.namespace == "tool_-MCP"
    assert capability.exposure.tool_name == "tool_-MCP__-__bond_basic_info"
    assert re.fullmatch(
        r"[A-Za-z][A-Za-z0-9_-]*",
        capability.exposure.tool_name,
    )


def test_exposed_tool_names_remain_unique() -> None:
    original_names = ["foo", "-foo", "_foo", "123foo"]
    capabilities = [
        _mcp_tool_to_capability(
            "test-driver",
            SimpleNamespace(
                name=name,
                description="Test tool",
                inputSchema={},
            ),
            display_name="-MCP",
        )
        for name in original_names
    ]

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


def test_exposed_tool_names_are_unique_across_driver_namespaces() -> None:
    driver_names = ["mcp-driver", "dash-mcp-driver", "numeric-mcp-driver"]
    display_names = ["MCP", "-MCP", "123MCP"]
    original_name = "shared_tool"
    capabilities = [
        _mcp_tool_to_capability(
            driver_name,
            SimpleNamespace(
                name=original_name,
                description="Test tool",
                inputSchema={},
            ),
            display_name=display_name,
        )
        for driver_name, display_name in zip(driver_names, display_names)
    ]

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
