# -*- coding: utf-8 -*-
"""Thin adapter over the AgentScope 2.0 *private* methods the scroll manager
depends on.

AgentScope 2.0 is alpha; ``_prepare_model_input`` and
``_split_context_for_compression`` are underscore-prefixed internals that may
be renamed or have their signatures changed between releases. Routing every
use through this one module means such a break surfaces *here* (and in
``tests/unit/agents/context/test_as_internals_signatures.py``, which asserts
they still exist with the expected shape) rather than scattered across the
manager's hot path.

Public 2.0 surface (``agent.model.count_tokens``, ``agent.state.context``,
``agent.context_config``) is intentionally NOT wrapped.
"""
from __future__ import annotations

from typing import Any


async def prepare_model_input(agent: Any) -> dict:
    """The kwargs AgentScope would pass to the model for the next step."""
    # pylint: disable-next=protected-access
    return await agent._prepare_model_input()


async def split_for_compression(
    agent: Any,
    reserve: float,
    tools: list,
) -> tuple:
    """Pairing-safe split of the live context into (to_compress, to_reserve),
    reserving roughly ``reserve`` tokens of the recent tail."""
    # pylint: disable-next=protected-access
    to_compress, to_reserve = await agent._split_context_for_compression(
        reserve,
        tools,
    )

    # DeepSeek/OpenAI constraint: tool messages must be preceded by
    # assistant message with tool_calls. Shift messages from to_compress
    # to to_reserve to prevent orphaned tool messages at start of reserve.
    while to_reserve and to_compress:
        first_msg = to_reserve[0]
        role = getattr(first_msg, "role", None) or (
            first_msg.get("role") if isinstance(first_msg, dict) else None
        )
        if role == "tool":
            to_reserve.insert(0, to_compress.pop())
        else:
            break

    return to_compress, to_reserve
