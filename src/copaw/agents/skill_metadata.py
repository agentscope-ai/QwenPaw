# -*- coding: utf-8 -*-
"""Structured skill metadata parsing."""

from __future__ import annotations

import json
from typing import Any

import frontmatter
from pydantic import BaseModel, Field


class SkillRequirements(BaseModel):
    """Runtime requirements declared by a skill."""

    env: list[str] = Field(default_factory=list)
    config: list[str] = Field(default_factory=list)
    bins: list[str] = Field(default_factory=list)


class SkillMetadata(BaseModel):
    """Structured metadata consumed by CoPaw runtime."""

    emoji: str | None = None
    skill_key: str | None = None
    primary_env: str | None = None
    requires: SkillRequirements = Field(default_factory=SkillRequirements)


def _normalize_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _parse_metadata_payload(raw_metadata: Any) -> dict[str, Any] | None:
    if isinstance(raw_metadata, dict):
        return raw_metadata
    if not isinstance(raw_metadata, str):
        return None
    raw_metadata = raw_metadata.strip()
    if not raw_metadata:
        return None
    try:
        parsed = json.loads(raw_metadata)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def parse_skill_metadata_from_content(content: str) -> SkillMetadata | None:
    """Parse metadata from raw SKILL.md content."""
    try:
        post = frontmatter.loads(content)
    except Exception:  # pragma: no cover - upstream parser failure
        return None
    return parse_skill_metadata_from_post(post.metadata)


def parse_skill_metadata_from_post(
    post_metadata: dict[str, Any],
) -> SkillMetadata | None:
    """Parse metadata from frontmatter metadata dict."""
    raw_metadata = post_metadata.get("metadata")
    metadata_payload = _parse_metadata_payload(raw_metadata)
    if metadata_payload is None:
        return None

    namespace = metadata_payload.get("copaw")
    if namespace is None:
        namespace = metadata_payload.get("openclaw")
    if namespace is None:
        namespace = metadata_payload
    if not isinstance(namespace, dict):
        return None

    raw_requires = namespace.get("requires")
    requires = raw_requires if isinstance(raw_requires, dict) else {}

    return SkillMetadata(
        emoji=namespace.get("emoji")
        if isinstance(namespace.get("emoji"), str)
        else None,
        skill_key=(
            namespace.get("skill_key")
            if isinstance(namespace.get("skill_key"), str)
            else namespace.get("skillKey")
            if isinstance(namespace.get("skillKey"), str)
            else None
        ),
        primary_env=(
            namespace.get("primary_env")
            if isinstance(namespace.get("primary_env"), str)
            else namespace.get("primaryEnv")
            if isinstance(namespace.get("primaryEnv"), str)
            else None
        ),
        requires=SkillRequirements(
            env=_normalize_string_list(requires.get("env")),
            config=_normalize_string_list(requires.get("config")),
            bins=_normalize_string_list(requires.get("bins")),
        ),
    )


def resolve_skill_key(skill_name: str, metadata: SkillMetadata | None) -> str:
    """Resolve the external config key for a skill."""
    if metadata and metadata.skill_key:
        return metadata.skill_key
    return skill_name


def declared_skill_env_keys(metadata: SkillMetadata | None) -> set[str]:
    """Return env keys explicitly declared by skill metadata."""
    if metadata is None:
        return set()

    keys = set(metadata.requires.env)
    if metadata.primary_env:
        keys.add(metadata.primary_env)
    return {item for item in keys if item}
