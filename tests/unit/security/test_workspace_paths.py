# -*- coding: utf-8 -*-
"""Tests for the shared reserved-workspace-directory guard."""
# pylint: disable=redefined-outer-name,unused-argument
from __future__ import annotations

from pathlib import Path

import pytest

from qwenpaw import constant
from qwenpaw.security import workspace_paths


@pytest.fixture()
def reserved_layout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Path:
    working = (tmp_path / "working").resolve()
    (working / "workspaces").mkdir(parents=True)
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


def test_normal_workspace_is_not_reserved(reserved_layout: Path) -> None:
    target = reserved_layout / "workspaces" / "agent1"
    assert workspace_paths.reserved_workspace_root_for(target) is None


def test_custom_path_outside_working_dir_is_not_reserved(
    reserved_layout: Path,
    tmp_path: Path,
) -> None:
    target = tmp_path / "elsewhere" / "agent1"
    assert workspace_paths.reserved_workspace_root_for(target) is None


@pytest.mark.parametrize("sub", ["custom_channels", "plugins"])
def test_auto_loaded_dirs_are_reserved(
    reserved_layout: Path,
    sub: str,
) -> None:
    target = reserved_layout / sub / "evil"
    matched = workspace_paths.reserved_workspace_root_for(target)
    assert matched == (reserved_layout / sub).resolve()


def test_secret_dir_is_reserved(reserved_layout: Path) -> None:
    matched = workspace_paths.reserved_workspace_root_for(constant.SECRET_DIR)
    assert matched == Path(constant.SECRET_DIR).resolve()


def test_relative_traversal_into_reserved_is_detected(
    reserved_layout: Path,
) -> None:
    target = reserved_layout / "workspaces" / ".." / "plugins" / "x"
    matched = workspace_paths.reserved_workspace_root_for(target)
    assert matched == (reserved_layout / "plugins").resolve()


def test_ancestor_of_reserved_is_detected(reserved_layout: Path) -> None:
    # A destination equal to WORKING_DIR is an ancestor of custom_channels /
    # plugins; restoring a workspace there would drop the workspace's own
    # custom_channels/... files into the real reserved directory.
    matched = workspace_paths.reserved_workspace_root_for(reserved_layout)
    assert matched in (
        (reserved_layout / "custom_channels").resolve(),
        (reserved_layout / "plugins").resolve(),
    )


def test_parent_of_working_dir_is_detected(
    reserved_layout: Path,
    tmp_path: Path,
) -> None:
    # WORKING_DIR.parent is an ancestor of every reserved directory too.
    matched = workspace_paths.reserved_workspace_root_for(tmp_path)
    assert matched is not None


def test_assert_allows_normal_workspace(reserved_layout: Path) -> None:
    target = reserved_layout / "workspaces" / "agent1"
    assert workspace_paths.assert_workspace_dir_allowed(target) == (
        target.resolve()
    )


def test_assert_raises_for_reserved(reserved_layout: Path) -> None:
    target = reserved_layout / "plugins" / "evil"
    with pytest.raises(workspace_paths.ReservedWorkspaceError) as exc_info:
        workspace_paths.assert_workspace_dir_allowed(target)
    assert exc_info.value.reserved == (reserved_layout / "plugins").resolve()
