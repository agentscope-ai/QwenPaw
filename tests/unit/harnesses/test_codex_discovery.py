# -*- coding: utf-8 -*-
"""Tests for discovering Codex inside the ChatGPT editor extension."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from qwenpaw.harnesses.codex.discovery import (
    default_install_candidates,
    resolve_codex_binary,
    resolve_codex_binary_info,
)


def _executable(path: Path) -> Path:
    path.parent.mkdir(parents=True)
    path.touch()
    path.chmod(path.stat().st_mode | 0o111)
    return path


def test_resolves_explicit_binary(tmp_path: Path) -> None:
    binary = _executable(tmp_path / "custom" / "codex")

    assert resolve_codex_binary(str(binary), extension_roots=[]) == binary


def test_resolves_qwenpaw_environment_binary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binary = _executable(tmp_path / "environment" / "codex")
    monkeypatch.setenv("PATH", "")
    monkeypatch.setenv("CODEX_BINARY", str(binary))

    resolution = resolve_codex_binary_info(
        install_candidates=[],
        extension_roots=[],
    )

    assert resolution is not None
    assert resolution.path == binary
    assert resolution.source == "environment"


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
        install_candidates=[],
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
        install_candidates=[],
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
        install_candidates=[],
    )

    assert resolved == binary


def test_discovers_macos_chatgpt_app_binary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PATH", "")
    binary = _executable(
        tmp_path
        / "Applications"
        / "ChatGPT.app"
        / "Contents"
        / "Resources"
        / "codex",
    )
    candidates = default_install_candidates(
        tmp_path,
        platform_name="darwin",
        environ={},
    )
    assert (binary, "chatgpt-app") in candidates

    resolution = resolve_codex_binary_info(
        install_candidates=[(binary, "chatgpt-app")],
        extension_roots=[],
        platform_name="darwin",
        environ={},
    )

    assert resolution is not None
    assert resolution.path == binary
    assert resolution.source == "chatgpt-app"


def test_discovers_windows_standalone_binary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PATH", "")
    local_app_data = tmp_path / "LocalAppData"
    binary = (
        local_app_data / "Programs" / "OpenAI" / "Codex" / "bin" / "codex.exe"
    )
    binary.parent.mkdir(parents=True)
    binary.touch()
    environment = {"LOCALAPPDATA": str(local_app_data)}
    candidates = default_install_candidates(
        tmp_path,
        platform_name="win32",
        environ=environment,
    )

    resolution = resolve_codex_binary_info(
        install_candidates=candidates,
        extension_roots=[],
        platform_name="win32",
        environ=environment,
    )

    assert resolution is not None
    assert resolution.path == binary
    assert resolution.source == "standalone"


def test_discovers_linux_standalone_binary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PATH", "")
    binary = _executable(tmp_path / ".local" / "bin" / "codex")
    candidates = default_install_candidates(
        tmp_path,
        platform_name="linux",
        environ={},
    )

    resolution = resolve_codex_binary_info(
        install_candidates=candidates,
        extension_roots=[],
        platform_name="linux",
        environ={},
    )

    assert resolution is not None
    assert resolution.path == binary
    assert resolution.source == "standalone"


def test_invalid_manual_binary_does_not_fall_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PATH", "")
    fallback = _executable(tmp_path / ".local" / "bin" / "codex")

    resolution = resolve_codex_binary_info(
        str(tmp_path / "missing" / "codex"),
        install_candidates=[(fallback, "standalone")],
        extension_roots=[],
    )

    assert resolution is None
