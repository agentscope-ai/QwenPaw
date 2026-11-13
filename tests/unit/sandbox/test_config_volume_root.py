# -*- coding: utf-8 -*-
"""Volume-root handling for ``SandboxConfig`` / ``create_sandbox``.

Sandbox ACLs are inheritable and are written on the workspace, on every
mount and on every deny path. A volume root has no parent, so such a write
re-propagates to every existing child of the volume; if the root DACL is
missing or is replaced with a sandbox-only DACL, SYSTEM / Administrators /
Users can vanish from the subtree and the drive becomes inaccessible.

QwenPaw must not treat a volume root as a grant root, but the command
should still run: ``create_sandbox`` falls back to unsandboxed execution.
See #7943.
"""

import os
from pathlib import Path

from qwenpaw.sandbox import (
    MountSpec,
    SandboxConfig,
    SandboxMode,
    create_sandbox,
    is_volume_root,
    volume_root_paths,
)


def _volume_root(path: Path) -> str:
    """The volume root that contains *path*."""
    if os.name == "nt":
        drive, _ = os.path.splitdrive(str(path))
        return drive + os.sep
    return os.sep


def test_is_volume_root_accepts_roots(tmp_path: Path):
    """Drive roots and ``/`` are volume roots."""
    assert is_volume_root(_volume_root(tmp_path))
    assert is_volume_root(os.sep)


def test_is_volume_root_rejects_subdirectories(tmp_path: Path):
    """A directory below a volume root is not itself a volume root."""
    assert not is_volume_root(str(tmp_path))
    assert not is_volume_root(os.path.join(str(tmp_path), "child"))


def test_is_volume_root_ignores_empty_path():
    """An empty path is not a volume root."""
    assert not is_volume_root("")


def test_volume_root_paths_flags_workspace(tmp_path: Path):
    """The workspace is reported when it is a volume root."""
    config = SandboxConfig(
        mode=SandboxMode.NONE,
        workspace_dir=_volume_root(tmp_path),
    )
    assert volume_root_paths(config) == [_volume_root(tmp_path)]


def test_volume_root_paths_flags_any_mount(tmp_path: Path):
    """Read-only mounts get an inheritable ACE too, so they are flagged."""
    root = _volume_root(tmp_path)
    for writable in (True, False):
        config = SandboxConfig(
            mode=SandboxMode.NONE,
            workspace_dir=str(tmp_path),
            mounts=[MountSpec(path=root, writable=writable)],
        )
        assert volume_root_paths(config) == [root]


def test_volume_root_paths_flags_deny_paths(tmp_path: Path):
    """The deny ACE is inheritable, so a volume-root deny path is flagged."""
    config = SandboxConfig(
        mode=SandboxMode.NONE,
        workspace_dir=str(tmp_path),
        deny_paths=[_volume_root(tmp_path)],
    )
    assert volume_root_paths(config) == [_volume_root(tmp_path)]


def test_volume_root_paths_is_empty_for_normal_paths(tmp_path: Path):
    """Ordinary directories are not flagged."""
    project = tmp_path / "project"
    config = SandboxConfig(
        mode=SandboxMode.NONE,
        workspace_dir=str(tmp_path),
        mounts=[MountSpec(path=str(project), writable=True)],
        deny_paths=[str(tmp_path / ".ssh")],
    )
    assert not volume_root_paths(config)


def test_volume_root_config_does_not_raise(tmp_path: Path):
    """Building the config must not fail: the command still has to run."""
    config = SandboxConfig(
        mode=SandboxMode.NONE,
        workspace_dir=_volume_root(tmp_path),
    )
    assert config.workspace_dir == _volume_root(tmp_path)


def test_create_sandbox_downgrades_a_volume_root_workspace(tmp_path: Path):
    """A volume root falls back to unsandboxed execution (the drive is
    never given an inheritable ACE, and the command still runs)."""
    from qwenpaw.sandbox.local_sandbox import NoneSandbox

    config = SandboxConfig(
        mode=SandboxMode.WINDOWS,
        workspace_dir=_volume_root(tmp_path),
        allow_read_all=True,
    )
    sandbox = create_sandbox(config)
    assert isinstance(sandbox, NoneSandbox)


def test_create_sandbox_keeps_the_sandbox_for_normal_paths(tmp_path: Path):
    """A normal workspace keeps whatever backend was requested."""
    config = SandboxConfig(
        mode=SandboxMode.NONE,
        workspace_dir=str(tmp_path),
    )
    sandbox = create_sandbox(config)
    assert sandbox is not None
    assert type(sandbox).__name__ == "NoneSandbox"
