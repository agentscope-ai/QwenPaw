# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

import pytest

from qwenpaw.platform_ops.deployment_backup import (
    BackupValidationError,
    new_manifest,
    preflight_restore,
    sanitize_environment,
    verify_manifest,
    write_manifest,
)


def _valid_backup(root: Path) -> Path:
    root.mkdir()
    for name in ("database.dump", "working.tar.gz", "secrets.tar.gz"):
        (root / name).write_bytes(name.encode())
    write_manifest(root, new_manifest(root, environment={"WELDON_DB_USER": "weldon"}))
    return root


def test_environment_manifest_never_contains_secrets():
    clean = sanitize_environment(
        {
            "WELDON_DB_USER": "weldon",
            "WELDON_DB_PASSWORD": "secret-value",
            "API_TOKEN": "token-value",
        }
    )
    payload = json.dumps(clean)
    assert clean["WELDON_DB_USER"] == "weldon"
    assert "secret-value" not in payload
    assert "token-value" not in payload


def test_verify_manifest_detects_changed_archive(tmp_path: Path):
    backup = _valid_backup(tmp_path / "backup")
    (backup / "working.tar.gz").write_bytes(b"changed")
    result = verify_manifest(backup)
    assert result.ok is False
    assert "working.tar.gz" in " ".join(result.errors)


def test_restore_rejects_non_empty_target(tmp_path: Path):
    backup = _valid_backup(tmp_path / "backup")
    target = tmp_path / "target"
    (target / "working").mkdir(parents=True)
    (target / "working" / "existing.txt").write_text("keep", encoding="utf-8")
    with pytest.raises(BackupValidationError, match="必须为空"):
        preflight_restore(backup, target)


def test_restore_accepts_empty_managed_directories(tmp_path: Path):
    backup = _valid_backup(tmp_path / "backup")
    target = tmp_path / "target"
    (target / "working").mkdir(parents=True)
    (target / "secrets").mkdir()
    assert preflight_restore(backup, target).format_version == 1
