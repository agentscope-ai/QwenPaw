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


def drop_plugin_settings(plugin_id: str) -> None:
    """Remove ``config.plugins.<id>`` after a successful uninstall."""
    from ..config.utils import mutate_config

    def _apply(root) -> None:
        root.plugins.pop(plugin_id, None)
        from .official_channel_catalog import official_channel_for_plugin

        if official_channel_for_plugin(plugin_id) is not None:
            state = root.channel_plugin_state
            if plugin_id not in state.uninstalled:
                state.uninstalled.append(plugin_id)
            state.legacy_pending = [
                key for key in state.legacy_pending if key != plugin_id
            ]

    mutate_config(_apply)


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


def clear_channel_tombstone(plugin_id: str) -> None:
    """Explicit source commit clears that plugin's uninstall intent."""
    from .official_channel_catalog import official_channel_for_plugin
    from ..config.utils import mutate_config

    if official_channel_for_plugin(plugin_id) is not None:

        def apply(root):
            root.channel_plugin_state.uninstalled = [
                key
                for key in root.channel_plugin_state.uninstalled
                if key != plugin_id
            ]

        mutate_config(apply)
