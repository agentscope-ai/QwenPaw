# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .constants import DEFAULT_PILOT_TARGETS
from .paths import (
    agent_state_dir,
    agent_workspace,
    drift_reviews_path,
    file_baseline_root,
    settings_path,
    validate_protected_paths,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class FileBaselineSettings:
    enabled: bool = False
    pilot_mode: bool = True
    protected_targets: list[str] = field(default_factory=lambda: list(DEFAULT_PILOT_TARGETS))
    baseline_established: bool = False
    baseline_cleared_at: str | None = None
    agents: dict[str, dict[str, Any]] = field(default_factory=dict)
    scan_status: str | None = None
    last_scan_at: str | None = None
    last_scan_drift_count: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "pilot_mode": self.pilot_mode,
            "protected_targets": list(self.protected_targets),
            "baseline_established": self.baseline_established,
            "baseline_cleared_at": self.baseline_cleared_at,
            "agents": self.agents,
            "scan_status": self.scan_status,
            "last_scan_at": self.last_scan_at,
            "last_scan_drift_count": self.last_scan_drift_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FileBaselineSettings":
        protected = data.get("protected_targets")
        if protected is None:
            protected = list(DEFAULT_PILOT_TARGETS)
        return cls(
            enabled=bool(data.get("enabled", False)),
            pilot_mode=bool(data.get("pilot_mode", True)),
            protected_targets=list(protected),
            baseline_established=bool(data.get("baseline_established", False)),
            baseline_cleared_at=data.get("baseline_cleared_at"),
            agents=dict(data.get("agents") or {}),
            scan_status=data.get("scan_status"),
            last_scan_at=data.get("last_scan_at"),
            last_scan_drift_count=data.get("last_scan_drift_count"),
        )


class SettingsStore:
    def __init__(self, working_dir: Path) -> None:
        self.working_dir = working_dir
        self._path = settings_path(working_dir)

    def load(self) -> FileBaselineSettings:
        if not self._path.is_file():
            return FileBaselineSettings()
        data = json.loads(self._path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return FileBaselineSettings()
        return FileBaselineSettings.from_dict(data)

    def save(self, settings: FileBaselineSettings) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(settings.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp.replace(self._path)

    def effective_paths(self, settings: FileBaselineSettings, agent_id: str) -> list[str]:
        agent_cfg = settings.agents.get(agent_id) or {}
        override = agent_cfg.get("protected_targets")
        if override is not None:
            return list(override)
        return list(settings.protected_targets)

    def list_agent_ids(self) -> list[str]:
        workspaces = self.working_dir / "workspaces"
        if workspaces.is_dir():
            ids = sorted(
                path.name
                for path in workspaces.iterdir()
                if path.is_dir()
            )
            if ids:
                return ids
        return ["default"]

    def resolve_workspace(self, agent_id: str) -> Path:
        workspace = agent_workspace(self.working_dir, agent_id)
        if workspace.is_dir():
            return workspace
        if agent_id == "default" and self.working_dir.is_dir():
            return self.working_dir
        workspace.mkdir(parents=True, exist_ok=True)
        return workspace

    def delete_runtime_state(self) -> None:
        root = file_baseline_root(self.working_dir)
        if not root.is_dir():
            return
        for child in root.iterdir():
            if child.name in {"settings.json", "drift_reviews.json"}:
                continue
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
        drift_path = drift_reviews_path(self.working_dir)
        if drift_path.is_file():
            drift_path.unlink()

    def ensure_protected_files(
        self,
        workspace: Path,
        paths: list[str],
    ) -> None:
        for rel in paths:
            target = workspace / rel
            if target.is_file():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                f"# Persona baseline placeholder for {rel}\n",
                encoding="utf-8",
            )

    def update_protected_targets(
        self,
        settings: FileBaselineSettings,
        paths: list[str],
    ) -> FileBaselineSettings:
        settings.protected_targets = validate_protected_paths(paths)
        return settings

    def agent_state(self, agent_id: str) -> Path:
        return agent_state_dir(self.working_dir, agent_id)
