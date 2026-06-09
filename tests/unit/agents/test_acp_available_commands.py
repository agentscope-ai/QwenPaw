# -*- coding: utf-8 -*-
"""Tests for the ACP agent advertising its slash commands.

The ACP server sends an ``available_commands_update`` notification after a
session is created so clients (e.g. the paw TUI) can offer autocompletion.
"""

# pylint: disable=protected-access

from __future__ import annotations

import asyncio

from qwenpaw.agents.acp.server import (
    _ACP_REDUNDANT_COMMANDS,
    ACP_AGENT_META_KEY,
    ACP_ERROR_META_KEY,
    QwenPawACPAgent,
)


class _FakeConn:
    """Records ``session_update`` calls made by the agent."""

    def __init__(self) -> None:
        self.updates: list[tuple[str, object]] = []

    async def session_update(self, session_id: str, update: object) -> None:
        self.updates.append((session_id, update))


async def _drain() -> None:
    """Let the fire-and-forget advertise task run to completion."""
    for _ in range(5):
        await asyncio.sleep(0)


def test_build_available_commands_set():
    commands = QwenPawACPAgent._build_available_commands()
    names = {c.name for c in commands}

    # Exactly the curated subset is advertised: the user-facing conversation
    # commands plus mission and skills. Everything else (history, plan, /new,
    # the ACP-redundant control commands, etc.) is intentionally not
    # advertised.
    assert names == {"clear", "compact", "mission", "skills"}

    # Hidden from the palette: history/plan are internal; /new overlaps the
    # dedicated ACP ``new_session`` affordance (clients start a fresh session
    # natively, and /clear covers the in-session "start over" need).
    assert "history" not in names
    assert "plan" not in names
    assert "new" not in names

    # Commands with a dedicated ACP affordance are not advertised.
    assert names.isdisjoint(_ACP_REDUNDANT_COMMANDS)

    # Every advertised command carries a human-readable description.
    assert all(c.description for c in commands)


async def test_new_session_advertises_commands():
    agent = QwenPawACPAgent(agent_id="default")
    conn = _FakeConn()
    agent.on_connect(conn)

    response = await agent.new_session(cwd="/tmp")
    await _drain()

    assert conn.updates, "expected an available_commands_update notification"
    session_id, update = conn.updates[0]
    assert session_id == response.session_id
    assert update.session_update == "available_commands_update"

    names = {c.name for c in update.available_commands}
    assert "mission" in names
    assert "clear" in names


async def test_load_session_advertises_commands():
    agent = QwenPawACPAgent(agent_id="default")
    conn = _FakeConn()
    agent.on_connect(conn)

    await agent.load_session(cwd="/tmp", session_id="sess-123")
    await _drain()

    assert conn.updates
    session_id, update = conn.updates[0]
    assert session_id == "sess-123"
    assert update.session_update == "available_commands_update"


async def test_new_session_reports_agent_id_in_meta():
    agent = QwenPawACPAgent(agent_id="my-agent")
    conn = _FakeConn()
    agent.on_connect(conn)

    response = await agent.new_session(cwd="/tmp")
    assert response.field_meta == {ACP_AGENT_META_KEY: "my-agent"}


async def test_report_prompt_error_is_sent_to_client():
    agent = QwenPawACPAgent(agent_id="default")
    conn = _FakeConn()
    agent.on_connect(conn)

    await agent._report_prompt_error(
        "sess-err",
        RuntimeError("boom: invalid api key"),
    )

    assert conn.updates
    session_id, update = conn.updates[0]
    assert session_id == "sess-err"
    # Delivered as a visible assistant message chunk with the error text...
    assert update.session_update == "agent_message_chunk"
    assert "boom: invalid api key" in update.content.text
    # ...tagged via _meta so clients can render it as an error.
    assert update.field_meta == {ACP_ERROR_META_KEY: True}
