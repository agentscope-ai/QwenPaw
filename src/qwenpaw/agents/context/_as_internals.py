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

import math
from typing import Any

from ...token_usage import calibration


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
    """Count the formatter's omission view without altering model input.

    The local estimator is scaled by the last provider-reported prompt size
    for the same model. Bytes/4 undercounts digit- and identifier-heavy
    prompts by up to 4x, and Scroll's trigger is only safe when the number it
    compares is expressed in provider tokens.
    """
    get_formatter = getattr(agent, "_get_active_formatter", None)
    formatter = get_formatter() if callable(get_formatter) else None
    project = getattr(
        formatter,
        "_prepare_messages_for_token_counting",
        None,
    )
    if callable(project):
        kwargs = {**kwargs, "messages": project(kwargs["messages"])}
    estimate = await agent.model.count_tokens(**kwargs)
    ratio = calibration.ratio_for(_model_identity(agent), estimate)
    if ratio <= 1.0:
        return estimate
    return math.ceil(estimate * ratio)


def _model_identity(agent: Any) -> str | None:
    """Return the ``provider:model`` key used for calibration."""
    model = getattr(agent, "model", None)
    key = getattr(model, "model_key", None)
    return key if isinstance(key, str) and key else None
