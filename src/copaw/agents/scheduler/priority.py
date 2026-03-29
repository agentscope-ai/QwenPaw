# -*- coding: utf-8 -*-
"""Message Priority Definitions.

Defines priority levels for agent messages, supporting different
scheduling strategies based on urgency.
"""

from enum import IntEnum


class MessagePriority(IntEnum):
    """Message priority levels for agent scheduling.

    Lower values indicate higher priority.

    Attributes:
        CRITICAL: Emergency tasks that should interrupt current work.
            Example: "Stop all file deletion operations immediately"
        HIGH: Important tasks that should be queued at the front.
            Example: "Generate this report right now"
        NORMAL: Standard tasks with normal queuing.
            Example: Regular user queries and commands
        LOW: Background tasks that run when system is idle.
            Example: Scheduled cleanup, periodic checks
    """

    CRITICAL = 0  # Emergency: Interrupt current task immediately
    HIGH = 1  # Important: Queue at front, execute before NORMAL
    NORMAL = 2  # Standard: Normal FIFO queuing
    LOW = 3  # Background: Only execute when system is idle

    @classmethod
    def from_string(cls, value: str) -> "MessagePriority":
        """Convert string to MessagePriority.

        Args:
            value: String representation of priority (case-insensitive).

        Returns:
            MessagePriority enum value.

        Raises:
            ValueError: If the string doesn't match any priority.
        """
        mapping = {
            "critical": cls.CRITICAL,
            "high": cls.HIGH,
            "normal": cls.NORMAL,
            "low": cls.LOW,
            "urgent": cls.CRITICAL,  # Alias for CRITICAL
            "important": cls.HIGH,  # Alias for HIGH
            "default": cls.NORMAL,  # Alias for NORMAL
            "background": cls.LOW,  # Alias for LOW
        }
        lower_value = value.lower().strip()
        if lower_value not in mapping:
            raise ValueError(
                f"Invalid priority '{value}'. "
                f"Valid values: {list(mapping.keys())}"
            )
        return mapping[lower_value]

    def __str__(self) -> str:
        """Return string representation."""
        return self.name

    def __repr__(self) -> str:
        """Return repr string."""
        return f"MessagePriority.{self.name}"
