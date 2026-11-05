# -*- coding: utf-8 -*-
"""Decode ACP inputs into native session runtime parameters."""

from dataclasses import dataclass, field, replace
from typing import Any, Self

from ...config.overrides import merge_overrides
from ...config.runtime import RuntimeParameters
from .meta import (
    ACP_CONFIG_META_KEY,
    ACP_EPHEMERAL_META_KEY,
    ACP_PROJECT_DIR_META_KEY,
)

MODE_DEFAULT = "default"
MODE_BYPASS = "bypassPermissions"


@dataclass(frozen=True, kw_only=True)
class ACPRuntimeParameters(RuntimeParameters):
    """Translate wire inputs without maintaining another config schema."""

    cwd: str = ""
    supplied: dict[str, Any] = field(default_factory=dict)

    @property
    def mode(self) -> str:
        """Expose the effective guard policy through ACP's mode selector."""
        return (
            MODE_BYPASS
            if self.config.approval_level.upper() == "OFF"
            else MODE_DEFAULT
        )

    def for_session(
        self,
        cwd: str,
        meta: dict[str, Any],
        *,
        previous: Self | None = None,
        resume: bool = False,
        restored: bool = False,
    ) -> Self:
        """Normalize legacy metadata before the common merge and validation."""
        overrides = meta.get(
            ACP_CONFIG_META_KEY,
            previous.supplied if previous else {},
        )
        if not isinstance(overrides, dict):
            raise ValueError("Configuration overrides must be an object")
        overrides = merge_overrides({}, overrides)
        transport: dict[str, Any] = {}
        project_keys = {"project_dir", "project_dirs"}
        has_project = bool(project_keys.intersection(overrides))
        if (
            resume
            and previous
            and not (ACP_CONFIG_META_KEY in meta and has_project)
        ):
            transport.update(
                project_dir=previous.config.project_dir,
                project_dirs=previous.config.project_dirs,
            )
        elif not has_project and not project_keys.intersection(self.defaults):
            transport["project_dir"] = cwd
        explicit_project = meta.get(ACP_PROJECT_DIR_META_KEY)
        if isinstance(explicit_project, str) and explicit_project.strip():
            transport["project_dir"] = explicit_project
            transport.pop("project_dirs", None)
        elif explicit_project is not None and not (resume and previous):
            transport.pop("project_dir", None)

        if resume and previous and "session_persistence" not in overrides:
            transport[
                "session_persistence"
            ] = previous.config.session_persistence
        if meta.get(ACP_EPHEMERAL_META_KEY) is True:
            transport["session_persistence"] = False

        merged = merge_overrides(overrides, transport)
        return replace(
            self,
            cwd=cwd,
            supplied=overrides,
            overrides=merged,
            start_mode=not (resume or restored),
        )

    def with_overrides(self, values, *, reset: bool = False) -> Self:
        """Preserve standard ACP setters when a session is resumed."""
        result = super().with_overrides(values, reset=reset)
        return replace(
            result,
            supplied=merge_overrides({} if reset else self.supplied, values),
        )

    def with_permission_mode(self, mode: str) -> Self:
        """Translate the permission selector to a session setting."""
        if mode not in {MODE_DEFAULT, MODE_BYPASS}:
            raise ValueError(f"Invalid permission mode: {mode!r}")
        level = "OFF" if mode == MODE_BYPASS else self.base.approval_level
        return self.with_overrides({"approval_level": level})
