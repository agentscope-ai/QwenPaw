# -*- coding: utf-8 -*-
"""Skill runtime config resolution, eligibility, and env injection."""

from __future__ import annotations

import os
import shutil
from contextlib import contextmanager
from typing import Any, Iterator

from pydantic import BaseModel, Field

from ..config import Config, SkillEntryConfig
from .skill_metadata import SkillMetadata, resolve_skill_key


class SkillEligibilityStatus(BaseModel):
    """Eligibility status for a skill."""

    eligible: bool = True
    disabled: bool = False
    missing_env: list[str] = Field(default_factory=list)
    missing_config: list[str] = Field(default_factory=list)
    missing_bins: list[str] = Field(default_factory=list)


class SkillConfigStatus(BaseModel):
    """Sanitized skill config status for API/UI consumption."""

    key: str
    enabled: bool | None = None
    has_api_key: bool = False
    env_keys: list[str] = Field(default_factory=list)
    config_keys: list[str] = Field(default_factory=list)


def resolve_skill_config(
    config: Config | None,
    skill_name: str,
    metadata: SkillMetadata | None,
) -> SkillEntryConfig | None:
    """Resolve a skill config entry using metadata.skill_key when present."""
    if config is None:
        return None
    skill_key = resolve_skill_key(skill_name, metadata)
    return config.skills.entries.get(skill_key)


def build_skill_config_status(
    config: Config | None,
    skill_name: str,
    metadata: SkillMetadata | None,
) -> SkillConfigStatus:
    """Build a public, masked view of skill config."""
    skill_key = resolve_skill_key(skill_name, metadata)
    skill_config = resolve_skill_config(config, skill_name, metadata)
    return SkillConfigStatus(
        key=skill_key,
        enabled=skill_config.enabled if skill_config else None,
        has_api_key=bool(skill_config and skill_config.api_key),
        env_keys=sorted(skill_config.env.keys()) if skill_config else [],
        config_keys=sorted(skill_config.config.keys()) if skill_config else [],
    )


def _resolve_config_path(config: Config | None, path: str) -> Any:
    current: Any = (
        config.model_dump(mode="json", by_alias=True) if config else {}
    )
    for part in [item for item in path.split(".") if item]:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _is_truthy(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (list, dict, str)):
        return bool(value)
    return True


def compute_skill_eligibility(
    config: Config | None,
    skill_name: str,
    metadata: SkillMetadata | None,
) -> SkillEligibilityStatus:
    """Compute whether a skill is eligible for registration/runtime."""
    skill_config = resolve_skill_config(config, skill_name, metadata)
    if skill_config and skill_config.enabled is False:
        return SkillEligibilityStatus(eligible=False, disabled=True)

    missing_env: list[str] = []
    missing_config: list[str] = []
    missing_bins: list[str] = []
    requirements = metadata.requires if metadata else None

    if requirements:
        for env_name in requirements.env:
            has_value = bool(os.environ.get(env_name))
            if not has_value and skill_config:
                has_value = bool(skill_config.env.get(env_name))
                if (
                    not has_value
                    and metadata
                    and metadata.primary_env == env_name
                ):
                    has_value = bool(skill_config.api_key)
            if not has_value:
                missing_env.append(env_name)

        for config_path in requirements.config:
            if not _is_truthy(_resolve_config_path(config, config_path)):
                missing_config.append(config_path)

        for bin_name in requirements.bins:
            if shutil.which(bin_name) is None:
                missing_bins.append(bin_name)

    eligible = not (missing_env or missing_config or missing_bins)
    return SkillEligibilityStatus(
        eligible=eligible,
        missing_env=missing_env,
        missing_config=missing_config,
        missing_bins=missing_bins,
    )


def has_skill_env_overrides(
    skills: list[Any],
    config: Config | None,
) -> bool:
    """Return True when any skill needs temporary env/api_key injection."""
    for skill in skills:
        metadata = getattr(skill, "metadata", None)
        skill_config = resolve_skill_config(config, skill.name, metadata)
        if not skill_config:
            continue

        if skill_config.env:
            return True

        if metadata and metadata.primary_env and skill_config.api_key:
            return True

    return False


@contextmanager
def apply_skill_env_overrides(
    skills: list[Any],
    config: Config | None,
) -> Iterator[None]:
    """Temporarily inject skill env/api_key overrides into process env."""
    original_values: dict[str, str | None] = {}

    try:
        for skill in skills:
            metadata = getattr(skill, "metadata", None)
            skill_config = resolve_skill_config(config, skill.name, metadata)
            if not skill_config:
                continue

            pending_env = dict(skill_config.env)
            if metadata and metadata.primary_env and skill_config.api_key:
                pending_env.setdefault(
                    metadata.primary_env,
                    skill_config.api_key,
                )

            for env_name, env_value in pending_env.items():
                if not env_name or env_value is None:
                    continue
                if env_name not in original_values:
                    original_values[env_name] = os.environ.get(env_name)
                os.environ[env_name] = env_value

        yield
    finally:
        for env_name in reversed(list(original_values.keys())):
            original = original_values[env_name]
            if original is None:
                os.environ.pop(env_name, None)
            else:
                os.environ[env_name] = original
