# -*- coding: utf-8 -*-
"""Live context accounting uses message and summary estimates."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agentscope.agent import Agent

from qwenpaw.agents import react_agent
from qwenpaw.token_usage.model_wrapper import (
    TokenRecordingModelWrapper,
    set_conversation_context_tokens,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(f"fails", [False, True])
async def test_prepare_captures_context_without_provider_prompt(
    monkeypatch,
    fails,
):
    agent = object.__new__(react_agent.QwenPawAgent)
    agent.state = SimpleNamespace(context=[], summary=f"summary")
    agent.model = SimpleNamespace(context_size=1000)
    prepared = {f"messages": [{f"content": f"system and tools"}]}
    monkeypatch.setattr(
        Agent,
        f"_prepare_model_input",
        AsyncMock(return_value=prepared),
    )
    monkeypatch.setattr(
        react_agent,
        f"freeze_local_images_async",
        AsyncMock(),
    )
    estimate = AsyncMock(
        return_value={f"estimated_tokens": 123},
        side_effect=ValueError(f"estimate failed") if fails else None,
    )
    monkeypatch.setattr(react_agent, f"estimate_context_tokens", estimate)
    captured = []
    monkeypatch.setattr(
        react_agent,
        f"set_conversation_context_tokens",
        captured.append,
    )

    assert await agent._prepare_model_input() is prepared
    assert estimate.await_args.args[0] is agent.state
    assert estimate.await_args.args[2] == 1000
    assert captured == ([None] if fails else [None, 123])


@pytest.mark.asyncio
async def test_context_snapshot_survives_prepare_task_boundary(monkeypatch):
    session_id = f"context-task-boundary"
    monkeypatch.setattr(
        f"qwenpaw.app.agent_context.get_current_session_id",
        lambda: session_id,
    )

    async def prepare():
        set_conversation_context_tokens(321)

    await asyncio.create_task(prepare())
    snapshot = TokenRecordingModelWrapper.peek_usage_for_session(session_id)
    assert snapshot == {f"context_tokens": 321}
    assert TokenRecordingModelWrapper.pop_usage_for_session(session_id) is None
    assert (
        TokenRecordingModelWrapper.peek_usage_for_session(session_id) is None
    )
