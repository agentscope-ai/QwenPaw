# -*- coding: utf-8 -*-
"""Compute session context usage from the active agent's memory."""

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def snapshot_context_usage_for_agent(
    agent: Any,
    agent_id: str,
) -> dict[str, Any] | None:
    """Build a lightweight context-usage dict from an agent's memory.

    Used when emitting terminal SSE events: ``query_handler``'s ``finally``
    may clear ``_streaming_agent`` before the runtime yields the final
    ``response`` event, so we also stash a one-shot snapshot on the runner.
    """
    try:
        memory = getattr(agent, "memory", None)
        if memory is None:
            return None

        from ..config.config import load_agent_config

        cfg = load_agent_config(agent_id)
        raw_max = getattr(cfg.running, "max_input_length", 0) or 0
        max_input_length = int(raw_max)
        if max_input_length <= 0:
            return None

        stats = await memory.estimate_tokens(max_input_length)
        details = stats.pop("messages_detail", None) or []
        latest_assistant_tokens = 0
        last_user_idx = -1
        for idx, msg_stat in enumerate(details):
            if getattr(msg_stat, "role", "") == "user":
                last_user_idx = idx
        for msg_stat in reversed(details[last_user_idx + 1 :]):
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


async def compute_context_usage(workspace: Any) -> dict[str, Any] | None:
    """Return estimated context usage for the current session.

    Prefer the live streaming agent; otherwise consume a one-shot snapshot
    stored on the runner when the query finishes.
    """
    try:
        runner = getattr(workspace, "runner", None)
        if runner is None:
            return None

        agent_id = getattr(workspace, "agent_id", None) or "default"
        agent = getattr(runner, "_streaming_agent", None)
        if agent is not None:
            return await snapshot_context_usage_for_agent(agent, agent_id)

        snap = getattr(runner, "_context_usage_snapshot", None)
        if snap is not None:
            setattr(runner, "_context_usage_snapshot", None)
            return snap
        return None
    except Exception:
        logger.debug("Failed to compute context usage", exc_info=True)
        return None
