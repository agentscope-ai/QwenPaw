# -*- coding: utf-8 -*-
"""LSP server specs + discovery chain.

Each supported language has a :class:`LspServerSpec` whose ``discover``
callable returns the argv used to spawn the language server, or
``None`` if no server is reachable.

The Python entry has a guaranteed bundled fallback
(``python -m pylsp``) so it is always available once
``python-lsp-server[all]`` is a hard dependency of QwenPaw.  All other
languages return ``None`` when the user has not installed a server —
the Coding Mode toolkit then simply omits them from the ``lsp`` tool's
description (no popups, no auto-downloads — see PROPOSAL §三).
"""
from __future__ import annotations

import importlib.util
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional


@dataclass(frozen=True)
class LspServerSpec:
    """Static metadata + discovery callable for one language."""

    id: str
    display_name: str
    extensions: tuple[str, ...]
    root_markers: tuple[str, ...]
    discover: Callable[[Path], Optional[list[str]]]


# ---------------------------------------------------------------------
# Discovery callables
# ---------------------------------------------------------------------


def _module_importable(name: str) -> bool:
    """True when ``import {name}`` would succeed without actually importing."""
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _discover_python(_project_dir: Path) -> Optional[list[str]]:
    """Pyright → user-installed pylsp → bundled ``python -m pylsp``."""
    pyright = shutil.which("pyright-langserver")
    if pyright:
        return [pyright, "--stdio"]
    pylsp = shutil.which("pylsp")
    if pylsp:
        return [pylsp]
    if _module_importable("pylsp"):
        # Bundled fallback — guaranteed to work because pylsp is a
        # hard dep of QwenPaw.  Going via ``sys.executable -m`` is the
        # cross-platform way (avoids the ``pylsp.exe`` shim on Windows
        # which may not be on ``PATH`` inside conda envs).
        return [sys.executable, "-m", "pylsp"]
    return None


def _discover_typescript(project_dir: Path) -> Optional[list[str]]:
    """Global typescript-language-server → project-local node_modules."""
    binary = shutil.which("typescript-language-server")
    if binary:
        return [binary, "--stdio"]
    suffix = ".cmd" if sys.platform == "win32" else ""
    local = (
        project_dir
        / "node_modules"
        / ".bin"
        / f"typescript-language-server{suffix}"
    )
    if local.exists():
        return [str(local), "--stdio"]
    return None


# ---------------------------------------------------------------------
# Spec registry
# ---------------------------------------------------------------------


PYTHON_SPEC = LspServerSpec(
    id="python",
    display_name="Python",
    extensions=(".py", ".pyi"),
    root_markers=(
        "pyproject.toml",
        "setup.py",
        "setup.cfg",
        "requirements.txt",
        "Pipfile",
    ),
    discover=_discover_python,
)

TYPESCRIPT_SPEC = LspServerSpec(
    id="typescript",
    display_name="TypeScript",
    extensions=(".ts", ".tsx", ".mts", ".cts"),
    root_markers=("tsconfig.json", "package.json"),
    discover=_discover_typescript,
)

JAVASCRIPT_SPEC = LspServerSpec(
    id="javascript",
    display_name="JavaScript",
    extensions=(".js", ".jsx", ".mjs", ".cjs"),
    root_markers=("package.json", "jsconfig.json"),
    discover=_discover_typescript,  # same server handles JS
)

LSP_SERVERS: dict[str, LspServerSpec] = {
    PYTHON_SPEC.id: PYTHON_SPEC,
    TYPESCRIPT_SPEC.id: TYPESCRIPT_SPEC,
    JAVASCRIPT_SPEC.id: JAVASCRIPT_SPEC,
}


# ---------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------


def detect_available_lsp_languages(
    project_dir: Path,
) -> dict[str, list[str]]:
    """Return ``{language_id: argv}`` for every reachable server.

    Languages whose ``discover`` returns ``None`` are absent from the
    result.  Used at toolkit creation time to decide which languages
    to advertise in the ``lsp`` tool description.
    """
    available: dict[str, list[str]] = {}
    for spec in LSP_SERVERS.values():
        cmd = spec.discover(project_dir)
        if cmd is not None:
            available[spec.id] = cmd
    return available


def language_for_file(file_path: Path) -> Optional[str]:
    """Map a file path to a language id by extension, or ``None``."""
    suffix = file_path.suffix.lower()
    for spec in LSP_SERVERS.values():
        if suffix in spec.extensions:
            return spec.id
    return None


def display_name(language_id: str) -> str:
    """Pretty display name (falls back to the raw id)."""
    spec = LSP_SERVERS.get(language_id)
    return spec.display_name if spec else language_id
