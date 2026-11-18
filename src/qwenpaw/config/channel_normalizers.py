# -*- coding: utf-8 -*-
"""Fixed, SDK-free configuration normalizers shared by models and schemas.

The marker selects a host-defined pure function, never plugin Python code.
Normalizers run after validation, matching Pydantic's field-validator mode.
"""

from collections.abc import Mapping
from types import MappingProxyType

NORMALIZER_MARKER = "x-qwenpaw-normalizer"


def strip_trailing_slash(value: str) -> str:
    """Preserve the historical normalization, including non-URL strings."""
    return value.rstrip("/")


_NORMALIZERS = MappingProxyType({"strip_trailing_slash": strip_trailing_slash})


def field_normalizer(schema):
    """Resolve an explicit string-field declaration or reject unknown claims."""
    if not isinstance(schema, Mapping) or NORMALIZER_MARKER not in schema:
        return None
    name = schema[NORMALIZER_MARKER]
    if not isinstance(name, str) or name not in _NORMALIZERS:
        raise ValueError("Unknown channel field normalizer")
    if schema.get("type") != "string":
        raise ValueError("Channel field normalizer requires a string schema")
    return _NORMALIZERS[name]


def normalize_channel_fields(schema, values):
    """Normalize detached, already schema-validated top-level field values."""
    result = dict(values)
    for name, field in schema.get("properties", {}).items():
        normalizer = field_normalizer(field)
        if normalizer is not None and name in result:
            result[name] = normalizer(result[name])
    return result
