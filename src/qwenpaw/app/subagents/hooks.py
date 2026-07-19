# -*- coding: utf-8 -*-
"""QwenPaw Runtime hooks for background-subagent integration."""

from __future__ import annotations

from ...hooks.base import LifecycleHook
from ...runtime.hooks import HookAction, HookContext, HookResult
from ...runtime.phases import Phase
from .context import (
    SubagentSpawnContext,
    reset_subagent_spawn_context,
    set_subagent_spawn_context,
)

_CLAIM_ID_ATTR = "_qwenpaw_subagent_event_claim_id"
_CLAIM_IDS_ATTR = "_qwenpaw_subagent_event_claim_ids"


def _claimed_event_ids(agent: object) -> list[str]:
    claim_ids = list(getattr(agent, _CLAIM_IDS_ATTR, []))
    legacy_claim_id = getattr(agent, _CLAIM_ID_ATTR, None)
    if legacy_claim_id and legacy_claim_id not in claim_ids:
        claim_ids.append(legacy_claim_id)
    return claim_ids


def _clear_claimed_event_ids(agent: object) -> None:
    if hasattr(agent, _CLAIM_IDS_ATTR):
        delattr(agent, _CLAIM_IDS_ATTR)
    if hasattr(agent, _CLAIM_ID_ATTR):
        delattr(agent, _CLAIM_ID_ATTR)


class SubagentWakeGuardHook(LifecycleHook):
    """Skip a queued wakeup if another run already consumed its events."""

    phase = Phase.PRE_EXECUTE
    name = "subagent_wake_guard"
    priority = 5

    async def run(self, ctx: HookContext) -> HookResult:
        request_context = getattr(ctx.request, "request_context", None) or {}
        if not request_context.get("subagent_wakeup"):
            return HookResult()
        manager = getattr(ctx.workspace, "subagent_task_manager", None)
        if manager is None:
            return HookResult(action=HookAction.SKIP_AGENT)
        if not await manager.has_pending_events(ctx.session_id):
            return HookResult(action=HookAction.SKIP_AGENT)

        # AgentScope rejects ``inputs=None`` while a tool call is parked on
        # user confirmation or external execution.  Keep the inbox pending;
        # the real continuation request will drain it before reasoning.
        agent = getattr(ctx, "agent", None)
        state = getattr(agent, "state", None)
        context = getattr(state, "context", None) or []
        if context:
            from agentscope.message import ToolCallState

            last = context[-1]
            tool_calls = last.get_content_blocks("tool_call")
            if any(
                call.state in (ToolCallState.ASKING, ToolCallState.SUBMITTED)
                for call in tool_calls
            ):
                return HookResult(action=HookAction.SKIP_AGENT)
        return HookResult()


class SubagentContextSetupHook(LifecycleHook):
    """Expose the current Workspace manager to plain function tools."""

    phase = Phase.PRE_EXECUTE
    name = "subagent_context_setup"
    priority = 15

    async def run(self, ctx: HookContext) -> HookResult:
        manager = getattr(ctx.workspace, "subagent_task_manager", None)
        if manager is None:
            return HookResult()
        request_context = getattr(ctx.request, "request_context", None) or {}
        token = set_subagent_spawn_context(
            SubagentSpawnContext(
                manager=manager,
                agent_id=ctx.agent_id,
                session_id=ctx.session_id,
                root_session_id=ctx.root_session_id or ctx.session_id,
                user_id=getattr(ctx.request, "user_id", "") or "",
                channel=getattr(ctx.request, "channel", "") or "console",
                channel_meta=dict(
                    getattr(ctx.request, "channel_meta", None) or {},
                ),
                is_subagent=bool(request_context.get("is_subagent")),
            ),
        )
        ctx.extras["subagent_context_token"] = token
        return HookResult()


class SubagentContextCleanupHook(LifecycleHook):
    """Reset the request-local spawn context on every exit path."""

    phase = Phase.FINALLY
    name = "subagent_context_cleanup"
    priority = 90

    async def run(self, ctx: HookContext) -> HookResult:
        manager = getattr(ctx.workspace, "subagent_task_manager", None)
        claim_ids = _claimed_event_ids(ctx.agent)
        if manager is not None:
            for claim_id in claim_ids:
                await manager.release_events(claim_id)
        _clear_claimed_event_ids(ctx.agent)
        token = ctx.extras.pop("subagent_context_token", None)
        if token is not None:
            reset_subagent_spawn_context(token)
        return HookResult()


class SubagentEventAckHook(LifecycleHook):
    """Ack claimed inbox events only after session persistence succeeds."""

    phase = Phase.POST_RESPONSE
    name = "subagent_event_ack"
    priority = 95
    after = ("session_save",)

    async def run(self, ctx: HookContext) -> HookResult:
        if not ctx.extras.get("session_save_succeeded"):
            return HookResult()
        manager = getattr(ctx.workspace, "subagent_task_manager", None)
        claim_ids = _claimed_event_ids(ctx.agent)
        if manager is not None:
            for claim_id in claim_ids:
                await manager.ack_events(claim_id)
        _clear_claimed_event_ids(ctx.agent)
        return HookResult()


__all__ = [
    "SubagentContextCleanupHook",
    "SubagentContextSetupHook",
    "SubagentEventAckHook",
    "SubagentWakeGuardHook",
]
