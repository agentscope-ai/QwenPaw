# -*- coding: utf-8 -*-
"""Langfuse trace lifecycle hooks.

Applies ``agent_trace_scope`` as a PRE_EXECUTE / FINALLY hook pair,
grouping each agent request into a single Langfuse trace.
"""
from __future__ import annotations

import logging
import uuid

from ..base import LifecycleHook
from ...runtime.hooks import HookContext, HookResult
from ...runtime.phases import Phase

logger = logging.getLogger(__name__)

_LANGFUSE_SCOPE_KEY = "_qp_langfuse_trace_scope"


class LangfuseTraceHook(LifecycleHook):
    """Open Langfuse root trace span before agent execution."""

    phase = Phase.PRE_EXECUTE
    name = "langfuse_trace"
    # After ContextVarsSetupHook(10) so session/agent metadata is available,
    # before BootstrapHook(20) which injects guidance into messages.
    priority = 12

    async def run(self, ctx: HookContext) -> HookResult:
        from ...observability.langfuse import (
            agent_trace_scope,
            is_langfuse_enabled,
        )

        if not is_langfuse_enabled():
            return HookResult()

        from ...runtime.message_convert import _get_last_user_text

        trace_id = str(uuid.uuid4())
        metadata = {
            "session_id": ctx.session_id,
            "root_session_id": ctx.root_session_id,
            "agent_id": ctx.agent_id,
            "root_agent_id": ctx.root_agent_id,
            "user_id": getattr(ctx.request, "user_id", None) or "",
            "channel": getattr(ctx.request, "channel", None) or "",
        }
        scope = agent_trace_scope(
            trace_id=trace_id,
            name="qwenpaw.agent.react_loop",
            metadata=metadata,
            input={
                "query": _get_last_user_text(ctx.input_msgs),
                "messages_count": len(ctx.input_msgs),
            },
        )
        try:
            await scope.__aenter__()
            ctx.extras[_LANGFUSE_SCOPE_KEY] = scope
        except Exception:
            logger.debug("langfuse trace scope open failed", exc_info=True)
        return HookResult()


class LangfuseTraceCleanupHook(LifecycleHook):
    """Close Langfuse root trace span in FINALLY phase."""

    phase = Phase.FINALLY
    name = "langfuse_trace_cleanup"
    # After SkillEnvCleanupHook(40); trace closure does not depend on
    # other cleanup hooks so a later priority is safe.
    priority = 50

    async def run(self, ctx: HookContext) -> HookResult:
        scope = ctx.extras.pop(_LANGFUSE_SCOPE_KEY, None)
        if scope is not None:
            exc = ctx.error
            try:
                await scope.__aexit__(
                    type(exc) if exc else None,
                    exc,
                    exc.__traceback__ if exc else None,
                )
            except Exception:
                logger.debug("langfuse trace cleanup failed", exc_info=True)
        return HookResult()


__all__ = ["LangfuseTraceHook", "LangfuseTraceCleanupHook"]
