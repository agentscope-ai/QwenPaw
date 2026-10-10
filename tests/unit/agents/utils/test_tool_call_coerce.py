# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Tests for schema-guided tool-call input coercion (issue #6839).

Pure-function layer (provider-agnostic).  The agent-layer funnel that
applies it is covered by
``tests/unit/agents/test_react_agent_tool_coercion.py``.

Models sometimes emit unquoted numbers or booleans for string-typed
tool parameters (e.g. ``"assetInfo": 1.000001`` where the schema
declares ``type: string``).  ``jsonschema.validate`` rejects those
values, so the tool call always fails.  The coercion converts declared
``string`` fields back to strings before agentscope validates the
input.
"""
from __future__ import annotations

import json

from qwenpaw.agents.utils.tool_call_coerce import (
    _coerce_string_fields,
    _coerce_tool_input,
)

STOCK_SCHEMA = {
    "type": "object",
    "required": ["apiKey", "assetInfo"],
    "properties": {
        "apiKey": {"type": "string"},
        "assetInfo": {"type": "string"},
        "count": {"type": "integer", "default": 240},
    },
}


# ---------------------------------------------------------------------------
# Pure coercion helpers (ported from the former provider-level tests)
# ---------------------------------------------------------------------------


def test_coerce_tool_input_number_to_string() -> None:
    """The exact issue #6839 case: unquoted float for a string field."""
    raw = '{"apiKey": "k", "assetInfo": 1.000001, "count": 240}'
    out = _coerce_tool_input(raw, STOCK_SCHEMA)
    parsed = json.loads(out)
    assert parsed == {"apiKey": "k", "assetInfo": "1.000001", "count": 240}
    # The integer-typed field keeps its numeric type.
    assert isinstance(parsed["count"], int)
    assert isinstance(parsed["assetInfo"], str)


def test_coerce_tool_input_integer_field_untouched() -> None:
    """Numbers landing in integer/number fields are never coerced."""
    raw = '{"apiKey": "k", "assetInfo": "1.000001", "count": 240}'
    out = _coerce_tool_input(raw, STOCK_SCHEMA)
    assert out == raw  # byte-identical no-op


def test_coerce_tool_input_bool_to_json_literal() -> None:
    schema = {
        "type": "object",
        "properties": {"flag": {"type": "string"}},
    }
    assert json.loads(_coerce_tool_input('{"flag": true}', schema)) == {
        "flag": "true",
    }
    assert json.loads(_coerce_tool_input('{"flag": false}', schema)) == {
        "flag": "false",
    }


def test_coerce_tool_input_invalid_json_passthrough() -> None:
    """Broken JSON is left to agentscope's existing json-repair path."""
    broken = '{"apiKey": "k", "assetInfo": 1.000001, "count": 240'
    assert _coerce_tool_input(broken, STOCK_SCHEMA) == broken


def test_coerce_tool_input_no_schema_passthrough() -> None:
    raw = '{"assetInfo": 1.000001}'
    assert _coerce_tool_input(raw, None) == raw


def test_coerce_tool_input_non_dict_passthrough() -> None:
    raw = "[1, 2, 3]"
    assert _coerce_tool_input(raw, STOCK_SCHEMA) == raw


def test_coerce_string_fields_unknown_property_untouched() -> None:
    """Fields absent from schema properties are never touched."""
    parsed = {"mystery": 42, "assetInfo": 1.5}
    out = _coerce_string_fields(dict(parsed), STOCK_SCHEMA)
    assert out["mystery"] == 42
    assert out["assetInfo"] == "1.5"


# ---------------------------------------------------------------------------
# Nested structures: walk value and schema in lockstep
# ---------------------------------------------------------------------------


def test_nested_object_string_field_coerced() -> None:
    """{"config": {"assetInfo": 1.0}} — dict inside dict (MCP-common)."""
    schema = {
        "type": "object",
        "properties": {
            "config": {
                "type": "object",
                "properties": {"assetInfo": {"type": "string"}},
            },
        },
    }
    raw = '{"config": {"assetInfo": 1.0}}'
    assert json.loads(_coerce_tool_input(raw, schema)) == {
        "config": {"assetInfo": "1.0"},
    }


