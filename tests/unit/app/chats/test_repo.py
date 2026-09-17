# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name
from __future__ import annotations

import json
from pathlib import Path

import pytest

from qwenpaw.app.chats.models import ChatSpec, ChatsFile
from qwenpaw.app.chats.repo.json_repo import (
    JsonChatRepository,
    migrate_legacy_weixin_chats_file,
)


@pytest.fixture
def repo(tmp_path: Path) -> JsonChatRepository:
    return JsonChatRepository(tmp_path / "chats.json")


# ---------------------------------------------------------------------------
# load / save round-trip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_returns_empty_when_missing(repo: JsonChatRepository):
    result = await repo.load()
    assert result.chats == []


@pytest.mark.asyncio
async def test_save_and_load_round_trip(repo: JsonChatRepository):
    spec = ChatSpec(session_id="console:u1", user_id="u1")
    cf = ChatsFile(version=1, chats=[spec])
    await repo.save(cf)

    loaded = await repo.load()
    assert len(loaded.chats) == 1
    assert loaded.chats[0].user_id == "u1"


# ---------------------------------------------------------------------------
# get_chat / upsert_chat / delete_chats
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_chat_returns_none_for_missing(repo: JsonChatRepository):
    assert await repo.get_chat("ghost") is None


@pytest.mark.asyncio
async def test_upsert_inserts_new_chat(repo: JsonChatRepository):
    spec = ChatSpec(session_id="console:u1", user_id="u1")
    await repo.upsert_chat(spec)

    loaded = await repo.load()
    assert len(loaded.chats) == 1


@pytest.mark.asyncio
async def test_upsert_updates_existing_chat(repo: JsonChatRepository):
    spec = ChatSpec(session_id="console:u1", user_id="u1", name="Before")
    await repo.upsert_chat(spec)

    spec.name = "After"
    await repo.upsert_chat(spec)

    loaded = await repo.load()
    assert len(loaded.chats) == 1
    assert loaded.chats[0].name == "After"


@pytest.mark.asyncio
async def test_delete_chats_returns_true_when_existing(
    repo: JsonChatRepository,
):
    spec = ChatSpec(session_id="console:u1", user_id="u1")
    await repo.upsert_chat(spec)

    assert await repo.delete_chats([spec.id]) is True
    assert await repo.get_chat(spec.id) is None


@pytest.mark.asyncio
async def test_delete_chats_returns_false_when_missing(
    repo: JsonChatRepository,
):
    assert await repo.delete_chats(["ghost"]) is False


# ---------------------------------------------------------------------------
# migrate_legacy_weixin_chats_file
# ---------------------------------------------------------------------------


def test_migrate_weixin_session_ids(tmp_path: Path):
    chats_path = tmp_path / "chats.json"
    data = {
        "version": 1,
        "chats": [
            {
                "session_id": "weixin:u1",
                "user_id": "u1",
            },
        ],
    }
    chats_path.write_text(json.dumps(data), encoding="utf-8")

    migrate_legacy_weixin_chats_file(chats_path)

    result = json.loads(chats_path.read_text(encoding="utf-8"))
    assert result["chats"][0]["session_id"] == "wechat:u1"


def test_migrate_is_idempotent(tmp_path: Path):
    chats_path = tmp_path / "chats.json"
    data = {
        "version": 1,
        "chats": [
            {
                "session_id": "wechat:u1",
                "user_id": "u1",
            },
        ],
    }
    original = json.dumps(data)
    chats_path.write_text(original, encoding="utf-8")

    migrate_legacy_weixin_chats_file(chats_path)

    assert chats_path.read_text(encoding="utf-8") == original


def test_migrate_noop_when_file_missing(tmp_path: Path):
    migrate_legacy_weixin_chats_file(tmp_path / "nonexistent.json")
