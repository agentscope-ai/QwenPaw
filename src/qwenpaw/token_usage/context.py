# -*- coding: utf-8 -*-
"""Context-usage snapshot from an agent's memory."""

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def snapshot_context_usage_for_agent(
    agent: Any,
    agent_id: str,
) -> dict[str, Any] | None:
    """Estimate token totals + latest assistant tokens from `agent.memory`.

    Returns ``None`` when ``max_input_length`` is unset/zero (no ratio to
    report). Drops ``messages_detail`` from the result since the callers only
    need the scalar totals; the latest assistant message tokens are extracted
    into ``latest_assistant_tokens``.
    """
    try:
        memory = getattr(agent, "memory", None)
        if memory is None:
            return None

        from ..config.config import load_agent_config

        max_input_length = int(
            getattr(load_agent_config(agent_id).running, "max_input_length", 0)
            or 0,
        )
        if max_input_length <= 0:
            return None

        stats = await memory.estimate_tokens(max_input_length)
        details = stats.pop("messages_detail", None) or []

        # Find tokens of the assistant message that closes the latest turn.
        last_user_idx = -1
        for idx, msg_stat in enumerate(details):
            if getattr(msg_stat, "role", "") == "user":
                last_user_idx = idx
        latest_assistant_tokens = 0
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
