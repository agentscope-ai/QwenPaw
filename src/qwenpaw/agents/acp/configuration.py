# -*- coding: utf-8 -*-
"""Translate ACP configuration inputs into ordinary agent configuration."""

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from ...config.config import AgentProfileConfig, ModelSlotConfig
from ...config.overrides import apply_config_overrides, merge_overrides
from ...constant import WORKING_DIR
from .meta import (
    ACP_CONFIG_META_KEY,
    ACP_EPHEMERAL_META_KEY,
    ACP_PROJECT_DIR_META_KEY,
)


MODE_DEFAULT = "default"
MODE_BYPASS = "bypassPermissions"


# These resources are constructed once by Workspace, shared by its sessions.
_SHARED_RESOURCE_PATHS = (
    "workspace_dir",
    "backend",
    "channels",
    "mcp",
    "heartbeat",
    "mail",
    "language",
    "acp",
    "running.llm_max_concurrent",
    "running.llm_max_qpm",
    "running.llm_rate_limit_pause",
    "running.llm_rate_limit_jitter",
    "running.memory_manager_backend",
    "running.memory_backend_configs",
    "running.reme_light_memory_config",
    "running.daily_memory_dir",
    "running.light_context_config.strategy",
    "running.light_context_config.scroll_config",
    "running.loop.goal",
    "running.loop.mission",
    "running.loop.custom_modes",
)


def _validate_session_config(
    base: AgentProfileConfig,
    candidate: AgentProfileConfig,
) -> None:
    """Reject changes to resources already owned by the shared workspace."""
    for path in _SHARED_RESOURCE_PATHS:
        before, after = base, candidate
        for name in path.split("."):
            before, after = getattr(before, name), getattr(after, name)
        if before != after:
            raise ValueError(
                f"{path} requires an ACP restart; set it with --config",
            )


@dataclass(frozen=True)
class ACPSession:
    """Protocol state and the single effective configuration of a session."""

    cwd: str
    config: AgentProfileConfig
    overrides: dict[str, Any]

    @property
    def mode(self) -> str:
        """Expose the effective guard policy through ACP's mode selector."""
        return (
            MODE_BYPASS
            if self.config.approval_level.upper() == "OFF"
            else MODE_DEFAULT
        )


def _apply_overrides(
    profile: AgentProfileConfig,
    overrides: dict[str, Any],
) -> AgentProfileConfig:
    """Resolve ACP's single-directory input into the canonical root list."""
    config = apply_config_overrides(profile, overrides)
    if "project_dir" in overrides and config.project_dir:
        directory = config.project_dir
        config = apply_config_overrides(
            config,
            {
                "project_dirs": [
                    {"path": directory},
                    *(
                        item
                        for item in config.project_dirs
                        if item.get("path") != directory
                    ),
                ],
            },
        )
    return config


class ACPConfiguration:
    """Own startup defaults and normalize every session configuration input."""

    def __init__(
        self,
        profile: AgentProfileConfig,
        overrides: dict[str, Any],
        *,
        workspace_dir: Path | None = None,
        agent_mode: str | None = None,
        goal_token_budget: int | None = None,
        runtime_model: ModelSlotConfig | None = None,
    ) -> None:
        startup: dict[str, Any] = {
            "workspace_dir": (
                str(workspace_dir)
                if workspace_dir is not None
                else overrides.get("workspace_dir")
                or str(WORKING_DIR / "workspaces" / profile.id)
            ),
        }
        if agent_mode == "code":
            startup["coding_mode"] = {"enabled": True}
        if goal_token_budget is not None:
            startup["running"] = {
                "loop": {"goal": {"max_tokens": goal_token_budget}},
            }
        if runtime_model is not None:
            if profile.active_model != runtime_model:
                profile = apply_config_overrides(
                    profile,
                    {
                        "thinking_level": "inherit",
                        "thinking_budget": None,
                    },
                )
            startup.update(
                active_model=runtime_model.model_dump(),
                session_persistence=False,
                fallback_policy={"enabled": False},
            )
        self.overrides = merge_overrides(overrides, startup)
        self.base = _apply_overrides(profile, self.overrides)

    def resolve(
        self,
        cwd: str,
        meta: dict[str, Any],
        *,
        previous: ACPSession | None = None,
        resume: bool = False,
    ) -> ACPSession:
        """Normalize legacy metadata before the common merge and validation."""
        overrides = meta.get(
            ACP_CONFIG_META_KEY,
            previous.overrides if previous else {},
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
        elif not has_project and not project_keys.intersection(self.overrides):
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
        config = self._apply(self.base, merged)
        return ACPSession(cwd, config, overrides)

    def update(
        self,
        session: ACPSession,
        overrides: dict[str, Any],
    ) -> ACPSession:
        """Replace the snapshot atomically, including standard ACP setters."""
        return replace(
            session,
            config=self._apply(session.config, overrides),
            overrides=merge_overrides(session.overrides, overrides),
        )

    def set_mode(self, session: ACPSession, mode: str) -> ACPSession:
        """Translate the ACP permission selector to the native guard policy."""
        if mode not in {MODE_DEFAULT, MODE_BYPASS}:
            raise ValueError(f"Invalid permission mode: {mode!r}")
        approval_level = (
            "OFF" if mode == MODE_BYPASS else self.base.approval_level
        )
        return self.update(session, {"approval_level": approval_level})

    def _apply(
        self,
        base: AgentProfileConfig,
        overrides: dict[str, Any],
    ) -> AgentProfileConfig:
        config = _apply_overrides(base, overrides)
        _validate_session_config(self.base, config)
        return config
