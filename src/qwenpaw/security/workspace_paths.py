# -*- coding: utf-8 -*-
"""Shared guard for agent workspace locations.

Several entry points let a user choose where an agent workspace lives
(HTTP ``create_agent``, the ``qwenpaw agents create`` CLI, and backup
restore).  Custom locations are an intended feature, so the guard does not
restrict *where* a workspace may go; it only blocks directories the server
auto-loads code from or that hold credentials, because placing a workspace
there turns "write files" into code execution or secret tampering:

* ``custom_channels`` – modules here are imported on agent reload.
* ``plugins`` – plugin packages here are discovered and executed.
* ``SECRET_DIR`` – holds credentials and the master key.

Constants are read lazily on each call so tests (and runtime overrides of
``WORKING_DIR``) are honoured.
"""
from __future__ import annotations

from pathlib import Path


def _resolve_path(p: Path) -> Path:
    """Resolve *p* even when it does not exist yet.

    Falls back to the absolute path when ``resolve()`` fails.
    """
    try:
        return p.resolve()
    except OSError:
        return p.absolute()


def _is_within(child: Path, parent: Path) -> bool:
    """Return True when *child* is *parent* itself or nested under it."""
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def reserved_workspace_roots() -> tuple[Path, ...]:
    """Return resolved directories a workspace must never be placed in."""
    from .. import constant

    return (
        _resolve_path(Path(constant.CUSTOM_CHANNELS_DIR)),
        _resolve_path(Path(constant.PLUGINS_DIR)),
        _resolve_path(Path(constant.SECRET_DIR)),
    )


def reserved_workspace_root_for(path: Path | str) -> Path | None:
    """Return the reserved root *path* conflicts with, or ``None`` if safe.

    A path conflicts with a reserved directory when it lives **inside** it (or
    is it), or is an **ancestor** of it.  The ancestor case matters because a
    workspace placed at e.g. ``WORKING_DIR`` would, on restore, receive the
    workspace's own relative files (such as a nested ``custom_channels``
    package) directly into the real reserved directory.

    The returned path is the matched reserved directory (resolved), suitable
    for inclusion in an error message.
    """
    resolved = _resolve_path(Path(path).expanduser())
    for reserved in reserved_workspace_roots():
        if _is_within(resolved, reserved) or _is_within(reserved, resolved):
            return reserved
    return None


class ReservedWorkspaceError(ValueError):
    """Raised when a workspace path targets a reserved server directory."""

    def __init__(self, path: Path, reserved: Path) -> None:
        self.path = path
        self.reserved = reserved
        super().__init__(
            f"workspace_dir '{path}' targets reserved directory "
            f"'{reserved}'. The server auto-loads code from "
            "custom_channels/plugins and stores credentials in the secrets "
            "directory; placing a workspace there is unsafe.",
        )


def assert_workspace_dir_allowed(path: Path | str) -> Path:
    """Return the resolved *path*, or raise :class:`ReservedWorkspaceError`.

    Shared entry point for the HTTP and CLI agent-creation flows so the check
    and its message live in one place.
    """
    resolved = _resolve_path(Path(path).expanduser())
    reserved = reserved_workspace_root_for(resolved)
    if reserved is not None:
        raise ReservedWorkspaceError(resolved, reserved)
    return resolved
