# -*- coding: utf-8 -*-

import errno
from pathlib import Path

import pytest

from copaw.app.runner.models import ChatsFile
from copaw.app.runner.repo.json_repo import JsonChatRepository


@pytest.mark.asyncio
async def test_chat_repo_retries_replace_on_ebusy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = JsonChatRepository(tmp_path / "chats.json")
    chats_file = ChatsFile(version=1, chats=[])
    original_replace = Path.replace
    attempts = {"count": 0}

    def flaky_replace(self: Path, target: Path) -> Path:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise OSError(errno.EBUSY, "Device or resource busy")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", flaky_replace)

    await repo.save(chats_file)

    assert attempts["count"] == 2
    assert repo.path.exists()
