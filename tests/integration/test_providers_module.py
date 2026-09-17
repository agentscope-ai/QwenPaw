# -*- coding: utf-8 -*-
"""Integration tests for Providers module internals.

Covers src/qwenpaw/providers/openai_chat_model_compat.py (80
uncovered) — stream/chunk sanitization helpers.
"""

from __future__ import annotations

import pytest


class _Block(dict):
    """Minimal dict-like block for the compat helpers."""


# ------------------------------------------------------------------ #
# block helpers
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_battr_default() -> None:
    """_battr returns the default when key missing."""
    from qwenpaw.providers.openai_chat_model_compat import _battr

    assert _battr(_Block(), "missing", "dflt") == "dflt"


@pytest.mark.integration
@pytest.mark.p1
def test_bset_roundtrip() -> None:
    """_bset writes a key readable by _battr."""
    from qwenpaw.providers.openai_chat_model_compat import (
        _battr,
        _bset,
    )

    block = _Block()
    _bset(block, "k", "v")
    assert _battr(block, "k") == "v"


# ------------------------------------------------------------------ #
# schema sanitization
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_strip_boolean_schema_special_cases() -> None:
    """_strip_boolean_schema_special_cases passes non-dict through."""
    from qwenpaw.providers.openai_chat_model_compat import (
        _strip_boolean_schema_special_cases,
    )

    assert _strip_boolean_schema_special_cases("x") == "x"
    assert _strip_boolean_schema_special_cases(1) == 1


@pytest.mark.integration
@pytest.mark.p1
def test_sanitize_boolean_schemas_dict() -> None:
    """_sanitize_boolean_schemas walks a dict schema."""
    from qwenpaw.providers.openai_chat_model_compat import (
        _sanitize_boolean_schemas,
    )

    schema = {"type": "object", "properties": {}}
    result = _sanitize_boolean_schemas(schema)
    assert isinstance(result, dict)


@pytest.mark.integration
@pytest.mark.p1
def test_walk_schema_list() -> None:
    """_walk_schema handles list schemas."""
    from qwenpaw.providers.openai_chat_model_compat import _walk_schema

    result = _walk_schema(
        {"items": [{"type": "boolean"}]},
        lambda s: s,
    )
    assert isinstance(result, dict)
    assert isinstance(result["items"], list)


# ------------------------------------------------------------------ #
# tool call sanitization
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_sanitize_tool_call_none() -> None:
    """_sanitize_tool_call returns None for a non-tool-call block."""
    from qwenpaw.providers.openai_chat_model_compat import (
        _sanitize_tool_call,
    )

    assert _sanitize_tool_call(_Block()) is None
