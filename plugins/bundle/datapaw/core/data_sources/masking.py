# -*- coding: utf-8 -*-
"""Mask / restore sensitive data-source config values."""
from __future__ import annotations

from typing import Dict

SENSITIVE_CONFIG_KEYS = frozenset({"password", "access_key"})


def mask_value(value: str) -> str:
    """Mask a secret showing prefix/suffix (same rules as MCP env masking)."""
    if not value:
        return value

    length = len(value)
    if length <= 8:
        return "*" * length

    prefix_len = 3 if length > 2 and value[2] == "-" else 2
    prefix = value[:prefix_len]
    suffix = value[-4:]
    masked_len = max(length - prefix_len - 4, 4)
    return f"{prefix}{'*' * masked_len}{suffix}"


def mask_config(config: Dict[str, object]) -> Dict[str, object]:
    """Return a copy of *config* with sensitive string values masked."""
    masked: Dict[str, object] = {}
    for key, value in config.items():
        if key in SENSITIVE_CONFIG_KEYS and isinstance(value, str):
            masked[key] = mask_value(value)
        else:
            masked[key] = value
    return masked


def restore_config_values(
    incoming: Dict[str, object],
    existing: Dict[str, object],
) -> Dict[str, object]:
    """Preserve original secrets when incoming matches masked form."""
    restored: Dict[str, object] = {}
    for key, value in incoming.items():
        if (
            key in SENSITIVE_CONFIG_KEYS
            and key in existing
            and isinstance(value, str)
            and isinstance(existing[key], str)
            and value == mask_value(existing[key])
        ):
            restored[key] = existing[key]
        else:
            restored[key] = value
    return restored
