# -*- coding: utf-8 -*-
"""Shared multi-agent startup state and configuration."""

from enum import Enum


class AgentStartupStatus(str, Enum):
    """Runtime status for one configured agent."""

    DISABLED = "disabled"
    PENDING = "pending"
    STARTING = "starting"
    RUNNING = "running"
    FAILED = "failed"
