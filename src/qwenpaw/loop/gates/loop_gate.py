# -*- coding: utf-8 -*-
"""LoopGate — generic session-safe base for stateful gates.

Hierarchy:
    StopGate (ABC)
     └── LoopGate (ABC)  ← session isolation only
          ├── FileLoopGate ← file state + iterations
          │    ├── RalphGate, UltraworkGate, ...
          ├── IterationGate
          ├── BudgetGate
          ├── DoomLoopGate
          └── MissionGate

LoopGate handles:
    - per-session state isolation via ``_sessions`` dict
    - ``activate()`` / ``deactivate()`` lifecycle
    - session ID retrieval from context var

Subclasses MUST still implement ``name``, ``check()``.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from .base import StopGate

logger = logging.getLogger(__name__)


def _session_id() -> str:
    """Get current session id from context var."""
    from ...app.agent_context import (
        get_current_session_id,
    )

    return get_current_session_id() or "default"


class LoopGate(StopGate):
    """Session-safe abstract base for all stateful gates.

    Manages ``_sessions: dict[str, Any]`` keyed by
    session ID.  Subclasses store arbitrary per-session
    state objects via ``activate(state)`` and retrieve
    them via ``_state()``.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, Any] = {}

    @staticmethod
    def _session_id() -> str:
        """Return current session ID."""
        return _session_id()

    def _state(self) -> Optional[Any]:
        """Return per-session state or None."""
        return self._sessions.get(_session_id())

    def activate(
        self,
        state: Any = None,
    ) -> None:
        """Activate gate for current session."""
        sid = _session_id()
        self._sessions[sid] = state
        logger.debug(
            "LoopGate '%s' activated (session=%s)",
            self.name,
            sid,
        )

    def deactivate(self) -> None:
        """Deactivate gate for current session."""
        sid = _session_id()
        self._sessions.pop(sid, None)
        logger.debug(
            "LoopGate '%s' deactivated (session=%s)",
            self.name,
            sid,
        )

    def reset_session(self) -> None:
        """Remove state for the current conversation session."""
        self.deactivate()


__all__ = ["LoopGate"]
