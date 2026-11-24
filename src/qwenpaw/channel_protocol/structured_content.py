# -*- coding: utf-8 -*-
"""Closed outbound display content, distinct from the legacy semantic wire."""

from .models import _closed, _error, _object, _string, _validate_event_part


def validate_structured_parts(values):
    """Tool results contain ordered display blocks, never recursive tool calls."""
    remaining = 4096

    def validate(value, *, nested=False):
        nonlocal remaining
        remaining -= 1
        if remaining < 0:
            raise _error("Too many structured content blocks")
        data = dict(_object(value))
        kind = data.get("type")
        if kind not in {"tool_call", "tool_result"}:
            return _validate_event_part(data)
        if nested:
            raise _error("Nested tool content is not a display block")
        field = "arguments" if kind == "tool_call" else "output"
        _closed(data, {"type", "id", "name", "state", field})
        if "state" in data:
            _string(data["state"], "state", non_empty=False)
        _string(data.get("id"), "id", non_empty=False)
        _string(data.get("name"), "name")
        value = data.get(field)
        if kind == "tool_result" and isinstance(value, list):
            data[field] = [validate(item, nested=True) for item in value]
        else:
            _string(value, field, non_empty=False)
        return data

    if not isinstance(values, (list, tuple)):
        raise _error("Structured content must be a list")
    return tuple(validate(value) for value in values)
