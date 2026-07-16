# -*- coding: utf-8 -*-
"""Shared multi-agent startup state and configuration."""

from enum import Enum

from ..constant import EnvVarLoader

CUSTOM_AGENT_STARTUP_CONCURRENCY_ENV = (
    "QWENPAW_CUSTOM_AGENT_STARTUP_CONCURRENCY"
)
DEFAULT_CUSTOM_AGENT_STARTUP_CONCURRENCY = 2


class AgentStartupStatus(str, Enum):
    """Runtime status for one configured agent."""

    DISABLED = "disabled"
    PENDING = "pending"
    STARTING = "starting"
    RUNNING = "running"
    FAILED = "failed"


def get_custom_agent_startup_concurrency() -> int:
    """Return the bounded startup concurrency for custom agents."""
    return EnvVarLoader.get_int(
        CUSTOM_AGENT_STARTUP_CONCURRENCY_ENV,
        default=DEFAULT_CUSTOM_AGENT_STARTUP_CONCURRENCY,
        min_value=1,
    )
