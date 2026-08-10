# -*- coding: utf-8 -*-
"""Session load/save lifecycle hooks.

Loads persisted session state into ``ctx.session_state`` (PRE_AGENT_BUILD)
so the builder can inject it into the newly-constructed agent. Saves
agent state back to session storage after the response completes.
"""

from __future__ import annotations

import logging

from ...agents.artifacts import (
    MAX_WORKSPACE_ARTIFACT_MANIFESTS,
    merge_artifact_manifests,
    merge_artifact_root_mappings,
)
from ..base import LifecycleHook
from ...agents.acp.meta import ACP_EPHEMERAL_META_KEY
from ...runtime._state_utils import StateProxy
from ...runtime.hooks import HookContext, HookResult
from ...runtime.phases import Phase
from .signals import SESSION_SAVE_SUCCEEDED_KEY

logger = logging.getLogger(__name__)

_merge_workspace_artifact_manifests = merge_artifact_manifests


def _is_ephemeral_request(ctx: HookContext) -> bool:
    request = ctx.request
    request_context = getattr(request, "request_context", None)
    if isinstance(request_context, dict):
        value = request_context.get(ACP_EPHEMERAL_META_KEY)
        if value is True:
            return True
        if isinstance(value, str) and value.lower() in {"1", "true", "yes"}:
            return True
    return False


class SessionLoadHook(LifecycleHook):
    """Load persisted session state before agent construction."""

    phase = Phase.PRE_AGENT_BUILD
    name = "session_load"
    priority = 10

    async def run(self, ctx: HookContext) -> HookResult:
        if _is_ephemeral_request(ctx):
            return HookResult()
        if ctx.workspace is None:
            return HookResult()
        session = getattr(ctx.workspace, "session", None)
        if session is None:
            return HookResult()
        try:
            request = ctx.request
            user_id = getattr(request, "user_id", "") or ctx.session_id
            channel = getattr(request, "channel", "") or ""

            proxy = StateProxy()
            await session.load_session_state(
                session_id=ctx.session_id,
                user_id=user_id,
                channel=channel,
                agent=proxy,
            )
            if proxy.data:
                ctx.session_state = proxy.data
                mode_state = proxy.data.get("mode_state")
                if isinstance(mode_state, dict):
                    loaded_mode_state = dict(mode_state)
                    loaded_mode_state.update(ctx.mode_state)
                    ctx.mode_state = loaded_mode_state
        except KeyError as e:
            logger.debug(
                "session_load: skipped (schema mismatch): %s",
                e,
            )
        except Exception:
            logger.debug("session_load: failed", exc_info=True)
        return HookResult()


class SessionSaveHook(LifecycleHook):
    """Persist agent state before the response envelope is finalized."""

    phase = Phase.FINALIZE_TURN
    name = "session_save"
    priority = 90

    async def run(self, ctx: HookContext) -> HookResult:
        ctx.extras[SESSION_SAVE_SUCCEEDED_KEY] = False
        if _is_ephemeral_request(ctx):
            return HookResult()
        if ctx.workspace is None:
            return HookResult()
        session = getattr(ctx.workspace, "session", None)
        if session is None:
            return HookResult()
        try:
            request = ctx.request
            user_id = getattr(request, "user_id", "") or ctx.session_id
            channel = getattr(request, "channel", "") or ""
            manifest = ctx.extras.get("workspace_artifact_manifest")
            root_mappings = ctx.extras.get("workspace_artifact_roots")

            if ctx.agent is None:
                if manifest is None:
                    return HookResult()
                states = await session.get_session_state_dict(
                    session_id=ctx.session_id,
                    user_id=user_id,
                    channel=channel,
                )
                agent_state = states.get("agent", {})
                if not isinstance(agent_state, dict):
                    agent_state = {}
                manifests = _merge_workspace_artifact_manifests(
                    agent_state,
                    manifest,
                )
                roots = merge_artifact_root_mappings(
                    agent_state,
                    manifests,
                    root_mappings,
                )
                agent_state["workspace_artifact_manifests"] = manifests
                agent_state["workspace_artifact_roots"] = roots
                proxy = StateProxy()
                proxy.data = agent_state
                await session.save_session_state(
                    session_id=ctx.session_id,
                    user_id=user_id,
                    channel=channel,
                    agent=proxy,
                )
                ctx.extras[SESSION_SAVE_SUCCEEDED_KEY] = True
                return HookResult()

            proxy = StateProxy()
            proxy.data = ctx.agent.state_dict()
            proxy.data["mode_state"] = ctx.mode_state
            manifests = _merge_workspace_artifact_manifests(
                ctx.session_state,
                manifest,
            )
            if manifests:
                proxy.data["workspace_artifact_manifests"] = manifests[
                    -MAX_WORKSPACE_ARTIFACT_MANIFESTS:
                ]
            proxy.data[
                "workspace_artifact_roots"
            ] = merge_artifact_root_mappings(
                ctx.session_state,
                manifests,
                root_mappings,
            )
            await session.save_session_state(
                session_id=ctx.session_id,
                user_id=user_id,
                channel=channel,
                agent=proxy,
            )
            ctx.extras[SESSION_SAVE_SUCCEEDED_KEY] = True
        except Exception:
            logger.debug("session_save: failed", exc_info=True)
        return HookResult()


__all__ = ["SessionLoadHook", "SessionSaveHook"]
