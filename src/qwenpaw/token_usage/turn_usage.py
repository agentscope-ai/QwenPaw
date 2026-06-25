# -*- coding: utf-8 -*-
"""Per-turn usage metadata, console finalize, and SSE pending state."""

from __future__ import annotations

import logging
from collections import OrderedDict
from typing import Any

from .model_wrapper import TokenRecordingModelWrapper

logger = logging.getLogger(__name__)

TURN_USAGE_META_KEY = "qwenpaw_turn_usage"

_PendingUsageMap = OrderedDict[
    str,
    tuple[dict[str, Any] | None, dict[str, Any] | None],
]
_pending_usage_by_session: _PendingUsageMap = OrderedDict()
_PENDING_USAGE_MAX_SESSIONS = 128


async def snapshot_context_usage_for_state(
    state: Any,
    agent_id: str,
) -> dict[str, Any] | None:
    """Estimate token totals from ``AgentState``."""
    try:
        from ..config.config import (
            load_agent_config,
            get_model_max_input_length,
        )
        from ..agents.utils.context_stats import estimate_context_tokens
        from ..agents.utils.estimate_token_counter import (
            EstimatedTokenCounter,
        )

        agent_config = load_agent_config(agent_id)
        max_input_length = int(get_model_max_input_length(agent_config) or 0)
        if max_input_length <= 0:
            return None

        stats = await estimate_context_tokens(
            state,
            EstimatedTokenCounter(),
            max_input_length,
        )
        details = stats.pop("messages_detail", None) or []

        last_user_idx = -1
        for idx, msg_stat in enumerate(details):
            if getattr(msg_stat, "role", "") == "user":
                last_user_idx = idx
        latest_assistant_tokens = 0
        start = last_user_idx + 1
        for msg_stat in reversed(details[start:]):
            if getattr(msg_stat, "role", "") == "assistant":
                latest_assistant_tokens = int(
                    getattr(msg_stat, "total_tokens", 0) or 0,
                )
                break
        stats["latest_assistant_tokens"] = latest_assistant_tokens
        return stats
    except Exception:
        logger.debug("Failed to snapshot context usage", exc_info=True)
        return None


def fmt_tokens(n: int) -> str:
    """Compact token count for terminal status lines."""
    return f"{n / 1000:.1f}K" if n >= 1000 else str(n)


def reset_pending_usage_for_stream(session_id: str) -> None:
    if not session_id:
        return
    _pending_usage_by_session[session_id] = (None, None)
    _pending_usage_by_session.move_to_end(session_id)
    while len(_pending_usage_by_session) > _PENDING_USAGE_MAX_SESSIONS:
        _pending_usage_by_session.popitem(last=False)


def get_pending_usage_for_stream(
    session_id: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    value = _pending_usage_by_session.get(session_id) if session_id else None
    if value is None:
        return (None, None)
    _pending_usage_by_session.move_to_end(session_id)
    return value


def _set_pending_usage_for_stream(
    session_id: str,
    value: tuple[dict[str, Any] | None, dict[str, Any] | None],
) -> None:
    if not session_id:
        return
    _pending_usage_by_session[session_id] = value
    _pending_usage_by_session.move_to_end(session_id)


def reconcile_turn_with_context(
    turn: dict[str, Any] | None,
    ctx: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Fill turn usage from the context snapshot when the provider lies."""
    if ctx is None:
        return turn
    latest_out = int(ctx.get("latest_assistant_tokens", 0) or 0)
    ctx_est = int(ctx.get("estimated_tokens", 0) or 0)
    if turn is None and ctx_est > 0:
        return {
            "provider_id": "",
            "model_name": "",
            "prompt_tokens": max(ctx_est - latest_out, 0),
            "completion_tokens": latest_out,
            "total_tokens": ctx_est,
            "estimated": True,
        }
    if turn is not None and latest_out > 0:
        actual_out = int(turn.get("completion_tokens", 0) or 0)
        if actual_out <= 1 and latest_out > actual_out:
            prompt_tokens = int(turn.get("prompt_tokens", 0) or 0)
            return {
                **turn,
                "completion_tokens": latest_out,
                "total_tokens": prompt_tokens + latest_out,
                "estimated": True,
            }
    return turn


def find_turn_closing_assistant_in_context(messages: Any) -> Any | None:
    """Return the last assistant message after the most recent user message."""
    if not messages:
        return None
    for msg in reversed(list(messages)):
        role = getattr(msg, "role", None)
        if role == "user":
            break
        if role == "assistant":
            return msg
    return None


def _write_turn_usage_meta(
    msg: Any,
    turn: dict[str, Any] | None,
    ctx: dict[str, Any] | None,
) -> bool:
    """Write turn/context usage onto a specific assistant message."""
    if msg is None or (turn is None and ctx is None):
        return False
    meta = getattr(msg, "metadata", None)
    if not isinstance(meta, dict):
        meta = {}
        msg.metadata = meta
    meta[TURN_USAGE_META_KEY] = {
        "usage": turn,
        "context_usage": ctx,
    }
    return True


async def finalize_console_turn_usage(
    *,
    session: Any,
    session_id: str,
    user_id: str,
    channel: str,
    agent_id: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """After the session-save hook persists agent.state, attach per-turn usage
    metadata to the closing assistant message and stage the SSE pending state.
    """
    turn = TokenRecordingModelWrapper.pop_usage_for_session(session_id)
    ctx: dict[str, Any] | None = None

    try:
        state = await session.get_session_state_dict(
            session_id=session_id,
            user_id=user_id,
            channel=channel,
            allow_not_exist=True,
        )
    except Exception:
        logger.debug("get_session_state_dict skipped", exc_info=True)
        state = None

    if state:
        # Agent context lives in ``agent.state``.
        agent_raw = state.get("agent", {})
        state_raw = agent_raw.get("state")
        agent_state = None
        if isinstance(state_raw, dict):
            try:
                from agentscope.state import AgentState

                agent_state = AgentState.model_validate(state_raw)
            except Exception:
                logger.debug("AgentState parse skipped", exc_info=True)
                agent_state = None

        if agent_state is not None:
            ctx = await snapshot_context_usage_for_state(agent_state, agent_id)

        turn = reconcile_turn_with_context(turn, ctx)

        # Persist usage onto the closing assistant message so reopening the
        # chat from history still renders the ring/popover.
        if agent_state is not None:
            try:
                msg = find_turn_closing_assistant_in_context(
                    getattr(agent_state, "context", None),
                )
                if _write_turn_usage_meta(msg, turn, ctx):
                    await session.update_session_state(
                        session_id=session_id,
                        key="agent.state",
                        value=agent_state.model_dump(mode="json"),
                        user_id=user_id,
                        channel=channel,
                        create_if_not_exist=False,
                    )
            except Exception:
                logger.debug(
                    "update_session_state for turn usage skipped",
                    exc_info=True,
                )
    else:
        turn = reconcile_turn_with_context(turn, ctx)

    _set_pending_usage_for_stream(session_id, (turn, ctx))
    return turn, ctx
