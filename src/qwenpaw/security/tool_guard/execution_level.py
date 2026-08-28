# -*- coding: utf-8 -*-
"""Tool approval modes for QwenPaw agent.

Defines different approval strategies for tool execution:
- STRICT: All tools require approval
- SMART: Low-risk tools auto-allowed, medium+ require approval
- AUTO: Only guarded_tools require approval (backward compatible)
- OFF: Tool approval disabled; file protection remains independent
"""
from __future__ import annotations

from enum import Enum


class ToolExecutionLevel(str, Enum):
    """Tool approval mode.

    Controls when tools require user approval before execution.
    """

    STRICT = "strict"
    """All tools require approval (highest security).

    Use case: Production environments, high-security deployments.
    Behavior: Even INFO-level findings trigger approval flow.
    """

    SMART = "smart"
    """Low-risk tools auto-allowed, medium+ require approval (recommended).

    Use case: Balanced security and productivity (default recommended).
    Behavior:
        - INFO/LOW severity: auto-allow
        - MEDIUM/HIGH/CRITICAL severity: require approval
    """

    AUTO = "auto"
    """Only explicitly guarded tools require approval (backward compatible).

    Use case: Current behavior, legacy compatibility.
    Behavior: Only tools in guarded_tools list are checked.
    """

    OFF = "off"
    """Tool approval disabled.

    Use case: Development/testing, fully trusted environments.
    Behavior: Tools do not request approval. File protection still applies.
    """

    @classmethod
    def from_config(cls, value: str | None) -> "ToolExecutionLevel":
        """Parse execution level from config string.

        Args:
            value: Config value (case-insensitive)

        Returns:
            ToolExecutionLevel enum value, defaults to AUTO if invalid
        """
        if not value:
            return cls.AUTO

        try:
            return cls(value.lower().strip())
        except ValueError:
            return cls.AUTO

    def requires_approval_for_all_tools(self) -> bool:
        """Check if this level requires approval for all tools."""
        return self == ToolExecutionLevel.STRICT

    def is_disabled(self) -> bool:
        """Check whether tool approval is disabled."""
        return self == ToolExecutionLevel.OFF

    def is_smart_mode(self) -> bool:
        """Check if using smart risk-based approval."""
        return self == ToolExecutionLevel.SMART
