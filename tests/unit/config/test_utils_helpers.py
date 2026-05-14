# -*- coding: utf-8 -*-
# pylint: disable=protected-access
from __future__ import annotations

from pathlib import Path

from qwenpaw.config import utils as config_utils


def test_normalize_working_dir_bound_paths_rewrites_legacy_roots(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(config_utils, "WORKING_DIR", tmp_path)
    legacy_abs = str(Path("~/.copaw").expanduser().resolve())
    data = {
        "workspace_dir": "~/.copaw/workspaces/default",
        "nested": {
            "media_dir": f"{legacy_abs}/media",
            "other": "~/.copaw/keep",
        },
        "items": [{"workspace_dir": "~/.copaw/workspaces/child"}],
    }

    normalized = config_utils._normalize_working_dir_bound_paths(data)

    assert normalized == {
        "workspace_dir": f"{tmp_path}/workspaces/default",
        "nested": {
            "media_dir": f"{tmp_path}/media",
            "other": "~/.copaw/keep",
        },
        "items": [{"workspace_dir": f"{tmp_path}/workspaces/child"}],
    }


def test_remove_nested_key_handles_dicts_and_lists() -> None:
    data = {"agents": [{"id": "a", "bad": True}], "keep": 1}

    assert config_utils._remove_nested_key(data, ["agents", 0, "bad"]) is True
    assert data == {"agents": [{"id": "a"}], "keep": 1}
    assert config_utils._remove_nested_key(data, ["agents", 9, "bad"]) is False
    assert config_utils._remove_nested_key(data, ["missing"]) is False


def test_remove_bad_field_falls_back_to_ancestor_key() -> None:
    data = {"outer": {"inner": {"bad": True}}, "keep": 1}

    assert config_utils._remove_bad_field(data, ["outer", "missing", "bad"])
    assert data == {"keep": 1}


def test_remove_bad_field_removes_exact_leaf_first() -> None:
    data = {"outer": {"inner": {"bad": True, "keep": True}}}

    assert config_utils._remove_bad_field(data, ["outer", "inner", "bad"])
    assert data == {"outer": {"inner": {"keep": True}}}


def test_linux_desktop_to_kind_and_path_maps_known_browsers() -> None:
    assert config_utils._linux_desktop_to_kind_and_path(
        "/usr/bin/google-chrome",
    ) == ("chromium", "/usr/bin/google-chrome")
    assert config_utils._linux_desktop_to_kind_and_path(
        "/usr/bin/firefox",
    ) == ("firefox", "/usr/bin/firefox")
    assert config_utils._linux_desktop_to_kind_and_path(
        "/usr/bin/microsoft-edge",
    ) == ("chromium", "/usr/bin/microsoft-edge")
    assert config_utils._linux_desktop_to_kind_and_path(
        "/opt/browser/custom",
    ) == ("chromium", "/opt/browser/custom")


def test_working_dir_path_helpers_use_configured_root(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(config_utils, "WORKING_DIR", tmp_path)

    assert config_utils.get_config_path() == tmp_path / "config.json"
    assert config_utils.get_heartbeat_query_path() == tmp_path / "HEARTBEAT.md"
    assert config_utils.get_jobs_path() == tmp_path / "jobs.json"
    assert config_utils.get_chats_path() == tmp_path / "chats.json"
