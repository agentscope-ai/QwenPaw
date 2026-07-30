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


def test_tool_namespace_starts_with_letter() -> None:
    assert (
        _tool_namespace_from_display_name("-123-MCP", fallback="fallback")
        == "MCP"
    )
    assert (
        _tool_namespace_from_display_name("", fallback="-driver") == "driver"
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
    assert capability.exposure.namespace == "MCP"
    assert capability.exposure.tool_name == "MCP__-__bond_basic_info"
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
        "MCP__foo",
        "MCP__-foo",
        "MCP___foo",
        "MCP__123foo",
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
