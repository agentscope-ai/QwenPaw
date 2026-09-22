# -*- coding: utf-8 -*-
"""Workspace ownership tests for durable per-turn usage."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from qwenpaw.app.chats.transcript import TranscriptStore
from qwenpaw.app.chats.transcript_recorder import (
    TRANSCRIPT_TURN_ID_CONTEXT_KEY,
)
from qwenpaw.app.workspace.workspace import Workspace
from qwenpaw.schemas import AgentRequest, Message, TextContent
from qwenpaw.token_usage.turn_usage import TURN_USAGE_META_KEY


@pytest.mark.asyncio
async def test_workspace_persists_and_caches_turn_usage(tmp_path) -> None:
    store = TranscriptStore(tmp_path / "session.db")
    store.start_turn(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        turn_id="turn-1",
    )
    store.upsert_message(
        session_id="session-1",
        turn_id="turn-1",
        message=Message(
            id="assistant-1",
            role="assistant",
            content=[TextContent(text="answer")],
        ).completed(),
        ordinal=0,
    )
    store.finish_turn(
        session_id="session-1",
        turn_id="turn-1",
        status="completed",
    )
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
    usage = {"total_tokens": 42, "cache_hit_rate": 80.0}
    context_usage = {
        "estimated_tokens": 21,
        "max_input_length": 1000,
        "context_usage_ratio": 2.1,
    }
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
    page = store.get_page(
        session_id="session-1",
        user_id="user-1",
        channel="console",
    )
    assert page is not None
    metadata = page.messages[0].metadata
    assert metadata is not None
    assert metadata[TURN_USAGE_META_KEY] == {
        "usage": usage,
        "context_usage": context_usage,
    }
    store.close()


@pytest.mark.asyncio
async def test_workspace_transcript_write_survives_session_failure(
    tmp_path,
) -> None:
    store = TranscriptStore(tmp_path / "session.db")
    store.start_turn(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        turn_id="turn-1",
    )
    store.upsert_message(
        session_id="session-1",
        turn_id="turn-1",
        message=Message(
            id="assistant-1",
            role="assistant",
            content=[TextContent(text="answer")],
        ).completed(),
        ordinal=0,
    )
    store.finish_turn(
        session_id="session-1",
        turn_id="turn-1",
        status="completed",
    )
    workspace = object.__new__(Workspace)
    workspace.agent_id = "agent-1"
    workspace._service_manager = (  # pylint: disable=protected-access
        SimpleNamespace(
            services={
                "session": SimpleNamespace(),
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

    with patch(
        "qwenpaw.app.workspace.workspace.resolve_turn_usage",
        AsyncMock(return_value=({"total_tokens": 7}, None, object())),
    ), patch(
        "qwenpaw.app.workspace.workspace.persist_turn_usage",
        AsyncMock(side_effect=OSError("session unavailable")),
    ):
        result = await workspace.finalize_turn_usage(request)

    assert result == ({"total_tokens": 7}, None)
    page = store.get_page(
        session_id="session-1",
        user_id="user-1",
        channel="console",
    )
    assert page is not None
    assert page.messages[0].metadata[TURN_USAGE_META_KEY]["usage"] == {
        "total_tokens": 7,
    }
    store.close()


@pytest.mark.asyncio
async def test_workspace_session_write_survives_transcript_failure() -> None:
    store = Mock(spec=TranscriptStore)
    store.attach_turn_usage.side_effect = OSError("transcript unavailable")
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
    persist = AsyncMock()

    with patch(
        "qwenpaw.app.workspace.workspace.resolve_turn_usage",
        AsyncMock(return_value=({"total_tokens": 7}, None, object())),
    ), patch(
        "qwenpaw.app.workspace.workspace.persist_turn_usage",
        persist,
    ):
        result = await workspace.finalize_turn_usage(request)

    assert result == ({"total_tokens": 7}, None)
    persist.assert_awaited_once()
    store.attach_turn_usage.assert_called_once()
