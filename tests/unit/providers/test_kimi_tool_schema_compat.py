# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Moonshot rejects tool schemas whose ``enum`` node carries no ``type``.

Moonshot's flavored JSON Schema validator (MFJS) only accepts ``enum`` on a
node that also declares ``type``.  MCP servers emit parameters such as
``{"anyOf": [{"type": "string"}, {"type": "integer"}], "enum": [...]}`` to
tolerate LLM mis-serialization, and ``walle -level strict`` rejects them with
``type is not defined`` -- the 400 reported in #7959.  Kimi providers reach
that pipeline through ``OpenAIChatModelCompat._format_tools``.
"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest
from agentscope.tool import Toolkit

from qwenpaw.agents.tools.file_io import read_file
from qwenpaw.governance import PolicyGuardedTool
from qwenpaw.providers.services.kimi import KimiProvider


def _enum_nodes_missing_type(
    node: Any,
    path: tuple[str, ...] = (),
) -> list[str]:
    """Paths of nodes that carry ``enum`` without the ``type`` MFJS wants."""
    missing: list[str] = []
    if isinstance(node, dict):
        if "enum" in node and "type" not in node:
            missing.append(".".join(path) or "<root>")
        for key, value in node.items():
            missing.extend(
                _enum_nodes_missing_type(value, path + (str(key),)),
            )
    elif isinstance(node, list):
        for index, value in enumerate(node):
            missing.extend(
                _enum_nodes_missing_type(value, path + (str(index),)),
            )
    return missing


def _schema_by_name(
    schemas: list[dict[str, Any]],
    name: str,
) -> dict[str, Any]:
    for schema in schemas:
        function = schema.get("function", {})
        if function.get("name") == name:
            return function["parameters"]
    raise AssertionError(f"missing tool schema: {name}")


def _make_kimi_model():
    provider = KimiProvider(
        id="kimi-cn",
        name="Kimi (China)",
        base_url="https://api.moonshot.cn/v1",
        api_key="sk-test",
    )
    return provider.get_chat_model_instance("kimi-k3")


def _tushare_minutes_tool() -> dict[str, Any]:
    """The MCP tool from #7959: ``freq`` is ``string | integer`` + enum."""
    return {
        "type": "function",
        "function": {
            "name": "hk_mins",
            "description": "港股分钟行情",
            "parameters": {
                "type": "object",
                "required": ["ts_code"],
                "properties": {
                    "ts_code": {"type": "string"},
                    "freq": {
                        "anyOf": [{"type": "string"}, {"type": "integer"}],
                        "description": "分钟频度",
                        "enum": ["1min", "5min", "15min", "30min", "60min"],
                    },
                },
            },
        },
    }


def test_format_tools_types_enum_without_type() -> None:
    tools = [_tushare_minutes_tool()]

    formatted, tool_choice = _make_kimi_model()._format_tools(tools, None)

    assert tool_choice is None
    assert formatted is not None
    assert not _enum_nodes_missing_type(formatted)

    parameters = _schema_by_name(formatted, "hk_mins")
    assert parameters["properties"]["freq"] == {
        "anyOf": [{"type": "string"}, {"type": "integer"}],
        "description": "分钟频度",
        "enum": ["1min", "5min", "15min", "30min", "60min"],
        "type": "string",
    }
    # Source schemas stay intact so AgentScope's local validator still
    # accepts the values the tool was written to tolerate.
    source_freq = tools[0]["function"]["parameters"]["properties"]["freq"]
    assert "type" not in source_freq


def test_format_tools_leaves_typed_enum_untouched() -> None:
    tools = [
        {
            "type": "function",
            "function": {
                "name": "demo",
                "description": "demo",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "unit": {
                            "type": "string",
                            "enum": ["min", "hour"],
                        },
                    },
                },
            },
        },
    ]

    formatted, _ = _make_kimi_model()._format_tools(tools, None)

    assert formatted is not None
    assert _schema_by_name(formatted, "demo")["properties"]["unit"] == {
        "type": "string",
        "enum": ["min", "hour"],
    }


