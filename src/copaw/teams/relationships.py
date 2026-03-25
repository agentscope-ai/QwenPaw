# -*- coding: utf-8 -*-
"""RelationshipStore: persist agent relationships with humans and other agents.

Storage: {workspace_dir}/relationships.json
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class HumanRelationship(BaseModel):
    user_id: str
    name: str = ""
    relation: str = "other"  # creator|direct_leader|collaborator|stakeholder|team_member|mentor|other
    note: str = ""


class AgentRelationship(BaseModel):
    agent_id: str
    name: str = ""
    relation: str = "other"  # peer|supervisor|assistant|subordinate|other
    note: str = ""


class RelationshipData(BaseModel):
    humans: list[HumanRelationship] = Field(default_factory=list)
    agents: list[AgentRelationship] = Field(default_factory=list)


class RelationshipStore:
    """File-based relationship store.

    Storage: {workspace_dir}/relationships.json
    """

    def __init__(self, workspace_dir: Path):
        self._path = workspace_dir / "relationships.json"
        self._data: Optional[RelationshipData] = None

    def _load(self) -> RelationshipData:
        if self._data is not None:
            return self._data
        if self._path.exists():
            try:
                self._data = RelationshipData.model_validate(
                    json.loads(self._path.read_text(encoding="utf-8"))
                )
            except Exception as e:
                logger.warning("RelationshipStore: load failed: %s", e)
                self._data = RelationshipData()
        else:
            self._data = RelationshipData()
        return self._data

    def _save(self) -> None:
        if self._data is None:
            return
        self._path.write_text(self._data.model_dump_json(indent=2), encoding="utf-8")

    # ── dict-like get for backward compat (room conclusion flow) ──
    def get(self, key: str, default=None):
        """Dict-like get for fields used in room conclusion flow."""
        data = self._load()
        return getattr(data, key, default)

    # ── Human relationships ───────────────────────────────────────

    def add_human(
        self, user_id: str, name: str = "", relation: str = "other", note: str = ""
    ) -> HumanRelationship:
        data = self._load()
        # update if exists
        for h in data.humans:
            if h.user_id == user_id:
                h.name = name or h.name
                h.relation = relation
                h.note = note or h.note
                self._save()
                return h
        rel = HumanRelationship(user_id=user_id, name=name, relation=relation, note=note)
        data.humans.append(rel)
        self._save()
        return rel

    def remove_human(self, user_id: str) -> bool:
        data = self._load()
        before = len(data.humans)
        data.humans = [h for h in data.humans if h.user_id != user_id]
        if len(data.humans) < before:
            self._save()
            return True
        return False

    def list_humans(self) -> list[HumanRelationship]:
        return self._load().humans

    # ── Agent relationships ───────────────────────────────────────

    def add_agent(
        self, agent_id: str, name: str = "", relation: str = "other", note: str = ""
    ) -> AgentRelationship:
        data = self._load()
        for a in data.agents:
            if a.agent_id == agent_id:
                a.name = name or a.name
                a.relation = relation
                a.note = note or a.note
                self._save()
                return a
        rel = AgentRelationship(agent_id=agent_id, name=name, relation=relation, note=note)
        data.agents.append(rel)
        self._save()
        return rel

    def remove_agent(self, agent_id: str) -> bool:
        data = self._load()
        before = len(data.agents)
        data.agents = [a for a in data.agents if a.agent_id != agent_id]
        if len(data.agents) < before:
            self._save()
            return True
        return False

    def list_agents(self) -> list[AgentRelationship]:
        return self._load().agents

    # ── Prompt section ────────────────────────────────────────────

    def build_prompt_section(self) -> str:
        """Build a human-readable relationship summary for agent prompt."""
        data = self._load()
        lines = []
        if data.humans:
            lines.append("## 人类关系")
            for h in data.humans:
                line = f"- {h.name or h.user_id} ({h.relation})"
                if h.note:
                    line += f"：{h.note}"
                lines.append(line)
        if data.agents:
            lines.append("## Agent 关系")
            for a in data.agents:
                line = f"- {a.name or a.agent_id} ({a.relation})"
                if a.note:
                    line += f"：{a.note}"
                lines.append(line)
        return "\n".join(lines)
