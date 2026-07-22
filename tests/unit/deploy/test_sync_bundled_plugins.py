# -*- coding: utf-8 -*-
"""Tests for ``deploy/sync-bundled-plugins.sh``.

The script installs plugins shipped inside the Docker image into the
working directory, where ``PluginLoader`` discovers them.  It runs on every
container start, so it must be idempotent and must never leave a backup
inside ``<working_dir>/plugins`` (the loader would treat the backup as a
second, stale plugin).
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[3] / "deploy" / "sync-bundled-plugins.sh"
)


def _make_plugin(root: Path, name: str, version: str) -> Path:
    """Create a minimal plugin directory with a plugin.json manifest."""
    plugin_dir = root / name
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.json").write_text(
        json.dumps(
            {
                "id": name,
                "name": name,
                "version": version,
                "min_version": "1.1.7",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (plugin_dir / "plugin.py").write_text(
        f"# {name} {version}\n",
        encoding="utf-8",
    )
    return plugin_dir


def _run(tmp_path: Path) -> subprocess.CompletedProcess:
    """Run the sync script against sandboxed directories."""
    env = dict(os.environ)
    env.update(
        {
            "BUNDLED_PLUGINS_DIR": str(tmp_path / "bundled"),
            "QWENPAW_WORKING_DIR": str(tmp_path / "working"),
            "PLUGIN_BACKUP_DIR": str(tmp_path / "backups"),
        },
    )
    return subprocess.run(
        ["sh", str(SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture(name="dirs")
def _dirs(tmp_path: Path) -> dict:
    bundled = tmp_path / "bundled"
    bundled.mkdir()
    working = tmp_path / "working"
    (working / "plugins").mkdir(parents=True)
    return {
        "bundled": bundled,
        "working": working,
        "plugins": working / "plugins",
        "backups": tmp_path / "backups",
    }


def test_installs_plugin_missing_from_working_dir(tmp_path, dirs):
    _make_plugin(dirs["bundled"], "nocobase_auth", "0.1.0")

    result = _run(tmp_path)

    assert result.returncode == 0, result.stderr
    installed = dirs["plugins"] / "nocobase_auth"
    assert (installed / "plugin.py").read_text() == "# nocobase_auth 0.1.0\n"


def test_creates_plugins_dir_when_absent(tmp_path):
    bundled = tmp_path / "bundled"
    bundled.mkdir()
    (tmp_path / "working").mkdir()
    _make_plugin(bundled, "nocobase_auth", "0.1.0")

    result = _run(tmp_path)

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "working" / "plugins" / "nocobase_auth").is_dir()


def test_same_version_is_left_untouched(tmp_path, dirs):
    _make_plugin(dirs["bundled"], "nocobase_auth", "0.1.0")
    installed = _make_plugin(dirs["plugins"], "nocobase_auth", "0.1.0")
    (installed / "local-edit.txt").write_text("keep me", encoding="utf-8")

    result = _run(tmp_path)

    assert result.returncode == 0, result.stderr
    assert (installed / "local-edit.txt").exists()
    assert not dirs["backups"].exists()


def test_repeated_runs_are_idempotent(tmp_path, dirs):
    _make_plugin(dirs["bundled"], "nocobase_auth", "0.1.0")

    _run(tmp_path)
    result = _run(tmp_path)

    assert result.returncode == 0, result.stderr
    assert not dirs["backups"].exists()
    assert list(dirs["plugins"].iterdir()) == [
        dirs["plugins"] / "nocobase_auth",
    ]


def test_different_version_replaces_installed_copy(tmp_path, dirs):
    _make_plugin(dirs["bundled"], "nocobase_auth", "0.2.0")
    _make_plugin(dirs["plugins"], "nocobase_auth", "0.1.0")

    result = _run(tmp_path)

    assert result.returncode == 0, result.stderr
    installed = dirs["plugins"] / "nocobase_auth"
    assert (installed / "plugin.py").read_text() == "# nocobase_auth 0.2.0\n"


def test_replaced_copy_is_backed_up_outside_plugins_dir(tmp_path, dirs):
    _make_plugin(dirs["bundled"], "nocobase_auth", "0.2.0")
    _make_plugin(dirs["plugins"], "nocobase_auth", "0.1.0")

    _run(tmp_path)

    # PluginLoader scans every directory under <working_dir>/plugins, so a
    # backup left there would be loaded as a stale second plugin.
    assert list(dirs["plugins"].iterdir()) == [
        dirs["plugins"] / "nocobase_auth",
    ]
    backups = list(dirs["backups"].glob("nocobase_auth-0.1.0-*"))
    assert len(backups) == 1
    assert (backups[0] / "plugin.py").read_text() == "# nocobase_auth 0.1.0\n"


def test_missing_bundle_dir_is_not_an_error(tmp_path):
    (tmp_path / "working" / "plugins").mkdir(parents=True)

    result = _run(tmp_path)

    assert result.returncode == 0, result.stderr


def test_non_plugin_directories_are_skipped(tmp_path, dirs):
    (dirs["bundled"] / "not-a-plugin").mkdir()

    result = _run(tmp_path)

    assert result.returncode == 0, result.stderr
    assert not (dirs["plugins"] / "not-a-plugin").exists()
