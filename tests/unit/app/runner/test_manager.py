# -*- coding: utf-8 -*-
"""Unit tests for ``qwenpaw.app.runner.manager.ChatManager``.

Uses the real :class:`JsonChatRepository` backed by ``tmp_path`` so the
tests cover the integrated CRUD path without mocking the repo away.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from qwenpaw.app.runner.manager import ChatManager
from qwenpaw.app.runner.models import ChatSpec, ChatUpdate, SessionSource
from qwenpaw.app.runner.repo import JsonChatRepository
from qwenpaw.app.channels.schema import DEFAULT_CHANNEL


@pytest.fixture
def repo_path(tmp_path: Path) -> Path:
    return tmp_path / "chats.json"


@pytest.fixture
def manager(repo_path: Path) -> ChatManager:
    return ChatManager(repo=JsonChatRepository(repo_path))


def _make_spec(
    *,
    chat_id: str | None = None,
    session_id: str = "console:u1",
    user_id: str = "u1",
    name: str = "New Chat",
    source: SessionSource = SessionSource.chat,
) -> ChatSpec:
    kwargs = {
        "session_id": session_id,
        "user_id": user_id,
        "name": name,
        "source": source,
    }
    if chat_id is not None:
        kwargs["id"] = chat_id
    return ChatSpec(**kwargs)


# ---------------------------------------------------------------------------
# create / get / list
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_chat_returns_none_for_missing(manager: ChatManager):
    assert await manager.get_chat("does-not-exist") is None


@pytest.mark.asyncio
async def test_create_and_get_chat_round_trip(manager: ChatManager):
    spec = _make_spec(name="Hello")

    created = await manager.create_chat(spec)

    assert created.id == spec.id
    fetched = await manager.get_chat(spec.id)
    assert fetched is not None
    assert fetched.name == "Hello"
    assert fetched.session_id == "console:u1"


@pytest.mark.asyncio
async def test_list_chats_filters_by_user_and_channel(manager: ChatManager):
    await manager.create_chat(
        _make_spec(session_id="console:alice", user_id="alice"),
    )
    await manager.create_chat(
        _make_spec(session_id="console:bob", user_id="bob"),
    )
    await manager.create_chat(
        _make_spec(session_id="discord:alice", user_id="alice"),
    )
    # Patch the discord chat onto a different channel.
    discord = (await manager.list_chats(user_id="alice"))[-1]
    discord.channel = "discord"
    await manager._repo.upsert_chat(discord)

    alice_all = await manager.list_chats(user_id="alice")
    alice_console = await manager.list_chats(
        user_id="alice",
        channel=DEFAULT_CHANNEL,
    )

    assert {c.user_id for c in alice_all} == {"alice"}
    assert len(alice_all) == 2
    assert all(c.channel == DEFAULT_CHANNEL for c in alice_console)
    assert len(alice_console) == 1


@pytest.mark.asyncio
async def test_count_chats(manager: ChatManager):
    for i in range(3):
        await manager.create_chat(_make_spec(session_id=f"s{i}"))

    assert await manager.count_chats() == 3


# ---------------------------------------------------------------------------
# get_or_create_chat
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_or_create_chat_creates_when_missing(manager: ChatManager):
    spec = await manager.get_or_create_chat(
        session_id="console:new",
        user_id="new-user",
        name="auto-registered",
    )

    assert spec.session_id == "console:new"
    assert spec.user_id == "new-user"
    assert spec.name == "auto-registered"
    assert spec.source == SessionSource.chat

    # Sanity: a follow-up call returns the SAME spec (idempotent).
    again = await manager.get_or_create_chat(
        session_id="console:new",
        user_id="new-user",
    )
    assert again.id == spec.id


@pytest.mark.asyncio
async def test_get_or_create_chat_invalid_source_falls_back_to_chat(
    manager: ChatManager,
):
    spec = await manager.get_or_create_chat(
        session_id="console:x",
        user_id="u",
        source="totally-bogus",
    )

    assert spec.source == SessionSource.chat


# ---------------------------------------------------------------------------
# patch_chat / patch_chat_if_name_matches
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_patch_chat_merges_partial_updates(manager: ChatManager):
    spec = await manager.create_chat(_make_spec(name="before"))
    before_updated = spec.updated_at

    patched = await manager.patch_chat(
        spec.id,
        ChatUpdate(name="after", pinned=True),
    )

    assert patched is not None
    assert patched.name == "after"
    assert patched.pinned is True
    # patch_chat refreshes updated_at.
    assert patched.updated_at >= before_updated


@pytest.mark.asyncio
async def test_patch_chat_missing_returns_none(manager: ChatManager):
    result = await manager.patch_chat("ghost", ChatUpdate(name="x"))

    assert result is None


@pytest.mark.asyncio
async def test_patch_chat_if_name_matches_applies_when_name_matches(
    manager: ChatManager,
):
    spec = await manager.create_chat(_make_spec(name="Old Title"))

    updated = await manager.patch_chat_if_name_matches(
        spec.id,
        expected_name="Old Title",
        patch=ChatUpdate(name="Auto Title"),
    )

    assert updated is not None
    assert updated.name == "Auto Title"


@pytest.mark.asyncio
async def test_patch_chat_if_name_matches_skips_on_mismatch(
    manager: ChatManager,
):
    # Simulate the race the CAS helper exists to prevent: user renamed
    # the chat between read and write, so background title generation
    # must NOT overwrite the new name.
    spec = await manager.create_chat(_make_spec(name="User Chosen"))

    result = await manager.patch_chat_if_name_matches(
        spec.id,
        expected_name="Old Default",  # stale expectation
        patch=ChatUpdate(name="Bogus Auto Title"),
    )

    assert result is None
    refreshed = await manager.get_chat(spec.id)
    assert refreshed.name == "User Chosen"


@pytest.mark.asyncio
async def test_patch_chat_if_name_matches_missing_returns_none(
    manager: ChatManager,
):
    result = await manager.patch_chat_if_name_matches(
        "ghost",
        expected_name="x",
        patch=ChatUpdate(name="y"),
    )

    assert result is None


@pytest.mark.asyncio
async def test_touch_chat_refreshes_updated_at(manager: ChatManager):
    spec = await manager.create_chat(_make_spec())
    before = spec.updated_at

    touched = await manager.touch_chat(spec.id)

    assert touched is not None
    assert touched.updated_at >= before


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_chats_returns_true_when_existing(manager: ChatManager):
    spec_a = await manager.create_chat(_make_spec(session_id="a"))
    spec_b = await manager.create_chat(_make_spec(session_id="b"))

    assert await manager.delete_chats([spec_a.id]) is True

    remaining = await manager.list_chats()
    assert [c.id for c in remaining] == [spec_b.id]


@pytest.mark.asyncio
async def test_delete_chats_returns_false_when_missing(manager: ChatManager):
    assert await manager.delete_chats(["nope"]) is False


# ---------------------------------------------------------------------------
# get_chat_id_by_session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_chat_id_by_session_returns_none_when_no_match(
    manager: ChatManager,
):
    assert (
        await manager.get_chat_id_by_session("missing", DEFAULT_CHANNEL)
        is None
    )


@pytest.mark.asyncio
async def test_get_chat_id_by_session_returns_most_recent_match(
    manager: ChatManager,
):
    old = await manager.create_chat(
        _make_spec(session_id="console:dup", name="old"),
    )
    new = await manager.create_chat(
        _make_spec(session_id="console:dup", name="new"),
    )
    # Force ``new`` to be the most recent.
    await manager.patch_chat(new.id, ChatUpdate(name="new+1"))

    chat_id = await manager.get_chat_id_by_session(
        "console:dup",
        DEFAULT_CHANNEL,
    )

    assert chat_id == new.id
    assert chat_id != old.id


# ---------------------------------------------------------------------------
# Lock serializes concurrent writes.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_writes_are_serialized(manager: ChatManager):
    # If the lock works, all 10 concurrent creates land without losing
    # any spec on disk.  The bug it prevents is two writes loading the
    # same file snapshot in parallel and clobbering each other.
    specs = [_make_spec(session_id=f"sess-{i}") for i in range(10)]

    await asyncio.gather(*(manager.create_chat(s) for s in specs))

    all_ids = {c.id for c in await manager.list_chats()}
    assert all_ids == {s.id for s in specs}
