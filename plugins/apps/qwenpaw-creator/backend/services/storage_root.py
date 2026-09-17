# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Creator data-root configuration independent of any storage backend."""

from __future__ import annotations

import os
from pathlib import Path


CREATOR_DATA_ROOT_ENV = "CREATOR_DATA_ROOT"


class CreatorDataRootError(RuntimeError):
    """Raised when the mandatory external Creator data root is unavailable."""


def require_creator_data_root(*, create: bool = True) -> Path:
    raw = os.environ.get(CREATOR_DATA_ROOT_ENV, "").strip()
    if not raw:
        raise CreatorDataRootError(
            "CREATOR_DATA_ROOT is required; the Creator runtime has no source-tree fallback",
        )
    root = Path(raw).expanduser()
    if not root.is_absolute():
        raise CreatorDataRootError(
            "CREATOR_DATA_ROOT must be an absolute path",
        )
    root = root.resolve(strict=False)
    if root.exists() and not root.is_dir():
        raise CreatorDataRootError(
            f"CREATOR_DATA_ROOT is not a directory: {root}",
        )
    if create:
        root.mkdir(parents=True, exist_ok=True)
    return root


__all__ = [
    "CREATOR_DATA_ROOT_ENV",
    "CreatorDataRootError",
    "require_creator_data_root",
]
