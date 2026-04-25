# -*- coding: utf-8 -*-
"""Command registry for priority-based message routing.

This module provides a centralized command registration system that maps
commands to priority levels. It supports flexible priority assignment
with 0/10/20/30 intervals for extensibility.

Example:
    >>> registry = CommandRegistry()
    >>> registry.register_command("/stop", priority="critical")
    >>> level = registry.get_priority_level("/stop")
    >>> assert level == 0
"""

from __future__ import annotations

import logging
from typing import Dict

logger = logging.getLogger(__name__)


class CommandRegistry:
    """Command registry with priority levels.

    Features:
    - Priority levels: 0, 10, 20, 30 (interval=10 for extensibility)
    - Dual registration: by name ("critical") or by number (5)
    - Fast lookup: O(1) command → priority_level
    - Extensible: insert new levels between existing ones

    Priority levels:
        - 0 (critical): Urgent control commands (/stop, /kill)
        - 10 (high): High priority queries (/status, /pause)
        - 20 (normal): Regular messages (default)
        - 30 (low): Batch tasks (future)

    Extension examples:
        - Level 5: Insert between critical and high
        - Level 15: Insert between high and normal
    """

    def __init__(self):
        """Initialize command registry with default priorities."""
        # Predefined priority names → level numbers
        self._priority_names: Dict[str, int] = {
            "critical": 0,
            "high": 10,
            "normal": 20,
            "low": 30,
        }

        # Command prefix → priority level (fast lookup)
        self._command_to_level: Dict[str, int] = {}

        # Default priority level for unknown commands
        self._default_level = 20  # normal

        # Register default control commands
        self._register_defaults()

        logger.info("CommandRegistry initialized")

    def _register_defaults(self) -> None:
        """Register default control commands."""
        # Critical (0): Control commands requiring immediate response
        self.register_command("/stop", priority_level=0)

        # High (10): Daemon commands (/daemon <sub> and short aliases)
        # Full daemon commands
        self.register_command("/daemon status", priority_level=10)
        self.register_command("/daemon restart", priority_level=10)
        self.register_command("/daemon reload-config", priority_level=10)
        self.register_command("/daemon version", priority_level=10)
        self.register_command("/daemon logs", priority_level=10)
        self.register_command("/daemon approve", priority_level=10)

        # Daemon short aliases
        self.register_command("/status", priority_level=10)
        self.register_command("/restart", priority_level=10)
        self.register_command("/reload-config", priority_level=10)
        self.register_command("/reload_config", priority_level=10)
        self.register_command("/version", priority_level=10)
        self.register_command("/logs", priority_level=10)
        self.register_command("/approve", priority_level=10)
        self.register_command("/deny", priority_level=10)

        # Approval commands (control commands, not daemon commands)
        self.register_command("/approval", priority_level=10)

        # Note: Conversation commands (/compact, /new) remain at
        # default level (20) and do not need explicit registration

    def register_command(
        self,
        command_prefix: str,
        priority: str | None = None,
        priority_level: int | None = None,
    ) -> None:
        """Register command to priority level.

        Args:
            command_prefix: Command prefix (e.g. "/stop")
            priority: Priority name ("critical", "high", "normal", "low")
            priority_level: Direct priority number (0-100, flexible)

        Raises:
            ValueError: If neither priority nor priority_level is specified
            ValueError: If unknown priority name is used

        Examples:
            # Method 1: Use predefined name
            registry.register_command("/stop", priority="critical")
            # → level = 0

            # Method 2: Direct number (flexible extension)
            registry.register_command("/emergency", priority_level=5)
            # → level = 5 (between critical and high)
        """
        # Determine priority level
        if priority_level is not None:
            level = priority_level
        elif priority is not None:
            level = self._priority_names.get(priority)
            if level is None:
                raise ValueError(f"Unknown priority name: {priority}")
        else:
            raise ValueError(
                "Must specify either priority or priority_level",
            )

        # Register to lookup table
        prefix_lower = command_prefix.lower()
        self._command_to_level[prefix_lower] = level

        logger.info(
            f"Registered command: {command_prefix} → level={level}",
        )

    def is_control_command(self, query: str) -> bool:
        """Check if query is a registered control command.

        Args:
            query: User query (e.g. "/stop" or "normal question")

        Returns:
            True if query matches any registered command prefix

        Examples:
            is_control_command("/stop") → True
            is_control_command("/daemon status") → True
            is_control_command("/stopx") → False (no match)
            is_control_command("hello") → False
        """
        if not query or not isinstance(query, str):
            return False

        query_lower = query.strip().lower()

        if not query_lower.startswith("/"):
            return False

        sorted_prefixes = sorted(
            self._command_to_level.keys(),
            key=len,
            reverse=True,
        )
        for prefix in sorted_prefixes:
            if query_lower.startswith(prefix):
                next_char_idx = len(prefix)
                if next_char_idx >= len(query_lower):
                    return True
                next_char = query_lower[next_char_idx]
                if next_char in (" ", "\t", "\n"):
                    return True

        return False

    def get_priority_level(self, query: str) -> int:
        """Get priority level for a query.

        Args:
            query: User query (e.g. "/stop" or "normal question")

        Returns:
            Priority level (0-100, lower = higher priority)

        Examples:
            get_priority_level("/stop") → 0 (critical)
            get_priority_level("/status") → 10 (high)
            get_priority_level("/statusx") → 20 (no match, default)
            get_priority_level("hello") → 20 (normal, default)
        """
        if not query or not isinstance(query, str):
            return self._default_level

        query_lower = query.strip().lower()

        if not query_lower.startswith("/"):
            return self._default_level

        sorted_prefixes = sorted(
            self._command_to_level.items(),
            key=lambda x: len(x[0]),
            reverse=True,
        )
        for prefix, level in sorted_prefixes:
            if query_lower.startswith(prefix):
                next_char_idx = len(prefix)
                if next_char_idx >= len(query_lower):
                    logger.debug(
                        f"Query '{query[:30]}' → priority_level={level}",
                    )
                    return level
                next_char = query_lower[next_char_idx]
                if next_char in (" ", "\t", "\n"):
                    logger.debug(
                        f"Query '{query[:30]}' → priority_level={level}",
                    )
                    return level

        return self._default_level

    def get_priority_name(self, level: int) -> str:
        """Get priority name from level number.

        Args:
            level: Priority level number

        Returns:
            Priority name or "custom-{level}" if not predefined

        Examples:
            get_priority_name(0) → "critical"
            get_priority_name(5) → "custom-5"
        """
        for name, lvl in self._priority_names.items():
            if lvl == level:
                return name
        return f"custom-{level}"

    def get_all_priority_names(self) -> list[str]:
        """Get all predefined priority names (sorted by level).

        Returns:
            ["critical", "high", "normal", "low"]
        """
        return sorted(
            self._priority_names.keys(),
            key=lambda p: self._priority_names[p],
        )

    def get_registered_commands(self) -> Dict[str, int]:
        """Get all registered commands and their levels.

        Returns:
            {"/stop": 0, "/status": 10, ...}
        """
        return dict(self._command_to_level)

    def is_registered(self, command_prefix: str) -> bool:
        """Check if a command is registered.

        Args:
            command_prefix: Command prefix to check

        Returns:
            True if registered
        """
        return command_prefix.lower() in self._command_to_level
