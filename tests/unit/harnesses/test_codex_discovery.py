# -*- coding: utf-8 -*-
"""Tests for discovering standalone Codex CLI installations."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from qwenpaw.harnesses.codex import discovery
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


def test_reads_official_sdk_bundled_cli_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binary = tmp_path / "sdk" / "codex"
    module = SimpleNamespace(bundled_codex_path=lambda: binary)
    monkeypatch.setattr(
        discovery.importlib,
        "import_module",
        lambda name: module,
    )

    assert discovery.bundled_cli_candidate() == binary


def test_resolves_explicit_binary(tmp_path: Path) -> None:
    binary = _executable(tmp_path / "custom" / "codex")
    bundled = _executable(tmp_path / "sdk" / "codex")

    assert resolve_codex_binary(str(binary), sdk_candidate=bundled) == binary


def test_resolves_qwenpaw_environment_binary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binary = _executable(tmp_path / "environment" / "codex")
    monkeypatch.setenv("PATH", "")
    monkeypatch.setenv("CODEX_BINARY", str(binary))

    resolution = resolve_codex_binary_info(
        sdk_candidate=tmp_path / "missing",
        install_candidates=[],
    )

    assert resolution is not None
    assert resolution.path == binary
    assert resolution.source == "environment"


def test_prefers_python_sdk_bundled_cli(tmp_path: Path) -> None:
    binary = _executable(tmp_path / "sdk" / "codex")

    resolution = resolve_codex_binary_info(
        environ={},
        sdk_candidate=binary,
        install_candidates=[],
    )

    assert resolution is not None
    assert resolution.path == binary
    assert resolution.source == "python-sdk"


def test_rejects_chatgpt_extension_binary_from_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binary = _executable(
        tmp_path
        / "extensions"
        / "openai.chatgpt-26.707.1-darwin-arm64"
        / "bin"
        / "macos-aarch64"
        / "codex",
    )
    monkeypatch.setenv("PATH", str(binary.parent))

    resolution = resolve_codex_binary_info(
        "codex",
        sdk_candidate=tmp_path / "missing",
        install_candidates=[],
    )

    assert resolution is None


def test_rejects_explicit_chatgpt_app_binary(
    tmp_path: Path,
) -> None:
    binary = _executable(
        tmp_path
        / "Applications"
        / "ChatGPT.app"
        / "Contents"
        / "Resources"
        / "codex",
    )

    resolution = resolve_codex_binary_info(str(binary))

    assert resolution is None


def test_falls_back_from_path_extension_to_standalone(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extension_binary = _executable(
        tmp_path
        / "extensions"
        / "openai.chatgpt-26.707.1-win32-x64"
        / "bin"
        / "linux-x64"
        / "codex",
    )
    standalone = _executable(tmp_path / ".local" / "bin" / "codex")
    monkeypatch.setenv("PATH", str(extension_binary.parent))

    resolution = resolve_codex_binary_info(
        "codex",
        sdk_candidate=tmp_path / "missing",
        install_candidates=[(standalone, "standalone")],
    )

    assert resolution is not None
    assert resolution.path == standalone
    assert resolution.source == "standalone"


def test_macos_candidates_only_include_standalone_cli(
    tmp_path: Path,
) -> None:
    candidates = default_install_candidates(
        tmp_path,
        platform_name="darwin",
        environ={},
    )

    assert candidates == (
        (tmp_path / ".local" / "bin" / "codex", "standalone"),
    )


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
        sdk_candidate=tmp_path / "missing.exe",
        install_candidates=candidates,
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
        sdk_candidate=tmp_path / "missing",
        install_candidates=candidates,
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
        sdk_candidate=tmp_path / "missing-sdk" / "codex",
        install_candidates=[(fallback, "standalone")],
    )

    assert resolution is None
