# -*- coding: utf-8 -*-
"""Unit tests for the schema-position-aware boolean sanitizer.

Regression coverage for issue #4646: MCP tool JSON Schemas with
boolean-valued annotation keywords (``nullable``, ``deprecated``, etc.)
were being corrupted into invalid object schemas, causing strict
OpenAI-compatible providers to reject the tool definition.
"""

from __future__ import annotations

from qwenpaw.providers.openai_chat_model_compat import (
    _sanitize_boolean_schemas,
    _sanitize_tool_schemas,
)


# ---------------------------------------------------------------------------
# Bug regression: boolean-valued annotation keywords must be preserved.
# ---------------------------------------------------------------------------


def test_nullable_true_preserved() -> None:
    schema = {"type": "string", "nullable": True}
    assert _sanitize_boolean_schemas(schema) == {
        "type": "string",
        "nullable": True,
    }


def test_nullable_false_preserved() -> None:
    schema = {"type": "string", "nullable": False}
    assert _sanitize_boolean_schemas(schema) == {
        "type": "string",
        "nullable": False,
    }


def test_all_common_boolean_annotations_preserved() -> None:
    schema = {
        "type": "string",
        "nullable": True,
        "deprecated": False,
        "readOnly": True,
        "writeOnly": False,
        "uniqueItems": True,
    }
    assert _sanitize_boolean_schemas(schema) == schema


def test_nested_annotation_preserved() -> None:
    schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "nullable": True},
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "uniqueItems": True,
            },
        },
    }
    expected = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "nullable": True},
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "uniqueItems": True,
            },
        },
    }
    assert _sanitize_boolean_schemas(schema) == expected


# ---------------------------------------------------------------------------
# Boolean schemas in actual schema-positions must still be converted.
# ---------------------------------------------------------------------------


def test_root_true_becomes_empty() -> None:
    assert _sanitize_boolean_schemas(True) == {}


def test_root_false_becomes_not_empty() -> None:
    assert _sanitize_boolean_schemas(False) == {"not": {}}


def test_items_true_converted() -> None:
    assert _sanitize_boolean_schemas({"type": "array", "items": True}) == {
        "type": "array",
        "items": {},
    }


def test_items_false_converted() -> None:
    assert _sanitize_boolean_schemas({"type": "array", "items": False}) == {
        "type": "array",
        "items": {"not": {}},
    }


def test_items_tuple_form_converted() -> None:
    schema = {"type": "array", "items": [True, {"type": "string"}, False]}
    assert _sanitize_boolean_schemas(schema) == {
        "type": "array",
        "items": [{}, {"type": "string"}, {"not": {}}],
    }


def test_properties_bool_schema_converted() -> None:
    schema = {
        "type": "object",
        "properties": {"anything": True, "nothing": False},
    }
    assert _sanitize_boolean_schemas(schema) == {
        "type": "object",
        "properties": {"anything": {}, "nothing": {"not": {}}},
    }


def test_allof_bool_schemas_converted() -> None:
    schema = {"allOf": [True, {"type": "string"}, False]}
    assert _sanitize_boolean_schemas(schema) == {
        "allOf": [{}, {"type": "string"}, {"not": {}}],
    }


def test_anyof_oneof_bool_schemas_converted() -> None:
    schema = {"anyOf": [True], "oneOf": [{"type": "integer"}, False]}
    assert _sanitize_boolean_schemas(schema) == {
        "anyOf": [{}],
        "oneOf": [{"type": "integer"}, {"not": {}}],
    }


def test_not_true_converted() -> None:
    assert _sanitize_boolean_schemas({"not": True}) == {"not": {}}


def test_if_then_else_converted() -> None:
    schema = {"if": True, "then": False, "else": {"type": "string"}}
    assert _sanitize_boolean_schemas(schema) == {
        "if": {},
        "then": {"not": {}},
        "else": {"type": "string"},
    }


def test_patternproperties_converted() -> None:
    schema = {"patternProperties": {"^x": True, "^y": {"type": "string"}}}
    assert _sanitize_boolean_schemas(schema) == {
        "patternProperties": {"^x": {}, "^y": {"type": "string"}},
    }


def test_defs_converted() -> None:
    schema = {"$defs": {"any": True}, "definitions": {"never": False}}
    assert _sanitize_boolean_schemas(schema) == {
        "$defs": {"any": {}},
        "definitions": {"never": {"not": {}}},
    }


def test_prefixitems_converted() -> None:
    schema = {"prefixItems": [True, {"type": "string"}]}
    assert _sanitize_boolean_schemas(schema) == {
        "prefixItems": [{}, {"type": "string"}],
    }


# ---------------------------------------------------------------------------
# Existing special-case behavior preserved.
# ---------------------------------------------------------------------------