def test_nested_list_items_coerced() -> None:
    """{"tags": [1, 2]} with items: {type: string} — list of scalars."""
    schema = {
        "type": "object",
        "properties": {
            "tags": {"type": "array", "items": {"type": "string"}},
        },
    }
    raw = '{"tags": [1, 2]}'
    assert json.loads(_coerce_tool_input(raw, schema)) == {
        "tags": ["1", "2"],
    }


def test_nested_list_of_objects_coerced() -> None:
    """Array of objects: dict nested under a list."""
    schema = {
        "type": "object",
        "properties": {
            "rows": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"id": {"type": "string"}},
                },
            },
        },
    }
    raw = '{"rows": [{"id": 1}, {"id": "ok"}]}'
    assert json.loads(_coerce_tool_input(raw, schema)) == {
        "rows": [{"id": "1"}, {"id": "ok"}],
    }


def test_nested_numeric_fields_untouched() -> None:
    """Lockstep walk must not corrupt nested numeric fields."""
    schema = {
        "type": "object",
        "properties": {
            "config": {
                "type": "object",
                "properties": {
                    "assetInfo": {"type": "string"},
                    "count": {"type": "integer"},
                },
            },
            "ratios": {"type": "array", "items": {"type": "number"}},
        },
    }
    raw = '{"config": {"assetInfo": 2.5, "count": 3}, "ratios": [0.5, 2]}'
    parsed = json.loads(_coerce_tool_input(raw, schema))
    assert parsed == {
        "config": {"assetInfo": "2.5", "count": 3},
        "ratios": [0.5, 2],
    }
    assert isinstance(parsed["config"]["count"], int)
    assert isinstance(parsed["ratios"][0], float)


# ---------------------------------------------------------------------------
# Union shapes: type lists and anyOf (Optional[str])
# ---------------------------------------------------------------------------


def test_type_list_declaring_string_coerces() -> None:
    schema = {
        "type": "object",
        "properties": {"v": {"type": ["string"]}},
    }
    assert json.loads(_coerce_tool_input('{"v": 5}', schema)) == {"v": "5"}


def test_type_list_accepting_number_left_alone() -> None:
    """type: ["string", "number"] already validates a number."""
    schema = {
        "type": "object",
        "properties": {"v": {"type": ["string", "number"]}},
    }
    raw = '{"v": 5}'
    assert _coerce_tool_input(raw, schema) == raw


def test_anyof_string_null_optional_field() -> None:
    """anyOf [string, null] is how Optional[str] arrives."""
    schema = {
        "type": "object",
        "properties": {
            "v": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        },
    }
    assert json.loads(_coerce_tool_input('{"v": 5}', schema)) == {"v": "5"}
    # null already validates — untouched, byte-identical.
    assert _coerce_tool_input('{"v": null}', schema) == '{"v": null}'


def test_anyof_string_number_leaves_valid_number() -> None:
    schema = {
        "type": "object",
        "properties": {
            "v": {"anyOf": [{"type": "string"}, {"type": "number"}]},
        },
    }
    raw = '{"v": 5}'
    assert _coerce_tool_input(raw, schema) == raw


# ---------------------------------------------------------------------------
# Lossless float literals
# ---------------------------------------------------------------------------


def test_float_literal_lossless() -> None:
    """str(float) normalizes 1.000000 -> "1.0"; coercion must not."""
    schema = {
        "type": "object",
        "properties": {"v": {"type": "string"}},
    }
    raw = '{"v": 1.000000}'
    assert json.loads(_coerce_tool_input(raw, schema)) == {"v": "1.000000"}
    raw = '{"v": 1e2}'
    assert json.loads(_coerce_tool_input(raw, schema)) == {"v": "1e2"}


def test_float_literal_in_number_field_byte_identical() -> None:
    """Nothing coerced -> input returned byte-identical."""
    schema = {
        "type": "object",
        "properties": {"count": {"type": "number"}},
    }
    raw = '{"count": 1.000000}'
    assert _coerce_tool_input(raw, schema) == raw


def test_float_literal_preserved_when_sibling_coerced() -> None:
    """When a re-dump happens, untouched floats stay real numbers."""
    schema = {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "count": {"type": "number"},
        },
    }
    out = _coerce_tool_input('{"id": 7, "count": 240.5}', schema)
    parsed = json.loads(out)
    assert parsed == {"id": "7", "count": 240.5}
    assert isinstance(parsed["count"], float)
    assert isinstance(parsed["id"], str)
