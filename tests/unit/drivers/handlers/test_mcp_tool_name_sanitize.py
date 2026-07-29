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
            "MCP__get_consensus_forecast",
        ),
        ("-A__get_esg_data", "A__get_esg_data"),
        ("-__bond_basic_info", "bond_basic_info"),
        ("get_esg_data", "get_esg_data"),
        ("pat.batch_plan", "pat_batch_plan"),
        ("123", "tool_123"),
        ("", "tool"),
    ],
)
def test_sanitize_tool_name(name: str, expected: str) -> None:
    sanitized = _sanitize_tool_name(name)
    assert sanitized == expected
    assert re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", sanitized)


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
    assert capability.exposure.tool_name == "MCP__bond_basic_info"
    assert re.fullmatch(
        r"[A-Za-z][A-Za-z0-9_-]*",
        capability.exposure.tool_name,
    )
