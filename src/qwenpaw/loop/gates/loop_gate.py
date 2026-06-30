# -*- coding: utf-8 -*-
"""LoopGate — session-safe base class for loop plugins.

Hierarchy:
    StopGate (ABC)
     └── LoopGate (session management + template method)
          ├── RalphGate
          ├── UltraworkGate
          └── ...

LoopGate handles:
    - per-session state isolation via context var
    - session-scoped state directory
    - max iteration enforcement
    - activate / deactivate lifecycle

Subclasses implement:
    - name (property)
    - _is_complete(state_dir) -> bool
    - continuation_prompt() -> str

Optional overrides:
    - priority (property), default 90
    - _MAX_ITERATIONS (class var), default 30
"""
from __future__ import annotations

import logging
from abc import abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from .base import (
    StopAction,
    StopGate,
    StopHandlerResult,
)

logger = logging.getLogger(__name__)


def _session_id() -> str:
    """Get current session id from context var."""
    from ...app.agent_context import (
        get_current_session_id,
    )

    return get_current_session_id() or "default"


@dataclass
class _LoopState:
    """Per-session loop state managed by LoopGate."""

    active: bool = True
    iteration: int = 0
    workspace_dir: Optional[Path] = None


class LoopGate(StopGate):
    """Session-safe base for loop plugin gates.

    Automatically isolates state per session_id.
    State files are placed under a session-scoped
    directory to prevent cross-session interference.
    """

    _MAX_ITERATIONS: int = 30

    def __init__(self) -> None:
        self._sessions: dict[str, _LoopState] = {}

    # -- Lifecycle (called by plugin register) --

    def activate(
        self,
        workspace_dir: Optional[Path] = None,
    ) -> None:
        """Activate loop for current session."""
        sid = _session_id()
        ws = workspace_dir or Path(".")
        state_dir = self._build_state_dir(ws, sid)
        state_dir.mkdir(parents=True, exist_ok=True)
        self._sessions[sid] = _LoopState(
            workspace_dir=ws,
        )
        logger.debug(
            "LoopGate '%s' activated (session=%s)",
            self.name,
            sid,
        )

    def deactivate(self) -> None:
        """Deactivate loop for current session."""
        sid = _session_id()
        self._sessions.pop(sid, None)
        logger.debug(
            "LoopGate '%s' deactivated (session=%s)",
            self.name,
            sid,
        )

    # -- StopGate interface --

    @property
    def priority(self) -> int:
        return 90

    async def check(
        self,
        ctx: Any,  # pylint: disable=unused-argument
    ) -> Optional[StopHandlerResult]:
        """Session-aware check with iteration limit."""
        sid = _session_id()
        state = self._sessions.get(sid)
        if state is None or not state.active:
            return None

        state.iteration += 1

        if state.iteration > self._MAX_ITERATIONS:
            self._sessions.pop(sid, None)
            return StopHandlerResult(
                action=StopAction.STOP,
                reason=(
                    f"{self.name} max iterations " f"({self._MAX_ITERATIONS})"
                ),
            )

        state_dir = self._build_state_dir(
            state.workspace_dir or Path("."),
            sid,
        )
        if self._is_complete(state_dir):
            self._sessions.pop(sid, None)
            return StopHandlerResult(
                action=StopAction.STOP,
                reason=f"{self.name} completed",
            )

        return StopHandlerResult(
            action=StopAction.CONTINUE,
            continuation_message=(self.continuation_prompt()),
            reason=(
                f"{self.name} iteration "
                f"{state.iteration}"
                f"/{self._MAX_ITERATIONS}"
            ),
        )

    # -- Template methods for subclasses --

    @abstractmethod
    def _is_complete(self, state_dir: Path) -> bool:
        """Check if the loop task is complete.

        Args:
            state_dir: Session-scoped directory
                containing state files.

        Returns:
            True if the task is done.
        """

    # -- Internals --

    @staticmethod
    def _build_state_dir(
        workspace_dir: Path,
        sid: str,
    ) -> Path:
        """Session-scoped state directory."""
        return workspace_dir / ".qwenpaw" / "loop_state" / sid


__all__ = ["LoopGate"]
