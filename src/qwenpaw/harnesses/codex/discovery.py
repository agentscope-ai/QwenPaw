# -*- coding: utf-8 -*-
"""Locate standalone Codex CLI executables."""

from __future__ import annotations

import importlib
import os
import shutil
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class CodexBinaryResolution:
    """One resolved Codex executable and how it was discovered."""

    path: Path
    source: str


def bundled_cli_candidate() -> Path | None:
    """Return the CLI runtime distributed by the official Python SDK."""
    try:
        module = importlib.import_module("codex_cli_bin")
        bundled_codex_path = module.bundled_codex_path
        return Path(bundled_codex_path())
    except (AttributeError, ImportError, FileNotFoundError):
        return None


def default_install_candidates(
    home: Path | None = None,
    *,
    platform_name: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> tuple[tuple[Path, str], ...]:
    """Return known Codex install locations for one platform."""
    user_home = home or Path.home()
    platform_value = platform_name or sys.platform
    environment = environ if environ is not None else os.environ
    if platform_value == "win32":
        local_app_data = environment.get("LOCALAPPDATA")
        install_root = (
            Path(local_app_data)
            if local_app_data
            else user_home / "AppData" / "Local"
        )
        return (
            (
                install_root
                / "Programs"
                / "OpenAI"
                / "Codex"
                / "bin"
                / "codex.exe",
                "standalone",
            ),
        )
    return ((user_home / ".local" / "bin" / "codex", "standalone"),)


def resolve_codex_binary(
    binary: str | None = None,
    *,
    sdk_candidate: Path | None = None,
    install_candidates: Iterable[tuple[Path, str]] | None = None,
    platform_name: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> Path | None:
    """Resolve a configured, PATH, or standalone Codex CLI binary."""
    resolution = resolve_codex_binary_info(
        binary,
        sdk_candidate=sdk_candidate,
        install_candidates=install_candidates,
        platform_name=platform_name,
        environ=environ,
    )
    return resolution.path if resolution is not None else None


def resolve_codex_binary_info(
    binary: str | None = None,
    *,
    sdk_candidate: Path | None = None,
    install_candidates: Iterable[tuple[Path, str]] | None = None,
    platform_name: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> CodexBinaryResolution | None:
    """Resolve Codex and retain the discovery source for diagnostics."""
    environment = environ if environ is not None else os.environ
    configured = binary
    if configured:
        resolved = _resolve_configured(configured, platform_name=platform_name)
        if resolved is not None or configured != "codex":
            return (
                CodexBinaryResolution(resolved, "configured")
                if resolved is not None
                else None
            )

    environment_binary = environment.get("CODEX_BINARY")
    if environment_binary:
        resolved = _resolve_configured(
            environment_binary,
            platform_name=platform_name,
        )
        if resolved is not None or environment_binary != "codex":
            return (
                CodexBinaryResolution(resolved, "environment")
                if resolved is not None
                else None
            )

    bundled = sdk_candidate
    if bundled is None:
        bundled = bundled_cli_candidate()
    if bundled is not None and _is_executable(
        bundled,
        platform_name=platform_name,
    ):
        return CodexBinaryResolution(bundled.resolve(), "python-sdk")

    on_path = shutil.which("codex")
    if on_path:
        resolved = Path(on_path).resolve()
        if not _is_embedded_runtime(resolved):
            return CodexBinaryResolution(resolved, "path")

    candidates = (
        install_candidates
        if install_candidates is not None
        else default_install_candidates(
            platform_name=platform_name,
            environ=environment,
        )
    )
    for path, source in candidates:
        resolved = path.resolve()
        if _is_executable(
            path,
            platform_name=platform_name,
        ) and not _is_embedded_runtime(resolved):
            return CodexBinaryResolution(resolved, source)
    return None


def _resolve_configured(
    binary: str,
    *,
    platform_name: str | None = None,
) -> Path | None:
    path = Path(binary).expanduser()
    if path.is_absolute() or path.parent != Path("."):
        resolved = path.resolve()
        if not _is_executable(path, platform_name=platform_name):
            return None
        return None if _is_embedded_runtime(resolved) else resolved
    on_path = shutil.which(binary)
    if not on_path:
        return None
    path = Path(on_path).resolve()
    return None if _is_embedded_runtime(path) else path


def _is_executable(
    path: Path,
    *,
    platform_name: str | None = None,
) -> bool:
    if not path.is_file():
        return False
    return (platform_name or sys.platform) == "win32" or os.access(
        path,
        os.X_OK,
    )


def _is_embedded_runtime(path: Path) -> bool:
    """Return whether a path belongs to an app or editor extension."""
    parts = path.parts
    if any(part.startswith("openai.chatgpt-") for part in parts):
        return True
    return any(part.endswith(".app") for part in parts)


__all__ = [
    "CodexBinaryResolution",
    "bundled_cli_candidate",
    "default_install_candidates",
    "resolve_codex_binary",
    "resolve_codex_binary_info",
]
