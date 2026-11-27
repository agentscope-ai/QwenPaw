# -*- coding: utf-8 -*-
"""Workspace ownership test for durable per-turn usage."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from qwenpaw.app.chats.transcript import TranscriptStore
from qwenpaw.app.chats.transcript_recorder import (
    TRANSCRIPT_TURN_ID_CONTEXT_KEY,
)
from qwenpaw.app.workspace.workspace import Workspace
from qwenpaw.schemas import AgentRequest


@pytest.mark.asyncio
async def test_command_keeps_projection_without_recharging_transcript():
    previous = {f"total_tokens": 42, f"session_cache_read_tokens": 20}
    session = SimpleNamespace(
        get_current_usage=AsyncMock(return_value=(0, {f"usage": previous})),
        set_current_usage=AsyncMock(),
    )
    store = Mock(spec=TranscriptStore)
    workspace = object.__new__(Workspace)
    workspace.agent_id = f"agent-1"
    workspace._service_manager = (  # pylint: disable=protected-access
        SimpleNamespace(
            services={f"session": session, f"transcript_store": store},
        )
    )
    request = AgentRequest(
        session_id=f"session-1",
        request_context={
            f"conversation_command": f"compact",
            TRANSCRIPT_TURN_ID_CONTEXT_KEY: f"command-turn",
        },
    )
    ctx = {f"estimated_tokens": 21}
    with patch(
        f"qwenpaw.app.workspace.workspace.resolve_turn_usage",
        AsyncMock(return_value=(None, ctx, None)),
    ) as resolve:
        assert await workspace.finalize_turn_usage(request) == (None, ctx)
    assert resolve.await_args.kwargs[f"estimate_missing_usage"] is False
    assert session.set_current_usage.await_args.kwargs[f"usage"] == previous
    assert store.attach_turn_usage.call_args.kwargs[f"usage"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize(f"has_previous", [False, True])
async def test_workspace_persists_and_caches_turn_usage(has_previous) -> None:
    store = Mock(spec=TranscriptStore)
    store.attach_turn_usage.return_value = True
    session = SimpleNamespace(
        set_current_usage=AsyncMock(),
        get_current_usage=AsyncMock(
            return_value=(
                0,
                (
                    {
                        f"usage": {
                            f"session_cache_read_tokens": 100,
                            f"session_cache_eligible_input_tokens": 200,
                            f"session_cache_observed": True,
                        },
                    }
                    if has_previous
                    else None
                ),
            ),
        ),
    )
    workspace = object.__new__(Workspace)
    workspace.agent_id = "agent-1"
    workspace._service_manager = (  # pylint: disable=protected-access
        SimpleNamespace(
            services={
                "session": session,
                "transcript_store": store,
            },
        )
    )
    request = AgentRequest(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        request_context={TRANSCRIPT_TURN_ID_CONTEXT_KEY: "turn-1"},
    )
    usage = {
        f"total_tokens": 42,
        f"cache_read_tokens": 20,
        f"cache_eligible_input_tokens": 40,
        f"cache_observed": True,
    }
    expected = dict(usage)
    if has_previous:
        expected.update(
            session_cache_read_tokens=120,
            session_cache_eligible_input_tokens=240,
            session_cache_observed=True,
            session_cache_hit_rate=50,
        )
    context_usage = {"estimated_tokens": 21}
    resolve = AsyncMock(
        return_value=(usage, context_usage, SimpleNamespace()),
    )
    with patch(
        "qwenpaw.app.workspace.workspace.resolve_turn_usage",
        resolve,
    ):
        first = await workspace.finalize_turn_usage(request)
        second = await workspace.finalize_turn_usage(request)

    assert first == (expected, context_usage)
    assert second == first
    resolve.assert_awaited_once()
    session.get_current_usage.assert_awaited_once()
    session.set_current_usage.assert_awaited_once_with(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        usage=expected,
        context_usage=context_usage,
    )
    store.attach_turn_usage.assert_called_once_with(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        turn_id="turn-1",
        usage=expected,
        context_usage=context_usage,
    )
