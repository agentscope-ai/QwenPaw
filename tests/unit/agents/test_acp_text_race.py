# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Regression tests for the ACP text-dropping race condition.

When a ``session/update`` notification and the ``session/prompt`` response
arrive in the same TCP segment, the ACP transport resolves the prompt future
inline while the notification runner is still queued as a separate task.
``finish_prompt()`` can then observe an empty ``_assistant_text`` and drop the
final text (surfacing as "completed without text output" in
``delegate_external_agent``).

These tests pin the two fixes:
1. client: AgentMessageChunk notifications set an event signalling new text
   is available; the event is waited on (with timeout) before finish_prompt().
2. service: _wait_for_prompt_outcome() waits on the client's event with a
   bounded timeout, then retries finish_prompt() if it returned no text.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from qwenpaw.agents.acp.client import ACPHostedClient
from qwenpaw.agents.acp.service import ACPService
from qwenpaw.config.config import ACPAgentConfig, ACPConfig


def _make_client(*, trusted: bool = True) -> ACPHostedClient:
    config = ACPAgentConfig(
        enabled=True,
        command="test",
        trusted=trusted,
        tool_parse_mode="call_title",
    )
    return ACPHostedClient(
        agent_name="test-agent",
        agent_config=config,
        cwd="/tmp",
    )


def _chunk(text: str):
    from acp import text_block
    from acp.schema import AgentMessageChunk

    return AgentMessageChunk(
        sessionUpdate="agent_message_chunk",
        content=text_block(text),
    )


class TestACPAssistantTextEmission:
    """AgentMessageChunk must signal new text availability."""

    @pytest.mark.asyncio
    async def test_agent_message_chunk_sets_event(self) -> None:
        client = _make_client()

        # Event should be clear initially
        assert not client._assistant_text_event.is_set()

        await client.session_update(
            session_id="sess-1",
            update=_chunk("Hello from ACP"),
        )

        # Event should be set after processing a chunk
        assert client._assistant_text_event.is_set()

    @pytest.mark.asyncio
    async def test_finish_prompt_returns_accumulated_text(self) -> None:
        client = _make_client()

        await client.session_update(
            session_id="sess-1",
            update=_chunk("final answer"),
        )

        result = await client.finish_prompt()
        assert result is not None
        assert result["type"] == "text"
        assert result["text"] == "final answer"


class TestACPServicePromptOutcomeWait:
    """_wait_for_prompt_outcome waits on client event before finish_prompt()."""

    @pytest.mark.asyncio
    async def test_waits_on_event_before_finish_prompt(self) -> None:
        client = _make_client()
        client._on_message = AsyncMock()  # noqa: W0212

        # A notification that is still queued when the prompt response resolves
        async def queued_notification() -> None:
            await client.session_update(
                session_id="sess-1",
                update=_chunk("late arrival"),
            )

        notification_task = asyncio.create_task(queued_notification())

        async def prompt_done() -> None:
            # Resolve the prompt future without waiting for the queued
            # notification, mirroring the transport's inline response path.
            await asyncio.sleep(0)

        conversation = SimpleNamespace(
            prompt_task=asyncio.create_task(prompt_done()),
            client=client,
        )

        observed: dict = {}
        original_finish = client.finish_prompt

        async def finish_probe() -> dict | None:
            observed["assistant_text"] = client._assistant_text  # noqa: W0212
            return await original_finish()

        client.finish_prompt = finish_probe  # type: ignore[method-assign]
        service = ACPService(config=ACPConfig())
        try:
            result = await service._wait_for_prompt_outcome(  # noqa: W0212
                conversation=conversation,  # type: ignore[arg-type]
                on_message=AsyncMock(),
            )
        finally:
            client.finish_prompt = original_finish  # type: ignore
            notification_task.cancel()
            try:
                await notification_task
            except asyncio.CancelledError:
                pass

        assert result["status"] == "completed"
        assert observed.get("assistant_text"), (
            "finish_prompt() should observe text that arrived via a "
            "notification queued before the prompt response resolved"
        )

    @pytest.mark.asyncio
    async def test_retries_finish_prompt_if_first_returns_none(self) -> None:
        """If finish_prompt() returns None but event is set, retry once."""
        client = _make_client()

        # Pre-set the event (simulating chunks arrived) but don't actually
        # add any text yet - this mimics a race where the notification
        # task hasn't quite flushed _assistant_text when finish_prompt()
        # is first called.
        client._assistant_text_event.set()

        # First call to finish_prompt should return None (no text yet)
        result1 = await client.finish_prompt()
        assert result1 is None

        # Now add text (as if notification task flushed)
        await client.session_update(
            session_id="sess-1",
            update=_chunk("recovered text"),
        )

        # Second call should return the text
        result2 = await client.finish_prompt()
        assert result2 is not None
        assert result2["text"] == "recovered text"