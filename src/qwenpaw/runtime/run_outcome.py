# -*- coding: utf-8 -*-
"""Helpers for recording and consuming structured run outcomes."""

from __future__ import annotations

from typing import Any

from ..loop.gates.base import StopAction, StopHandlerResult
from ..schemas import RunOutcome

_OUTCOME_ATTR = "_run_outcome"

# Text patterns used when gates omit ``outcome_code``.
_REASON_PATTERNS: tuple[tuple[str, RunOutcome], ...] = (
    ("doom loop", RunOutcome.LoopDetected),
    ("max iterations", RunOutcome.MaxIterations),
)


def outcome_from_stop_result(
    result: StopHandlerResult,
) -> RunOutcome | None:
    """Map a gate stop result to a run outcome, if abnormal."""
    if result.action != StopAction.TERMINATE:
        return None

    if result.outcome_code:
        try:
            return RunOutcome(result.outcome_code)
        except ValueError:
            pass

    reason = (result.reason or "").lower()
    for pattern, outcome in _REASON_PATTERNS:
        if pattern in reason:
            return outcome
    return None


def record_run_outcome(
    agent: Any,
    outcome: RunOutcome,
    stop_reason: str | None = None,
) -> None:
    """Persist outcome on *agent* for runtime finalize."""
    setattr(
        agent,
        _OUTCOME_ATTR,
        {
            "outcome": outcome,
            "stop_reason": stop_reason,
        },
    )


def record_run_outcome_from_stop(
    agent: Any,
    result: StopHandlerResult,
) -> None:
    """Record outcome from a gate ``StopHandlerResult`` when applicable."""
    outcome = outcome_from_stop_result(result)
    if outcome is not None:
        record_run_outcome(agent, outcome, result.reason or None)


def consume_run_outcome(
    agent: Any,
) -> tuple[RunOutcome, str | None]:
    """Read and clear the outcome stored on *agent*."""
    payload = getattr(agent, _OUTCOME_ATTR, None)
    if payload is None:
        return RunOutcome.Success, None
    setattr(agent, _OUTCOME_ATTR, None)
    outcome = payload.get("outcome", RunOutcome.Success)
    if isinstance(outcome, str):
        try:
            outcome = RunOutcome(outcome)
        except ValueError:
            outcome = RunOutcome.Success
    stop_reason = payload.get("stop_reason")
    return outcome, stop_reason


def build_outcome_response(
    session_id: str,
    *,
    outcome: RunOutcome,
    stop_reason: str | None = None,
    status: Any = None,
) -> Any:
    """Build a terminal ``AgentResponse`` for non-runtime paths."""
    from datetime import datetime, timezone
    from uuid import uuid4

    from ..schemas import AgentResponse, RunStatus

    if status is None:
        status = RunStatus.Completed
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    response = AgentResponse(
        output=[],
        status=status,
        outcome=outcome,
        stop_reason=stop_reason,
        created_at=now,
        completed_at=now,
    )
    response.object = "response"
    response.id = "response_" + uuid4().hex
    response.session_id = session_id
    return response


__all__ = [
    "build_outcome_response",
    "consume_run_outcome",
    "outcome_from_stop_result",
    "record_run_outcome",
    "record_run_outcome_from_stop",
]
