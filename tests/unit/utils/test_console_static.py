# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

import pytest

from qwenpaw.utils import console_static


def _write_index(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    index = directory / "index.html"
    index.write_text("<!doctype html>", encoding="utf-8")
    return directory


@pytest.fixture(autouse=True)
def _clear_console_static_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QWENPAW_CONSOLE_STATIC_DIR", raising=False)
    monkeypatch.delenv("COPAW_CONSOLE_STATIC_DIR", raising=False)


def test_resolve_console_static_dir_prefers_qwenpaw_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    configured = tmp_path / "configured-console"
    monkeypatch.setenv("QWENPAW_CONSOLE_STATIC_DIR", str(configured))

    assert console_static.resolve_console_static_dir() == str(configured)


def test_resolve_console_static_dir_accepts_legacy_copaw_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    configured = tmp_path / "legacy-console"
    monkeypatch.setenv("COPAW_CONSOLE_STATIC_DIR", str(configured))

    assert console_static.resolve_console_static_dir() == str(configured)


def test_resolve_console_static_dir_prefers_packaged_console(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    package_dir = tmp_path / "site-packages" / "qwenpaw"
    packaged_console = _write_index(package_dir / "console")
    fake_module = tmp_path / "site-packages" / "qwenpaw" / "utils" / "console_static.py"
    monkeypatch.setattr(console_static, "__file__", str(fake_module))
    monkeypatch.chdir(tmp_path)

    assert console_static.resolve_console_static_dir() == str(packaged_console)


def test_resolve_console_static_dir_falls_back_to_repo_dist(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repo_dir = tmp_path / "repo"
    repo_console = _write_index(repo_dir / "console" / "dist")
    fake_module = repo_dir / "src" / "qwenpaw" / "utils" / "console_static.py"
    monkeypatch.setattr(console_static, "__file__", str(fake_module))
    monkeypatch.chdir(tmp_path)

    assert console_static.resolve_console_static_dir() == str(repo_console)


def test_resolve_console_static_dir_falls_back_to_cwd_console_dist(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cwd_console = _write_index(tmp_path / "console" / "dist")
    fake_module = (
        tmp_path
        / "venv"
        / "lib"
        / "python3.12"
        / "site-packages"
        / "qwenpaw"
        / "utils"
        / "console_static.py"
    )
    monkeypatch.setattr(console_static, "__file__", str(fake_module))
    monkeypatch.chdir(tmp_path)

    assert console_static.resolve_console_static_dir() == str(cwd_console)


def test_resolve_console_static_dir_returns_missing_cwd_console_dist(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fake_module = (
        tmp_path
        / "venv"
        / "lib"
        / "python3.12"
        / "site-packages"
        / "qwenpaw"
        / "utils"
        / "console_static.py"
    )
    monkeypatch.setattr(console_static, "__file__", str(fake_module))
    monkeypatch.chdir(tmp_path)

    assert console_static.resolve_console_static_dir() == str(
        tmp_path / "console" / "dist",
    )
