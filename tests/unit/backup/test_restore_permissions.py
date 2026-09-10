# -*- coding: utf-8 -*-
"""Tests for pre-commit secret directory permission hardening."""
from __future__ import annotations

import importlib
import io
import os
import stat
import zipfile
from pathlib import Path

import pytest

from qwenpaw.backup._utils.safe_swap import _extract_zip_to, extract_to_tmp

restore_ops = importlib.import_module("qwenpaw.backup._ops.restore")

pytestmark = pytest.mark.skipif(
    os.name == "nt",
    reason="POSIX permission bits are not enforced on Windows",
)


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_harden_secret_dir_recurses_into_nested_subdir(
    tmp_path: Path,
) -> None:
    """A nested providers/ dir must not stay world-traversable."""
    secret_dir = tmp_path / "secrets"
    nested = secret_dir / "providers"
    nested.mkdir(parents=True)
    (secret_dir / ".master_key").write_text("KEY", encoding="utf-8")
    (nested / "openai.json").write_text("{}", encoding="utf-8")

    # Simulate the world-readable state left behind by extraction.
    os.chmod(secret_dir, 0o755)
    os.chmod(nested, 0o755)
    os.chmod(secret_dir / ".master_key", 0o644)
    os.chmod(nested / "openai.json", 0o644)

    restore_ops._harden_secret_dir(secret_dir)

    assert _mode(secret_dir) == 0o700
    assert _mode(nested) == 0o700
    assert _mode(secret_dir / ".master_key") == 0o600
    assert _mode(nested / "openai.json") == 0o600


def test_harden_secret_dir_handles_deep_nesting(tmp_path: Path) -> None:
    """Hardening reaches arbitrarily deep subdirectories."""
    secret_dir = tmp_path / "secrets"
    deep = secret_dir / "a" / "b"
    deep.mkdir(parents=True)
    (deep / "cred.json").write_text("{}", encoding="utf-8")
    os.chmod(secret_dir / "a", 0o755)
    os.chmod(deep, 0o755)
    os.chmod(deep / "cred.json", 0o644)

    restore_ops._harden_secret_dir(secret_dir)

    assert _mode(secret_dir) == 0o700
    assert _mode(secret_dir / "a") == 0o700
    assert _mode(deep) == 0o700
    assert _mode(deep / "cred.json") == 0o600


def test_extract_does_not_apply_unauthenticated_mode(tmp_path: Path) -> None:
    """Archive mode metadata must not affect restored files."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        info = zipfile.ZipInfo("data/workspaces/default/tool.sh")
        info.external_attr = 0o777 << 16
        zf.writestr(info, "#!/bin/sh\n")
    buf.seek(0)

    dst = tmp_path / "ws"
    target = dst / "default" / "tool.sh"
    target.parent.mkdir(parents=True)
    target.write_text("old", encoding="utf-8")
    os.chmod(target, 0o600)
    with zipfile.ZipFile(buf) as zf:
        _extract_zip_to(zf, "data/workspaces/", dst, dst.resolve())

    assert _mode(target) == 0o600


def test_extract_to_tmp_creates_restricted_staging_dir(
    tmp_path: Path,
) -> None:
    """Secret staging starts restricted rather than relying on chmod."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("data/secrets/token.json", "{}")
    buf.seek(0)

    dst = tmp_path / "secrets"
    with zipfile.ZipFile(buf) as zf:
        staged = extract_to_tmp(
            zf,
            "data/secrets/",
            dst,
            dir_mode=0o700,
        )

    assert _mode(staged) == 0o700


@pytest.mark.parametrize("failure_target", ["root", "file"])
def test_harden_secret_dir_propagates_chmod_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_target: str,
) -> None:
    """Permission enforcement failures must abort the restore."""
    secret_dir = tmp_path / "secrets"
    secret_dir.mkdir()
    secret_file = secret_dir / "token.json"
    secret_file.write_text("{}", encoding="utf-8")
    original_chmod = os.chmod

    def fail_chmod(path: Path, mode: int) -> None:
        target = secret_dir if failure_target == "root" else secret_file
        if path == target:
            raise PermissionError("chmod denied")
        original_chmod(path, mode)

    monkeypatch.setattr(restore_ops.os, "chmod", fail_chmod)

    with pytest.raises(PermissionError, match="chmod denied"):
        restore_ops._harden_secret_dir(secret_dir)


def test_stage_secrets_discards_tmp_when_hardening_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An insecure staging tree is discarded without replacing live data."""
    secret_dir = tmp_path / "secrets"
    secret_dir.mkdir()
    existing = secret_dir / "existing.json"
    existing.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(restore_ops, "SECRET_DIR", secret_dir)
    monkeypatch.setattr(
        restore_ops,
        "handle_master_key_conflict",
        lambda _zf: None,
    )

    def fail_hardening(_path: Path) -> None:
        raise PermissionError("chmod denied")

    monkeypatch.setattr(
        restore_ops,
        "_harden_secret_dir",
        fail_hardening,
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("data/secrets/token.json", "{}")
    buf.seek(0)
    staged_dirs: list[Path] = []

    with zipfile.ZipFile(buf) as zf:
        with pytest.raises(PermissionError, match="chmod denied"):
            restore_ops._stage_secrets(zf, staged_dirs)

    assert existing.exists()
    assert staged_dirs == []
    assert not secret_dir.with_name("secrets.restore_tmp").exists()
