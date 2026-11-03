# -*- coding: utf-8 -*-
"""JSON-based chat repository."""
from __future__ import annotations

import json
import logging
import os
import shutil
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path

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
        raw = read_json(self._path)
        changed = False
        chats = raw.get("chats") if isinstance(raw, dict) else None
        recovered = False
        if isinstance(chats, list):
            recovered = self._recover_catalog_bindings(chats)
            changed = recovered
            for chat in chats:
                if isinstance(chat, dict) and not chat.get("storage_id"):
                    chat["storage_id"] = str(uuid.uuid4())
                    changed = True
        result = ChatsFile.model_validate(raw)
        storage_ids = [chat.storage_id for chat in result.chats]
        if len(storage_ids) != len(set(storage_ids)):
            raise ValueError("duplicate chat storage_id")
        if changed:
            if recovered:
                backup = self._path.with_name(
                    self._path.name + "." + uuid.uuid4().hex + ".recovery.bak",
                )
                shutil.copy2(self._path, backup)
                logger.warning("Recovered chat identities; backup: %s", backup)
            write_json_atomic(
                self._path,
                result.model_dump(mode="json"),
                sort_keys=True,
            )
        return result

    def _recover_catalog_bindings(self, chats: list) -> bool:
        """Restore lost bindings using verified, read-only database facts."""
        catalog = self._path.parent / "transcript_catalog.db"
        if not catalog.is_file():
            return False
        with closing(
            sqlite3.connect(
                catalog.resolve().as_uri() + "?mode=ro",
                uri=True,
            ),
        ) as connection:
            bindings = {
                (row[0], row[1], row[2]): row[3]
                for row in connection.execute(
                    "SELECT session_id, user_id, channel, storage_id "
                    "FROM transcript_files",
                )
            }
        changed = False
        for chat in chats:
            if not isinstance(chat, dict):
                continue
            identity = (
                chat.get("session_id"),
                chat.get("user_id"),
                chat.get("channel"),
            )
            storage_id = bindings.get(identity)
            current = chat.get("storage_id")
            if not storage_id or current == storage_id:
                continue
            directory = self._path.parent / "transcripts"
            if current and (directory / (current + ".db")).exists():
                raise ValueError(
                    "conflicting chat databases; recovery refused",
                )
            path = directory / (storage_id + ".db")
            with closing(
                sqlite3.connect(
                    path.resolve().as_uri() + "?mode=ro",
                    uri=True,
                ),
            ) as connection:
                rows = connection.execute(
                    "SELECT session_id, user_id, channel, storage_id "
                    "FROM transcript_sessions",
                ).fetchall()
                if rows != [(*identity, storage_id)]:
                    raise ValueError("chat database identity mismatch")
                fork = connection.execute(
                    "SELECT payload_json FROM event_log "
                    "WHERE event_type = 'session.forked' ORDER BY seq LIMIT 1",
                ).fetchone()
            if fork is not None:
                fact = json.loads(fork[0])
                fields = {
                    "parent_chat_id": fact["source_chat_id"],
                    "fork_turn_id": fact["turn_id"],
                    "fork_turn_seq": fact["turn_seq"],
                }
                for key, value in fields.items():
                    if chat.get(key) not in (None, value):
                        raise ValueError("conflicting chat fork metadata")
                    chat[key] = value
            chat["storage_id"] = storage_id
            changed = True
        return changed

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


def migrate_legacy_weixin_chats_file(chats_path: Path | str) -> None:
    """Rewrite legacy ``weixin:`` session_id prefixes to ``wechat:``.

    Idempotent; backs up the original file before rewrite.
    """
    path = (
        Path(chats_path).expanduser()
        if isinstance(
            chats_path,
            str,
        )
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
