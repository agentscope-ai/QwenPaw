# -*- coding: utf-8 -*-
"""Shared adapter over AgentScope 2.0 context preparation and token counting.

AgentScope 2.0 is alpha; ``_prepare_model_input`` and
``_split_context_for_compression`` are underscore-prefixed internals that may
be renamed or have their signatures changed between releases. Routing every
use through this one module means such a break surfaces *here* (and in
``tests/unit/agents/context/test_as_internals_signatures.py``, which asserts
they still exist with the expected shape) rather than scattered across
Native, Scroll, and decision compaction.
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
    return await agent._split_context_for_compression(reserve, tools)


async def count_model_input_tokens(agent: Any, kwargs: dict) -> int:
    """Count the formatter's omission view without altering model input."""
    get_formatter = getattr(agent, "_get_active_formatter", None)
    formatter = get_formatter() if callable(get_formatter) else None
    project = getattr(
        formatter,
        "_prepare_messages_for_token_counting",
        None,
    )
    if callable(project):
        kwargs = {**kwargs, "messages": project(kwargs["messages"])}
    return await agent.model.count_tokens(**kwargs)
