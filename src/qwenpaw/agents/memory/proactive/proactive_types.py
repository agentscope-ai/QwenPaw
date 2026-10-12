# -*- coding: utf-8 -*-
"""Type definitions for the proactive agenda feature."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class ProactiveConfig:
    """Runtime state of one armed idle watcher.

    Topic production lives in ReMe, so nothing here describes a task: the
    config only tracks the idle threshold and the stamps the trigger loop
    needs to decide when a round is due.
    """

    enabled: bool = False
    idle_minutes: int = 30
    last_user_interaction: Optional[datetime] = None
    running_task_id: Optional[str] = None
    mode_enabled_time: Optional[datetime] = None
