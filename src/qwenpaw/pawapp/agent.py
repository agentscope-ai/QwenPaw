# -*- coding: utf-8 -*-
"""App-owned agent profiles for PawApps.

This module keeps QwenPaw configuration details behind the PawApp SDK.  A
consumer declares a stable agent identity; the SDK creates it idempotently,
starts it through the normal workspace manager, and detaches the profile on
uninstall without deleting conversations or artifacts.
"""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

from qwenpaw.agents.skill_system import get_workspace_skills_dir
from qwenpaw.agents.utils import (
    copy_workspace_md_files,
    normalize_agent_language,
)
from qwenpaw.config.config import (
    AgentProfileConfig,
    AgentProfileRef,
    ChannelConfig,
    HeartbeatConfig,
    MCPConfig,
    PlanConfig,
    ToolsConfig,
    load_agent_config,
    save_agent_config,
    validate_agent_id,
)
from qwenpaw.config.utils import load_config, save_config
from qwenpaw.constant import WORKING_DIR

logger = logging.getLogger(__name__)


def _normalized_agent_order(config) -> list[str]:
    ordered: list[str] = []
    for agent_id in config.agents.agent_order:
        if agent_id in config.agents.profiles and agent_id not in ordered:
            ordered.append(agent_id)
    for agent_id in config.agents.profiles:
        if agent_id not in ordered:
            ordered.append(agent_id)
    return ordered


def _write_initial_json(path: Path, payload: dict) -> None:
    if path.exists():
        return
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


@dataclass(frozen=True)
class ManagedAgentProfileSpec:
    """Declarative profile owned by one PawApp."""

    app_id: str
    agent_id: str
    name: str
    description: str = ""
    persona_dir: Path | None = None
    language: str | None = None
    plan_enabled: bool = True
    pinned: bool = True

    @property
    def template_id(self) -> str:
        return f"pawapp:{self.app_id}"


class ManagedAgentProfile:
    """Runtime handle for an app-owned QwenPaw agent profile."""

    def __init__(self, spec: ManagedAgentProfileSpec):
        if not spec.app_id.strip():
            raise ValueError("managed agent profile requires an app id")
        if not spec.agent_id.strip() or not spec.name.strip():
            raise ValueError("managed agent profile requires an id and name")
        self.spec = spec

    @property
    def workspace_dir(self) -> Path:
        return (
            Path(WORKING_DIR) / "workspaces" / self.spec.agent_id
        ).resolve()

    def ensure(self) -> bool:
        """Create the profile if absent and refresh app-owned persona files.

        Returns ``True`` when a new profile was created. Existing user model,
        channel, tool, and security settings are intentionally preserved.
        """
        config = load_config()
        agent_id = self.spec.agent_id
        expected_workspace = self.workspace_dir
        existing = config.agents.profiles.get(agent_id)
        created = existing is None

        if existing is None:
            validate_agent_id(agent_id, set(config.agents.profiles))
            expected_workspace.mkdir(parents=True, exist_ok=True)
            config.agents.profiles[agent_id] = AgentProfileRef(
                id=agent_id,
                workspace_dir=str(expected_workspace),
                enabled=True,
                pinned=self.spec.pinned,
            )
            config.agents.agent_order = _normalized_agent_order(config)
            save_config(config)
        else:
            actual_workspace = (
                Path(existing.workspace_dir).expanduser().resolve()
            )
            if actual_workspace != expected_workspace:
                raise RuntimeError(
                    f"Agent '{agent_id}' already uses a different workspace",
                )

        language = normalize_agent_language(
            self.spec.language or config.agents.language or "en",
        )
        self._ensure_workspace(expected_workspace, language)

        if created or not (expected_workspace / "agent.json").exists():
            profile = AgentProfileConfig(
                id=agent_id,
                name=self.spec.name,
                description=self.spec.description,
                workspace_dir=str(expected_workspace),
                template_id=self.spec.template_id,
                language=language,
                channels=ChannelConfig(),
                mcp=MCPConfig(),
                heartbeat=HeartbeatConfig(),
                tools=ToolsConfig(),
                plan=PlanConfig(enabled=self.spec.plan_enabled),
            )
        else:
            profile = load_agent_config(agent_id)
            if profile.template_id not in {
                self.spec.template_id,
                self.spec.agent_id,
            }:
                raise RuntimeError(
                    f"Agent '{agent_id}' exists but is not owned by PawApp "
                    f"'{self.spec.app_id}'",
                )
            profile.name = self.spec.name
            profile.description = self.spec.description
            profile.template_id = self.spec.template_id
            profile.plan.enabled = self.spec.plan_enabled
        save_agent_config(agent_id, profile)
        return created

    def detach(self) -> bool:
        """Detach an owned profile while preserving its workspace data."""
        config = load_config()
        ref = config.agents.profiles.get(self.spec.agent_id)
        if ref is None:
            return False
        try:
            profile = load_agent_config(self.spec.agent_id)
        except Exception:  # pragma: no cover - corrupted profile is not owned
            return False
        if profile.template_id != self.spec.template_id:
            return False
        config.agents.profiles.pop(self.spec.agent_id, None)
        config.agents.agent_order = _normalized_agent_order(config)
        if config.agents.active_agent == self.spec.agent_id:
            config.agents.active_agent = "default"
        save_config(config)
        return True

    def _ensure_workspace(self, workspace: Path, language: str) -> None:
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / "sessions").mkdir(exist_ok=True)
        (workspace / "memory").mkdir(exist_ok=True)
        get_workspace_skills_dir(workspace).mkdir(exist_ok=True)
        copy_workspace_md_files(language, workspace)
        (workspace / "BOOTSTRAP.md").unlink(missing_ok=True)
        _write_initial_json(
            workspace / "jobs.json",
            {"version": 1, "jobs": []},
        )
        _write_initial_json(
            workspace / "chats.json",
            {"version": 1, "chats": []},
        )

        persona_dir = self.spec.persona_dir
        if persona_dir is None:
            return
        localized = persona_dir / language
        source_dir = localized if localized.is_dir() else persona_dir
        for filename in ("SOUL.md", "PROFILE.md", "AGENTS.md"):
            source = source_dir / filename
            if source.is_file():
                shutil.copy2(source, workspace / filename)