def test_additional_properties_true_stripped() -> None:
    assert _sanitize_boolean_schemas(
        {"type": "object", "additionalProperties": True},
    ) == {"type": "object"}


def test_additional_properties_false_becomes_not_empty() -> None:
    assert _sanitize_boolean_schemas(
        {"type": "object", "additionalProperties": False},
    ) == {"type": "object", "additionalProperties": {"not": {}}}


def test_additional_properties_object_recursed() -> None:
    schema = {
        "type": "object",
        "additionalProperties": {"type": "string", "nullable": True},
    }
    assert _sanitize_boolean_schemas(schema) == {
        "type": "object",
        "additionalProperties": {"type": "string", "nullable": True},
    }


def test_required_bool_stripped() -> None:
    schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "required": True},
            "body": {"type": "string", "required": False},
        },
    }
    assert _sanitize_boolean_schemas(schema) == {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "body": {"type": "string"},
        },
    }


def test_required_array_preserved() -> None:
    schema = {
        "type": "object",
        "properties": {"a": {"type": "string"}},
        "required": ["a", "b"],
    }
    assert _sanitize_boolean_schemas(schema) == schema


# ---------------------------------------------------------------------------
# draft-07 dependencies special-case.
# ---------------------------------------------------------------------------


def test_dependencies_string_array_preserved() -> None:
    schema = {"dependencies": {"credit_card": ["billing_address"]}}
    assert _sanitize_boolean_schemas(schema) == schema


def test_dependencies_schema_recursed() -> None:
    schema = {
        "dependencies": {
            "credit_card": {"type": "object", "nullable": True},
            "wildcard": True,
        },
    }
    assert _sanitize_boolean_schemas(schema) == {
        "dependencies": {
            "credit_card": {"type": "object", "nullable": True},
            "wildcard": {},
        },
    }


# ---------------------------------------------------------------------------
# Non-schema keys with dict/bool values must pass through unchanged.
# This is the key behavioural change vs the old recursive sanitizer.
# ---------------------------------------------------------------------------


def test_vendor_extension_dict_passes_through_unchanged() -> None:
    schema = {
        "type": "string",
        "x-vendor": {"nullable": True, "flag": False},
    }
    assert _sanitize_boolean_schemas(schema) == schema


def test_non_schema_key_with_bool_value_preserved() -> None:
    # Unknown bool-valued key (e.g. some custom annotation): must remain bool.
    schema = {"type": "string", "x-internal": True}
    assert _sanitize_boolean_schemas(schema) == {
        "type": "string",
        "x-internal": True,
    }


def test_default_bool_literal_preserved() -> None:
    # `default` holds a literal value, not a sub-schema.
    schema = {"type": "boolean", "default": True}
    assert _sanitize_boolean_schemas(schema) == {
        "type": "boolean",
        "default": True,
    }


def test_const_bool_literal_preserved() -> None:
    schema = {"const": False}
    assert _sanitize_boolean_schemas(schema) == {"const": False}


def test_enum_with_bool_literals_preserved() -> None:
    schema = {"enum": [True, False, "maybe"]}
    assert _sanitize_boolean_schemas(schema) == {
        "enum": [True, False, "maybe"],
    }


def test_examples_with_bool_literals_preserved() -> None:
    schema = {"type": "boolean", "examples": [True, False]}
    assert _sanitize_boolean_schemas(schema) == {
        "type": "boolean",
        "examples": [True, False],
    }


# ---------------------------------------------------------------------------
# End-to-end: full tool dict matching the issue #4646 repro pattern.
# ---------------------------------------------------------------------------


def test_sanitize_tool_schemas_preserves_nullable_in_property() -> None:
    tools = [
        {
            "type": "function",
            "function": {
                "name": "create_draft",
                "description": "Create an email draft",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "nullable": True},
                        "body": {
                            "type": "string",
                            "nullable": False,
                            "deprecated": True,
                        },
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "uniqueItems": True,
                        },
                        "anything": True,
                    },
                    "required": ["title"],
                    "additionalProperties": True,
                },
            },
        },
    ]
    sanitized = _sanitize_tool_schemas(tools)
    params = sanitized[0]["function"]["parameters"]
    props = params["properties"]

    assert props["title"]["nullable"] is True
    assert props["body"]["nullable"] is False
    assert props["body"]["deprecated"] is True
    assert props["tags"]["uniqueItems"] is True
    # Boolean schema in `properties` position is still converted:
    assert props["anything"] == {}
    # `additionalProperties: true` is still stripped:
    assert "additionalProperties" not in params
    # `required` array is untouched:
    assert params["required"] == ["title"]


def test_sanitize_tool_schemas_passthrough_non_dict() -> None:
    # Non-dict tool entries are returned as-is.
    tools = ["not a dict", {"function": "not a dict"}, {"no_function": True}]
    assert _sanitize_tool_schemas(tools) == tools  # type: ignore[arg-type]
