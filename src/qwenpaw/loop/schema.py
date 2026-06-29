# -*- coding: utf-8 -*-
"""Loop Skill configuration schema (6 dimensions + budget)."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class RubricConfig(BaseModel):
    """Rubric: completion judgment when agent wants to stop."""

    mode: str = Field(
        default="none",
        description="hard_check | soft_judge | none",
    )
    check_expression: str = Field(
        default="",
        description="Expression for hard check mode",
    )
    soft_judge_prompt: str = Field(
        default="",
        description="LLM evaluation prompt for soft judge",
    )
    continuation_prompt: str = Field(
        default="",
        description="Message injected when BLOCK",
    )


class StateConfig(BaseModel):
    """State: persistent state across iterations."""

    mode: str = Field(
        default="none",
        description="json_file | none",
    )
    filename: str = Field(
        default="",
        description="State file name",
    )
    schema_hint: str = Field(
        default="",
        description="Schema description for the state",
    )


class DoomLoopConfig(BaseModel):
    """Doom loop detection configuration."""

    enabled: bool = True
    window_size: int = Field(default=3, ge=2, le=20)
    similarity_threshold: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
    )
    action: str = Field(
        default="hitl",
        description="hitl | force_stop | inject_correction",
    )
    hitl_message: str = Field(
        default="",
        description="Message shown in HITL popup",
    )


class BudgetConfig(BaseModel):
    """Token and cost budget limits."""

    max_tokens: int = Field(
        default=500000,
        ge=1000,
        description="Max tokens (input + output)",
    )
    max_cost_usd: float = Field(
        default=5.0,
        ge=0.01,
        description="Max cost in USD",
    )
    on_exceed: str = Field(
        default="hitl",
        description="hitl | force_stop",
    )
    warning_threshold: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description="Fraction at which to warn",
    )


class SafetyConfig(BaseModel):
    """Safety valve: hard limits as ultimate fallback."""

    max_iterations: int = Field(default=30, ge=1, le=200)
    thinking_only_streak_limit: int = Field(
        default=3,
        ge=1,
        le=20,
    )
    consecutive_error_limit: int = Field(
        default=5,
        ge=1,
        le=50,
    )
    budget: BudgetConfig = Field(
        default_factory=BudgetConfig,
    )


class LoopSkillConfig(BaseModel):
    """Complete loop skill configuration (6 dimensions).

    Serialized as JSON, loaded by LoopLoader, translated into
    PluginApi calls.
    """

    name: str = Field(
        ...,
        description="Unique loop skill name",
    )
    version: str = Field(default="1.0.0")
    slash_command: str = Field(
        ...,
        description="Command name without leading /",
    )
    description: str = Field(default="")

    skill_prompt: str = Field(
        ...,
        description="Natural language instructions for agent",
    )

    rubric: RubricConfig = Field(
        default_factory=RubricConfig,
    )
    state: StateConfig = Field(
        default_factory=StateConfig,
    )
    doom_loop: DoomLoopConfig = Field(
        default_factory=DoomLoopConfig,
    )
    safety: SafetyConfig = Field(
        default_factory=SafetyConfig,
    )

    # Optional priority for multi-loop nesting
    priority: int = Field(
        default=100,
        description="Stop handler priority (lower = first)",
    )


# Budget presets for frontend selector
BUDGET_PRESETS: dict[str, dict[str, Any]] = {
    "low": {
        "max_tokens": 100000,
        "max_cost_usd": 1.0,
        "max_iterations": 10,
    },
    "medium": {
        "max_tokens": 300000,
        "max_cost_usd": 3.0,
        "max_iterations": 20,
    },
    "high": {
        "max_tokens": 500000,
        "max_cost_usd": 5.0,
        "max_iterations": 30,
    },
}


__all__ = [
    "BUDGET_PRESETS",
    "BudgetConfig",
    "DoomLoopConfig",
    "LoopSkillConfig",
    "RubricConfig",
    "SafetyConfig",
    "StateConfig",
]
