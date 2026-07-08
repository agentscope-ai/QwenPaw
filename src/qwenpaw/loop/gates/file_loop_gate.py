# -*- coding: utf-8 -*-
"""FileLoopGate — file-state + iteration loop base.

For plugins that track completion via state files on disk.

Hierarchy:
    LoopGate (session isolation)
     └── FileLoopGate (file state + iteration cap)
          ├── RalphGate
          ├── UltraworkGate
          └── ...

Subclasses implement:
    - ``name`` (property)
    - ``_is_complete(state_dir)`` -> bool
    - ``continuation_prompt()`` -> str
"""
from __future__ import annotations

import logging
from abc import abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from .base import StopAction, StopHandlerResult
from .loop_gate import LoopGate

logger = logging.getLogger(__name__)


@dataclass
class _FileLoopState:
    """Per-session state for FileLoopGate."""

    active: bool = True
    iteration: int = 0
    workspace_dir: Optional[Path] = None


class FileLoopGate(LoopGate):
    """Session-safe base for file-state loop plugins.

    Manages a session-scoped state directory and enforces
    ``_MAX_ITERATIONS``.  Subclasses only need to check
    whether the task is done via ``_is_complete()``.
    """

    _MAX_ITERATIONS: int = 30

    @property
    def priority(self) -> int:
        return 90

    def activate(  # pylint: disable=arguments-renamed
        self,
        workspace_dir: Optional[Path] = None,
    ) -> None:
        """Activate file loop for current session."""
        ws = workspace_dir or Path(".")
        sid = self._session_id()
        state_dir = self._build_state_dir(ws, sid)
        state_dir.mkdir(parents=True, exist_ok=True)
        fls = _FileLoopState(workspace_dir=ws)
        super().activate(fls)

    async def check(
        self,
        ctx: Any,  # pylint: disable=unused-argument
    ) -> Optional[StopHandlerResult]:
        """Session-aware check with iteration limit."""
        state: Optional[_FileLoopState] = self._state()
        if state is None or not state.active:
            return None

        state.iteration += 1

        if state.iteration > self._MAX_ITERATIONS:
            self.deactivate()
            return StopHandlerResult(
                action=StopAction.STOP,
                reason=(
                    f"{self.name} max iterations " f"({self._MAX_ITERATIONS})"
                ),
            )

        state_dir = self._build_state_dir(
            state.workspace_dir or Path("."),
            self._session_id(),
        )
        if self._is_complete(state_dir):
            self.deactivate()
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

    @abstractmethod
    def _is_complete(self, state_dir: Path) -> bool:
        """Check if the loop task is complete.

        Args:
            state_dir: Session-scoped directory
                containing state files.
        """

    @staticmethod
    def _build_state_dir(
        workspace_dir: Path,
        sid: str,
    ) -> Path:
        """Session-scoped state directory."""
        return workspace_dir / ".qwenpaw" / "loop_state" / sid


__all__ = ["FileLoopGate"]
