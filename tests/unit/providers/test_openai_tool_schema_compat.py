# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
from typing import Any

import pytest
from agentscope.tool import Toolkit

from qwenpaw.agents.tools.file_io import read_file
from qwenpaw.agents.tools.shell import execute_shell_command
from qwenpaw.governance import PolicyGuardedTool
from qwenpaw.providers.openai_chat_model_compat import (
    _expand_regex_shorthands,
    _sanitize_tool_schemas,
)


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


def test_sanitize_tool_schemas_removes_nullable_inline_schema_branches() -> (
    None
):
    tools = [
        {
            "type": "function",
            "function": {
                "name": "demo",
                "description": "demo",
                "parameters": {
                    "type": "object",
                    "required": ["path"],
                    "properties": {
                        "path": {
                            "anyOf": [
                                {"type": "string", "format": "path"},
                                {"type": "null"},
                            ],
                            "default": None,
                        },
                        "config": {
                            "anyOf": [
                                {},
                                {"type": "null"},
                            ],
                            "default": None,
                            "description": "optional config",
                        },
                        "nested": {
                            "type": "object",
                            "properties": {
                                "limit": {
                                    "oneOf": [
                                        {"type": "integer"},
                                        {"type": "null"},
                                    ],
                                    "default": None,
                                },
                            },
                        },
                    },
                },
            },
        },
    ]

    sanitized = _sanitize_tool_schemas(tools)
    parameters = sanitized[0]["function"]["parameters"]

    assert not _type_null_paths(sanitized)
    assert parameters == {
        "type": "object",
        "required": ["path"],
        "properties": {
            "path": {
                "type": "string",
                "format": "path",
                "default": None,
            },
            "config": {
                "default": None,
                "description": "optional config",
                "type": "object",
            },
            "nested": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "default": None,
                    },
                },
            },
        },
    }


def test_sanitize_tool_schemas_removes_nullable_builtin_tool_branches() -> (
    None
):
    tools = [
        PolicyGuardedTool(
            read_file,
            governor=None,
            request_context={},
        ),
        PolicyGuardedTool(
            execute_shell_command,
            governor=None,
            request_context={},
        ),
    ]
    schemas = asyncio.run(Toolkit(tools=tools).get_tool_schemas())

    sanitized = _sanitize_tool_schemas(schemas)

    assert not _type_null_paths(sanitized)

    read_file_params = _schema_by_name(sanitized, "read_file")
    assert read_file_params["required"] == ["file_path"]
    start_line = read_file_params["properties"]["start_line"]
    assert start_line == {
        "type": "integer",
        "description": "First line to read (1-based, inclusive).",
        "default": None,
    }

    shell_params = _schema_by_name(sanitized, "execute_shell_command")
    assert shell_params["required"] == ["command"]
    cwd = shell_params["properties"]["cwd"]
    assert cwd == {
        "type": "string",
        "format": "path",
        "description": (
            "The working directory for the command execution.\n"
            "If None, defaults to the agent workspace."
        ),
        "default": None,
    }

    sandbox_config = shell_params["properties"]["sandbox_config"]
    assert sandbox_config == {
        "default": None,
        "description": (
            "Sandbox execution configuration compiled from "
            "governance policy.\n"
            "When provided, the command executes within a sandboxed "
            "environment\n"
            "with the specified mount permissions and network restrictions."
        ),
        "type": "object",
    }


def test_sanitize_tool_schemas_removes_null_from_type_arrays() -> None:
    tools = [
        {
            "type": "function",
            "function": {
                "name": "demo",
                "description": "demo",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "single": {
                            "type": ["string", "null"],
                            "default": None,
                        },
                        "multiple": {
                            "type": ["integer", "number", "null"],
                        },
                        "null_only": {
                            "type": ["null"],
                            "default": None,
                        },
                    },
                },
            },
        },
    ]

    sanitized = _sanitize_tool_schemas(tools)
    properties = sanitized[0]["function"]["parameters"]["properties"]

    assert properties == {
        "single": {"type": "string", "default": None},
        "multiple": {"type": ["integer", "number"]},
        "null_only": {"type": "object", "default": None},
    }


# -- Pattern shorthand expansion (#6201) --


@pytest.mark.parametrize(
    ("input_pat", "expected"),
    [
        (r"^\d+$", r"^[0-9]+$"),
        (r"\D+", r"[^0-9]+"),
        (r"\w+", "[a-zA-Z0-9_]+"),
        (r"\W", "[^a-zA-Z0-9_]"),
        (r"\s+", r"[\t\n\r\f\v ]+"),
        (r"\S", r"[^\t\n\r\f\v ]"),
        (r"^\d{4}-\d{2}-\d{2}$", r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$"),
        (r"^[A-Z]{2,3}$", r"^[A-Z]{2,3}$"),
        (r"(PMC)?\d+", r"(PMC)?[0-9]+"),
    ],
    ids=[
        "d",
        "D",
        "w",
        "W",
        "s",
        "S",
        "multi",
        "no-op",
        "pubmed-pmc",
    ],
)
def test_expand_regex_shorthands(
    input_pat: str,
    expected: str,
) -> None:
    assert _expand_regex_shorthands(input_pat) == expected


def test_sanitize_tool_schemas_expands_pattern_shorthands() -> None:
    """End-to-end: patterns in tool schemas are expanded (#6201)."""
    tools = [
        {
            "type": "function",
            "function": {
                "name": "demo",
                "description": "demo",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pmid": {
                            "type": "string",
                            "pattern": r"^\d+$",
                        },
                        "ids": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "pattern": r"\d+",
                            },
                        },
                        "name": {"type": "string"},
                    },
                },
            },
        },
    ]

    sanitized = _sanitize_tool_schemas(tools)
    props = sanitized[0]["function"]["parameters"]["properties"]

    assert props["pmid"]["pattern"] == r"^[0-9]+$"
    assert props["ids"]["items"]["pattern"] == "[0-9]+"
    assert "pattern" not in props["name"]
