# -*- coding: utf-8 -*-
"""Agent execution driver.

Drives ``agent.reply_stream(inputs=msgs)`` with heartbeat wrapping
and delegates each ``EventType`` event to ``Envelope.translate_event()``.
"""

from __future__ import annotations

import logging
from typing import Any, AsyncGenerator

from agentscope.event import ReplyEndEvent

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

    def _record_reply_completion(self, event: ReplyEndEvent) -> None:
        """Apply a terminal reply event to its persisted context message."""
        state = getattr(self._agent, "state", None)
        context = getattr(state, "context", None)
        if not context:
            return
        for message in reversed(context):
            if getattr(message, "id", None) != event.reply_id:
                continue
            if (
                getattr(message, "role", None) == "assistant"
                and getattr(message, "finished_at", None) is None
            ):
                message.append_event(event)
            return

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

            if isinstance(event, ReplyEndEvent):
                self._record_reply_completion(event)

            async for obj in self._envelope.translate_event(event):
                yield obj


__all__ = ["AgentExecutor"]
