# -*- coding: utf-8 -*-
"""Persisted plugin settings: enabled flag in ``config.plugins``."""

from __future__ import annotations

from typing import Any
from pathlib import Path
import json
import re

ENABLED_KEY = "enabled"


def _intent_path(plugin_id, plugins_dir=None):
    if (
        not isinstance(plugin_id, str)
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", plugin_id)
        or plugin_id in {".", ".."}
    ):
        raise ValueError("Invalid plugin identifier")
    if plugins_dir is None:
        from ..config.utils import get_plugins_dir

        plugins_dir = get_plugins_dir()
    return Path(plugins_dir) / ".plugin-intents" / (plugin_id + ".json")


def read_plugin_intent(plugin_id, *, plugins_dir=None):
    """Read explicit uninstall intent; corrupt evidence fails closed."""
    path = _intent_path(plugin_id, plugins_dir)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    if (
        value != {"schema": 1, "intent": "uninstalled"}
        or type(value.get("schema")) is not int
    ):
        raise ValueError("Invalid plugin intent")
    return value


def record_plugin_uninstall(plugin_id, *, plugins_dir=None):
    """Retain intent independently of the removable SDK 1.0 config row."""
    from ..utils.io_utils import write_json_atomic

    write_json_atomic(
        _intent_path(plugin_id, plugins_dir),
        {"schema": 1, "intent": "uninstalled"},
    )


def clear_plugin_intent(plugin_id, *, plugins_dir=None):
    """Explicit successful installation/enabling supersedes uninstall."""
    _intent_path(plugin_id, plugins_dir).unlink(missing_ok=True)


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

    mutate_config(_apply)


def persist_plugin_settings(
    plugin_id: str,
    *,
    enabled: bool | None = None,
    config: dict[str, Any] | None = None,
    config_path: Path | None = None,
    refuse_disabled: bool = False,
) -> None:
    """Write ``enabled`` and/or plugin config into ``config.plugins``."""
    from ..config.utils import mutate_config

    def _apply(root) -> None:
        row = dict(root.plugins.get(plugin_id) or {})
        if refuse_disabled and row.get(ENABLED_KEY) is False:
            raise ValueError("Plugin was explicitly disabled")
        if config is not None:
            kept = row.get(ENABLED_KEY, True) if enabled is None else enabled
            row = dict(runtime_config(config))
            row[ENABLED_KEY] = kept
        elif enabled is not None:
            row[ENABLED_KEY] = enabled
        root.plugins[plugin_id] = row

    if config_path is None:
        mutate_config(_apply)
    else:
        mutate_config(_apply, config_path)
