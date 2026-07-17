# -*- coding: utf-8 -*-
"""Structured completion rubric gate."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

from agentscope.message import Msg, TextBlock
from pydantic import BaseModel, Field

from .base import StopAction, StopHandlerResult
from .loop_gate import LoopGate


class RubricCriterionResult(BaseModel):
    """One structured evaluator result."""

    id: str
    passed: bool
    score: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)
    feedback: str = ""


class CompletionRubricResult(BaseModel):
    """Structured result returned by the evaluator model."""

    criteria: list[RubricCriterionResult]
    feedback: str = ""


@dataclass
class _CompletionState:
    """Per-turn completion evaluation state."""

    revisions: int = 0
    grader_errors: int = 0
    continuation: str = ""


class CompletionRubricGate(LoopGate):
    """Evaluate completion criteria and request bounded revisions."""

    def __init__(
        self,
        *,
        criteria: list[dict[str, Any]],
        pass_threshold: float = 1.0,
        max_revisions: int = 2,
        include_last_tool_results: int = 5,
        on_grader_error: Literal["stop", "continue_once"] = "stop",
    ) -> None:
        super().__init__()
        self._criteria = criteria
        self._pass_threshold = pass_threshold
        self._max_revisions = max_revisions
        self._evidence_limit = include_last_tool_results
        self._on_grader_error = on_grader_error

    @property
    def name(self) -> str:
        return "completion-rubric"

    @property
    def priority(self) -> int:
        return 90

    def reset_turn(self) -> None:
        """Reset revisions for a new user turn."""
        self.activate(_CompletionState())

    async def check(self, ctx: Any) -> StopHandlerResult:
        """Evaluate text-only completion candidates."""
        if ctx.get("has_tool_calls") or ctx.get("final_msg") is None:
            return StopHandlerResult(action=StopAction.BYPASS)

        state = self._state()
        if state is None:
            state = _CompletionState()
            self.activate(state)

        try:
            result = await self._evaluate(ctx)
        except Exception as exc:  # noqa: BLE001
            return self._handle_grader_error(state, exc)

        passed, score, feedback = self._score(result)
        if passed:
            return StopHandlerResult(
                action=StopAction.TERMINATE,
                reason=f"Completion rubric passed ({score:.0%})",
            )

        if state.revisions >= self._max_revisions:
            return StopHandlerResult(
                action=StopAction.TERMINATE,
                reason=(
                    f"Completion rubric stopped after "
                    f"{self._max_revisions} revisions: {feedback}"
                ),
            )

        state.revisions += 1
        state.continuation = (
            f"The completion check found remaining work. "
            f"Address only these unmet criteria, then verify again:\n"
            f"{feedback}"
        )
        return StopHandlerResult(
            action=StopAction.INTERRUPT_AND_CONTINUE,
            reason=f"Completion rubric requested revision {state.revisions}",
            reset_peers=True,
        )

    def build_continuation(self) -> str:
        """Return the latest bounded evaluator feedback."""
        state = self._state()
        return state.continuation if state is not None else ""

    async def _evaluate(self, ctx: Any) -> CompletionRubricResult:
        """Call the current model through its structured-output API."""
        agent = ctx.get("agent")
        model = getattr(agent, "model", None)
        if model is None:
            raise RuntimeError("Agent model is unavailable for evaluation")

        final_text = self._message_text(ctx.get("final_msg"))
        evidence = self._tool_evidence(agent)
        goal = self._user_goal(agent)
        payload = {
            "user_goal": goal,
            "criteria": self._criteria,
            "candidate_response": final_text,
            "observable_tool_evidence": evidence,
        }
        system_text = (
            "Evaluate only the supplied completion criteria. Use observable "
            "evidence, not claims of completion. Return one result per "
            "criterion. Do not include hidden reasoning."
        )
        user_text = (
            f"Evaluate this completion candidate:\n{json.dumps(payload)}"
        )
        response = await model.generate_structured_output(
            messages=[
                Msg(
                    name="system",
                    role="system",
                    content=[TextBlock(type="text", text=system_text)],
                ),
                Msg(
                    name="user",
                    role="user",
                    content=[TextBlock(type="text", text=user_text)],
                ),
            ],
            structured_model=CompletionRubricResult,
        )
        return CompletionRubricResult.model_validate(response.content)

    def _score(
        self,
        result: CompletionRubricResult,
    ) -> tuple[bool, float, str]:
        """Apply required and weighted criterion semantics."""
        by_id = {item.id: item for item in result.criteria}
        weighted_score = 0.0
        total_weight = 0.0
        unmet: list[str] = []
        required_failed = False
        for criterion in self._criteria:
            criterion_id = str(criterion["id"])
            item = by_id.get(criterion_id)
            weight = float(criterion.get("weight", 1.0))
            total_weight += weight
            if item is not None:
                weighted_score += item.score * weight
            if item is None or not item.passed:
                if criterion.get("required", True):
                    required_failed = True
                detail = item.feedback if item is not None else "Not evaluated"
                unmet.append(f"- {criterion['description']}: {detail}")

        score = weighted_score / total_weight if total_weight else 0.0
        passed = not required_failed and score >= self._pass_threshold
        feedback = "\n".join(unmet) or result.feedback
        return passed, score, feedback

    def _handle_grader_error(
        self,
        state: _CompletionState,
        exc: Exception,
    ) -> StopHandlerResult:
        """Apply the configured fail-closed grader error policy."""
        if (
            self._on_grader_error == "continue_once"
            and not state.grader_errors
        ):
            state.grader_errors += 1
            state.continuation = (
                "The completion evaluator was unavailable. Verify the "
                "deliverable once more before stopping."
            )
            return StopHandlerResult(
                action=StopAction.INTERRUPT_AND_CONTINUE,
                reason=f"Completion evaluator error: {exc}",
                reset_peers=True,
            )
        return StopHandlerResult(
            action=StopAction.TERMINATE,
            reason=f"Completion evaluator error: {exc}",
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
            if block_type == "text":
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
        """Find the latest non-empty user message in agent context."""
        context = getattr(getattr(agent, "state", None), "context", [])
        for message in reversed(context):
            if getattr(message, "role", None) != "user":
                continue
            text = self._message_text(message)
            if text:
                return text
        return ""


__all__ = [
    "CompletionRubricGate",
    "CompletionRubricResult",
    "RubricCriterionResult",
]
