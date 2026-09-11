# -*- coding: utf-8 -*-
"""Backend-internal schema for manually configured external skills.

``<CREATOR_DATA_ROOT>/config/skills_config.json`` is edited by hand only;
there is no frontend surface or plugin config block for it. The document
shape is ``{"skills": [SkillEntry, ...]}``.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class SkillRequirementKind(StrEnum):
    BINARY = "binary"
    NODE_MIN = "node_min"
    ENV = "env"


class SkillRequirement(BaseModel):
    """One probeable runtime requirement declared by a skill entry."""

    model_config = ConfigDict(extra="forbid")

    kind: SkillRequirementKind
    value: str = Field(min_length=1)


class SkillEntry(BaseModel):
    """One manually configured external skill directory."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9][a-z0-9._-]*$",
    )
    path: str = Field(min_length=1)
    enabled: bool = True
    description: str | None = None
    # Env variable names forwarded to script subprocesses; values are read
    # from the host environment at execution time (never stored here).
    env: list[str] = Field(default_factory=list)
    requirements: list[SkillRequirement] = Field(default_factory=list)


__all__ = [
    "SkillEntry",
    "SkillRequirement",
    "SkillRequirementKind",
]
