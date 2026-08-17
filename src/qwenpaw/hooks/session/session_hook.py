# -*- coding: utf-8 -*-
"""Session load/save lifecycle hooks.

Loads persisted session state into ``ctx.session_state`` (PRE_AGENT_BUILD)
so the builder can inject it into the newly-constructed agent. Saves
agent state back to session storage after the response completes, plus an
early save at turn start (PRE_EXECUTE) so a mid-turn refresh already sees
the current turn's user message instead of the previous turn's state.
The early save projects ``ctx.input_msgs`` into the persisted snapshot
(without mutating the live agent), because execution has not committed
them to the agent context yet at PRE_EXECUTE time.
"""

from __future__ import annotations

import copy
import logging

from ..base import LifecycleHook
from ...agents.acp.meta import ACP_EPHEMERAL_META_KEY
from ...runtime._state_utils import StateProxy
from ...runtime.hooks import HookContext, HookResult
from ...runtime.phases import Phase
from .signals import SESSION_SAVE_SUCCEEDED_KEY

logger = logging.getLogger(__name__)


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


def _project_current_input(
    state_dict: dict,
    input_msgs: list,
) -> dict:
    """Return a copy of *state_dict* whose context ends with the current
    turn's input messages — mirroring what AgentScope commits to
    ``agent.state.context`` inside ``_handle_incoming_messages``.

    The PRE_EXECUTE early save runs before ``AgentExecutor.run`` hands
    ``ctx.input_msgs`` to the agent, and AgentScope only appends those
    inputs to the context once ``reply_stream()`` starts — after the hook
    has returned.  To persist the current user message without waiting for
    execution (and without appending the input twice to the live agent),
    the same ``Msg`` objects are serialized into a deep copy of the state
    dict.  ``model_dump(mode="json")`` is exactly how ``state_dict()``
    serializes the context once the messages are appended, so the projected
    snapshot round-trips through ``load_state_dict`` unchanged.

    Returns *state_dict* unchanged when there is no input, the state has no
    ``context`` list, or serialization fails (best-effort: still persist
    the previous state rather than nothing).
    """
    if not input_msgs:
        return state_dict
    try:
        from agentscope.message import Msg

        projected = copy.deepcopy(state_dict)
        state = projected.get("state")
        if not isinstance(state, dict):
            return state_dict
        context = state.get("context")
        if not isinstance(context, list):
            return state_dict
        for msg in input_msgs:
            if isinstance(msg, Msg):
                context.append(msg.model_dump(mode="json"))
        return projected
    except Exception:
        logger.debug(
            "session_early_save: input projection failed; "
            "persisting unprojected state",
            exc_info=True,
        )
        return state_dict


async def _do_session_save(
    ctx: HookContext,
    *,
    include_input: bool = False,
) -> bool:
    """Persist ``ctx.agent`` state + mode_state to session storage.

    Shared by the canonical POST_RESPONSE save and the PRE_EXECUTE early
    save.  ``include_input`` (early save only) projects the current turn's
    ``ctx.input_msgs`` into the snapshot without touching the live agent,
    so a mid-turn refresh already sees the just-sent user message even
    though execution has not yet committed it to the context.  Returns
    ``True`` on success, ``False`` when skipped or failed — callers decide
    what a failure means for them (only the POST_RESPONSE hook publishes
    SESSION_SAVE_SUCCEEDED_KEY).
    """
    if _is_ephemeral_request(ctx):
        return False
    if ctx.workspace is None or ctx.agent is None:
        return False
    session = getattr(ctx.workspace, "session", None)
    if session is None:
        return False
    try:
        request = ctx.request
        user_id = getattr(request, "user_id", "") or ctx.session_id
        channel = getattr(request, "channel", "") or ""

        proxy = StateProxy()
        snapshot = ctx.agent.state_dict()
        if include_input:
            snapshot = _project_current_input(snapshot, ctx.input_msgs)
        proxy.data = snapshot
        proxy.data["mode_state"] = ctx.mode_state
        await session.save_session_state(
            session_id=ctx.session_id,
            user_id=user_id,
            channel=channel,
            agent=proxy,
        )
        return True
    except Exception:
        logger.debug("session_save: failed", exc_info=True)
        return False


class SessionSaveHook(LifecycleHook):
    """Persist agent state after response completion."""

    phase = Phase.POST_RESPONSE
    name = "session_save"
    priority = 90

    async def run(self, ctx: HookContext) -> HookResult:
        ctx.extras[SESSION_SAVE_SUCCEEDED_KEY] = False
        if await _do_session_save(ctx):
            ctx.extras[SESSION_SAVE_SUCCEEDED_KEY] = True
        return HookResult()


class SessionEarlySaveHook(LifecycleHook):
    """Persist agent state at turn start, before execution begins.

    The canonical save only runs at POST_RESPONSE, so refreshing mid-turn
    shows the PREVIOUS turn's state: the just-sent user message is missing
    from the chat view (it only survives same-tab via the frontend's
    sessionStorage patch). Saving once at PRE_EXECUTE — after session load,
    agent build and mode start, i.e. the final pre-execution state — makes
    the current turn's user message durable immediately. The POST_RESPONSE
    (or cancel/error) save overwrites this with the completed turn later.

    The live agent's context does not yet contain ``ctx.input_msgs`` at
    PRE_EXECUTE time — AgentScope appends them inside ``reply_stream()``
    via ``_handle_incoming_messages``, which runs after this hook returns.
    ``include_input`` therefore projects the input into a deep copy of the
    persisted state (see ``_project_current_input``) rather than mutating
    the live agent, so execution still appends each message exactly once.

    Runs last within PRE_EXECUTE (higher priority = later) so the snapshot
    reflects state left by the earlier PRE_EXECUTE hooks. Does NOT set
    SESSION_SAVE_SUCCEEDED_KEY: that signal is reserved for the canonical
    POST_RESPONSE save that CheckpointAutoSnapshotHook depends on.
    """

    phase = Phase.PRE_EXECUTE
    name = "session_early_save"
    priority = 95

    async def run(self, ctx: HookContext) -> HookResult:
        await _do_session_save(ctx, include_input=True)
        return HookResult()


__all__ = ["SessionEarlySaveHook", "SessionLoadHook", "SessionSaveHook"]
