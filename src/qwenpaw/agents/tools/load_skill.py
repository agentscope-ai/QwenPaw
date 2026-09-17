# -*- coding: utf-8 -*-
"""Built-in tool wrapper for loading enabled local skills."""

from ..skill_runtime import load_skill as _load_skill
from ...runtime.tool_registry import tool_descriptor


@tool_descriptor(
    async_execution=True,
    tool_type="internal",
    policy_name="LoadSkill",
    ui_description="Load an enabled local skill definition",
    ui_icon="🧩",
)
async def load_skill(skill: str, args: str | None = None):
    """Load an enabled local skill definition and its instructions."""
    return await _load_skill(skill, args)


__all__ = ["load_skill"]
