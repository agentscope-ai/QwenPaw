# -*- coding: utf-8 -*-
"""JSON-based chat repository."""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .base import BaseChatRepository
from ..models import ChatsFile


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

    def _make_backup_path(self) -> Path:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ")
        return self._path.with_name(f"{self._path.name}.backup-{timestamp}")

    def _backup_current_file(self) -> None:
        """Create a timestamped backup of the current chats file."""
        if not self._path.exists():
            return

        shutil.copy2(self._path, self._make_backup_path())

    async def delete_chats(self, chat_ids: list[str]) -> bool:
        """Delete chats and back up the current file before persisting."""
        if not chat_ids:
            return False

        cf = await self.load()
        existing_ids = {chat.id for chat in cf.chats}
        if not any(chat_id in existing_ids for chat_id in chat_ids):
            return False

        self._backup_current_file()
        cf.chats = [chat for chat in cf.chats if chat.id not in chat_ids]
        await self.save(cf)
        return True
