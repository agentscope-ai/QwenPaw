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
@pytest.mark.parametrize("alias_user", [None, "", "console:u1", "other"])
async def test_save_and_load_round_trip(
    repo: JsonChatRepository,
    monkeypatch: pytest.MonkeyPatch,
    alias_user: str | None,
):
    spec = ChatSpec(session_id="console:u1", user_id="console:u1")
    specs = [spec]
    if alias_user is not None:
        specs.append(
            ChatSpec(
                session_id=spec.session_id,
                user_id=alias_user,
                storage_id=spec.storage_id,
            ),
        )
    cf = ChatsFile(version=1, chats=specs)
    await repo.save(cf)

    def reject_recovery(_chats):
        pytest.fail("Complete storage IDs must not query recovery bindings")

    monkeypatch.setattr(repo, "_recover_catalog_bindings", reject_recovery)
    if alias_user == "other":
        with pytest.raises(ValueError, match="duplicate chat storage_id"):
            await repo.load()
        return
    loaded = await repo.load()
    assert len(loaded.chats) == len(specs)
    assert loaded.chats[0].user_id == "console:u1"


@pytest.mark.asyncio
@pytest.mark.parametrize("chat_id", [None, "legacy-chat"])
async def test_load_persists_storage_id_for_existing_chat(
    repo: JsonChatRepository,
    chat_id: str | None,
):
    repo.path.write_text(
        json.dumps(
            {
                "version": 1,
                "chats": [
                    {
                        **({"id": chat_id} if chat_id else {}),
                        "session_id": "shared-group",
                        "user_id": "u1",
                        "channel": "feishu",
                    },
                ],
            },
        ),
        encoding="utf-8",
    )

    loaded = await repo.load()
    persisted = json.loads(repo.path.read_text(encoding="utf-8"))

    assert persisted["chats"][0]["storage_id"] == (loaded.chats[0].storage_id)
    assert loaded.chats[0].storage_id == loaded.chats[0].id
    if chat_id:
        assert loaded.chats[0].id == chat_id
    persisted["chats"][0].pop("storage_id")
    repo.path.write_text(json.dumps(persisted), encoding="utf-8")
    reloaded = await repo.load()
    assert reloaded.chats[0].storage_id == loaded.chats[0].storage_id


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
