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
        self._migrate_legacy_weixin_on_disk(data)
        return ChatsFile.model_validate(data)

    def _migrate_legacy_weixin_on_disk(self, data: dict) -> None:
        """One-shot migration: rewrite legacy ``weixin:`` session_ids.

        Older releases used ``weixin`` as the ``session_id`` prefix for
        WeChat (iLink) chats. The canonical prefix is now ``wechat``.
        The ``channel`` field has always been ``wechat``, so only the
        ``session_id`` prefix needs to be rewritten. Original file is
        backed up before rewrite.
        """
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
            backup_path = self._path.with_suffix(
                self._path.suffix
                + f".{uuid.uuid4().hex[:8]}.weixin-migrate.bak",
            )
            shutil.copy2(self._path, backup_path)
            tmp_path = self._path.with_suffix(self._path.suffix + ".tmp")
            tmp_path.write_text(
                json.dumps(
                    data,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            shutil.move(str(tmp_path), str(self._path))
            logger.warning(
                "Migrated legacy 'weixin' chat entries -> 'wechat' in %s "
                "(backup: %s)",
                self._path,
                backup_path,
            )
        except OSError as exc:
            logger.error(
                "Failed to migrate legacy 'weixin' chat entries in %s: %s",
                self._path,
                exc,
            )

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
