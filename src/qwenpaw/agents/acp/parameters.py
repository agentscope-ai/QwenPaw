# -*- coding: utf-8 -*-
"""Decode ACP inputs into native session runtime parameters."""

from dataclasses import dataclass, field, replace
from collections.abc import Mapping
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
    metadata: dict[str, Any] = field(default_factory=dict)

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
        supplied = meta.get(
            ACP_CONFIG_META_KEY,
            previous.metadata.get(ACP_CONFIG_META_KEY, {}) if previous else {},
        )
        if not isinstance(supplied, dict):
            raise ValueError("Configuration overrides must be an object")
        metadata = {ACP_CONFIG_META_KEY: merge_overrides({}, supplied)}
        project_keys = {"project_dir", "project_dirs"}
        if resume and previous:
            for key in (ACP_PROJECT_DIR_META_KEY, ACP_EPHEMERAL_META_KEY):
                if key in previous.metadata:
                    metadata[key] = previous.metadata[key]
            if ACP_CONFIG_META_KEY in meta:
                if project_keys.intersection(supplied):
                    metadata.pop(ACP_PROJECT_DIR_META_KEY, None)
                if "session_persistence" in supplied:
                    metadata.pop(ACP_EPHEMERAL_META_KEY, None)

        explicit_project = meta.get(ACP_PROJECT_DIR_META_KEY)
        if isinstance(explicit_project, str) and explicit_project.strip():
            metadata[ACP_PROJECT_DIR_META_KEY] = explicit_project
        elif explicit_project is not None and not (resume and previous):
            metadata[ACP_PROJECT_DIR_META_KEY] = None
        if (
            ACP_PROJECT_DIR_META_KEY not in metadata
            and not project_keys.intersection(supplied)
            and not project_keys.intersection(self.defaults)
        ):
            metadata[ACP_PROJECT_DIR_META_KEY] = cwd
        if meta.get(ACP_EPHEMERAL_META_KEY) is True:
            metadata[ACP_EPHEMERAL_META_KEY] = True

        transport: dict[str, Any] = {}
        project = metadata.get(ACP_PROJECT_DIR_META_KEY)
        if project is not None:
            transport["project_dir"] = project
        if metadata.get(ACP_EPHEMERAL_META_KEY) is True:
            transport["session_persistence"] = False
        overrides = merge_overrides(supplied, transport)
        selected_mode = overrides.get("agent_mode", self.config.agent_mode)
        return replace(
            self,
            cwd=cwd,
            metadata=metadata,
            overrides=overrides,
            restored_mode=(
                previous.config.agent_mode if previous else selected_mode
            )
            if resume or restored
            else None,
        )

    def with_overrides(self, values: Mapping) -> Self:
        """Preserve standard ACP setters when a session is resumed."""
        result = super().with_overrides(values)
        supplied = self.metadata.get(ACP_CONFIG_META_KEY, {})
        metadata = merge_overrides(self.metadata, {})
        metadata[ACP_CONFIG_META_KEY] = merge_overrides(supplied, values)
        return replace(result, metadata=metadata)

    def with_permission_mode(self, mode: str) -> Self:
        """Translate the permission selector to a session setting."""
        if mode not in {MODE_DEFAULT, MODE_BYPASS}:
            raise ValueError(f"Invalid permission mode: {mode!r}")
        level = "OFF" if mode == MODE_BYPASS else self.base.approval_level
        return self.with_overrides({"approval_level": level})
