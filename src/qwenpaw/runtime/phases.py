# -*- coding: utf-8 -*-
"""Runtime hook phase enum.

Eight phase points covering the full request lifecycle::

    PRE_DISPATCH      — request normalization, before slash dispatch
    POST_DISPATCH     — slash dispatch finished without a match
    PRE_AGENT_BUILD   — session.load and other pre-build setup
    POST_AGENT_BUILD  — agent constructed; inject mode context
    PRE_EXECUTE       — bootstrap / prompt refresh / env stack push
    POST_RESPONSE     — session.save / cron trigger writeback
    ON_ERROR          — exception normalization, cancel envelope
    FINALLY           — idempotent cleanup (close mcp, reset ContextVars)

Phase points are fixed; the slash-command registry and ``AgentBuilder.build``
sit between phases as fixed steps and are not themselves hooks.

These hooks are the runtime-orchestration layer, distinct from the
``agentscope.middleware`` middlewares that wrap a single agent's reply
loop. The two are orthogonal.
"""

from __future__ import annotations

from enum import Enum


class Phase(str, Enum):
    """Eight phase points around a single ``Runtime.run()`` invocation."""

    PRE_DISPATCH = "pre_dispatch"
    POST_DISPATCH = "post_dispatch"
    PRE_AGENT_BUILD = "pre_agent_build"
    POST_AGENT_BUILD = "post_agent_build"
    PRE_EXECUTE = "pre_execute"
    POST_RESPONSE = "post_response"
    ON_ERROR = "on_error"
    FINALLY = "finally"


__all__ = ["Phase"]
