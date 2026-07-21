# -*- coding: utf-8 -*-
"""Agent-native completion rubric gate."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from ...constant import (
    QWENPAW_MESSAGE_TAG_KEY,
    RUBRIC_EVALUATION_MESSAGE_TAG,
)
from .base import StopAction, StopHandlerResult
from .loop_gate import LoopGate


@dataclass
class _CompletionRubricState:
    """Per-turn candidate and evaluation state."""

    phase: Literal["candidate", "evaluation"] = "candidate"
    evaluations: int = 0
    candidate: Any = None
    continuation: str = ""


class CompletionRubricGate(LoopGate):
    """Ask the active agent for a configurable completion signal."""

    def __init__(
        self,
        *,
        prompt: str,
        completion_signal: str = "COMPLETED",
        continuation_prompt: str = (
            "Address the remaining work, then verify completion again."
        ),
        max_evaluations: int = 3,
    ) -> None:
        super().__init__()
        self._prompt = prompt
        self._completion_signal = completion_signal.strip()
        self._continuation_prompt = continuation_prompt
        self._max_evaluations = max_evaluations

    @property
    def name(self) -> str:
        return "completion-rubric"

    @property
    def priority(self) -> int:
        return 90

    def reset_turn(self) -> None:
        """Start a fresh candidate/evaluation cycle."""
        self.activate(_CompletionRubricState())

    async def check(self, ctx: Any) -> StopHandlerResult:
        """Request or consume an agent-native completion evaluation."""
        if ctx.get("has_tool_calls") or ctx.get("final_msg") is None:
            return StopHandlerResult(action=StopAction.BYPASS)

        state = self._state()
        if state is None:
            state = _CompletionRubricState()
            self.activate(state)

        if state.phase == "evaluation":
            return self._consume_evaluation(state, ctx.get("final_msg"))

        state.candidate = ctx.get("final_msg")
        state.phase = "evaluation"
        state.evaluations += 1
        state.continuation = self._evaluation_prompt()
        return StopHandlerResult(
            action=StopAction.INTERRUPT_AND_CONTINUE,
            reason="completion rubric requested agent evaluation",
            reset_peers=True,
            continuation_metadata={
                QWENPAW_MESSAGE_TAG_KEY: RUBRIC_EVALUATION_MESSAGE_TAG,
            },
        )

    def build_continuation(self) -> str:
        """Return the current evaluation or revision instruction."""
        state = self._state()
        return state.continuation if state is not None else ""

    def _consume_evaluation(
        self,
        state: _CompletionRubricState,
        message: Any,
    ) -> StopHandlerResult:
        """Compare the Agent output with the configured completion signal."""
        output = self._message_text(message).strip().casefold()
        signal = self._completion_signal.casefold()
        if output == signal:
            return StopHandlerResult(
                action=StopAction.TERMINATE,
                reason="Completion rubric passed",
                final_message=state.candidate,
            )

        if state.evaluations >= self._max_evaluations:
            return StopHandlerResult(
                action=StopAction.TERMINATE,
                reason=(
                    f"Completion rubric stopped after "
                    f"{state.evaluations} evaluations"
                ),
                final_message=state.candidate,
            )

        state.phase = "candidate"
        state.continuation = self._continuation_prompt
        return StopHandlerResult(
            action=StopAction.INTERRUPT_AND_CONTINUE,
            reason=(
                f"completion rubric requested revision after evaluation "
                f"{state.evaluations}"
            ),
            reset_peers=True,
        )

    def _evaluation_prompt(self) -> str:
        """Build the completion check request for the active agent."""
        return (
            f"Evaluate your latest candidate against this completion rubric:\n"
            f"{self._prompt}\n"
            f"Do not invent unstated requirements. If the candidate is "
            f"complete, output {self._completion_signal} only, with no other "
            f"text. If it is incomplete, output anything except that exact "
            f"completion signal. Do not call tools or continue the task "
            f"during this evaluation step."
        )

    @staticmethod
    def _message_text(message: Any) -> str:
        """Extract text blocks from one message."""
        content = getattr(message, "content", None)
        if isinstance(content, str):
            return content
        texts: list[str] = []
        for block in content or []:
            block_type = (
                block.get("type")
                if isinstance(block, dict)
                else getattr(block, "type", None)
            )
            if block_type != "text":
                continue
            text = (
                block.get("text", "")
                if isinstance(block, dict)
                else getattr(block, "text", "")
            )
            if text:
                texts.append(str(text))
        return "\n".join(texts)


__all__ = ["CompletionRubricGate"]
