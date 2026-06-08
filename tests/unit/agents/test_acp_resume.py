# -*- coding: utf-8 -*-
"""Tests for ACP session resume: list, load and history replay.

The ACP server enumerates resumable paw sessions by scanning the persisted
session files (under the default ``console`` channel sub-dir, where the runner
writes them), filters out empty and backend-warmup sessions, and replays a
loaded session's saved transcript via ``session/update`` notifications.
"""

# pylint: disable=protected-access

from __future__ import annotations

import json

import pytest

from qwenpaw.app.channels.schema import DEFAULT_CHANNEL
from qwenpaw.agents.acp.server import QwenPawACPAgent, _WARMUP_TITLE_PREFIX


class _FakeConn:
    """Records ``session_update`` calls made by the agent."""

    def __init__(self) -> None:
        self.updates: list[tuple[str, object]] = []

    async def session_update(self, session_id: str, update: object) -> None:
        self.updates.append((session_id, update))


def _agent(tmp_path) -> QwenPawACPAgent:
    return QwenPawACPAgent(agent_id="testagent", workspace_dir=tmp_path)


def _write_session(agent, session_id, turns, *, channel=DEFAULT_CHANNEL):
    """Persist a session file under the channel dir the runner uses.

    ``turns`` is a list of (role, content) where content is a string (user) or
    a list of blocks (assistant), mirroring real on-disk message shapes.
    """
    content = [
        [
            {
                "role": role,
                "name": role,
                "content": body,
                "metadata": {},
            },
            [],
        ]
        for role, body in turns
    ]
    state = {"agent": {"memory": {"content": content}}}
    directory = agent._sessions_dir() / channel if channel else (
        agent._sessions_dir()
    )
    directory.mkdir(parents=True, exist_ok=True)
    (directory / agent._session_filename(session_id)).write_text(
        json.dumps(state), encoding="utf-8"
    )


@pytest.mark.asyncio
async def test_list_scans_console_dir_and_titles_from_first_user(tmp_path):
    agent = _agent(tmp_path)
    # Real session in the console channel dir; user content is a plain string.
    _write_session(
        agent,
        "aaaaaaaa" + "0" * 24,
        [
            ("user", "Fix the parser bug"),
            ("assistant", [{"type": "text", "text": "On it."}]),
        ],
    )
    # A backend-warmup session (must be filtered out).
    _write_session(
        agent,
        "bbbbbbbb" + "0" * 24,
        [("user", _WARMUP_TITLE_PREFIX + " for an interactive session.")],
    )
    # An empty session (never prompted) is skipped too.
    _write_session(agent, "cccccccc" + "0" * 24, [])

    infos = await agent.list_persisted_sessions()
    ids = [i.session_id for i in infos]
    assert ids == ["aaaaaaaa" + "0" * 24]
    assert infos[0].title == "Fix the parser bug"
    assert infos[0].updated_at


@pytest.mark.asyncio
async def test_list_is_newest_first(tmp_path):
    agent = _agent(tmp_path)
    older = "11111111" + "0" * 24
    newer = "22222222" + "0" * 24
    _write_session(agent, older, [("user", "older")])
    _write_session(agent, newer, [("user", "newer")])
    # Make `newer` the more recently modified file.
    import os
    import time

    base = agent._sessions_dir() / DEFAULT_CHANNEL
    os.utime(base / agent._session_filename(older), (1_000, 1_000))
    os.utime(base / agent._session_filename(newer), (2_000, 2_000))
    del time

    infos = await agent.list_persisted_sessions()
    assert [i.title for i in infos] == ["newer", "older"]


@pytest.mark.asyncio
async def test_load_session_replays_user_and_assistant_text(tmp_path):
    agent = _agent(tmp_path)
    agent._conn = _FakeConn()
    sid = "dddddddd" + "0" * 24
    _write_session(
        agent,
        sid,
        [
            ("user", "How do I write a loop in Rust?"),
            (
                "assistant",
                [
                    {"type": "thinking", "thinking": "consider for-loops"},
                    {"type": "text", "text": "Use a `for` loop."},
                ],
            ),
            ("user", "Thanks!"),
        ],
    )

    await agent.load_session(cwd="/anywhere", session_id=sid)

    kinds = [getattr(u, "sessionUpdate", None) for _, u in agent._conn.updates]
    texts = [
        getattr(getattr(u, "content", None), "text", None)
        for _, u in agent._conn.updates
    ]
    # Thinking/tool blocks are intentionally dropped; only visible turns shown.
    assert kinds == [
        "user_message_chunk",
        "agent_message_chunk",
        "user_message_chunk",
    ]
    assert texts == [
        "How do I write a loop in Rust?",
        "Use a `for` loop.",
        "Thanks!",
    ]


@pytest.mark.asyncio
async def test_load_session_uses_stable_user_id(tmp_path):
    """A loaded session keeps the deterministic acp user_id so the runner
    reloads the matching persisted state on the next prompt."""
    agent = _agent(tmp_path)
    agent._conn = _FakeConn()
    sid = "eeeeeeee" + "0" * 24
    _write_session(agent, sid, [("user", "hi")])

    await agent.load_session(cwd="/anywhere", session_id=sid)
    assert agent._sessions[sid]["user_id"] == agent._user_id_for(sid)
