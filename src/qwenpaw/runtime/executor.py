# -*- coding: utf-8 -*-
"""Agent execution driver.

Drives ``agent.reply_stream(inputs=msgs)`` with heartbeat wrapping
and delegates each ``EventType`` event to ``Envelope.translate_event()``.
"""

from __future__ import annotations

import logging
from datetime import datetime
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

            self._maybe_stamp_finished_at(event)

            async for obj in self._envelope.translate_event(event):
                yield obj

    def _maybe_stamp_finished_at(self, event: Any) -> None:
        """Backfill ``finished_at`` on the reply's assistant message.

        agentscope only stamps ``Msg.finished_at`` via
        ``Msg.append_event(REPLY_END)``, a path that only agentscope's own
        app service invokes.  QwenPaw persists context through
        ``_save_to_context``, which never writes ``finished_at`` and pins
        ``created_at`` at the first saved segment of the reply.  The
        session snapshot therefore records no real completion time, and
        history rebuilt from the API falls back to ``created_at`` for the
        assistant completion time — under-reporting turns that include
        long tool calls (issue #6826).

        ``REPLY_END`` is emitted after every ``_save_to_context`` call of
        the reply, so stamping here lands in the session snapshot that is
        persisted at turn end.  Best-effort by design: any failure is
        logged and swallowed so the SSE stream is never affected.
        """
        try:
            from agentscope.event import EventType

            if getattr(event, "type", None) != EventType.REPLY_END.value:
                return
            context = getattr(
                getattr(self._agent, "state", None),
                "context",
                None,
            )
            if not context:
                return
            reply_id = getattr(event, "reply_id", None)
            target = None
            if reply_id is not None:
                for msg in reversed(context):
                    if getattr(msg, "id", None) == reply_id:
                        target = msg
                        break
            if target is None:
                last = context[-1]
                if getattr(last, "role", None) == "assistant":
                    target = last
            if target is None or getattr(target, "finished_at", None):
                return
            target.finished_at = (
                getattr(event, "created_at", None)
                or datetime.now().isoformat()
            )
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "executor: failed to stamp finished_at on REPLY_END",
                exc_info=True,
            )


__all__ = ["AgentExecutor"]
