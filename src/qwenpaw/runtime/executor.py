# -*- coding: utf-8 -*-
"""Agent execution driver.

Drives ``agent.reply_stream(inputs=msgs)`` with heartbeat wrapping
and delegates each ``EventType`` event to ``Envelope.translate_event()``.
"""

from __future__ import annotations

import logging
from typing import Any, AsyncGenerator

from .envelope import Envelope
from .heartbeat import (
    _iter_with_heartbeat,
    _HEARTBEAT_TICK,
    HEARTBEAT_INTERVAL_SECONDS,
)

logger = logging.getLogger(__name__)


class AgentExecutor:
    """Execute the agent's reply stream and translate
    events into SSE envelopes.

    One instance per ``Runtime.run()`` invocation.  The executor owns the
    heartbeat wrapper but not the agent itself (that belongs to the
    ``HookContext``).
    """

    def __init__(self, agent: Any, envelope: Envelope) -> None:
        self._agent = agent
        self._envelope = envelope

    async def run(
        self,
        msgs: list[Any],
    ) -> AsyncGenerator[Any, None]:
        """Drive ``agent.reply_stream`` and yield SSE envelope objects.

        Wraps the raw event stream with ``_iter_with_heartbeat`` so long
        idle periods (e.g. tool-guard approval waits) emit keep-alive
        envelopes instead of letting the connection drop.
        """
        agent_iter = self._agent.reply_stream(inputs=msgs).__aiter__()
        async for event in _iter_with_heartbeat(
            agent_iter,
            HEARTBEAT_INTERVAL_SECONDS,
        ):
            if event is _HEARTBEAT_TICK:
                async for obj in self._envelope.heartbeat():
                    yield obj
                continue

            async for obj in self._envelope.translate_event(event):
                yield obj


__all__ = ["AgentExecutor"]
