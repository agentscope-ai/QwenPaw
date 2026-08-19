# -*- coding: utf-8 -*-
"""Resolve QwenPaw-Data package assets without machine coupling."""

from __future__ import annotations

import os
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path


PLUGIN_DIR = Path(__file__).resolve().parent.parent
DEV_DIR = PLUGIN_DIR / ".datapaw-dev"


def context_python() -> Path:
    configured = os.getenv("DATAPAW_CONTEXT_PYTHON", "").strip()
    if configured:
        # Do not resolve a venv launcher symlink to the underlying base Python;
        # doing so drops the venv's site-packages at process startup.
        return Path(configured).expanduser().absolute()
    candidates = (
        PLUGIN_DIR / ".venv-datapaw" / "bin" / "python",
        PLUGIN_DIR / ".venv-datapaw" / "Scripts" / "python.exe",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.absolute()
    return candidates[0]


def context_working_dir() -> Path | None:
    configured = os.getenv("DATAPAW_CONTEXT_CWD", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    source = DEV_DIR / "source"
    return source.resolve() if source.exists() else None


def skills_root() -> Path | None:
    configured = os.getenv("DATAPAW_SKILLS_DIR", "").strip()
    if configured:
        path = Path(configured).expanduser().resolve()
        return path if path.is_dir() else None
    development = DEV_DIR / "skills"
    if development.is_dir():
        return development.resolve()
    try:
        package = distribution("datapaw-skills")
    except PackageNotFoundError:
        return None
    installed = Path(package.locate_file("datapaw_skills/skills"))
    return installed.resolve() if installed.is_dir() else None


def skill_layers(root: Path) -> list[Path]:
    """Return category directories containing immediate skill children."""
    layers: list[Path] = []
    for candidate in sorted(root.iterdir()):
        if not candidate.is_dir():
            continue
        if any(
            (child / "SKILL.md").is_file() for child in candidate.iterdir()
        ):
            layers.append(candidate)
    return layers
