# -*- coding: utf-8 -*-
"""Package-relative skill contribution with persistent provisioning."""

from dataclasses import dataclass


@dataclass(frozen=True)
class SkillSpec:
    directory: str = "skills"
    enabled_by_default: bool = True
    channels: tuple[str, ...] = ("all",)