def test_format_tools_keeps_untyped_union_without_enum() -> None:
    """A union with no ``enum`` is valid MFJS and must not be narrowed."""
    tools = [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "demo",
                "parameters": {
                    "type": "object",
                    "required": ["file_path"],
                    "properties": {
                        "file_path": {"type": "string"},
                        "start_line": {
                            "anyOf": [
                                {"type": "integer"},
                                {"type": "string"},
                            ],
                            "description": "First line to read.",
                            "default": None,
                        },
                    },
                },
            },
        },
    ]

    formatted, _ = _make_kimi_model()._format_tools(tools, None)

    assert formatted is not None
    assert _schema_by_name(formatted, "read_file")["properties"][
        "start_line"
    ] == {
        "anyOf": [{"type": "integer"}, {"type": "string"}],
        "description": "First line to read.",
        "default": None,
    }


def test_format_tools_still_collapses_nullable_unions() -> None:
    tools = [
        {
            "type": "function",
            "function": {
                "name": "demo",
                "description": "demo",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "cwd": {
                            "anyOf": [
                                {"type": "string", "format": "path"},
                                {"type": "null"},
                            ],
                            "default": None,
                        },
                    },
                },
            },
        },
    ]

    formatted, _ = _make_kimi_model()._format_tools(tools, None)

    assert formatted is not None
    assert _schema_by_name(formatted, "demo")["properties"]["cwd"] == {
        "type": "string",
        "format": "path",
        "default": None,
    }


@pytest.mark.parametrize(
    ("values", "expected_type"),
    [
        (["a", "b"], "string"),
        ([1, 2], "integer"),
        ([1, 2.5], "number"),
        ([True, False], "boolean"),
        ([None], "null"),
        (["a", None], ["string", "null"]),
    ],
    ids=["string", "integer", "number", "boolean", "null", "nullable"],
)
def test_format_tools_derives_enum_type(
    values: list[Any],
    expected_type: Any,
) -> None:
    tools = [
        {
            "type": "function",
            "function": {
                "name": "demo",
                "description": "demo",
                "parameters": {
                    "type": "object",
                    "properties": {"value": {"enum": values}},
                },
            },
        },
    ]

    formatted, _ = _make_kimi_model()._format_tools(tools, None)

    assert formatted is not None
    assert _schema_by_name(formatted, "demo")["properties"]["value"] == {
        "enum": values,
        "type": expected_type,
    }


def test_format_tools_leaves_untypeable_enum_alone() -> None:
    """MFJS cannot express a mixed-type enum, so it is left for the server."""
    tools = [
        {
            "type": "function",
            "function": {
                "name": "demo",
                "description": "demo",
                "parameters": {
                    "type": "object",
                    "properties": {"value": {"enum": ["a", 1]}},
                },
            },
        },
    ]

    formatted, _ = _make_kimi_model()._format_tools(tools, None)

    assert formatted is not None
    assert _schema_by_name(formatted, "demo")["properties"]["value"] == {
        "enum": ["a", 1],
    }


def test_format_tools_types_enum_inside_array_items() -> None:
    tools = [
        {
            "type": "function",
            "function": {
                "name": "demo",
                "description": "demo",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "freqs": {
                            "type": "array",
                            "items": {
                                "anyOf": [
                                    {"type": "string"},
                                    {"type": "integer"},
                                ],
                                "enum": ["1min", "5min"],
                            },
                        },
                    },
                },
            },
        },
    ]

    formatted, _ = _make_kimi_model()._format_tools(tools, None)

    assert formatted is not None
    assert _schema_by_name(formatted, "demo")["properties"]["freqs"][
        "items"
    ] == {
        "anyOf": [{"type": "string"}, {"type": "integer"}],
        "enum": ["1min", "5min"],
        "type": "string",
    }


def test_format_tools_satisfies_enum_rule_for_builtin_tools() -> None:
    schemas = asyncio.run(
        Toolkit(
            tools=[
                PolicyGuardedTool(
                    read_file,
                    governor=None,
                    request_context={},
                ),
            ],
        ).get_tool_schemas(),
    )

    formatted, _ = _make_kimi_model()._format_tools(schemas, None)

    assert formatted is not None
    assert not _enum_nodes_missing_type(formatted)
