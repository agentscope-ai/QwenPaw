# -*- coding: utf-8 -*-
"""Advisor mode — self-contained ``AgentMode`` plugin.

A stronger "advisor" model (the agent's main model) writes a strategic
plan before the agent's first step and is consulted again when the agent
keeps failing, while the agent itself runs on the cheaper
``subagent_model`` when one is configured.

All advisor-mode logic lives under this package:

- ``AdvisorMode`` — the ``AgentMode`` entry point (hooks, middleware,
  ``/advisor`` command).
- ``AdvisorMiddleware`` — plan injection + mid-run intervention.
- ``AdvisorClient`` — the advisor model, built through the model factory.
- ``InterventionTrigger`` / ``FailureDetector`` — when to step back in.
"""

from __future__ import annotations

from .middleware import (
    FOLLOWUP_TOOL_NAME,
    PLAN_TOOL_NAME,
    AdvisorMiddleware,
)
from .mode import AdvisorMode
from .models import AdvisorClient
from .tools import CONSULT_TOOL_NAME, make_consult_advisor
from .trigger import (
    FailureDetector,
    InterventionTrigger,
    TriggerConfig,
    TriggerEvent,
)

__all__ = [
    "CONSULT_TOOL_NAME",
    "FOLLOWUP_TOOL_NAME",
    "PLAN_TOOL_NAME",
    "AdvisorMiddleware",
    "AdvisorMode",
    "AdvisorClient",
    "FailureDetector",
    "InterventionTrigger",
    "TriggerConfig",
    "TriggerEvent",
    "make_consult_advisor",
]
