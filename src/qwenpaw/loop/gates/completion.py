# -*- coding: utf-8 -*-
"""Agent-native completion rubric gate."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

from ...constant import (
    QWENPAW_MESSAGE_TAG_KEY,
    RUBRIC_EVALUATION_MESSAGE_TAG,
    SYNTHETIC_USER_MESSAGE_TAGS,
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
        include_last_tool_results: int = 5,
    ) -> None:
        super().__init__()
        self._prompt = prompt
        self._completion_signal = completion_signal.strip()
        self._continuation_prompt = continuation_prompt
        self._max_evaluations = max_evaluations
        self._evidence_limit = include_last_tool_results

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
        state.continuation = self._evaluation_prompt(ctx.get("agent"))
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

    def _evaluation_prompt(self, agent: Any) -> str:
        """Build the completion check request for the active agent."""
        payload = {
            "user_goal": self._user_goal(agent),
            "rubric_prompt": self._prompt,
            "observable_tool_evidence": self._tool_evidence(agent),
        }
        return (
            f"Evaluate your latest candidate using the supplied rubric. "
            f"Do not invent unstated requirements. If the candidate passes, "
            f"reply with exactly this completion signal and nothing else: "
            f"{self._completion_signal}\n"
            f"If it does not pass, return anything except the completion "
            f"signal. Do not call tools or continue the task during this "
            f"evaluation step.\n"
            f"{json.dumps(payload, ensure_ascii=False)}"
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

    def _tool_evidence(self, agent: Any) -> list[str]:
        """Collect recent observable tool result text."""
        if self._evidence_limit == 0:
            return []
        evidence: list[str] = []
        context = getattr(getattr(agent, "state", None), "context", [])
        for message in reversed(context):
            content = getattr(message, "content", None)
            for block in content if isinstance(content, list) else []:
                block_type = (
                    block.get("type")
                    if isinstance(block, dict)
                    else getattr(block, "type", None)
                )
                if block_type not in ("tool_result", "tool_output"):
                    continue
                evidence.append(str(block)[:2000])
                if len(evidence) >= self._evidence_limit:
                    return evidence
        return evidence

    def _user_goal(self, agent: Any) -> str:
        """Find the latest external user request in agent context."""
        context = getattr(getattr(agent, "state", None), "context", [])
        for message in reversed(context):
            if getattr(message, "role", None) != "user":
                continue
            metadata = getattr(message, "metadata", None) or {}
            if metadata.get(QWENPAW_MESSAGE_TAG_KEY) in (
                SYNTHETIC_USER_MESSAGE_TAGS
            ):
                continue
            text = self._message_text(message)
            if text:
                return text
        return ""


__all__ = ["CompletionRubricGate"]
