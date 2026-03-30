# -*- coding: utf-8 -*-
"""Helpers for structured runtime i18n payloads."""
from __future__ import annotations

import json
from typing import Any


RUNTIME_I18N_PREFIX = "__copaw_i18n__:"


def encode_runtime_i18n_text(
    key: str,
    values: dict[str, Any] | None = None,
) -> str:
    """Encode a runtime message as an i18n payload string."""
    payload: dict[str, Any] = {"key": key}
    if values:
        payload["values"] = values
    return RUNTIME_I18N_PREFIX + json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def build_i18n_metadata(
    key: str,
    values: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Attach stable i18n metadata to structured backend payloads."""
    metadata: dict[str, Any] = {"i18n_key": key}
    if values:
        metadata["i18n_values"] = values
    return metadata
