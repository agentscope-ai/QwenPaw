# -*- coding: utf-8 -*-
"""QwenPaw-native tool documentation compression.

QwenPaw's built-in tools are ordinary Python functions. AgentScope derives
their input schemas from signatures, type hints, defaults, and docstrings.
The production policy below follows that contract instead of trying to be a
general-purpose JSON Schema rewriter.
"""

from __future__ import annotations

import json
from typing import Any


def _move_optional_parameter_descriptions(
    parameters: dict[str, Any],
) -> list[str]:
    """Remove direct optional descriptions and return their image text."""
    properties = parameters.get("properties")
    if not isinstance(properties, dict):
        return []
    required_value = parameters.get("required", [])
    if not isinstance(required_value, list) or not all(
        isinstance(name, str) for name in required_value
    ):
        return []
    required = set(required_value)
    lines: list[str] = []
    for name, schema in properties.items():
        if name in required or not isinstance(schema, dict):
            continue
        description = schema.get("description")
        if not isinstance(description, str) or not description.strip():
            continue
        encoded = json.dumps(
            description,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        lines.append(f"{name}: {encoded}")
        del schema["description"]
    return lines


def plan_qwenpaw_tool_documentation(
    tools: list[dict],
) -> tuple[list[dict], str]:
    """Image optional-parameter prose while preserving the native contract.

    Tool identity, top-level documentation, required-parameter documentation,
    types, defaults, and all structural schema fields remain native. Complex
    schemas are eligible, but this baseline only touches descriptions on
    direct optional properties; nested and unknown content remains unchanged.
    """
    copied = json.loads(json.dumps(tools, ensure_ascii=False))
    sections: list[str] = []
    for tool in copied:
        if not isinstance(tool, dict) or tool.get("type") != "function":
            continue
        function = tool.get("function")
        if not isinstance(function, dict):
            continue
        if (
            tool.get("defer_loading") is True
            or function.get("defer_loading") is True
        ):
            continue
        parameters = function.get("parameters")
        if (
            not isinstance(parameters, dict)
            or parameters.get("type") != "object"
            or not isinstance(parameters.get("properties"), dict)
        ):
            continue
        documentation = _move_optional_parameter_descriptions(parameters)
        if documentation:
            sections.append(
                "\n".join(
                    [
                        "## Optional parameters: "
                        + str(function.get("name", "unknown")),
                        *documentation,
                    ],
                ),
            )

    rendered = "\n\n".join(sections)
    if rendered:
        rendered = (
            "=== TOOL REFERENCE ===\n"
            "QwenPaw moved optional-parameter descriptions here to reduce "
            "token cost. Native tool definitions still carry every tool's "
            "identity, required-parameter guidance, types, defaults, and "
            "structural contract. Read this reference before supplying an "
            "optional argument.\n\n"
            + rendered
            + "\n=== END TOOL REFERENCE ==="
        )
    return copied, rendered


__all__ = ["plan_qwenpaw_tool_documentation"]
