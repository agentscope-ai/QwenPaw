# -*- coding: utf-8 -*-
from __future__ import annotations

from qwenpaw.backup._ops.restore_helpers import (
    LOCAL_PROTECTED_CONFIG_KEYS,
    overlay_local_keys,
    resolve_preserve_flag,
)
from qwenpaw.backup.models import BackupMeta, RestoreBackupRequest


def test_preserve_keys_are_limited_to_backup_trust_boundary():
    assert LOCAL_PROTECTED_CONFIG_KEYS == ("security", "mcp")


def test_overlay_local_keys_keeps_only_local_preserved_trees():
    backup_cfg = {
        "security": {"tool_guard": {"enabled": False}},
        "mcp": {"servers": {"evil": {}}},
        "providers": {"backup": True},
    }
    current_cfg = {"security": {"tool_guard": {"enabled": True}}}

    merged = overlay_local_keys(backup_cfg, current_cfg)

    assert merged["security"] == current_cfg["security"]
    assert "mcp" not in merged
    assert merged["providers"] == backup_cfg["providers"]


def test_resolve_preserve_flag_defaults_from_backup_trust_state():
    req = RestoreBackupRequest()

    assert resolve_preserve_flag(
        req,
        BackupMeta(name="Foreign", accepted_via_trust=True),
    )
    assert not resolve_preserve_flag(
        req,
        BackupMeta(name="Local", accepted_via_trust=False),
    )
    assert not resolve_preserve_flag(
        RestoreBackupRequest(preserve_local_protected_config=False),
        BackupMeta(name="Foreign", accepted_via_trust=True),
    )
    assert resolve_preserve_flag(
        RestoreBackupRequest(preserve_local_protected_config=True),
        BackupMeta(name="Local", accepted_via_trust=False),
    )
