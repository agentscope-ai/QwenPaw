# -*- coding: utf-8 -*-
"""Tests for config access-control migration and custom loop mode
sanitization.

Covers _migrate_access_control_fields (dm_policy/group_policy rewrite,
allow_from/group_allow_from whitelist import with failure tolerance)
and _sanitize_custom_loop_modes (invalid/non-list/over-limit pruning),
which previously had no coverage.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from qwenpaw.config import config as cfg_mod


# ---------------------------------------------------------------------------
# _migrate_access_control_fields
# ---------------------------------------------------------------------------


class TestMigrateAccessControlFields:
    def test_dm_policy_allowlist_migrated(self, tmp_path):
        channels = {"dingtalk": {"dm_policy": "allowlist"}}
        migrated = cfg_mod._migrate_access_control_fields(
            channels,
            tmp_path,
        )
        assert migrated is True
        assert channels["dingtalk"]["access_control_dm"] is True
        assert "dm_policy" not in channels["dingtalk"]

    def test_dm_policy_disabled_migrated(self, tmp_path):
        channels = {"dingtalk": {"dm_policy": "disabled"}}
        migrated = cfg_mod._migrate_access_control_fields(channels, tmp_path)
        assert migrated is True
        assert channels["dingtalk"]["dm_disabled"] is True

    def test_group_policy_allowlist_migrated(self, tmp_path):
        channels = {"feishu": {"group_policy": "allowlist"}}
        migrated = cfg_mod._migrate_access_control_fields(channels, tmp_path)
        assert migrated is True
        assert channels["feishu"]["access_control_group"] is True
        assert "group_policy" not in channels["feishu"]

    def test_group_policy_disabled_migrated(self, tmp_path):
        channels = {"feishu": {"group_policy": "disabled"}}
        migrated = cfg_mod._migrate_access_control_fields(channels, tmp_path)
        assert migrated is True
        assert channels["feishu"]["group_disabled"] is True

    def test_no_legacy_fields_no_migration(self, tmp_path):
        channels = {"console": {"enabled": True}}
        migrated = cfg_mod._migrate_access_control_fields(channels, tmp_path)
        assert migrated is False

    def test_non_dict_channel_skipped(self, tmp_path):
        channels = {"weird": "not-a-dict"}
        migrated = cfg_mod._migrate_access_control_fields(channels, tmp_path)
        assert migrated is False

    def test_existing_new_field_not_overwritten(self, tmp_path):
        channels = {
            "dingtalk": {
                "dm_policy": "allowlist",
                "access_control_dm": False,
            },
        }
        migrated = cfg_mod._migrate_access_control_fields(channels, tmp_path)
        assert migrated is True
        # existing value preserved (not overwritten)
        assert channels["dingtalk"]["access_control_dm"] is False
        assert "dm_policy" not in channels["dingtalk"]

    def test_allow_from_imported_and_removed(self, tmp_path, monkeypatch):
        store = MagicMock()
        monkeypatch.setattr(
            "qwenpaw.app.channels.access_control.get_access_control_store",
            lambda workspace_dir: store,
        )
        channels = {"dingtalk": {"allow_from": ["u1", "u2"]}}
        migrated = cfg_mod._migrate_access_control_fields(channels, tmp_path)
        assert migrated is True
        store.import_allow_from.assert_called_once_with(
            "dingtalk",
            {"u1", "u2"},
        )
        assert "allow_from" not in channels["dingtalk"]

    def test_allow_from_empty_list_removed_without_store(self, tmp_path):
        channels = {"dingtalk": {"allow_from": []}}
        migrated = cfg_mod._migrate_access_control_fields(channels, tmp_path)
        assert migrated is True
        assert "allow_from" not in channels["dingtalk"]

    def test_allow_from_import_failure_keeps_field(self, tmp_path, monkeypatch):
        def boom(workspace_dir):
            raise RuntimeError("store down")

        monkeypatch.setattr(
            "qwenpaw.app.channels.access_control.get_access_control_store",
            boom,
        )
        channels = {"dingtalk": {"allow_from": ["u1"]}}
        migrated = cfg_mod._migrate_access_control_fields(channels, tmp_path)
        assert migrated is False
        # field kept so migration can retry later
        assert channels["dingtalk"]["allow_from"] == ["u1"]

    def test_group_allow_from_imported(self, tmp_path, monkeypatch):
        store = MagicMock()
        monkeypatch.setattr(
            "qwenpaw.app.channels.access_control.get_access_control_store",
            lambda workspace_dir: store,
        )
        channels = {"matrix": {"group_allow_from": ["g1"]}}
        migrated = cfg_mod._migrate_access_control_fields(channels, tmp_path)
        assert migrated is True
        store.import_allow_from.assert_called_once_with("matrix", {"g1"})
        assert "group_allow_from" not in channels["matrix"]

    def test_allow_from_non_list_ignored(self, tmp_path):
        channels = {"dingtalk": {"allow_from": "not-a-list"}}
        migrated = cfg_mod._migrate_access_control_fields(channels, tmp_path)
        assert migrated is False
        assert channels["dingtalk"]["allow_from"] == "not-a-list"


# ---------------------------------------------------------------------------
# _sanitize_custom_loop_modes
# ---------------------------------------------------------------------------


class TestSanitizeCustomLoopModes:
    def test_no_running_section_noop(self):
        data = {}
        cfg_mod._sanitize_custom_loop_modes(data, "a1")
        assert data == {}

    def test_running_not_dict_noop(self):
        data = {"running": "bad"}
        cfg_mod._sanitize_custom_loop_modes(data, "a1")
        assert data["running"] == "bad"

    def test_loop_not_dict_noop(self):
        data = {"running": {"loop": "bad"}}
        cfg_mod._sanitize_custom_loop_modes(data, "a1")
        assert data["running"]["loop"] == "bad"

    def test_no_custom_modes_noop(self):
        data = {"running": {"loop": {}}}
        cfg_mod._sanitize_custom_loop_modes(data, "a1")
        assert data["running"]["loop"] == {}

    def test_non_list_custom_modes_reset(self):
        data = {"running": {"loop": {"custom_modes": "bad"}}}
        cfg_mod._sanitize_custom_loop_modes(data, "a1")
        assert data["running"]["loop"]["custom_modes"] == []

    def test_invalid_mode_skipped(self, monkeypatch):
        catalog = MagicMock()
        catalog.validate_params.side_effect = ValueError("bad gate")
        monkeypatch.setattr(
            "qwenpaw.loop.catalog.get_gate_catalog",
            lambda: catalog,
        )
        mode = {
            "id": "broken",
            "name": "broken",
            "slash_command": "broken",
            "gates": [{"type": "nope", "params": {}}],
        }
        data = {"running": {"loop": {"custom_modes": [mode]}}}
        cfg_mod._sanitize_custom_loop_modes(data, "a1")
        assert data["running"]["loop"]["custom_modes"] == []

    def test_valid_mode_kept(self, monkeypatch):
        catalog = MagicMock()
        monkeypatch.setattr(
            "qwenpaw.loop.catalog.get_gate_catalog",
            lambda: catalog,
        )
        mode = {
            "id": "standup",
            "name": "standup",
            "slash_command": "standup",
            "gates": [],
        }
        data = {"running": {"loop": {"custom_modes": [mode]}}}
        cfg_mod._sanitize_custom_loop_modes(data, "a1")
        assert len(data["running"]["loop"]["custom_modes"]) == 1

    def test_over_limit_modes_truncated(self, monkeypatch):
        catalog = MagicMock()
        monkeypatch.setattr(
            "qwenpaw.loop.catalog.get_gate_catalog",
            lambda: catalog,
        )
        modes = [
            {
                "id": f"mode{i}",
                "name": f"mode{i}",
                "slash_command": f"mode{i}",
                "gates": [],
            }
            for i in range(25)
        ]
        data = {"running": {"loop": {"custom_modes": modes}}}
        cfg_mod._sanitize_custom_loop_modes(data, "a1")
        assert len(data["running"]["loop"]["custom_modes"]) == 20

    def test_duplicate_command_skipped(self, monkeypatch):
        catalog = MagicMock()
        monkeypatch.setattr(
            "qwenpaw.loop.catalog.get_gate_catalog",
            lambda: catalog,
        )
        modes = [
            {
                "id": "a",
                "name": "a",
                "slash_command": "same",
                "gates": [],
            },
            {
                "id": "b",
                "name": "b",
                "slash_command": "same",
                "gates": [],
            },
        ]
        data = {"running": {"loop": {"custom_modes": modes}}}
        cfg_mod._sanitize_custom_loop_modes(data, "a1")
        # duplicate slash_command rejected
        assert len(data["running"]["loop"]["custom_modes"]) == 1
