# -*- coding: utf-8 -*-
"""Unit tests for console static directory resolution."""
from __future__ import annotations

from pathlib import Path

from copaw.app.console_static import (
    CONSOLE_STATIC_ENV,
    resolve_console_static_dir,
)


def _build_fake_repo(tmp_path: Path) -> tuple[Path, Path]:
    repo_root = tmp_path / "repo"
    module_file = repo_root / "src" / "copaw" / "app" / "_app.py"
    module_file.parent.mkdir(parents=True, exist_ok=True)
    module_file.write_text("# fake module\n", encoding="utf-8")
    return repo_root, module_file


def _write_console_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "index.html").write_text("<!doctype html>", encoding="utf-8")
    return path.resolve()


def test_resolve_console_static_dir_prefers_packaged_console(
    tmp_path: Path,
) -> None:
    repo_root, module_file = _build_fake_repo(tmp_path)
    packaged_console = _write_console_dir(
        repo_root / "src" / "copaw" / "console",
    )
    _write_console_dir(repo_root / "console" / "dist")
    cwd = tmp_path / "cwd"
    _write_console_dir(cwd / "console" / "dist")

    resolved = resolve_console_static_dir(
        env={},
        module_file=module_file,
        cwd=cwd,
    )

    assert resolved == str(packaged_console)


def test_resolve_console_static_dir_prefers_repo_root_before_cwd(
    tmp_path: Path,
) -> None:
    repo_root, module_file = _build_fake_repo(tmp_path)
    repo_console = _write_console_dir(repo_root / "console" / "dist")
    cwd = tmp_path / "cwd"
    _write_console_dir(cwd / "console" / "dist")

    resolved = resolve_console_static_dir(
        env={},
        module_file=module_file,
        cwd=cwd,
    )

    assert resolved == str(repo_console)


def test_resolve_console_static_dir_falls_back_to_cwd_candidates(
    tmp_path: Path,
) -> None:
    _, module_file = _build_fake_repo(tmp_path)
    cwd_console = _write_console_dir(tmp_path / "runtime" / "console_dist")

    resolved = resolve_console_static_dir(
        env={},
        module_file=module_file,
        cwd=cwd_console.parent,
    )

    assert resolved == str(cwd_console)


def test_resolve_console_static_dir_keeps_env_override_absolute(
    tmp_path: Path,
) -> None:
    _, module_file = _build_fake_repo(tmp_path)
    cwd = tmp_path / "runtime"
    cwd.mkdir(parents=True, exist_ok=True)

    resolved = resolve_console_static_dir(
        env={CONSOLE_STATIC_ENV: "custom/console-dist"},
        module_file=module_file,
        cwd=cwd,
    )

    assert resolved == str((cwd / "custom" / "console-dist").resolve())
