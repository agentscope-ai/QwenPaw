# -*- coding: utf-8 -*-
"""Shared helpers for normalizing provider SDK exceptions."""

from __future__ import annotations

from typing import Any


def _as_http_status(value: Any) -> int | None:
    """Return *value* as a valid HTTP status code, if possible."""
    if isinstance(value, bool):
        return None
    try:
        status = int(value)
    except (TypeError, ValueError):
        return None
    return status if 100 <= status <= 599 else None


def extract_status_code(exc: Exception) -> int | None:
    """Best-effort HTTP status extraction across supported provider SDKs."""
    for value in (
        getattr(exc, "status_code", None),
        getattr(exc, "code", None),
    ):
        status = _as_http_status(value)
        if status is not None:
            return status

    response = getattr(exc, "response", None)
    for value in (
        getattr(response, "status_code", None),
        getattr(response, "status", None),
    ):
        status = _as_http_status(value)
        if status is not None:
            return status

    for payload in (
        getattr(exc, "body", None),
        getattr(exc, "details", None),
    ):
        if not isinstance(payload, dict):
            continue
        for container in (payload, payload.get("error")):
            if not isinstance(container, dict):
                continue
            for key in ("status_code", "code"):
                status = _as_http_status(container.get(key))
                if status is not None:
                    return status

    return None
