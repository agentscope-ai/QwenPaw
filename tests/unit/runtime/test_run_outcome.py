# -*- coding: utf-8 -*-
"""Tests for structured SSE run outcome fields."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from qwenpaw.agents.tools.agent_management import is_abnormal_outcome
from qwenpaw.loop.gates.base import StopAction, StopHandlerResult
from qwenpaw.runtime.envelope import Envelope
from qwenpaw.runtime.run_outcome import (
    build_outcome_response,
    consume_run_outcome,
    outcome_from_stop_result,
    record_run_outcome,
    record_run_outcome_from_stop,
)
from qwenpaw.schemas import RunOutcome, RunStatus


async def _finalize_last(envelope: Envelope):
    items = []
    async for obj in envelope.finalize():
        items.append(obj)
    return items[-1]


@pytest.mark.asyncio
async def test_finalize_success_default():
    envelope = Envelope(session_id="sess-1")
    response = await _finalize_last(envelope)
    assert response.outcome == RunOutcome.Success
    assert response.stop_reason is None
    assert response.status == RunStatus.Completed


@pytest.mark.asyncio
async def test_finalize_error_sets_outcome():
    envelope = Envelope(session_id="sess-1")
    items = []
    async for obj in envelope.error_envelope("boom"):
        items.append(obj)
    response = items[-1]
    assert response.outcome == RunOutcome.Error
    assert response.stop_reason == "boom"
    assert response.status == RunStatus.Failed


@pytest.mark.asyncio
async def test_finalize_cancelled():
    envelope = Envelope(session_id="sess-1")
    items = []
    async for obj in envelope.cancel_envelope():
        items.append(obj)
    response = items[-1]
    assert response.outcome == RunOutcome.Cancelled
    assert response.stop_reason == "cancelled"
    assert response.status == RunStatus.Completed


@pytest.mark.asyncio
async def test_exceed_max_iters_sets_outcome():
    from agentscope.event import EventType

    envelope = Envelope(session_id="sess-1")
    event = SimpleNamespace(
        type=EventType.EXCEED_MAX_ITERS,
        name="agent",
    )
    async for _ in envelope.translate_event(event):
        pass
    response = await _finalize_last(envelope)
    assert response.outcome == RunOutcome.MaxIterations
    assert response.stop_reason is not None
    assert "maximum number of iterations" in response.stop_reason


def test_outcome_from_stop_result():
    doom = StopHandlerResult(
        action=StopAction.TERMINATE,
        reason="Doom loop: agent stuck",
        outcome_code="loop_detected",
    )
    assert outcome_from_stop_result(doom) == RunOutcome.LoopDetected

    iteration = StopHandlerResult(
        action=StopAction.TERMINATE,
        reason="Max iterations (20) reached",
        outcome_code="max_iterations",
    )
    assert outcome_from_stop_result(iteration) == RunOutcome.MaxIterations

    continue_result = StopHandlerResult(
        action=StopAction.INTERRUPT_AND_CONTINUE,
        reason="keep going",
    )
    assert outcome_from_stop_result(continue_result) is None


def test_record_and_consume_on_agent():
    agent = SimpleNamespace()
    record_run_outcome(
        agent,
        RunOutcome.LoopDetected,
        "Doom loop: agent stuck",
    )
    outcome, stop_reason = consume_run_outcome(agent)
    assert outcome == RunOutcome.LoopDetected
    assert stop_reason == "Doom loop: agent stuck"
    assert consume_run_outcome(agent) == (RunOutcome.Success, None)


def test_record_run_outcome_from_stop():
    agent = SimpleNamespace()
    record_run_outcome_from_stop(
        agent,
        StopHandlerResult(
            action=StopAction.TERMINATE,
            reason="Max iterations (10) reached",
            outcome_code="max_iterations",
        ),
    )
    outcome, stop_reason = consume_run_outcome(agent)
    assert outcome == RunOutcome.MaxIterations
    assert "Max iterations" in (stop_reason or "")


def test_build_outcome_response():
    response = build_outcome_response(
        "sess-42",
        outcome=RunOutcome.RateLimited,
        stop_reason="quota exceeded",
    )
    assert response.object == "response"
    assert response.session_id == "sess-42"
    assert response.outcome == RunOutcome.RateLimited
    assert response.stop_reason == "quota exceeded"
    assert response.status == RunStatus.Completed


def test_is_abnormal_outcome_helper():
    assert is_abnormal_outcome({"outcome": "success"}) is False
    assert is_abnormal_outcome({"outcome": "cancelled"}) is False
    assert is_abnormal_outcome({"outcome": "loop_detected"}) is True
    assert is_abnormal_outcome({"outcome": "error"}) is True
    assert is_abnormal_outcome({}) is False
