# -*- coding: utf-8 -*-
"""TeamManager: file-based team lifecycle management.

Stores team configs under {workspaces_dir}/shared/teams/{team_name}/config.json
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class TeammateSpec(BaseModel):
    agent_id: str
    role: str = ""


class TeamConfig(BaseModel):
    name: str
    lead_agent_id: str
    teammates: list[TeammateSpec] = Field(default_factory=list)
    status: str = "active"  # active | completed | disbanded
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)


class TeamManager:
    """File-based team manager.

    Storage layout:
        {workspaces_dir}/shared/teams/{team_name}/config.json
    """

    def __init__(self, workspaces_dir: Path):
        self._teams_root = workspaces_dir / "shared" / "teams"
        self._teams_root.mkdir(parents=True, exist_ok=True)

    def _config_path(self, team_name: str) -> Path:
        return self._teams_root / team_name / "config.json"

    def _load(self, team_name: str) -> Optional[TeamConfig]:
        p = self._config_path(team_name)
        if not p.exists():
            return None
        try:
            return TeamConfig.model_validate(json.loads(p.read_text(encoding="utf-8")))
        except Exception as e:
            logger.warning("TeamManager: failed to load %s: %s", team_name, e)
            return None

    def _save(self, config: TeamConfig) -> None:
        p = self._config_path(config.name)
        p.parent.mkdir(parents=True, exist_ok=True)
        config.updated_at = time.time()
        p.write_text(config.model_dump_json(indent=2), encoding="utf-8")

    def create_team(
        self,
        team_name: str,
        lead_agent_id: str,
        teammates: list[dict],
    ) -> TeamConfig:
        config = TeamConfig(
            name=team_name,
            lead_agent_id=lead_agent_id,
            teammates=[TeammateSpec(**t) for t in teammates],
        )
        self._save(config)
        logger.info("Team created: %s (lead=%s)", team_name, lead_agent_id)
        return config

    def get_team(self, team_name: str) -> Optional[TeamConfig]:
        return self._load(team_name)

    def list_teams(self) -> list[TeamConfig]:
        teams = []
        for p in self._teams_root.iterdir():
            if p.is_dir():
                cfg = self._load(p.name)
                if cfg:
                    teams.append(cfg)
        return teams

    def get_team_status(self, team_name: str) -> Optional[dict]:
        cfg = self._load(team_name)
        if not cfg:
            return None
        return {
            "name": cfg.name,
            "lead": cfg.lead_agent_id,
            "status": cfg.status,
            "teammates": [{"agent_id": t.agent_id, "role": t.role} for t in cfg.teammates],
            "created_at": cfg.created_at,
            "updated_at": cfg.updated_at,
        }

    def add_teammate(self, team_name: str, agent_id: str, role: str = "") -> Optional[TeamConfig]:
        cfg = self._load(team_name)
        if not cfg:
            return None
        # avoid duplicates
        if not any(t.agent_id == agent_id for t in cfg.teammates):
            cfg.teammates.append(TeammateSpec(agent_id=agent_id, role=role))
            self._save(cfg)
        return cfg

    def remove_teammate(self, team_name: str, agent_id: str) -> None:
        cfg = self._load(team_name)
        if not cfg:
            return
        cfg.teammates = [t for t in cfg.teammates if t.agent_id != agent_id]
        self._save(cfg)

    def disband_team(self, team_name: str) -> None:
        cfg = self._load(team_name)
        if cfg:
            cfg.status = "disbanded"
            self._save(cfg)

    def complete_team(self, team_name: str) -> None:
        cfg = self._load(team_name)
        if cfg:
            cfg.status = "completed"
            self._save(cfg)

    def get_task_board(self, team_name: str):
        """Return a TaskBoard bound to this team's directory."""
        from .task_board import TaskBoard
        team_dir = self._teams_root / team_name
        team_dir.mkdir(parents=True, exist_ok=True)
        return TaskBoard(team_dir=team_dir)
