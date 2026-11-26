# -*- coding: utf-8 -*-
"""Validated, non-persistent configuration for one execution scope."""

from collections.abc import Mapping
from copy import deepcopy
import json
from typing import Any

from pydantic import BaseModel


def merge_overrides(
    base: Mapping[str, Any],
    overrides: Mapping[str, Any],
) -> dict[str, Any]:
    """Merge objects recursively; replace arrays and scalar values."""
    result = deepcopy(dict(base))
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge_overrides(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def _check_fields(value: Any, parsed: Any, path: str = "config") -> None:
    """Reject ignored model fields while retaining open plugin mappings."""
    if isinstance(value, dict) and isinstance(parsed, BaseModel):
        fields = type(parsed).model_fields
        names = {field.alias or name: name for name, field in fields.items()}
        names.update({name: name for name in fields})
        for key, item in value.items():
            name = names.get(key)
            if name is None:
                if parsed.model_config.get("extra") != "allow":
                    raise ValueError(
                        f"Unknown configuration field: {path}.{key}",
                    )
            else:
                _check_fields(item, getattr(parsed, name), f"{path}.{key}")
    elif isinstance(value, dict) and isinstance(parsed, dict):
        for key, item in value.items():
            if key in parsed:
                _check_fields(item, parsed[key], f"{path}.{key}")
    elif isinstance(value, list) and isinstance(parsed, list):
        for index, (item, result) in enumerate(zip(value, parsed)):
            _check_fields(item, result, f"{path}[{index}]")


def parse_config_overrides(values: tuple[str, ...]) -> dict[str, Any]:
    """Parse repeated dotted-path assignments with JSON or string values."""
    overrides: dict[str, Any] = {}
    for assignment in values:
        path, separator, raw = assignment.partition("=")
        if not separator or not all(path.split(".")):
            raise ValueError(f"Expected CONFIG.PATH=VALUE: {assignment!r}")
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            value = raw
        patch = value
        for key in reversed(path.split(".")):
            patch = {key: patch}
        overrides = merge_overrides(overrides, patch)
    return overrides
