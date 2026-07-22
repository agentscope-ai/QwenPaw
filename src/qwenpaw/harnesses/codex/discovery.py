# -*- coding: utf-8 -*-
"""Locate Codex executables, including ChatGPT editor extensions."""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterable
from pathlib import Path


def default_extension_roots(home: Path | None = None) -> tuple[Path, ...]:
    """Return known editor extension roots on every supported platform."""
    user_home = home or Path.home()
    return (
        user_home / ".vscode" / "extensions",
        user_home / ".vscode-insiders" / "extensions",
        user_home / ".cursor" / "extensions",
        user_home / ".vscode-oss" / "extensions",
    )


def resolve_codex_binary(
    binary: str | None = None,
    *,
    extension_roots: Iterable[Path] | None = None,
) -> Path | None:
    """Resolve a configured, PATH, or ChatGPT-extension Codex binary."""
    configured = binary or os.environ.get("CODEX_BINARY")
    if configured:
        resolved = _resolve_configured(configured)
        if resolved is not None or configured != "codex":
            return resolved

    on_path = shutil.which("codex")
    if on_path:
        return Path(on_path).resolve()

    roots = extension_roots or default_extension_roots()
    candidates: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        for name in ("codex", "codex.exe"):
            candidates.extend(
                path
                for path in root.glob(
                    f"openai.chatgpt-*/bin/*/{name}",
                )
                if _is_executable(path)
            )
    if not candidates:
        return None
    return max(candidates, key=_candidate_timestamp).resolve()


def _resolve_configured(binary: str) -> Path | None:
    path = Path(binary).expanduser()
    if path.is_absolute() or path.parent != Path("."):
        return path.resolve() if _is_executable(path) else None
    resolved = shutil.which(binary)
    return Path(resolved).resolve() if resolved else None


def _is_executable(path: Path) -> bool:
    if not path.is_file():
        return False
    return os.name == "nt" or os.access(path, os.X_OK)


def _candidate_timestamp(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0


__all__ = ["default_extension_roots", "resolve_codex_binary"]
