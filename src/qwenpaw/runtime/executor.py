# -*- coding: utf-8 -*-
"""Agent execution driver.

Drives ``agent.reply_stream(inputs=msgs)`` with heartbeat wrapping and
yields raw AgentScope ``AgentEvent`` objects interleaved with
``_HEARTBEAT_TICK`` markers.  Output projection (SSE envelope vs. raw
events) is the caller's responsibility — see ``Runtime._lifecycle``.
"""

from __future__ import annotations

import logging
from typing import Any, AsyncGenerator

from .heartbeat import (
    _iter_with_heartbeat,
    HEARTBEAT_INTERVAL_SECONDS,
)

logger = logging.getLogger(__name__)


class AgentExecutor:
    """Drive the agent's reply stream.

    One instance per ``Runtime`` invocation.  The executor owns the
    heartbeat wrapper but not the agent itself (that belongs to the
    ``HookContext``).
    """

    def __init__(self, agent: Any) -> None:
        self._agent = agent

    async def run(
        self,
        msgs: list[Any],
    ) -> AsyncGenerator[Any, None]:
        """Drive ``agent.reply_stream`` and yield raw events plus ticks.

        Yields AgentScope ``AgentEvent`` objects from the agent's reply
        stream, interleaved with ``_HEARTBEAT_TICK`` markers during idle
        periods (e.g. tool-guard approval waits).  Callers project each
        item to their wire format.
        """
        agent_iter = self._agent.reply_stream(inputs=msgs).__aiter__()
        async for event in _iter_with_heartbeat(
            agent_iter,
            HEARTBEAT_INTERVAL_SECONDS,
        ):
            yield event


__all__ = ["AgentExecutor"]
