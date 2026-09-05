# -*- coding: utf-8 -*-
"""Advisor mode — self-contained ``AgentMode`` plugin.

A stronger "advisor" model (the agent's primary model) writes a strategic
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

from .middleware import AdvisorMiddleware
from .mode import AdvisorMode

__all__ = ["AdvisorMiddleware", "AdvisorMode"]
