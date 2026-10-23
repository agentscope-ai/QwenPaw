# -*- coding: utf-8 -*-
"""JSON-based chat repository."""
from __future__ import annotations

import json
import logging
import os
import shutil
import uuid
from pathlib import Path
from typing import Callable

from .base import BaseChatRepository
from ..models import ChatsFile
from ....utils.io_utils import read_json, run_sync_io, write_json_atomic

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

    def _load_sync(self) -> ChatsFile:
        """Load and validate chat specs as one worker-thread operation."""
        if not self._path.exists():
            return ChatsFile(version=1, chats=[])
        return ChatsFile.model_validate(read_json(self._path))

    async def load(self) -> ChatsFile:
        """Load and validate chat specs without blocking the event loop.

        Returns:
            ChatsFile with all chat specs
        """
        return await run_sync_io(self._load_sync)

    def _save_sync(self, chats_file: ChatsFile) -> None:
        """Serialize and atomically save chat specs in one worker thread."""
        write_json_atomic(
            self._path,
            chats_file.model_dump(mode="json"),
            sort_keys=True,
        )

    async def save(self, chats_file: ChatsFile) -> None:
        """Atomically save chat specs without blocking the event loop.

        Args:
            chats_file: ChatsFile to persist
        """
        await run_sync_io(self._save_sync, chats_file)


def _migrate_chats_file(
    chats_path: Path | str,
    migrate_chat: Callable[[dict], bool],
    backup_tag: str,
    description: str,
) -> None:
    """Apply *migrate_chat* to each chat record, backing up before rewrite.

    Idempotent: the file is only rewritten when some record changed.
    """
    path = (
        Path(chats_path).expanduser()
        if isinstance(chats_path, str)
        else chats_path
    )
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
        if isinstance(chat, dict) and migrate_chat(chat):
            mutated = True

    if not mutated:
        return

    try:
        backup_path = path.with_suffix(
            path.suffix + f".{uuid.uuid4().hex[:8]}.{backup_tag}.bak",
        )
        shutil.copy2(path, backup_path)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        # newline="\n" prevents Windows from translating LF -> CRLF and
        # polluting the file's line endings on rewrite.
        tmp_path.write_text(
            json.dumps(
                data,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
            newline="\n",
        )
        # os.replace is the documented atomic-overwrite primitive on all
        # supported platforms (POSIX rename + Windows ReplaceFile).
        os.replace(tmp_path, path)
        logger.warning(
            "Migrated %s in %s (backup: %s)",
            description,
            path,
            backup_path,
        )
    except OSError as exc:
        logger.error(
            "Failed to migrate %s in %s: %s",
            description,
            path,
            exc,
        )


def migrate_legacy_weixin_chats_file(chats_path: Path | str) -> None:
    """Rewrite legacy ``weixin:`` session_id prefixes to ``wechat:``."""

    def migrate(chat: dict) -> bool:
        sid = chat.get("session_id")
        if isinstance(sid, str) and sid.startswith("weixin:"):
            chat["session_id"] = "wechat:" + sid[len("weixin:") :]
            return True
        return False

    _migrate_chats_file(
        chats_path,
        migrate,
        "weixin-migrate",
        "legacy 'weixin' chat entries -> 'wechat'",
    )


def migrate_legacy_realtime_voice_sources_file(
    chats_path: Path | str,
) -> None:
    """Move legacy Voice Chat identity from ``source`` into metadata.

    Early development builds persisted ``source=realtime_voice``, which an
    older closed ``SessionSource`` enum cannot load. Only records carrying the
    matching capability metadata are rewritten.
    """

    def migrate(chat: dict) -> bool:
        meta = chat.get("meta")
        if chat.get("source") != "realtime_voice" or not isinstance(
            meta.get("realtime_voice") if isinstance(meta, dict) else None,
            dict,
        ):
            return False
        chat["source"] = "chat"
        return True

    _migrate_chats_file(
        chats_path,
        migrate,
        "voice-source-migrate",
        "legacy Voice Chat source entries",
    )
