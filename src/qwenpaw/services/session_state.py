# -*- coding: utf-8 -*-
"""Read and write session state independently of agent construction."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class StateProxy:
    """Minimal proxy satisfying SafeJSONSession's state_module protocol.

    Used by session hooks and builtin commands to load/save AgentState
    without instantiating a full agent.
    """

    def __init__(self) -> None:
        self.data: dict = {}

    def state_dict(self) -> dict:
        return self.data

    def load_state_dict(self, d: dict) -> None:
        self.data = d


async def load_session_state(ctx, config) -> dict | None:
    """Read persisted input before resolving this turn's runtime settings."""
    session = getattr(getattr(ctx, "workspace", None), "session", None)
    if session is None or not config.session_persistence:
        return None
    proxy = StateProxy()
    request = ctx.request
    try:
        await session.load_session_state(
            session_id=ctx.session_id,
            user_id=getattr(request, "user_id", None) or ctx.session_id,
            channel=getattr(request, "channel", None) or "",
            agent=proxy,
        )
    except KeyError as error:
        logger.debug("session_load: skipped (schema mismatch): %s", error)
    except Exception:
        logger.debug("session_load: failed", exc_info=True)
    return proxy.data or None


__all__ = ["StateProxy", "load_session_state"]
