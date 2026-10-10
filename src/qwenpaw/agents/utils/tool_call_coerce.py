# -*- coding: utf-8 -*-
"""Schema-guided type coercion for tool-call inputs (issue #6839).

Models sometimes emit unquoted numbers or booleans for tool parameters
declared as ``type: string`` (e.g. ``"assetInfo": 1.000001``).  The
shared parse-and-validate path in agentscope's agent layer rejects such
values outright (``1.000001 is not of type 'string'``), so every such
tool call fails on every provider.

These pure helpers convert the values of declared ``string`` fields to
their JSON literal string form.  The walk follows the value and the
schema in lockstep (dict ↔ ``properties``, list ↔ ``items``), so nested
structures common in MCP schemas are covered too, and union shapes such
as ``type: ["string"]`` or ``anyOf: [{"type": "string"},
{"type": "null"}]`` (how ``Optional[str]`` arrives) are understood.

Fields declared with any other type are left untouched — a value that
already validates against its schema node is never coerced — so real
numeric arguments are never corrupted and already-correct inputs are
returned byte-identical.  Invalid JSON is passed through unchanged and
left to agentscope's existing json-repair path.
"""

from __future__ import annotations

import json
from typing import Any

__all__ = [
    "_coerce_string_fields",
    "_coerce_tool_input",
]


class _FloatLiteral(str):
    """Marker carrying the source text of a JSON float.

    ``json.loads(..., parse_float=_FloatLiteral)`` yields these instead
    of ``float`` values.  ``str(float)`` is not lossless — ``1.000000``
    normalizes to ``"1.0"``, ``1e2`` to ``"100.0"`` — so keeping the
    source literal is what makes coercing a float into a string field
    lossless.
    """


# pylint: disable-next=too-many-return-statements
def _json_types_of(value: Any) -> set[str]:
    """JSON Schema type names *value* satisfies (jsonschema semantics).

    Mirrors the type checks ``jsonschema`` performs: booleans are not
    numbers, integral floats do satisfy ``integer``, and a preserved
    ``_FloatLiteral`` is judged by the number it denotes.
    """
    if isinstance(value, bool):
        return {"boolean"}
    if isinstance(value, _FloatLiteral):
        types = {"number"}
        try:
            if float(value).is_integer():
                types.add("integer")
        except ValueError:
            pass
        return types
    if isinstance(value, int):
        return {"integer", "number"}
    if isinstance(value, float):
        types = {"number"}
        if value.is_integer():
            types.add("integer")
        return types
    if isinstance(value, str):
        return {"string"}
    if value is None:
        return {"null"}
    if isinstance(value, dict):
        return {"object"}
    if isinstance(value, list):
        return {"array"}
    return set()


# pylint: disable-next=too-many-return-statements
def _schema_accepts(value: Any, schema: Any) -> bool:
    """Whether *schema* accepts *value* as-is, for coercion gating.

    A lightweight approximation of ``jsonschema.validate`` covering the
    shapes tool schemas actually use (``type`` as string or list,
    ``anyOf`` / ``oneOf`` / ``allOf``).  It deliberately ignores value
    constraints (``minimum``, ``maxLength``, ...): the gate only needs
    to answer "is the value's *type* already valid here?", and erring
    towards "accepted" simply skips coercion, which is always safe.
    """
    if isinstance(schema, bool):
        return schema
    if not isinstance(schema, dict):
        return True
    declared = schema.get("type")
    if declared is not None:
        types = _json_types_of(value)
        if isinstance(declared, str):
            return declared in types
        if isinstance(declared, list):
            return any(
                item in types for item in declared if isinstance(item, str)
            )
    for combinator in ("anyOf", "oneOf"):
        branches = schema.get(combinator)
        if isinstance(branches, list) and branches:
            return any(_schema_accepts(value, s) for s in branches)
    all_of = schema.get("allOf")
    if isinstance(all_of, list) and all_of:
        return all(_schema_accepts(value, s) for s in all_of)
    return True


