# -*- coding: utf-8 -*-
"""Persisted plugin settings: enabled flag in ``config.plugins``."""

from __future__ import annotations

from typing import Any

ENABLED_KEY = "enabled"


def runtime_config(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Return the plugin-facing config, without framework keys."""
    if not raw:
        return {}
    return {key: value for key, value in raw.items() if key != ENABLED_KEY}


def is_plugin_enabled(raw: dict[str, Any] | None) -> bool:
    """Default to enabled when the flag is absent."""
    if not raw:
        return True
    return bool(raw.get(ENABLED_KEY, True))


def persist_plugin_settings(
    plugin_id: str,
    *,
    enabled: bool | None = None,
    config: dict[str, Any] | None = None,
) -> None:
    """Write ``enabled`` and/or plugin config into ``config.plugins``."""
    from ..config.utils import mutate_config

    def _apply(root) -> None:
        row = dict(root.plugins.get(plugin_id) or {})
        if config is not None:
            kept = row.get(ENABLED_KEY, True) if enabled is None else enabled
            row = dict(runtime_config(config))
            row[ENABLED_KEY] = kept
        elif enabled is not None:
            row[ENABLED_KEY] = enabled
        root.plugins[plugin_id] = row

    mutate_config(_apply)
