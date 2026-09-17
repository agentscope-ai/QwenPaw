# -*- coding: utf-8 -*-
"""Agent-scoped ContextVar setup hook.

Injects ContextVars that depend on the built agent (its toolkit and
state) so that in-tool nested calls — e.g. ``run_tool_batch`` invoking
other registered tools via ``Toolkit.call_tool`` — can resolve the
current toolkit / agent_state from context.

Separate from :class:`ContextVarsSetupHook` (PRE_DISPATCH) on purpose:
those ContextVars are agent-independent and must be seeded before slash
command dispatch reads them. ``ctx.agent`` does not exist until the
agent is built, so toolkit / state can only be set at POST_AGENT_BUILD.
"""

from __future__ import annotations

import logging

from ..base import LifecycleHook
from ...runtime.hooks import HookContext, HookResult
from ...runtime.phases import Phase

logger = logging.getLogger(__name__)


class AgentContextVarsSetupHook(LifecycleHook):
    """Inject agent-scoped ContextVars once the agent is built."""

    # POST_AGENT_BUILD, not PRE_DISPATCH: ``ctx.agent`` (and thus its
    # toolkit / state) does not exist until the agent is built. Only
    # tools during agent execution read these ContextVars.
    phase = Phase.POST_AGENT_BUILD
    name = "agent_contextvars_setup"
    priority = 10

    async def run(self, ctx: HookContext) -> HookResult:
        from ...config.context import (
            set_current_toolkit,
            set_current_agent_state,
        )

        if ctx.agent is not None:
            set_current_toolkit(getattr(ctx.agent, "toolkit", None))
            set_current_agent_state(getattr(ctx.agent, "state", None))
        return HookResult()


__all__ = ["AgentContextVarsSetupHook"]
