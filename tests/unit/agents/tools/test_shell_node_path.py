# -*- coding: utf-8 -*-
"""Regression tests for shell PATH discovery."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from qwenpaw.agents.tools import shell
from qwenpaw.agents.tools.shell import (
    _build_subprocess_env,
    _dedupe_path_entries,
    _discover_node_bin_dirs,
    _discover_user_bin_dirs,
)


def _touch_node(bin_dir: Path) -> None:
    bin_dir.mkdir(parents=True, exist_ok=True)
    (bin_dir / "node").write_text("", encoding="utf-8")


def test_discover_node_bin_dirs_finds_common_user_managers(
    tmp_path: Path,
) -> None:
    """Node bins from Volta, fnm, and nvm should be discoverable."""
    volta_bin = tmp_path / ".volta" / "bin"
    fnm_bin = (
        tmp_path
        / ".local"
        / "share"
        / "fnm"
        / "node-versions"
        / "v24.14.1"
        / "installation"
        / "bin"
    )
    nvm_bin = tmp_path / ".nvm" / "versions" / "node" / "v22.0.0" / "bin"
    for bin_dir in (volta_bin, fnm_bin, nvm_bin):
        _touch_node(bin_dir)

    discovered = _discover_node_bin_dirs(home=tmp_path)

    assert str(volta_bin) in discovered
    assert str(fnm_bin) in discovered
    assert str(nvm_bin) in discovered


def test_build_subprocess_env_prepends_python_and_node_bins(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Subprocess PATH should include Python venv and discovered Node bins."""
    node_bin = tmp_path / ".volta" / "bin"
    _touch_node(node_bin)
    monkeypatch.setenv("PATH", os.pathsep.join([str(node_bin), "base"]))

    def discover_node_bin_dirs() -> list[str]:
        return [str(node_bin)]

    monkeypatch.setattr(
        shell,
        "_discover_node_bin_dirs",
        discover_node_bin_dirs,
    )

    path_entries = _build_subprocess_env()["PATH"].split(os.pathsep)

    assert path_entries[:3] == [
        str(Path(sys.executable).parent),
        str(node_bin),
        "base",
    ]
    assert path_entries.count(str(node_bin)) == 1


def test_discover_user_bin_dirs_finds_local_bin(tmp_path: Path) -> None:
    user_bin = tmp_path / ".local" / "bin"
    user_bin.mkdir(parents=True)

    assert _discover_user_bin_dirs(home=tmp_path) == [str(user_bin)]


def test_build_subprocess_env_prepends_user_local_bin(
    tmp_path: Path,
    monkeypatch,
) -> None:
    user_bin = tmp_path / ".local" / "bin"
    user_bin.mkdir(parents=True)
    monkeypatch.setenv("PATH", "base")

    def discover_user_bin_dirs() -> list[str]:
        return [str(user_bin)]

    monkeypatch.setattr(
        shell,
        "_discover_user_bin_dirs",
        discover_user_bin_dirs,
    )
    monkeypatch.setattr(shell, "_discover_node_bin_dirs", lambda: [])

    path_entries = _build_subprocess_env()["PATH"].split(os.pathsep)

    assert path_entries[:3] == [
        str(Path(sys.executable).parent),
        str(user_bin),
        "base",
    ]


def test_dedupe_path_entries_preserves_order() -> None:
    assert _dedupe_path_entries(["a", "b", "a", "", "c"]) == [
        "a",
        "b",
        "c",
    ]
