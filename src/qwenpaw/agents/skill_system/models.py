# -*- coding: utf-8 -*-
"""Shared models and constants for the skill system."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


ALL_SKILL_ROUTING_CHANNELS = [
    "console",
    "discord",
    "telegram",
    "dingtalk",
    "feishu",
    "imessage",
    "qq",
    "mattermost",
    "wecom",
    "mqtt",
]


@dataclass(frozen=True)
class BuiltinSkillVariant:
    name: str
    language: str
    source_name: str
    skill_dir: Path
    skill_md_path: Path
    description: str
    version_text: str


@dataclass(frozen=True)
class BuiltinSkillIdentity:
    name: str
    language: str
    source_name: str


class SkillInfo(BaseModel):
    """Workspace or hub skill details returned to callers.

    ``name`` is the stable runtime identifier: the directory / manifest key
    used by APIs, sync state, and channel routing. It is intentionally not
    derived from frontmatter because frontmatter can drift while the on-disk
    workspace identity must remain stable.
    """

    name: str
    description: str = ""
    version_text: str = ""
    content: str
    source: str
    references: dict[str, Any] = Field(default_factory=dict)
    scripts: dict[str, Any] = Field(default_factory=dict)
    emoji: str = ""


class SkillRequirements(BaseModel):
    """System-managed requirements declared by a skill."""

    require_bins: list[str] = Field(default_factory=list)
    require_envs: list[str] = Field(default_factory=list)


class SkillConflictError(RuntimeError):
    """Raised when an import or save operation hits a renameable conflict."""

    def __init__(self, detail: dict[str, Any]):
        super().__init__(str(detail.get("message") or "Skill conflict"))
        self.detail = detail
