# -*- coding: utf-8 -*-
"""JSON-based chat repository."""
from __future__ import annotations

import logging
from pathlib import Path

from pydantic import ValidationError

from .base import BaseChatRepository
from ..models import ChatsFile
from ....utils.json_storage import (
    load_json_with_recovery,
    repair_json_file,
    save_json_atomically,
)


logger = logging.getLogger(__name__)


class JsonChatRepository(BaseChatRepository):
    """chats.json repository (single-file storage).

    Stores chat_id (UUID) -> session_id mappings in a JSON file.
    Similar to JsonJobRepository pattern from crons.

    Notes:
    - Uses a sibling lock file for cross-process coordination.
    - Writes via unique temp file + atomic replace.
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
        default_file = ChatsFile(version=1, chats=[])
        data = load_json_with_recovery(
            self._path,
            default_payload=default_file.model_dump(mode="json"),
            storage_name="chat repository",
            logger_=logger,
        )
        try:
            return ChatsFile.model_validate(data)
        except ValidationError as exc:
            repair_json_file(
                self._path,
                default_payload=default_file.model_dump(mode="json"),
                storage_name="chat repository",
                reason=f"schema validation failed: {exc}",
                logger_=logger,
            )
            return default_file

    async def save(self, chats_file: ChatsFile) -> None:
        """Save chat specs to JSON file atomically.

        Args:
            chats_file: ChatsFile to persist
        """
        payload = chats_file.model_dump(mode="json")
        save_json_atomically(
            self._path,
            payload,
        )
