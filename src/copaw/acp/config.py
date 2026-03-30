# -*- coding: utf-8 -*-
"""ACP (Agent Client Protocol) configuration.

This module provides configuration models for ACP harnesses,
including OpenCode, Qwen CLI, and Gemini CLI.
"""
from typing import Any, Dict
from pydantic import BaseModel, Field, model_validator


def _default_harnesses() -> Dict[str, "ACPHarnessConfig"]:
    """Return built-in ACP harness defaults."""
    return {
        "opencode": ACPHarnessConfig(
            enabled=True,
            command="npx",
            args=["-y", "opencode-ai@latest", "acp"],
        ),
        "qwen": ACPHarnessConfig(
            enabled=True,
            command="npx",
            args=["-y", "@qwen-code/qwen-code@latest", "--acp"],
        ),
        "gemini": ACPHarnessConfig(
            enabled=False,
            command="npx",
            args=["-y", "@google/gemini-cli@latest", "--experimental-acp"],
        ),
    }


class ACPHarnessConfig(BaseModel):
    """Configuration for a single ACP harness."""

    enabled: bool = Field(
        default=False,
        description="Whether this harness is enabled",
    )
    command: str = Field(
        default="",
        description="Command to launch the harness",
    )
    args: list[str] = Field(
        default_factory=list,
        description="Arguments for the command",
    )
    env: Dict[str, str] = Field(
        default_factory=dict,
        description="Environment variables for the harness process",
    )
    keep_session_default: bool = Field(
        default=False,
        description=(
            "Whether this harness should reuse ACP sessions by default"
        ),
    )
    permission_broker_verified: bool = Field(
        default=False,
        description=(
            "Whether this harness is verified to honor ACP permission "
            "broker requests for dangerous operations"
        ),
    )


class ACPConfig(BaseModel):
    """ACP (Agent Client Protocol) configuration.

    Controls external coding agent integration via ACP protocol.
    All harnesses are disabled by default for security.
    """

    enabled: bool = Field(
        default=False,
        description="Global switch to enable/disable ACP functionality",
    )
    require_approval: bool = Field(
        default=True,
        description=(
            "Whether to require user approval before executing ACP tasks"
        ),
    )
    show_tool_calls: bool = Field(
        default=True,
        description=(
            "Whether to show ACP external-agent tool call messages "
            "in chat output"
        ),
    )
    save_dir: str = Field(
        default="~/.copaw/acp_sessions",
        description="Directory to save ACP session states",
    )
    harnesses: Dict[str, ACPHarnessConfig] = Field(
        default_factory=_default_harnesses,
        description="Available ACP harnesses",
    )

    @model_validator(mode="before")
    @classmethod
    def _merge_default_harnesses(cls, data: Any) -> Any:
        """Merge built-in harness defaults with user config overrides.

        This preserves newly added built-in harnesses for users whose
        existing config.json only overrides a subset of harnesses.
        """
        if not isinstance(data, dict):
            return data

        payload = dict(data)
        user_harnesses = payload.get("harnesses")
        if not isinstance(user_harnesses, dict):
            return payload

        merged: Dict[str, Any] = {}
        defaults = _default_harnesses()

        for name, default_cfg in defaults.items():
            override = user_harnesses.get(name)
            if isinstance(override, dict):
                base = default_cfg.model_dump(mode="python")
                base.update(override)
                merged[name] = base
            elif override is not None:
                merged[name] = override
            else:
                merged[name] = default_cfg

        for name, override in user_harnesses.items():
            if name not in merged:
                merged[name] = override

        payload["harnesses"] = merged
        return payload

    @property
    def has_enabled_harness(self) -> bool:
        """Check if any harness is enabled."""
        return any(h.enabled for h in self.harnesses.values())

    def get_enabled_harnesses(self) -> Dict[str, ACPHarnessConfig]:
        """Get all enabled harnesses."""
        return {name: h for name, h in self.harnesses.items() if h.enabled}

    def is_harness_enabled(self, name: str) -> bool:
        """Check if a specific harness is enabled."""
        harness = self.harnesses.get(name)
        return harness.enabled if harness else False
