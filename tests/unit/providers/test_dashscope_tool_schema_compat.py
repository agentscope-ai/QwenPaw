# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""DashScope must sanitize tool schemas before they leave the client.

Strict models served through DashScope (e.g. kimi-k3) reject nullable
``anyOf`` / empty JSON Schema branches that AgentScope generates from
``Optional[...]`` annotations.  The native DashScope path applies only
that nullable pass; OpenAI uses the broader ``_sanitize_tool_schemas``
pipeline, and Gemini has its own normalizer.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

from agentscope.tool import Toolkit

from qwenpaw.agents.tools.file_io import read_file
from qwenpaw.agents.tools.file_search import grep_search
from qwenpaw.agents.tools.shell import execute_shell_command
from qwenpaw.governance import PolicyGuardedTool
from qwenpaw.providers.dashscope_provider import DashScopeProvider


def _type_null_paths(node: Any, path: tuple[str, ...] = ()) -> list[str]:
    paths: list[str] = []
    if isinstance(node, dict):
        node_type = node.get("type")
        if node_type == "null" or (
            isinstance(node_type, list) and "null" in node_type
        ):
            paths.append(".".join(path + ("type",)))
        for key, value in node.items():
            paths.extend(_type_null_paths(value, path + (str(key),)))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            paths.extend(_type_null_paths(value, path + (str(index),)))
    return paths


def _schema_by_name(
    schemas: list[dict[str, Any]],
    name: str,
) -> dict[str, Any]:
    for schema in schemas:
        function = schema.get("function", {})
        if function.get("name") == name:
            return function["parameters"]
    raise AssertionError(f"missing tool schema: {name}")


def _make_dashscope_model():
    provider = DashScopeProvider(
        id="dashscope",
        name="DashScope",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key="sk-test",
    )
    return provider.get_chat_model_instance("kimi-k3")


def test_format_tools_strips_nullable_union_branches() -> None:
    tools = [
        {
            "type": "function",
            "function": {
                "name": "execute_shell_command",
                "description": "Run a command",
                "parameters": {
                    "type": "object",
                    "required": ["command"],
                    "properties": {
                        "command": {"type": "string"},
                        "cwd": {
                            "anyOf": [
                                {"type": "string", "format": "path"},
                                {"type": "null"},
                            ],
                            "default": None,
                        },
                        "sandbox_config": {
                            "anyOf": [
                                {},
                                {"type": "null"},
                            ],
                            "default": None,
                        },
                    },
                },
            },
        },
    ]

    formatted, tool_choice = _make_dashscope_model()._format_tools(
        tools,
        None,
    )

    assert tool_choice is None
    assert formatted is not None
    assert not _type_null_paths(formatted)

    properties = formatted[0]["function"]["parameters"]["properties"]
    assert properties["cwd"] == {
        "type": "string",
        "format": "path",
        "default": None,
    }
    assert properties["sandbox_config"] == {
        "type": "object",
        "default": None,
    }
    assert "anyOf" not in properties["cwd"]
    assert "anyOf" not in properties["sandbox_config"]
    # Source schemas stay intact so AgentScope's local validator still
    # accepts omitted / null optional arguments.
    source_function = tools[0]["function"]
    assert isinstance(source_function, dict)
    source_cwd = source_function["parameters"]["properties"]["cwd"]
    assert isinstance(source_cwd, dict)
    assert "anyOf" in source_cwd


def test_format_tools_sanitizes_builtin_tool_schemas() -> None:
    raw_schemas = asyncio.run(
        Toolkit(
            tools=[
                PolicyGuardedTool(
                    execute_shell_command,
                    governor=None,
                    request_context={},
                ),
                PolicyGuardedTool(
                    read_file,
                    governor=None,
                    request_context={},
                ),
                PolicyGuardedTool(
                    grep_search,
                    governor=None,
                    request_context={},
                ),
            ],
        ).get_tool_schemas(),
    )

    formatted, _ = _make_dashscope_model()._format_tools(raw_schemas, None)

    assert formatted is not None
    assert not _type_null_paths(formatted)

    cwd = _schema_by_name(formatted, "execute_shell_command")["properties"][
        "cwd"
    ]
    assert cwd["type"] == "string"
    assert "anyOf" not in cwd

    sandbox = _schema_by_name(formatted, "execute_shell_command")[
        "properties"
    ]["sandbox_config"]
    assert sandbox["type"] == "object"
    assert "anyOf" not in sandbox

    path = _schema_by_name(formatted, "grep_search")["properties"]["path"]
    assert path["type"] == "string"
    assert "anyOf" not in path


def test_format_tools_passes_through_missing_tools() -> None:
    formatted, tool_choice = _make_dashscope_model()._format_tools(
        None,
        None,
    )
    assert formatted is None
    assert tool_choice is None


def _shared_ref_parameters(depth: int) -> dict[str, Any]:
    """Build a linearly sized schema whose shared refs form a binary tree.

    Inlining every ``$ref`` would duplicate both children at each level
    and grow exponentially with *depth*.  DashScope must keep the shared
    references instead.
    """
    defs: dict[str, Any] = {"N0": {"type": "string"}}
    for index in range(1, depth + 1):
        previous = f"N{index - 1}"
        defs[f"N{index}"] = {
            "type": "object",
            "properties": {
                "left": {"$ref": f"#/$defs/{previous}"},
                "right": {"$ref": f"#/$defs/{previous}"},
            },
        }
    return {
        "type": "object",
        "properties": {"root": {"$ref": f"#/$defs/N{depth}"}},
        "$defs": defs,
    }


def test_format_tools_keeps_shared_refs_bounded() -> None:
    depth = 16
    parameters = _shared_ref_parameters(depth)
    tools = [
        {
            "type": "function",
            "function": {
                "name": "demo",
                "description": "Shared-ref schema",
                "parameters": parameters,
            },
        },
    ]

    formatted, _ = _make_dashscope_model()._format_tools(tools, None)

    assert formatted is not None
    formatted_params = formatted[0]["function"]["parameters"]
    assert formatted_params["properties"]["root"] == {
        "$ref": f"#/$defs/N{depth}",
    }
    assert set(formatted_params["$defs"]) == set(parameters["$defs"])
    assert len(json.dumps(formatted_params, sort_keys=True)) <= 2 * len(
        json.dumps(parameters, sort_keys=True),
    )
