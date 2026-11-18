# -*- coding: utf-8 -*-
"""One-time upgrades for persisted Hub registration and model settings."""

from __future__ import annotations

import json
import sqlite3
from copy import deepcopy

_MODES = {"open", "invite", "closed"}


def legacy_registration_mode(enabled) -> str:
    """Translate the registration flag from the published Hub config."""
    if enabled is not None and not isinstance(enabled, bool):
        raise ValueError("Legacy Hub registration flag must be boolean")
    return "open" if enabled else "closed"


def upgrade_registration(
    config: dict,
) -> tuple[dict, bool]:
    """Normalize the deprecated YAML field without rewriting the file."""
    plane = config.get("control_plane")
    registration = (
        plane.get("registration") if isinstance(plane, dict) else None
    )
    if not isinstance(registration, dict) or "enabled" not in registration:
        return config, False
    upgraded = deepcopy(config)
    registration = upgraded["control_plane"]["registration"]
    enabled = registration.pop("enabled")
    if "mode" not in registration and enabled is not None:
        registration["mode"] = legacy_registration_mode(
            enabled,
        )
    return upgraded, True


def migrate_hub_settings(db: sqlite3.Connection, now: str) -> bool:
    """Upgrade settings inside the caller's initialization transaction."""
    rows = {
        row["key"]: row
        for row in db.execute(
            "SELECT key, value_json "
            "FROM hub_settings WHERE key IN "
            "('hub_config', 'registration_enabled', 'registration_mode')",
        )
    }
    config_row = rows.get("hub_config")
    config = json.loads(config_row["value_json"]) if config_row else {}
    if not isinstance(config, dict):
        raise ValueError("Persisted Hub config must be an object")
    plane = config.get("control_plane")
    registration = plane.get("registration") if isinstance(plane, dict) else {}
    if not isinstance(registration, dict):
        registration = {}
    old_registration = "enabled" in registration
    if not old_registration and "registration_enabled" not in rows:
        return False

    mode_row = rows.get("registration_mode")
    stored_mode = json.loads(mode_row["value_json"]) if mode_row else None
    if mode_row is not None:
        mode = stored_mode
    elif "mode" in registration:
        mode = registration["mode"]
    else:
        old_row = rows.get("registration_enabled")
        enabled = (
            json.loads(old_row["value_json"])
            if old_row
            else registration.get("enabled")
        )
        mode = legacy_registration_mode(
            enabled,
        )
    if not isinstance(mode, str) or mode not in _MODES:
        raise ValueError("Invalid Hub registration mode during migration")

    if old_registration:
        registration.pop("enabled")
        registration["mode"] = mode
        db.execute(
            "UPDATE hub_settings SET value_json = ?, "
            "revision = revision + 1, updated_at = ? WHERE key = 'hub_config'",
            (json.dumps(config), now),
        )
    if mode_row is None or stored_mode != mode:
        db.execute(
            "INSERT INTO hub_settings(key, value_json, updated_at) "
            "VALUES ('registration_mode', ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET "
            "value_json = excluded.value_json, "
            "revision = hub_settings.revision + 1, "
            "updated_at = excluded.updated_at",
            (json.dumps(mode), now),
        )
    db.execute("DELETE FROM hub_settings WHERE key = 'registration_enabled'")
    return True
