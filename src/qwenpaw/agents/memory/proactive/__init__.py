# -*- coding: utf-8 -*-
"""Proactive memory submodule for CoPaw agents."""

from .proactive_types import (
    ProactiveConfig,
    ProactiveTask,
    ProactiveQueryResult,
)
from .proactive_trigger import (
    enable_proactive_for_session,
    proactive_trigger_loop,
    proactive_tasks,
    proactive_configs,
)
from .proactive_responder import generate_proactive_response
from .proactive_utils import extract_content

__all__ = [
    "ProactiveConfig",
    "ProactiveTask",
    "ProactiveQueryResult",
    "enable_proactive_for_session",
    "proactive_trigger_loop",
    "proactive_tasks",
    "proactive_configs",
    "generate_proactive_response",
    "extract_content",
]
