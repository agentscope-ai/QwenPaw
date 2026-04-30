# -*- coding: utf-8 -*-
"""Token counting utilities."""

from typing import TYPE_CHECKING

from .estimate_token_counter import EstimatedTokenCounter

if TYPE_CHECKING:
    from qwenpaw.config.config import AgentProfileConfig


def get_token_counter(
    agent_config: "AgentProfileConfig",
) -> EstimatedTokenCounter:
    """Get token counter for the given agent config.

    Args:
        agent_config: Agent profile configuration containing running settings.

    Returns:
        An EstimatedTokenCounter instance with the configured divisor.
    """
    divisor = (
        agent_config.running.light_context_config.token_count_estimate_divisor
    )
    return EstimatedTokenCounter(estimate_divisor=divisor)
