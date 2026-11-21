# -*- coding: utf-8 -*-
"""工作区标准目录及历史目录兼容规则。"""

from __future__ import annotations

import shutil
from pathlib import Path
from ..utils.path_safety import is_link_or_junction


ARTIFACTS_DIRECTORY = "artifacts"
LEGACY_ARTIFACTS_DIRECTORY = "产物"


def ensure_artifacts_directory(workspace_root: Path) -> Path:
    """创建英文产物目录，并无损复制历史中文目录中的缺失文件。"""
    root = Path(workspace_root)
    artifacts = root / ARTIFACTS_DIRECTORY
    if is_link_or_junction(artifacts):
        raise ValueError("workspace_symlink_denied")
    artifacts.mkdir(parents=True, exist_ok=True)

    legacy = root / LEGACY_ARTIFACTS_DIRECTORY
    if not legacy.is_dir() or is_link_or_junction(legacy):
        return artifacts

    for source in legacy.rglob("*"):
        if any(is_link_or_junction(parent) for parent in (source, *source.parents)):
            continue
        relative = source.relative_to(legacy)
        target = artifacts / relative
        if any(
            is_link_or_junction(parent)
            for parent in (target, *target.parents)
            if parent != artifacts.parent
        ):
            continue
        if source.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif source.is_file() and not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    return artifacts
