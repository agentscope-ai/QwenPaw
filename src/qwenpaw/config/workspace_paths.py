# -*- coding: utf-8 -*-
"""Validation helpers for agent workspace paths."""
from __future__ import annotations

from pathlib import Path

from ..constant import (
    BACKUP_DIR,
    CUSTOM_CHANNELS_DIR,
    PLUGINS_DIR,
    SECRET_DIR,
    WORKING_DIR,
)


class WorkspacePathValidationError(ValueError):
    """Raised when an agent workspace path targets an unsafe location."""

    def __init__(
        self,
        message: str,
        *,
        path: Path,
        protected_name: str | None = None,
        protected_dir: Path | None = None,
    ) -> None:
        self.path = str(path)
        self.protected_name = protected_name
        self.protected_dir = str(protected_dir) if protected_dir else None
        details: dict[str, str] = {"path": self.path}
        if protected_name is not None:
            details["protected_name"] = protected_name
        if protected_dir is not None:
            details["protected_dir"] = str(protected_dir)
        self.details = details
        super().__init__(message)


def resolve_workspace_path(path: Path | str) -> Path:
    """Return an absolute, expanded workspace path for validation."""
    expanded = Path(path).expanduser()
    try:
        return expanded.resolve()
    except OSError:
        return expanded.absolute()


def _is_same_or_child(path: Path, parent: Path) -> bool:
    return path == parent or path.is_relative_to(parent)


def _protected_agent_workspace_dirs() -> tuple[tuple[str, Path], ...]:
    return (
        ("custom_channels", CUSTOM_CHANNELS_DIR),
        ("plugins", PLUGINS_DIR),
        ("secrets", SECRET_DIR),
        ("backups", BACKUP_DIR),
        ("skill_pool", WORKING_DIR / "skill_pool"),
    )


def validate_agent_workspace_path(path: Path | str) -> Path:
    """Validate and return a resolved agent workspace path.

    Agent workspaces may live outside ``WORKING_DIR/workspaces`` when users
    choose a custom location, but they must not overlap with directories that
    QwenPaw treats as executable extension roots or app-managed storage.
    """
    resolved = resolve_workspace_path(path)
    resolved_working_dir = resolve_workspace_path(WORKING_DIR)
    if resolved == resolved_working_dir:
        raise WorkspacePathValidationError(
            "Agent workspace cannot be the QwenPaw working directory itself. "
            "Choose a dedicated agent workspace directory.",
            path=resolved,
            protected_name="working_dir",
            protected_dir=resolved_working_dir,
        )

    for name, protected_dir in _protected_agent_workspace_dirs():
        resolved_protected = resolve_workspace_path(protected_dir)
        if _is_same_or_child(resolved, resolved_protected):
            raise WorkspacePathValidationError(
                f"Agent workspace cannot be inside QwenPaw {name} "
                f"directory: {resolved_protected}. Choose a dedicated "
                "agent workspace directory.",
                path=resolved,
                protected_name=name,
                protected_dir=resolved_protected,
            )

    return resolved
