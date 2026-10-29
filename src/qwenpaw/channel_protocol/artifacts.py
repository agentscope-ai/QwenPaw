# -*- coding: utf-8 -*-
"""Source revision hashing for current Channel descriptions."""

from __future__ import annotations

from collections.abc import Collection
import hashlib
from pathlib import Path

from .errors import ArtifactValidationError


def _error(message: str, *path: str | int) -> ArtifactValidationError:
    return ArtifactValidationError(message, path=path)


def code_root_digest(
    code_root: Path,
    *,
    ignored_paths: Collection[str] = (),
) -> str:
    """Hash a Channel code root using the bootstrap source algorithm."""
    root = Path(code_root).resolve()
    if not root.is_dir():
        raise _error("code_root must be a directory", "code_root")
    digest = hashlib.sha256()
    files: list[Path] = []
    for path in root.rglob("*"):
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        if path.is_symlink():
            raise _error("code_root cannot contain symlinks", "code_root")
        if path.relative_to(root).as_posix() in ignored_paths:
            continue
        if path.is_file():
            files.append(path)
    for path in sorted(
        files,
        key=lambda item: item.relative_to(root).as_posix(),
    ):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        content = path.read_bytes()
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()
