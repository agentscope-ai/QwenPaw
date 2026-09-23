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
async def test_workspace_persists_and_caches_turn_usage() -> None:
    store = Mock(spec=TranscriptStore)
    store.attach_turn_usage.return_value = True
    session = SimpleNamespace()
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
    usage = {"total_tokens": 42}
    context_usage = {"estimated_tokens": 21}
    resolve = AsyncMock(
        return_value=(usage, context_usage, SimpleNamespace()),
    )
    persist = AsyncMock()

    with patch(
        "qwenpaw.app.workspace.workspace.resolve_turn_usage",
        resolve,
    ), patch(
        "qwenpaw.app.workspace.workspace.persist_turn_usage",
        persist,
    ):
        first = await workspace.finalize_turn_usage(request)
        second = await workspace.finalize_turn_usage(request)

    assert first == (usage, context_usage)
    assert second == first
    resolve.assert_awaited_once()
    persist.assert_awaited_once()
    store.attach_turn_usage.assert_called_once_with(
        session_id="session-1",
        turn_id="turn-1",
        usage=usage,
        context_usage=context_usage,
    )
