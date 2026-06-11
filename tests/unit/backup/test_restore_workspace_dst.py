# -*- coding: utf-8 -*-
"""Guards for restore workspace destination resolution.

Custom workspace locations (including paths outside ``WORKING_DIR``) are a
supported feature, so the guard only blocks restoring into directories the
server auto-loads code from (``custom_channels``, ``plugins``) or the secrets
store. Those are the vectors that turn "restore files" into code execution or
credential tampering.
"""
# pylint: disable=redefined-outer-name,protected-access,unused-argument
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from qwenpaw import constant
from qwenpaw.backup._ops import restore_helpers
from qwenpaw.backup.models import BackupValidationError


@pytest.fixture()
def working_dir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Path:
    """Point the restore helpers at an isolated WORKING_DIR layout.

    ``restore_helpers.WORKING_DIR`` drives the default-branch destination,
    while the reserved-dir guard lives in ``security.workspace_paths`` and
    reads the reserved directories from ``qwenpaw.constant`` lazily.
    """
    working = (tmp_path / "working").resolve()
    (working / "workspaces").mkdir(parents=True)
    monkeypatch.setattr(restore_helpers, "WORKING_DIR", working)
    monkeypatch.setattr(
        constant,
        "CUSTOM_CHANNELS_DIR",
        working / "custom_channels",
    )
    monkeypatch.setattr(constant, "PLUGINS_DIR", working / "plugins")
    monkeypatch.setattr(
        constant,
        "SECRET_DIR",
        (tmp_path / "working.secret").resolve(),
    )
    return working


def test_default_placement_is_allowed(working_dir: Path) -> None:
    dst, is_new = restore_helpers.resolve_workspace_dst("agent1", None, None)
    assert dst == working_dir / "workspaces" / "agent1"
    assert is_new is True


def test_explicit_workspace_dir_inside_working_dir_is_allowed(
    working_dir: Path,
) -> None:
    base = str(working_dir / "workspaces")
    dst, _ = restore_helpers.resolve_workspace_dst("agent1", None, base)
    assert dst == working_dir / "workspaces" / "agent1"


def test_custom_workspace_dir_outside_working_dir_is_allowed(
    working_dir: Path,
    tmp_path: Path,
) -> None:
    # Users may intentionally place agent workspaces outside WORKING_DIR;
    # this must remain a supported restore destination.
    base = str(tmp_path / "custom-agents")
    dst, _ = restore_helpers.resolve_workspace_dst("agent1", None, base)
    assert dst == (tmp_path / "custom-agents" / "agent1").resolve()


def test_custom_channels_destination_is_rejected(working_dir: Path) -> None:
    base = str(working_dir / "custom_channels")
    with pytest.raises(BackupValidationError) as exc_info:
        restore_helpers.resolve_workspace_dst("pocpkg", None, base)
    assert exc_info.value.code == "restore_workspace_dir_reserved"


def test_plugins_destination_is_rejected(working_dir: Path) -> None:
    base = str(working_dir / "plugins")
    with pytest.raises(BackupValidationError) as exc_info:
        restore_helpers.resolve_workspace_dst("pocpkg", None, base)
    assert exc_info.value.code == "restore_workspace_dir_reserved"


def test_secrets_destination_is_rejected(
    working_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secrets = working_dir / "secrets"
    monkeypatch.setattr(constant, "SECRET_DIR", secrets)
    with pytest.raises(BackupValidationError) as exc_info:
        restore_helpers.resolve_workspace_dst("agent1", None, str(secrets))
    assert exc_info.value.code == "restore_workspace_dir_reserved"


def test_relative_traversal_into_custom_channels_is_rejected(
    working_dir: Path,
) -> None:
    base = str(working_dir / "workspaces" / ".." / "custom_channels")
    with pytest.raises(BackupValidationError) as exc_info:
        restore_helpers.resolve_workspace_dst("pocpkg", None, base)
    assert exc_info.value.code == "restore_workspace_dir_reserved"


@pytest.mark.parametrize("aid", ["..", ".", "../evil", "a/b", "a\\b", ""])
def test_traversal_agent_id_is_rejected(working_dir: Path, aid: str) -> None:
    # A "../" agent id resolves dst back up to WORKING_DIR (which passes the
    # reserved-dir check) and reintroduces custom_channels via the zip prefix
    # during extraction. Reject unsafe ids before any path is built.
    with pytest.raises(BackupValidationError) as exc_info:
        restore_helpers.resolve_workspace_dst(aid, None, None)
    assert exc_info.value.code == "restore_invalid_agent_id"


def test_existing_ref_inside_custom_channels_is_rejected(
    working_dir: Path,
) -> None:
    # An agent profile may already point at custom_channels (create_agent
    # accepts an arbitrary workspace_dir); restoring into it must still be
    # blocked even though this branch reuses the existing path.
    ws = working_dir / "custom_channels" / "pocpkg"
    ws.mkdir(parents=True)
    ref = SimpleNamespace(workspace_dir=str(ws))
    with pytest.raises(BackupValidationError) as exc_info:
        restore_helpers.resolve_workspace_dst("pocpkg", ref, None)
    assert exc_info.value.code == "restore_workspace_dir_reserved"


def test_workspace_dir_that_is_ancestor_of_reserved_is_rejected(
    working_dir: Path,
    tmp_path: Path,
) -> None:
    # default_workspace_dir=WORKING_DIR.parent with aid=WORKING_DIR.name makes
    # dst == WORKING_DIR, an ancestor of custom_channels/plugins. A workspace
    # entry like custom_channels/pocpkg/__init__.py would then land in the
    # real custom_channels during extraction (RCE), so this must be rejected.
    base = str(working_dir.parent)
    aid = working_dir.name
    with pytest.raises(BackupValidationError) as exc_info:
        restore_helpers.resolve_workspace_dst(aid, None, base)
    assert exc_info.value.code == "restore_workspace_dir_reserved"


def test_existing_ref_in_normal_workspace_is_allowed(
    working_dir: Path,
) -> None:
    ws = working_dir / "workspaces" / "agent1"
    ws.mkdir(parents=True)
    ref = SimpleNamespace(workspace_dir=str(ws))
    dst, is_new = restore_helpers.resolve_workspace_dst("agent1", ref, None)
    assert dst == ws.resolve()
    assert is_new is False
