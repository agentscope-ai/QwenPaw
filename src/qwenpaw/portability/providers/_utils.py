# -*- coding: utf-8 -*-
"""Small normalization helpers shared by Migration Providers."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable


def parse_datetime(value: Any) -> datetime | None:
    """Parse common provider timestamp representations, best effort."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value).astimezone()
        except (OSError, OverflowError, ValueError):
            return None
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def find_nested_value(
    value: Any,
    keys: tuple[str, ...],
    normalize: Callable[[Any], str],
) -> str:
    """Return the first normalized keyed value in a nested JSON tree."""
    if isinstance(value, dict):
        for key in keys:
            if result := normalize(value.get(key)):
                return result
        children = value.values()
    elif isinstance(value, list):
        children = value
    else:
        return ""
    for child in children:
        if result := find_nested_value(child, keys, normalize):
            return result
    return ""


__all__ = ["find_nested_value", "parse_datetime"]
