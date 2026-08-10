# -*- coding: utf-8 -*-
"""Cross-platform durability helpers for private Creator files."""

from __future__ import annotations

import os
from pathlib import Path


def set_descriptor_mode(descriptor: int, mode: int) -> None:
    """Apply a POSIX descriptor mode when the platform provides it."""

    fchmod = getattr(os, "fchmod", None)
    if fchmod is not None:
        fchmod(descriptor, mode)


def fsync_directory(path: str | os.PathLike[str]) -> None:
    """Persist directory-entry changes where directory handles are usable."""

    if os.name == "nt":
        return

    directory = Path(path)
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    descriptor = os.open(directory, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
