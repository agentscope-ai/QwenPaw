# -*- coding: utf-8 -*-
"""Type definitions for proactive conversation feature."""

from dataclasses import dataclass
from typing import Optional
from datetime import datetime


@dataclass
class ProactiveConfig:
    """Configuration for proactive feature."""

    enabled: bool = False
    idle_minutes: int = 30
    last_user_interaction: Optional[datetime] = None
    running_task_id: Optional[str] = None
    mode_enabled_time: Optional[datetime] = None


@dataclass
class ProactiveTask:
    """Represents a task extracted from memory context."""

    task: str
    query: str
    priority: int  # Lower number means higher priority
    reason: str


@dataclass
class ProactiveQueryResult:
    """Result from executing a proactive query."""

    query: str
    success: bool
    data: Optional[str] = None
    error: Optional[str] = None
