# -*- coding: utf-8 -*-
"""Tests for post-restore secret directory permission hardening."""
from __future__ import annotations

import io
import os
import stat
import zipfile
from pathlib import Path

import pytest

from qwenpaw.backup._ops.restore import _harden_secret_dir
from qwenpaw.backup._utils.safe_swap import _extract_zip_to

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

    _harden_secret_dir(secret_dir)

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

    _harden_secret_dir(secret_dir)

    assert _mode(secret_dir) == 0o700
    assert _mode(secret_dir / "a") == 0o700
    assert _mode(deep) == 0o700
    assert _mode(deep / "cred.json") == 0o600


def test_extract_strips_setuid_from_archived_mode(tmp_path: Path) -> None:
    """setuid/setgid bits must never be restored from an archive."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        info = zipfile.ZipInfo("data/workspaces/default/tool.sh")
        info.external_attr = 0o4755 << 16  # setuid + rwxr-xr-x
        zf.writestr(info, "#!/bin/sh\n")
    buf.seek(0)

    dst = tmp_path / "ws"
    dst.mkdir()
    with zipfile.ZipFile(buf) as zf:
        _extract_zip_to(zf, "data/workspaces/", dst, dst.resolve())

    mode = (dst / "default" / "tool.sh").stat().st_mode
    assert mode & stat.S_ISUID == 0
    assert mode & stat.S_ISGID == 0
    assert stat.S_IMODE(mode) == 0o755
