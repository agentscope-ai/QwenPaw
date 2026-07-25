# -*- coding: utf-8 -*-
"""DoomLoopGate: session-safe doom loop detection.

Inherits LoopGate for per-session state isolation.
Includes inline sliding-window similarity detection.
"""
from __future__ import annotations

import hashlib
import json
import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from .base import (
    StopAction,
    StopHandlerResult,
)
from .loop_gate import LoopGate

logger = logging.getLogger(__name__)


@dataclass
class _ToolCallRecord:
    """One recorded tool call for pattern analysis."""

    tool_name: str
    args_hash: str


@dataclass
class _DoomState:
    """Per-session doom loop state."""

    history: deque = field(default_factory=deque)
    consecutive_hits: int = 0
    prompt: str = ""
    last_recorded_iter: int = -1


class DoomLoopGate(LoopGate):
    """Multi-stage doom loop gate (session-safe).

    Sliding-window repetition detection that escalates
    through configured stages.

    - action="modify_prompt": INTERRUPT_AND_CONTINUE,
      inject warning via build_continuation().
    - action="stop": return TERMINATE immediately.
    """

    @property
    def name(self) -> str:
        return "doom-loop"

    @property
    def priority(self) -> int:
        return 5

    def __init__(
        self,
        *,
        window_size: int = 3,
        similarity_threshold: float = 1.0,
        stages: list | None = None,
    ) -> None:
        super().__init__()
        self._window_size = max(2, window_size)
        self._threshold = similarity_threshold
        self._stages = sorted(
            stages or [],
            key=lambda s: s.after,
        )

    def _ensure_state(self) -> _DoomState:
        """Get or create per-session state."""
        state = self._state()
        if state is None:
            state = _DoomState(
                history=deque(
                    maxlen=self._window_size * 2,
                ),
            )
            self.activate(state)
        return state

    def record(
        self,
        tool_name: str,
        args_hash: str,
    ) -> None:
        """Record a completed tool call."""
        state = self._ensure_state()
        state.history.append(
            _ToolCallRecord(
                tool_name=tool_name,
                args_hash=args_hash,
            ),
        )

    def reset_turn(self) -> None:
        """Clear history and counters for current session."""
        state = self._state()
        if state is not None:
            state.history.clear()
            state.consecutive_hits = 0
            state.prompt = ""
            state.last_recorded_iter = -1

    async def check(
        self,
        ctx: Any,
    ) -> StopHandlerResult:
        """Evaluate doom loop state.

        Auto-records tool calls from agent context when
        available (no explicit record() needed).
        """
        _bypass = StopHandlerResult(
            action=StopAction.BYPASS,
        )
        state = self._ensure_state()
        self._auto_record_from_ctx(ctx, state)

        is_looping = self._detect_repetition(state)

        if not is_looping:
            state.consecutive_hits = 0
            state.prompt = ""
            return _bypass

        if state.consecutive_hits == 0:
            state.consecutive_hits = self._window_size
        else:
            state.consecutive_hits += 1

        active_stage = None
        for stage in reversed(self._stages):
            if state.consecutive_hits >= stage.after:
                active_stage = stage
                break

        if active_stage is None:
            return _bypass

        if active_stage.action == "stop":
            logger.info(
                "DoomLoopGate: STOP after %d hits",
                state.consecutive_hits,
            )
            return StopHandlerResult(
                action=StopAction.TERMINATE,
                reason=active_stage.prompt,
            )

        state.prompt = active_stage.prompt
        logger.warning(
            "DoomLoopGate: warning at %d hits",
            state.consecutive_hits,
        )
        return StopHandlerResult(
            action=StopAction.INTERRUPT_AND_CONTINUE,
            reason="doom_loop repetition warning",
        )

    def build_continuation(self) -> str:
        """Return current doom loop warning."""
        state = self._state()
        if state is None:
            return ""
        return state.prompt

    def _auto_record_from_ctx(
        self,
        ctx: Any,
        state: _DoomState,
    ) -> None:
        """Extract latest tool call from agent context."""
        if not isinstance(ctx, dict):
            return
        agent = ctx.get("agent")
        if agent is None:
            return
        cur_iter = ctx.get("iteration", 0)
        if cur_iter <= state.last_recorded_iter:
            return
        state.last_recorded_iter = cur_iter

        context = getattr(
            getattr(agent, "state", None),
            "context",
            [],
        )
        if not context:
            return
        last_msg = context[-1]
        content = getattr(last_msg, "content", None)
        if not content or not isinstance(content, list):
            return
        for block in reversed(content):
            btype = getattr(block, "type", None)
            if isinstance(block, dict):
                btype = block.get("type")
            if btype in ("tool_call", "tool_use"):
                name = (
                    block.get("name", "")
                    if isinstance(block, dict)
                    else getattr(block, "name", "")
                )
                raw_input = (
                    block.get("input", "")
                    if isinstance(block, dict)
                    else getattr(block, "input", "")
                )
                args_hash = self._hash_args(raw_input)
                state.history.append(
                    _ToolCallRecord(
                        tool_name=name,
                        args_hash=args_hash,
                    ),
                )
                return

    @staticmethod
    def _hash_args(raw_input: Any) -> str:
        """Hash tool call args with truncation for large inputs.

        Only the first 2048 bytes are hashed — enough
        for repetition detection without serializing
        potentially large file contents.
        """
        _MAX_HASH_INPUT = 2048
        if isinstance(raw_input, str):
            data = raw_input[:_MAX_HASH_INPUT].encode()
        else:
            data = json.dumps(
                raw_input,
                sort_keys=True,
                default=str,
            ).encode()[:_MAX_HASH_INPUT]
        return hashlib.md5(data).hexdigest()[:8]

    def _detect_repetition(
        self,
        state: _DoomState,
    ) -> bool:
        """Check sliding window for repetition."""
        if len(state.history) < self._window_size:
            return False

        window = list(state.history)[-self._window_size :]
        similarity = self._compute_similarity(window)

        if similarity >= self._threshold:
            logger.warning(
                "Doom loop: sim=%.2f thr=%.2f",
                similarity,
                self._threshold,
            )
            return True
        return False

    @staticmethod
    def _compute_similarity(
        window: list[_ToolCallRecord],
    ) -> float:
        """Compute action pattern similarity.

        Formula: 1 - (unique - 1) / (total - 1)

        Precondition: ``len(window) >= 2``.
        Callers must ensure this; ``_detect_repetition``
        guards via ``len(history) < window_size``
        where ``window_size >= 2``.
        """
        if not window or len(window) <= 1:
            return 0.0

        sigs = [f"{r.tool_name}:{r.args_hash}" for r in window]
        unique = len(set(sigs))
        total = len(sigs)
        return 1.0 - (unique - 1) / (total - 1)


__all__ = ["DoomLoopGate"]
