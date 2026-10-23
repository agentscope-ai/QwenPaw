# -*- coding: utf-8 -*-
"""Publication permissions are bounded without changing the host umask."""

import json
import subprocess
import sys

import pytest


@pytest.mark.parametrize("mask", [0o000, 0o022, 0o077])
def test_published_wheel_permissions_are_bounded_in_child(tmp_path, mask):
    # A child owns the process-global umask; host tests never change it.
    program = r"""
import json
import os
from pathlib import Path
import stat
import sys
from qwenpaw.plugins.dependency_gate import _write_additions
from qwenpaw.plugins.wheel_additions import WheelFiles

root = Path(sys.argv[1]).resolve()
root.mkdir(mode=0o700)
existing = root / "existing"
existing.mkdir(mode=0o700)
sentinel = existing / "user.txt"
sentinel.write_bytes(b"user environment")
sentinel.chmod(0o600)
mask = int(sys.argv[2])
os.umask(mask)
files = WheelFiles()
files.update({
    "new/deep/package/module.py": b"exact module bytes\x00\xff",
    "new/deep/bin/script": b"#!/bin/sh\nexit 0\n",
    "existing/addition.py": b"under existing parent",
})
files.executable_paths.add("new/deep/bin/script")
_write_additions(root, files)
probe = root / "umask-probe"
probe.touch(mode=0o666)
observed = {
    str(path.relative_to(root)): stat.S_IMODE(path.stat().st_mode)
    for path in root.rglob("*")
}
for relative, contents in files.items():
    assert (root / relative).read_bytes() == contents
assert sentinel.read_bytes() == b"user environment"
observed["."] = stat.S_IMODE(root.stat().st_mode)
print(json.dumps(observed))
"""
    result = subprocess.run(
        [sys.executable, "-c", program, str(tmp_path / "site"), str(mask)],
        capture_output=True,
        text=True,
        check=True,
    )
    modes = json.loads(result.stdout)
    assert modes["new/deep/package/module.py"] == 0o644 & ~mask
    assert modes["new/deep/bin/script"] == 0o755 & ~mask
    assert modes["existing/addition.py"] == 0o644 & ~mask
    for relative in ("new", "new/deep", "new/deep/package", "new/deep/bin"):
        assert modes[relative] == 0o755 & ~mask, relative
    assert modes["."] == modes["existing"] == 0o700
    assert modes["existing/user.txt"] == 0o600
    assert modes["umask-probe"] == 0o666 & ~mask


def test_publication_fsyncs_exact_validated_bytes(tmp_path, monkeypatch):
    import os

    from qwenpaw.plugins import dependency_gate as gate

    original_fsync = os.fsync
    synced = []

    def fsync(fd):
        synced.append(os.fstat(fd).st_size)
        original_fsync(fd)

    monkeypatch.setattr(gate.os, "fsync", fsync)
    payload = b"validated\x00wheel\xffpayload"
    gate._write_additions(tmp_path, {"nested/payload.py": payload})
    assert (tmp_path / "nested/payload.py").read_bytes() == payload
    assert synced == [len(payload)]


def test_publication_never_overwrites_existing_file(tmp_path):
    from qwenpaw.plugins.dependency_gate import _write_additions

    existing = tmp_path / "existing.py"
    existing.write_bytes(b"user-owned")
    existing.chmod(0o600)
    with pytest.raises(FileExistsError):
        _write_additions(tmp_path, {"existing.py": b"replacement"})
    assert existing.read_bytes() == b"user-owned"
    assert existing.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("parent_link", [False, True])
def test_publication_refuses_symlinks_outside_target(tmp_path, parent_link):
    from qwenpaw.plugins.dependency_gate import _write_additions

    target, outside = tmp_path / "site", tmp_path / "outside"
    target.mkdir()
    outside.mkdir()
    sentinel = outside / "user.py"
    sentinel.write_bytes(b"host-owned")
    if parent_link:
        (target / "alias").symlink_to(outside, target_is_directory=True)
        relative = "alias/user.py"
    else:
        (target / "alias.py").symlink_to(sentinel)
        relative = "alias.py"
    with pytest.raises(RuntimeError, match="DEPENDENCY_REPAIR_REQUIRED"):
        _write_additions(target, {relative: b"replacement"})
    assert sentinel.read_bytes() == b"host-owned"
    assert list(outside.iterdir()) == [sentinel]


@pytest.mark.parametrize("mask", [0o000, 0o022])
def test_publication_creates_missing_target_with_bounded_parents(
    tmp_path,
    mask,
):
    program = r"""
import json
import os
from pathlib import Path
import stat
import sys
from qwenpaw.plugins.dependency_gate import _write_additions

base = Path(sys.argv[1]).resolve()
os.umask(int(sys.argv[2]))
target = base / "new" / "site"
_write_additions(target, {"package/deep/module.py": b"exact bytes"})
assert (target / "package/deep/module.py").read_bytes() == b"exact bytes"
print(json.dumps({
    str(path.relative_to(base)): stat.S_IMODE(path.stat().st_mode)
    for path in base.rglob("*")
}))
"""
    result = subprocess.run(
        [sys.executable, "-c", program, str(tmp_path), str(mask)],
        capture_output=True,
        text=True,
        check=True,
    )
    modes = json.loads(result.stdout)
    for relative in (
        "new",
        "new/site",
        "new/site/package",
        "new/site/package/deep",
    ):
        assert modes[relative] == 0o755 & ~mask, relative
    assert modes["new/site/package/deep/module.py"] == 0o644 & ~mask


def test_publication_checks_parent_containment_before_creating_directories(
    tmp_path,
):
    from qwenpaw.plugins.dependency_gate import _write_additions

    target, outside = tmp_path / "site", tmp_path / "outside"
    target.mkdir()
    outside.mkdir()
    (target / "alias").symlink_to(outside, target_is_directory=True)
    with pytest.raises(RuntimeError, match="DEPENDENCY_REPAIR_REQUIRED"):
        _write_additions(target, {"alias/new/deep/module.py": b"validated"})
    assert list(outside.iterdir()) == []
    assert list(target.iterdir()) == [target / "alias"]
