# -*- coding: utf-8 -*-
"""Locate Codex executables, including ChatGPT editor extensions."""

from __future__ import annotations

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


def default_extension_roots(home: Path | None = None) -> tuple[Path, ...]:
    """Return known editor extension roots on every supported platform."""
    user_home = home or Path.home()
    return (
        user_home / ".vscode" / "extensions",
        user_home / ".vscode-insiders" / "extensions",
        user_home / ".cursor" / "extensions",
        user_home / ".vscode-oss" / "extensions",
    )


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
    candidates: list[tuple[Path, str]] = [
        (user_home / ".local" / "bin" / "codex", "standalone"),
    ]
    if platform_value == "darwin":
        candidates.extend(
            [
                (
                    Path(
                        "/Applications/ChatGPT.app/Contents/"
                        "Resources/codex",
                    ),
                    "chatgpt-app",
                ),
                (
                    user_home
                    / "Applications"
                    / "ChatGPT.app"
                    / "Contents"
                    / "Resources"
                    / "codex",
                    "chatgpt-app",
                ),
            ],
        )
    return tuple(candidates)


def resolve_codex_binary(
    binary: str | None = None,
    *,
    extension_roots: Iterable[Path] | None = None,
    install_candidates: Iterable[tuple[Path, str]] | None = None,
    platform_name: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> Path | None:
    """Resolve a configured, PATH, or ChatGPT-extension Codex binary."""
    resolution = resolve_codex_binary_info(
        binary,
        extension_roots=extension_roots,
        install_candidates=install_candidates,
        platform_name=platform_name,
        environ=environ,
    )
    return resolution.path if resolution is not None else None


def resolve_codex_binary_info(
    binary: str | None = None,
    *,
    extension_roots: Iterable[Path] | None = None,
    install_candidates: Iterable[tuple[Path, str]] | None = None,
    platform_name: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> CodexBinaryResolution | None:
    """Resolve Codex and retain the discovery source for diagnostics."""
    environment = environ if environ is not None else os.environ
    configured = binary
    if configured:
        resolved = _resolve_configured(configured)
        if resolved is not None or configured != "codex":
            return (
                CodexBinaryResolution(resolved, "configured")
                if resolved is not None
                else None
            )

    environment_binary = environment.get("CODEX_BINARY")
    if environment_binary:
        resolved = _resolve_configured(environment_binary)
        if resolved is not None or environment_binary != "codex":
            return (
                CodexBinaryResolution(resolved, "environment")
                if resolved is not None
                else None
            )

    on_path = shutil.which("codex")
    if on_path:
        return CodexBinaryResolution(Path(on_path).resolve(), "path")

    candidates = (
        install_candidates
        if install_candidates is not None
        else default_install_candidates(
            platform_name=platform_name,
            environ=environment,
        )
    )
    for path, source in candidates:
        if _is_executable(path, platform_name=platform_name):
            return CodexBinaryResolution(path.resolve(), source)

    roots = (
        extension_roots
        if extension_roots is not None
        else default_extension_roots()
    )
    extension_candidates: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        for name in ("codex", "codex.exe"):
            extension_candidates.extend(
                path
                for path in root.glob(
                    f"openai.chatgpt-*/bin/*/{name}",
                )
                if _is_executable(path, platform_name=platform_name)
            )
    if not extension_candidates:
        return None
    path = max(extension_candidates, key=_candidate_timestamp).resolve()
    return CodexBinaryResolution(path, "editor-extension")


def _resolve_configured(binary: str) -> Path | None:
    path = Path(binary).expanduser()
    if path.is_absolute() or path.parent != Path("."):
        return path.resolve() if _is_executable(path) else None
    resolved = shutil.which(binary)
    return Path(resolved).resolve() if resolved else None


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


def _candidate_timestamp(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0


__all__ = [
    "CodexBinaryResolution",
    "default_extension_roots",
    "default_install_candidates",
    "resolve_codex_binary",
    "resolve_codex_binary_info",
]
