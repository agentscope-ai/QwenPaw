# -*- coding: utf-8 -*-
from datetime import datetime, timezone
from pathlib import Path

import pytest

from copaw.app.runner.models import ChatsFile, ChatSpec
from copaw.app.runner.repo.json_repo import JsonChatRepository


def make_chat(chat_id: str, name: str) -> ChatSpec:
    timestamp = datetime(2026, 3, 26, 12, 0, 0, tzinfo=timezone.utc)
    return ChatSpec(
        id=chat_id,
        name=name,
        session_id=f"console:{chat_id}",
        user_id=f"user-{chat_id}",
        channel="console",
        created_at=timestamp,
        updated_at=timestamp,
    )


@pytest.mark.asyncio
async def test_delete_chats_creates_timestamped_backup(tmp_path: Path) -> None:
    repo = JsonChatRepository(tmp_path / "chats.json")
    await repo.save(
        ChatsFile(
            chats=[
                make_chat("chat-1", "First"),
                make_chat("chat-2", "Second"),
            ],
        ),
    )

    deleted = await repo.delete_chats(["chat-1"])

    assert deleted is True
    assert len(list(tmp_path.glob("chats.json.backup-*"))) == 1


@pytest.mark.asyncio
async def test_delete_chats_without_match_does_not_create_backup(
    tmp_path: Path,
) -> None:
    repo = JsonChatRepository(tmp_path / "chats.json")
    await repo.save(ChatsFile(chats=[make_chat("chat-1", "First")]))

    deleted = await repo.delete_chats(["missing"])

    assert deleted is False
    assert not list(tmp_path.glob("chats.json.backup-*"))


@pytest.mark.asyncio
async def test_backup_preserves_pre_delete_file_contents(
    tmp_path: Path,
) -> None:
    repo = JsonChatRepository(tmp_path / "chats.json")
    await repo.save(ChatsFile(chats=[make_chat("chat-1", "First")]))
    before_delete = repo.path.read_text(encoding="utf-8")

    await repo.delete_chats(["chat-1"])

    backup_files = list(tmp_path.glob("chats.json.backup-*"))
    assert len(backup_files) == 1
    assert backup_files[0].read_text(encoding="utf-8") == before_delete
