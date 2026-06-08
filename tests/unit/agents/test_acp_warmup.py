# -*- coding: utf-8 -*-
"""Tests for ACP backend-warmup hygiene.

The paw TUI opens a throwaway *warmup* session at startup to spin up the model.
It must leave no trace: the session is flagged ephemeral via ``_meta`` so the
server records the flag, threads it into ``query_handler`` (which then skips
chat auto-registration and state persistence), purges any leaked file on close,
and sweeps pre-existing warmup junk once at workspace boot.
"""

# pylint: disable=protected-access

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from acp import text_block

from qwenpaw.app.channels.schema import DEFAULT_CHANNEL
from qwenpaw.agents.acp.server import (
    ACP_EPHEMERAL_META_KEY,
    QwenPawACPAgent,
    _WARMUP_TITLE_PREFIX,
)


class _FakeConn:
    """Records ``session_update`` calls made by the agent."""

    def __init__(self) -> None:
        self.updates: list[tuple[str, object]] = []

    async def session_update(self, session_id: str, update: object) -> None:
        self.updates.append((session_id, update))


def _agent(tmp_path) -> QwenPawACPAgent:
    agent = QwenPawACPAgent(agent_id="testagent", workspace_dir=tmp_path)
    agent._conn = _FakeConn()

    async def _noop_advertise(session_id: str) -> None:
        return None

    # Skip the background command-advertise task; irrelevant here and it would
    # otherwise import the whole control-command registry.
    agent._advertise_commands = _noop_advertise  # type: ignore[assignment]
    return agent


def _write_session(agent, session_id, turns, *, channel=DEFAULT_CHANNEL):
    """Persist a session file under the channel dir the runner uses."""
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
    directory = (
        agent._sessions_dir() / channel if channel else agent._sessions_dir()
    )
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / agent._session_filename(session_id)
    path.write_text(json.dumps(state), encoding="utf-8")
    return path


@pytest.mark.asyncio
async def test_new_session_records_ephemeral_flag(tmp_path):
    agent = _agent(tmp_path)

    plain = await agent.new_session(cwd="/x")
    flagged = await agent.new_session(
        cwd="/x", **{ACP_EPHEMERAL_META_KEY: True}
    )

    assert agent._sessions[plain.session_id]["ephemeral"] is False
    assert agent._sessions[flagged.session_id]["ephemeral"] is True


@pytest.mark.asyncio
async def test_prompt_threads_ephemeral_into_query_handler(tmp_path):
    agent = _agent(tmp_path)
    sid = "f" * 32
    agent._sessions[sid] = {
        "cwd": "/x",
        "user_id": agent._user_id_for(sid),
        "mode": agent.MODE_DEFAULT,
        "ephemeral": True,
    }

    captured: dict[str, object] = {}

    class _FakeRunner:
        async def query_handler(self, msgs, request=None, **kwargs):
            captured["ephemeral"] = kwargs.get("ephemeral")
            return
            yield  # noqa: W0101 - marks this an (empty) async generator

    async def _fake_ensure():
        return _FakeRunner()

    agent._ensure_workspace = _fake_ensure  # type: ignore[assignment]

    await agent.prompt(prompt=[text_block("hello")], session_id=sid)

    assert captured["ephemeral"] is True


@pytest.mark.asyncio
async def test_close_session_purges_leaked_ephemeral_file(tmp_path):
    agent = _agent(tmp_path)
    sid = "a" * 32
    agent._sessions[sid] = {
        "cwd": "/x",
        "user_id": agent._user_id_for(sid),
        "mode": agent.MODE_DEFAULT,
        "ephemeral": True,
    }
    path = _write_session(agent, sid, [("user", "leaked warmup turn")])
    assert path.exists()

    await agent.close_session(session_id=sid)

    assert not path.exists()


@pytest.mark.asyncio
async def test_close_session_keeps_normal_session_file(tmp_path):
    agent = _agent(tmp_path)
    sid = "b" * 32
    agent._sessions[sid] = {
        "cwd": "/x",
        "user_id": agent._user_id_for(sid),
        "mode": agent.MODE_DEFAULT,
        "ephemeral": False,
    }
    path = _write_session(agent, sid, [("user", "real conversation")])

    await agent.close_session(session_id=sid)

    assert path.exists()


class _FakeChatManager:
    """Minimal ChatManager double recording deletions."""

    def __init__(self, chats):
        self._chats = list(chats)
        self.deleted: list[str] = []

    async def list_chats(self, channel=None):
        return list(self._chats)

    async def delete_chats(self, chat_ids):
        self.deleted.extend(chat_ids)
        self._chats = [c for c in self._chats if c.id not in chat_ids]
        return True


@pytest.mark.asyncio
async def test_purge_legacy_warmup_artifacts(tmp_path):
    agent = _agent(tmp_path)
    warm_id = "1" * 32
    real_id = "2" * 32
    warm_path = _write_session(
        agent,
        warm_id,
        [("user", _WARMUP_TITLE_PREFIX + " for a terminal session.")],
    )
    real_path = _write_session(agent, real_id, [("user", "Fix the bug")])

    chats = [
        # Warmup chat: name is the runner's 10-char truncation of the prompt.
        SimpleNamespace(
            id="chat-warm",
            session_id=warm_id,
            name=_WARMUP_TITLE_PREFIX[:10],
        ),
        SimpleNamespace(
            id="chat-real", session_id=real_id, name="Fix the bug"
        ),
    ]
    chat_manager = _FakeChatManager(chats)
    runner = SimpleNamespace(_chat_manager=chat_manager)

    await agent._purge_legacy_warmup_artifacts(runner)

    # Warmup file removed; the real session file untouched.
    assert not warm_path.exists()
    assert real_path.exists()
    # Warmup chat deleted; the real chat kept.
    assert chat_manager.deleted == ["chat-warm"]
