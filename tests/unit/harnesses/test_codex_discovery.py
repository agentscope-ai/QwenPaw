# -*- coding: utf-8 -*-
"""Tests for discovering Codex inside the ChatGPT editor extension."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from qwenpaw.harnesses.codex.discovery import resolve_codex_binary


def _executable(path: Path) -> Path:
    path.parent.mkdir(parents=True)
    path.touch()
    path.chmod(path.stat().st_mode | 0o111)
    return path


def test_resolves_explicit_binary(tmp_path: Path) -> None:
    binary = _executable(tmp_path / "custom" / "codex")

    assert resolve_codex_binary(str(binary), extension_roots=[]) == binary


def test_discovers_chatgpt_extension_binary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PATH", "")
    binary = _executable(
        tmp_path
        / "openai.chatgpt-26.707.1-darwin-arm64"
        / "bin"
        / "macos-aarch64"
        / "codex",
    )

    resolved = resolve_codex_binary(
        "codex",
        extension_roots=[tmp_path],
    )

    assert resolved == binary


def test_prefers_newest_chatgpt_extension_binary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PATH", "")
    older = _executable(
        tmp_path / "openai.chatgpt-1" / "bin" / "linux-x64" / "codex",
    )
    newer = _executable(
        tmp_path / "openai.chatgpt-2" / "bin" / "linux-x64" / "codex",
    )
    os.utime(older, ns=(1, 1))
    os.utime(newer, ns=(2, 2))

    resolved = resolve_codex_binary(
        "codex",
        extension_roots=[tmp_path],
    )

    assert resolved == newer


def test_discovers_windows_extension_binary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PATH", "")
    binary = _executable(
        tmp_path
        / "openai.chatgpt-26.707.1-win32-x64"
        / "bin"
        / "windows-x86_64"
        / "codex.exe",
    )

    resolved = resolve_codex_binary(
        "codex",
        extension_roots=[tmp_path],
    )

    assert resolved == binary
