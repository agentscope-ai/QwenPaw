# -*- coding: utf-8 -*-
"""Per-turn token/context usage: compute, reconcile, persist."""

from __future__ import annotations

import logging
from typing import Any

from .model_wrapper import TokenRecordingModelWrapper

logger = logging.getLogger(__name__)

TURN_USAGE_META_KEY = "qwenpaw_turn_usage"


def fmt_tokens(n: int) -> str:
    """Format token count for terminal output."""
    return f"{n / 1000:.1f}K" if n >= 1000 else str(n)


def reconcile_turn_completion_from_stats(
    turn: dict[str, Any],
    stats: dict[str, Any],
) -> dict[str, Any]:
    """Patch under-reported ``completion_tokens`` from state estimate."""
    latest_out = int(stats.get("latest_assistant_tokens", 0) or 0)
    actual_out = int(turn.get("completion_tokens", 0) or 0)
    if latest_out > 0 and actual_out <= 1 and latest_out > actual_out:
        prompt_tokens = int(turn.get("prompt_tokens", 0) or 0)
        return {
            **turn,
            "completion_tokens": latest_out,
            "total_tokens": prompt_tokens + latest_out,
            "estimated": True,
        }
    return turn


def _turn_from_stats(stats: dict[str, Any]) -> dict[str, Any] | None:
    """Build estimated turn usage from a context-stats snapshot."""
    est = int(stats.get("estimated_tokens", 0) or 0)
    if est <= 0:
        return None
    latest_out = int(stats.get("latest_assistant_tokens", 0) or 0)
    return {
        "provider_id": "",
        "model_name": "",
        "prompt_tokens": max(est - latest_out, 0),
        "completion_tokens": latest_out,
        "total_tokens": est,
        "estimated": True,
    }


async def snapshot_context_usage_for_state(
    state: Any,
    agent_id: str,
    preferred_max_input_length: int = 0,
) -> dict[str, Any] | None:
    """Character-based token estimate from ``AgentState``."""
    try:
        from ..config.config import (
            load_agent_config,
            get_model_max_input_length,
        )
        from ..agents.utils.context_stats import estimate_context_tokens
        from ..agents.utils.estimate_token_counter import (
            EstimatedTokenCounter,
        )

        max_input_length = int(preferred_max_input_length or 0)
        if max_input_length <= 0:
            agent_config = load_agent_config(agent_id)
            max_input_length = int(
                get_model_max_input_length(agent_config) or 0,
            )
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


async def resolve_turn_usage(
    *,
    session_id: str,
    agent_id: str,
    session: Any,
    user_id: str,
    channel: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, Any | None]:
    """Resolve turn/ctx from provider usage + full agent-state estimate."""
    turn = TokenRecordingModelWrapper.pop_usage_for_session(session_id)
    if session is None:
        return turn, None, None

    agent_state = await _load_agent_state(
        session=session,
        session_id=session_id,
        user_id=user_id,
        channel=channel,
    )
    if agent_state is None:
        return turn, None, None

    context_size = int((turn or {}).get("context_size", 0) or 0)
    stats = await snapshot_context_usage_for_state(
        agent_state,
        agent_id,
        preferred_max_input_length=context_size,
    )
    if not stats:
        return turn, None, agent_state

    ctx = {
        "estimated_tokens": stats["estimated_tokens"],
        "max_input_length": stats["max_input_length"],
        "context_usage_ratio": stats["context_usage_ratio"],
    }
    if turn is None:
        turn = _turn_from_stats(stats)
    else:
        turn = reconcile_turn_completion_from_stats(turn, stats)
    return turn, ctx, agent_state


def find_turn_closing_assistant_in_context(messages: Any) -> Any | None:
    """Last assistant message after the latest user message."""
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
    """Write usage meta onto an assistant message."""
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


async def _load_agent_state(
    *,
    session: Any,
    session_id: str,
    user_id: str,
    channel: str,
) -> Any | None:
    """Load ``AgentState`` from session store."""
    try:
        state = await session.get_session_state_dict(
            session_id=session_id,
            user_id=user_id,
            channel=channel,
            allow_not_exist=True,
        )
    except Exception:
        logger.debug("get_session_state_dict skipped", exc_info=True)
        return None
    if not state:
        return None
    agent_raw = state.get("agent", {})
    state_raw = agent_raw.get("state")
    if not isinstance(state_raw, dict):
        return None
    try:
        from agentscope.state import AgentState

        return AgentState.model_validate(state_raw)
    except Exception:
        logger.debug("AgentState parse skipped", exc_info=True)
        return None


async def persist_turn_usage(
    *,
    session: Any,
    session_id: str,
    user_id: str,
    channel: str,
    turn: dict[str, Any] | None,
    ctx: dict[str, Any] | None,
    agent_state: Any | None = None,
) -> None:
    """Attach turn/ctx meta to the closing assistant."""
    if turn is None and ctx is None:
        return
    if agent_state is None:
        agent_state = await _load_agent_state(
            session=session,
            session_id=session_id,
            user_id=user_id,
            channel=channel,
        )
    if agent_state is None:
        return
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
        logger.warning(
            "update_session_state for turn usage skipped",
            exc_info=True,
        )
