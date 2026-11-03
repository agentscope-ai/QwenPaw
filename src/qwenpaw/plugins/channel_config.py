# -*- coding: utf-8 -*-
"""Static channel configuration: host controls plus plugin JSON Schema."""

from copy import deepcopy
from collections.abc import Mapping
from types import SimpleNamespace

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from ..config.config import BaseChannelConfig
from ..config.channel_normalizers import (
    field_normalizer,
    normalize_channel_fields,
)


def channel_config_dict(value):
    """Detach config data without importing Drivers."""
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    elif isinstance(value, SimpleNamespace):
        value = vars(value)
    if isinstance(value, Mapping):
        return {key: channel_config_dict(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [channel_config_dict(item) for item in value]
    return deepcopy(value)


def validate_channel_config_schema(schema: Mapping) -> dict:
    """Check static Schema and local references without config values."""
    normalized_schema = channel_config_dict(schema)

    def check_refs(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in {"$ref", "$dynamicRef"} and (
                    not isinstance(value, str) or not value.startswith("#")
                ):
                    raise ValueError("Channel schema references must be local")
                check_refs(value)
        elif isinstance(node, list):
            for value in node:
                check_refs(value)

    check_refs(normalized_schema)
    try:
        Draft202012Validator.check_schema(normalized_schema)
    except SchemaError as exc:
        raise ValueError(f"Invalid channel schema: {exc.message}") from exc
    for field in normalized_schema.get("properties", {}).values():
        field_normalizer(field)
    return normalized_schema


def _fill_defaults(schema, values):
    """Apply explicit defaults, recursively, to an already detached value."""
    if not isinstance(schema, dict):
        return values
    if isinstance(values, dict):
        for key, field in schema.get("properties", {}).items():
            if not isinstance(field, dict):
                continue
            if key not in values and "default" in field:
                values[key] = deepcopy(field["default"])
            if key in values:
                _fill_defaults(field, values[key])
    elif isinstance(values, list) and isinstance(schema.get("items"), dict):
        for value in values:
            _fill_defaults(schema["items"], value)
    return values


def channel_config_defaults(schema: Mapping) -> dict:
    """Return independent public defaults and declared plugin defaults."""
    schema = validate_channel_config_schema(schema)
    return _fill_defaults(schema, BaseChannelConfig().model_dump(mode="json"))


def validate_channel_config(schema: Mapping, values: Mapping) -> dict:
    """Normalize public fields; validate plugin values without coercion."""
    schema = validate_channel_config_schema(schema)
    normalized_values = channel_config_dict(values)
    if not isinstance(normalized_values, dict):
        raise ValueError("Channel configuration must be an object")
    normalized_values = _fill_defaults(schema, normalized_values)
    public = BaseChannelConfig.model_validate(normalized_values).model_dump(
        mode="json",
    )
    normalized_values.update(public)
    # Even a closed plugin schema accepts host-owned common fields. The host
    # model above is authoritative when a plugin tries to relax their types.
    properties = schema.setdefault("properties", {})
    for key, field in BaseChannelConfig.model_json_schema()[
        "properties"
    ].items():
        properties.setdefault(key, field)
    errors = list(Draft202012Validator(schema).iter_errors(normalized_values))
    if errors:
        error = errors[0]
        path = ".".join(map(str, error.absolute_path)) or "config"
        raise ValueError(f"{path}: {error.message}")
    return normalize_channel_fields(schema, normalized_values)
