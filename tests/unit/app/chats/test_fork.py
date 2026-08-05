# -*- coding: utf-8 -*-
"""Unit tests for chat forking: ChatManager.fork_chat + SafeJSONSession
clone_session_state / delete_session_state.

Uses the real :class:`JsonChatRepository` and :class:`SafeJSONSession`
backed by ``tmp_path``.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

from pathlib import Path

import pytest

from qwenpaw.app.chats.manager import ChatManager
from qwenpaw.app.chats.models import ChatSpec, SessionSource
from qwenpaw.app.chats.repo import JsonChatRepository
from qwenpaw.app.chats.session import SafeJSONSession


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _DummyModule:
    """Minimal state module for testing SafeJSONSession."""

    def __init__(self, state: dict) -> None:
        self._state = state

    def state_dict(self) -> dict:
        return self._state

    def load_state_dict(self, data: dict) -> None:
        self._state = data


def _make_spec(
    *,
    chat_id: str | None = None,
    session_id: str = "console:u1",
    user_id: str = "u1",
    name: str = "Test Chat",
    source: SessionSource = SessionSource.chat,
    meta: dict | None = None,
) -> ChatSpec:
    kwargs: dict = {
        "session_id": session_id,
        "user_id": user_id,
        "name": name,
        "source": source,
    }
    if chat_id is not None:
        kwargs["id"] = chat_id
    if meta is not None:
        kwargs["meta"] = meta
    return ChatSpec(**kwargs)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def repo_path(tmp_path: Path) -> Path:
    return tmp_path / "chats.json"


@pytest.fixture
def sessions_dir(tmp_path: Path) -> Path:
    p = tmp_path / "sessions"
    p.mkdir()
    return p


@pytest.fixture
def manager(repo_path: Path) -> ChatManager:
    return ChatManager(repo=JsonChatRepository(repo_path))


@pytest.fixture
def session(sessions_dir: Path) -> SafeJSONSession:
    return SafeJSONSession(save_dir=str(sessions_dir))


# ---------------------------------------------------------------------------
# ChatManager.fork_chat
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fork_creates_independent_spec(manager: ChatManager):
    """Fork creates a new ChatSpec with lineage metadata."""
    source = await manager.create_chat(
        _make_spec(
            session_id="console:u1",
            user_id="u1",
            name="Source",
            meta={"custom": "value"},
        ),
    )

    forked = await manager.fork_chat(
        source_chat_id=source.id,
        new_session_id="console:u1:fork-abc12345",
        name="Fork of Source",
    )

    assert forked.id != source.id
    assert forked.name == "Fork of Source"
    assert forked.session_id == "console:u1:fork-abc12345"
    assert forked.user_id == source.user_id
    assert forked.channel == source.channel
    assert forked.source == SessionSource.chat
    # lineage
    assert forked.meta["forked_from_chat_id"] == source.id
    assert forked.meta["forked_from_session_id"] == source.session_id
    assert "forked_at" in forked.meta
    # deep copy — original meta preserved
    assert forked.meta["custom"] == "value"
    # original source meta unchanged
    assert source.meta == {"custom": "value"}


@pytest.mark.asyncio
async def test_fork_raises_on_unknown_source(manager: ChatManager):
    with pytest.raises(ValueError, match="Source chat not found"):
        await manager.fork_chat(
            source_chat_id="nonexistent-id",
            new_session_id="console:u1:fork-00000000",
            name="Ghost",
        )


@pytest.mark.asyncio
async def test_fork_meta_deep_copy_independence(manager: ChatManager):
    """Mutating source.meta after fork doesn't affect forked meta."""
    source = await manager.create_chat(
        _make_spec(
            session_id="console:u1",
            user_id="u1",
            name="Source",
            meta={"a": 1},
        ),
    )

    forked = await manager.fork_chat(
        source_chat_id=source.id,
        new_session_id="console:u1:fork-xyz",
        name="Fork",
    )

    source.meta["a"] = 999
    source.meta["b"] = 2

    assert forked.meta["a"] == 1
    assert "b" not in forked.meta


# ---------------------------------------------------------------------------
# SafeJSONSession.clone_session_state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clone_session_state_copies_full_state(
    session: SafeJSONSession,
):
    """Full state dict is copied to the new session file."""
    await session.save_session_state(
        session_id="src-session",
        user_id="u1",
        dummy=_DummyModule({"key": "value", "nested": {"x": 1}}),
    )

    await session.clone_session_state(
        src_session_id="src-session",
        dst_session_id="dst-session",
        user_id="u1",
    )

    dst_state = await session.get_session_state_dict(
        "dst-session",
        user_id="u1",
    )
    assert dst_state == {"dummy": {"key": "value", "nested": {"x": 1}}}


@pytest.mark.asyncio
async def test_clone_raises_when_source_missing(
    session: SafeJSONSession,
):
    with pytest.raises(FileNotFoundError):
        await session.clone_session_state(
            src_session_id="nonexistent",
            dst_session_id="dst",
            user_id="u1",
        )


@pytest.mark.asyncio
async def test_clone_allow_missing_writes_empty_dict(
    session: SafeJSONSession,
):
    """allow_missing_source=True writes {} to the destination."""
    await session.clone_session_state(
        src_session_id="nonexistent",
        dst_session_id="dst",
        user_id="u1",
        allow_missing_source=True,
    )

    dst_state = await session.get_session_state_dict("dst", user_id="u1")
    assert dst_state == {}


@pytest.mark.asyncio
async def test_clone_session_independent(
    session: SafeJSONSession,
):
    """Cloned session is independent — modifications don't cross."""
    await session.save_session_state(
        session_id="src",
        user_id="u1",
        dummy=_DummyModule({"v": 1}),
    )

    await session.clone_session_state(
        src_session_id="src",
        dst_session_id="dst",
        user_id="u1",
    )

    # modify original via update
    await session.update_session_state(
        session_id="src",
        key="dummy.v",
        value=99,
        user_id="u1",
    )

    src = await session.get_session_state_dict("src", user_id="u1")
    dst = await session.get_session_state_dict("dst", user_id="u1")
    assert src["dummy"]["v"] == 99
    assert dst["dummy"]["v"] == 1


# ---------------------------------------------------------------------------
# SafeJSONSession.delete_session_state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_session_state_removes_file(
    session: SafeJSONSession,
):
    await session.save_session_state(
        session_id="orphan",
        user_id="u1",
        dummy=_DummyModule({"x": 1}),
    )
    deleted = await session.delete_session_state(
        session_id="orphan",
        user_id="u1",
    )
    assert deleted is True
    state = await session.get_session_state_dict("orphan", user_id="u1")
    assert state == {}


@pytest.mark.asyncio
async def test_delete_session_state_returns_false_when_missing(
    session: SafeJSONSession,
):
    deleted = await session.delete_session_state(
        session_id="nonexistent",
        user_id="u1",
    )
    assert deleted is False


@pytest.mark.asyncio
async def test_delete_session_state_never_raises_on_double_delete(
    session: SafeJSONSession,
):
    """Deleting an already-deleted file returns False, never raises."""
    await session.save_session_state(
        session_id="temp",
        user_id="u1",
        dummy=_DummyModule({"x": 1}),
    )
    # first delete succeeds
    assert await session.delete_session_state(
        session_id="temp",
        user_id="u1",
    )
    # second delete is a no-op
    result = await session.delete_session_state(
        session_id="temp",
        user_id="u1",
    )
    assert result is False