def _schema_permits_string(schema: Any) -> bool:
    """Whether *schema* can validate a string value at all."""
    if not isinstance(schema, dict):
        return False
    declared = schema.get("type")
    if declared == "string":
        return True
    if isinstance(declared, list) and "string" in declared:
        return True
    for combinator in ("anyOf", "oneOf"):
        branches = schema.get(combinator)
        if isinstance(branches, list) and branches:
            return any(_schema_permits_string(s) for s in branches)
    return False


# pylint: disable-next=too-many-return-statements
def _coerce_node(
    value: Any,
    schema: Any,
) -> tuple[Any, bool]:
    """Walk *value* and *schema* in lockstep, coercing where needed.

    Returns ``(new_value, coerced)`` where *coerced* is True iff at
    least one value was actually converted to a string.  Dictionaries
    and lists are mutated in place.  Every preserved ``_FloatLiteral``
    that is not coerced is converted back to a real ``float`` so the
    result can be re-serialized as numbers.
    """
    if isinstance(value, dict):
        props = schema.get("properties") if isinstance(schema, dict) else None
        if not isinstance(props, dict):
            props = {}
        coerced = False
        for key, sub_value in list(value.items()):
            new_sub, sub_coerced = _coerce_node(sub_value, props.get(key))
            value[key] = new_sub
            coerced = coerced or sub_coerced
        return value, coerced
    if isinstance(value, list):
        items = schema.get("items") if isinstance(schema, dict) else None
        if not isinstance(items, dict):
            items = None
        coerced = False
        for index, item in enumerate(value):
            new_item, item_coerced = _coerce_node(item, items)
            value[index] = new_item
            coerced = coerced or item_coerced
        return value, coerced

    # Leaves. bool is a subclass of int — handle it first and keep the
    # JSON literal form ("true" / "false") rather than Python's str().
    if isinstance(value, _FloatLiteral):
        if not _schema_accepts(value, schema) and _schema_permits_string(
            schema,
        ):
            return str(value), True
        return float(value), False
    if isinstance(value, bool):
        if not _schema_accepts(value, schema) and _schema_permits_string(
            schema,
        ):
            return "true" if value else "false", True
        return value, False
    if isinstance(value, (int, float)):
        if not _schema_accepts(value, schema) and _schema_permits_string(
            schema,
        ):
            return str(value), True
        return value, False
    # Genuine strings, None, and anything else are never touched.
    return value, False


def _coerce_string_fields(
    parsed: dict[str, Any],
    schema: dict[str, Any] | None,
) -> dict[str, Any]:
    """Coerce values of schema-declared ``string`` fields to strings.

    Walks the parsed value and the schema in lockstep (dict ↔
    ``properties``, list ↔ ``items``), so nested objects and arrays are
    covered as well.  Fields declared with any other type are left
    untouched, so real numeric arguments are never corrupted.
    """
    if not isinstance(parsed, dict) or not isinstance(schema, dict):
        return parsed
    coerced, _ = _coerce_node(parsed, schema)
    return coerced


def _coerce_tool_input(
    input_str: str,
    schema: dict[str, Any] | None,
) -> str:
    """Schema-guided type coercion for a raw tool-call input JSON string.

    Returns *input_str* unchanged (byte-identical) when it is not valid
    JSON — those are left to agentscope's existing json-repair path —
    when it does not parse to a dict, when *schema* is unavailable, or
    when no field needed coercion.  The coercion is therefore an
    idempotent no-op for already-correct tool calls.

    Floats are parsed with ``parse_float=_FloatLiteral`` so the source
    literal survives: coercing ``1.000000`` yields ``"1.000000"``, not
    the ``str(float)`` normalization ``"1.0"``.
    """
    if not input_str or not isinstance(schema, dict):
        return input_str
    try:
        parsed = json.loads(input_str, parse_float=_FloatLiteral)
    except (json.JSONDecodeError, TypeError, ValueError):
        return input_str
    if not isinstance(parsed, dict):
        return input_str
    _, coerced = _coerce_node(parsed, schema)
    if not coerced:
        return input_str
    return json.dumps(parsed, ensure_ascii=False)
