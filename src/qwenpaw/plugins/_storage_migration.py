# -*- coding: utf-8 -*-
"""Host-validated legacy namespaces and atomic, non-overwriting copies."""

import os
from pathlib import Path
import shutil
import stat
import tempfile

from .errors import SDKError, SDKCompatibilityError

# These directories belong to the host, even if a plugin chooses that ID.
_RESERVED = frozenset(
    {
        "secrets",
        "plugins",
        "plugin-data",
        "workspaces",
        "agents",
        "media",
        "sessions",
        "skills",
        "active_skills",
        "customized_skills",
        "memory",
        "logs",
        "backups",
        "certs",
        "config",
        "models",
        "uploads",
        "downloads",
    },
)


def validate_sources(declaration, plugin_id):
    sources = declaration.get("legacy_storage", {})
    if not isinstance(sources, dict):
        raise SDKCompatibilityError(
            "sdk.legacy_storage must map names to relative paths",
        )
    for name, value in sources.items():
        if not isinstance(name, str) or not name or not isinstance(value, str):
            raise SDKCompatibilityError(
                "Legacy storage names and paths must be nonempty strings",
            )
        path = Path(value)
        if (
            not path.parts
            or path.is_absolute()
            or ".." in path.parts
            or "\\" in value
            or path.parts[0] != plugin_id
            or path.parts[0].lower() in _RESERVED
        ):
            raise SDKCompatibilityError(
                "Legacy source must stay in this plugin's old namespace",
            )
    return sources


def declared_source(sources, name):
    if name not in sources:
        raise SDKError(f"Undeclared legacy storage source: {name}")
    path = sources[name]
    for part in (path, *path.parents):
        if part.is_symlink():
            raise SDKError("Legacy source path cannot traverse symlinks")
    return path


def copy_missing(source, target, guard):
    flags = (
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    fd = os.open(source, flags)
    temporary = None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise SDKError("Legacy storage source must be a regular file")
        with os.fdopen(fd, "rb") as original:
            fd = None
            if target.exists():
                return False
            handle, temporary = tempfile.mkstemp(dir=target.parent)
            with os.fdopen(handle, "wb") as output:
                shutil.copyfileobj(original, output)
                output.flush()
                os.fsync(output.fileno())
            guard()
            try:
                # Unlike replace(), link() atomically refuses an existing
                # destination even when two migration calls race.
                os.link(temporary, target)
            except FileExistsError:
                return False
        return True
    finally:
        if fd is not None:
            os.close(fd)
        if temporary is not None:
            os.unlink(temporary)
