# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SOUL_GUARDIAN_SCRIPT = (
    _REPO_ROOT
    / "thirdparty"
    / "clawsec-main"
    / "clawsec-main"
    / "skills"
    / "soul-guardian"
    / "scripts"
    / "soul_guardian.py"
)


def repo_root() -> Path:
    return _REPO_ROOT


def soul_guardian_script() -> Path:
    return _SOUL_GUARDIAN_SCRIPT


def file_baseline_root(working_dir: Path) -> Path:
    return working_dir / "integrity-protection" / "file-baseline"


def integrity_protection_root(working_dir: Path) -> Path:
    return working_dir / "integrity-protection"


def frozen_agent_dir(working_dir: Path, agent_id: str) -> Path:
    return file_baseline_root(working_dir) / "frozen" / agent_id


def resolve_under_working_dir(working_dir: Path, absolute: Path) -> Path | None:
    try:
        return absolute.resolve().relative_to(working_dir.resolve())
    except ValueError:
        return None


def settings_path(working_dir: Path) -> Path:
    return file_baseline_root(working_dir) / "settings.json"


def drift_reviews_path(working_dir: Path) -> Path:
    return file_baseline_root(working_dir) / "drift_reviews.json"


def agent_state_dir(working_dir: Path, agent_id: str) -> Path:
    return file_baseline_root(working_dir) / agent_id


def agent_workspace(working_dir: Path, agent_id: str) -> Path:
    return working_dir / "workspaces" / agent_id


def normalize_relative_path(path: str) -> str:
    normalized = path.replace("\\", "/").strip().lstrip("/")
    if not normalized or ".." in normalized.split("/"):
        raise ValueError(f"Invalid protected path: {path!r}")
    return normalized


_PATH_PATTERN = re.compile(r"^[A-Za-z0-9._\-/]+$")


def workspace_relative_path(workspace_root: Path, absolute_path: Path) -> str | None:
    try:
        return absolute_path.resolve().relative_to(workspace_root.resolve()).as_posix()
    except ValueError:
        return None


def validate_protected_paths(paths: list[str]) -> list[str]:
    cleaned: list[str] = []
    for raw in paths:
        rel = normalize_relative_path(raw)
        if not _PATH_PATTERN.match(rel):
            raise ValueError(f"Invalid protected path: {raw!r}")
        cleaned.append(rel)
    return cleaned
