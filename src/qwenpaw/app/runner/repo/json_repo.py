# -*- coding: utf-8 -*-
"""JSON-based chat repository."""
from __future__ import annotations

import json
import logging
import shutil
import uuid
from pathlib import Path

from .base import BaseChatRepository
from ..models import ChatsFile

logger = logging.getLogger(__name__)


class JsonChatRepository(BaseChatRepository):
    """chats.json repository (single-file storage).

    Stores chat_id (UUID) -> session_id mappings in a JSON file.
    Similar to JsonJobRepository pattern from crons.

    Notes:
    - Single-machine, no cross-process lock.
    - Atomic write: write tmp then replace.
    """

    def __init__(self, path: Path | str):
        """Initialize JSON chat repository.

        Args:
            path: Path to chats.json file
        """
        if isinstance(path, str):
            path = Path(path)
        self._path = path.expanduser()

    @property
    def path(self) -> Path:
        """Get the repository file path."""
        return self._path

    async def load(self) -> ChatsFile:
        """Load chat specs from JSON file.

        Returns:
            ChatsFile with all chat specs
        """
        if not self._path.exists():
            return ChatsFile(version=1, chats=[])

        data = json.loads(self._path.read_text(encoding="utf-8"))
        return ChatsFile.model_validate(data)

    async def save(self, chats_file: ChatsFile) -> None:
        """Save chat specs to JSON file atomically.

        Args:
            chats_file: ChatsFile to persist
        """
        # Create parent directory if needed
        self._path.parent.mkdir(parents=True, exist_ok=True)

        # Write to temp file first (atomic write)
        tmp_path = self._path.with_suffix(self._path.suffix + ".tmp")
        payload = chats_file.model_dump(mode="json")

        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        # Atomic replace (shutil.move handles cross-disk on Windows)
        shutil.move(str(tmp_path), str(self._path))


def migrate_legacy_weixin_chats_file(chats_path: Path | str) -> None:
    """One-shot migration: rewrite legacy ``weixin:`` session_ids in chats.json.

    Older releases used ``weixin`` as the ``session_id`` prefix for
    WeChat (iLink) chats. The canonical prefix is now ``wechat``. The
    ``channel`` field has always been ``wechat``, so only the
    ``session_id`` prefix needs to be rewritten. Original file is
    backed up before rewrite. Idempotent: a no-op when no legacy
    entries are present.
    """
    path = Path(chats_path).expanduser() if isinstance(
        chats_path,
        str,
    ) else chats_path
    if not path.is_file():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(data, dict):
        return

    chats = data.get("chats")
    if not isinstance(chats, list):
        return

    mutated = False
    for chat in chats:
        if not isinstance(chat, dict):
            continue
        sid = chat.get("session_id")
        if isinstance(sid, str) and sid.startswith("weixin:"):
            chat["session_id"] = "wechat:" + sid[len("weixin:") :]
            mutated = True

    if not mutated:
        return

    try:
        backup_path = path.with_suffix(
            path.suffix + f".{uuid.uuid4().hex[:8]}.weixin-migrate.bak",
        )
        shutil.copy2(path, backup_path)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(
            json.dumps(
                data,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        shutil.move(str(tmp_path), str(path))
        logger.warning(
            "Migrated legacy 'weixin' chat entries -> 'wechat' in %s "
            "(backup: %s)",
            path,
            backup_path,
        )
    except OSError as exc:
        logger.error(
            "Failed to migrate legacy 'weixin' chat entries in %s: %s",
            path,
            exc,
        )
