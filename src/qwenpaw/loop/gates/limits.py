# -*- coding: utf-8 -*-
"""Built-in resource limit gates for custom loop modes."""
from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from .base import StopAction, StopHandlerResult
from .loop_gate import LoopGate


def _bypass() -> StopHandlerResult:
    """Return a gate bypass result."""
    return StopHandlerResult(action=StopAction.BYPASS)


@dataclass
class _TokenBudgetState:
    """Per-turn accumulated model usage."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    last_iteration: int = -1


class TokenBudgetGate(LoopGate):
    """Stop a loop when configured token limits are reached."""

    def __init__(
        self,
        *,
        max_total_tokens: int | None = None,
        max_prompt_tokens: int | None = None,
        max_completion_tokens: int | None = None,
    ) -> None:
        super().__init__()
        self._max_total = max_total_tokens
        self._max_prompt = max_prompt_tokens
        self._max_completion = max_completion_tokens

    @property
    def name(self) -> str:
        return "token-budget"

    @property
    def priority(self) -> int:
        return 20

    def reset_turn(self) -> None:
        """Start a fresh per-turn usage accumulator."""
        self.activate(_TokenBudgetState())

    async def check(self, ctx: Any) -> StopHandlerResult:
        """Record the latest model usage and enforce every limit."""
        state = self._state()
        if state is None:
            state = _TokenBudgetState()
            self.activate(state)

        iteration = int(ctx.get("iteration", 0))
        if state.last_iteration != iteration:
            usage = self._current_usage()
            state.prompt_tokens += int(usage.get("prompt_tokens", 0))
            state.completion_tokens += int(
                usage.get("completion_tokens", 0),
            )
            state.last_iteration = iteration

        total = state.prompt_tokens + state.completion_tokens
        exceeded = (
            self._reached(total, self._max_total)
            or self._reached(state.prompt_tokens, self._max_prompt)
            or self._reached(
                state.completion_tokens,
                self._max_completion,
            )
        )
        if not exceeded:
            return _bypass()
        return StopHandlerResult(
            action=StopAction.TERMINATE,
            reason=f"Token budget reached ({total} tokens used)",
        )

    @staticmethod
    def _reached(value: int, limit: int | None) -> bool:
        return limit is not None and value >= limit

    @staticmethod
    def _current_usage() -> dict[str, Any]:
        """Read usage recorded for the current session."""
        from ...app.agent_context import get_current_session_id
        from ...token_usage.model_wrapper import TokenRecordingModelWrapper

        session_id = get_current_session_id()
        if not session_id:
            return {}
        # pylint: disable=protected-access
        return TokenRecordingModelWrapper._usage_by_session.get(
            session_id,
            {},
        )


@dataclass
class _TimeoutState:
    """Monotonic start time for one turn."""

    started_at: float = field(default_factory=time.monotonic)


class TimeoutGate(LoopGate):
    """Stop at a loop boundary after a monotonic timeout."""

    def __init__(self, max_seconds: float) -> None:
        super().__init__()
        self._max_seconds = max_seconds

    @property
    def name(self) -> str:
        return "timeout"

    @property
    def priority(self) -> int:
        return 30

    def reset_turn(self) -> None:
        """Reset elapsed time for a new user turn."""
        self.activate(_TimeoutState())

    async def check(self, ctx: Any) -> StopHandlerResult:  # noqa: ARG002
        """Terminate after the configured elapsed duration."""
        state = self._state()
        if state is None:
            state = _TimeoutState()
            self.activate(state)
        elapsed = time.monotonic() - state.started_at
        if elapsed < self._max_seconds:
            return _bypass()
        return StopHandlerResult(
            action=StopAction.TERMINATE,
            reason=f"Loop time limit reached ({self._max_seconds:g}s)",
        )


@dataclass
class _ToolCallBudgetState:
    """Tool call counts observed during one turn."""

    total: int = 0
    by_tool: Counter[str] = field(default_factory=Counter)
    last_iteration: int = -1


class ToolCallBudgetGate(LoopGate):
    """Limit total and per-tool calls in one agent turn."""

    def __init__(
        self,
        *,
        max_calls: int | None = None,
        per_tool: dict[str, int] | None = None,
    ) -> None:
        super().__init__()
        self._max_calls = max_calls
        self._per_tool = per_tool or {}

    @property
    def name(self) -> str:
        return "tool-call-budget"

    @property
    def priority(self) -> int:
        return 40

    def reset_turn(self) -> None:
        """Reset tool call counters for a new turn."""
        self.activate(_ToolCallBudgetState())

    async def check(self, ctx: Any) -> StopHandlerResult:
        """Count the latest iteration's calls and enforce limits."""
        state = self._state()
        if state is None:
            state = _ToolCallBudgetState()
            self.activate(state)
        iteration = int(ctx.get("iteration", 0))
        if iteration != state.last_iteration:
            names = self._latest_tool_names(ctx.get("agent"))
            state.total += len(names)
            state.by_tool.update(names)
            state.last_iteration = iteration

        if self._max_calls is not None and state.total >= self._max_calls:
            return StopHandlerResult(
                action=StopAction.TERMINATE,
                reason=f"Tool call budget reached ({state.total} calls)",
            )
        for name, limit in self._per_tool.items():
            if state.by_tool[name] >= limit:
                return StopHandlerResult(
                    action=StopAction.TERMINATE,
                    reason=f"Tool '{name}' call budget reached ({limit})",
                )
        return _bypass()

    @staticmethod
    def _latest_tool_names(agent: Any) -> list[str]:
        """Extract tool names from the latest context message with calls."""
        context = getattr(getattr(agent, "state", None), "context", [])
        for message in reversed(context):
            names: list[str] = []
            content = getattr(message, "content", None)
            if not isinstance(content, list):
                continue
            for block in content:
                block_type = (
                    block.get("type")
                    if isinstance(block, dict)
                    else getattr(block, "type", None)
                )
                if block_type not in ("tool_call", "tool_use"):
                    continue
                name = (
                    block.get("name", "")
                    if isinstance(block, dict)
                    else getattr(block, "name", "")
                )
                if name:
                    names.append(str(name))
            if names:
                return names
        return []


__all__ = [
    "TimeoutGate",
    "TokenBudgetGate",
    "ToolCallBudgetGate",
]
