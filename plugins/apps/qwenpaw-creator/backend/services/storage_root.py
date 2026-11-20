# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Creator data-root configuration independent of any storage backend."""

from __future__ import annotations

import os
from pathlib import Path


CREATOR_DATA_ROOT_ENV = "CREATOR_DATA_ROOT"


class CreatorDataRootError(RuntimeError):
    """Raised when the mandatory external Creator data root is unavailable."""


def member_partition() -> tuple[str, str] | None:
    try:
        from qwenpaw.plugins.http_scope import runtime_plugin_scope
    except ModuleNotFoundError as exc:
        if exc.name != "qwenpaw":
            raise
        return None
    scope = runtime_plugin_scope()
    return scope.storage_parts if scope else None


def require_creator_data_root(
    *, create: bool = True, installation: bool = False
) -> Path:
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
    partition = None if installation else member_partition()
    if partition:
        root = root.joinpath("members", *partition)
    # Project transaction and staging filenames can exceed MAX_PATH even when
    # a standalone application's configured root is moderately short.
    if not installation and os.name == "nt" and not str(root).startswith("\\\\?\\"):
        local = str(root)
        root = Path(
            "\\\\?\\UNC\\" + local[2:]
            if local.startswith("\\\\")
            else "\\\\?\\" + local
        )
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
