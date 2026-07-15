# -*- coding: utf-8 -*-
"""Chat manager for managing chat specifications."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from collections.abc import Awaitable, Callable
from typing import Optional

from .models import (
    BatchArchiveResult,
    BatchFailure,
    ChatSpec,
    ChatUpdate,
    SessionSource,
)
from .repo import BaseChatRepository
from ..channels.schema import DEFAULT_CHANNEL

logger = logging.getLogger(__name__)

MAX_BATCH_SIZE = 500


class ChatManager:
    """Manages chat specifications in repository.

    Only handles ChatSpec CRUD operations.
    Does NOT manage Redis session state - that's handled by SafeJSONSession.

    Similar to CronManager's role in crons module.
    """

    def __init__(
        self,
        *,
        repo: BaseChatRepository,
    ):
        """Initialize chat manager.

        Args:
            repo: Chat spec repository for persistence
        """
        self._repo = repo
        self._lock = asyncio.Lock()
        logger.debug(
            f"ChatManager created with repo path: {repo.path}",
        )

    # ----- Read Operations -----

    async def list_chats(
        self,
        user_id: Optional[str] = None,
        channel: Optional[str] = None,
        archived: Optional[bool] = None,
    ) -> list[ChatSpec]:
        """List chat specs with optional filters.

        Args:
            user_id: Optional user ID filter
            channel: Optional channel filter
            archived: Optional archived status filter.
                False (default in API) = active only,
                True = archived only, None = all.

        Returns:
            List of chat specifications
        """
        async with self._lock:
            logger.debug(
                f"list_chats: repo path={self._repo.path}, "
                f"filters: user_id={user_id}, channel={channel}, "
                f"archived={archived}",
            )
            return await self._repo.filter_chats(
                user_id=user_id,
                channel=channel,
                archived=archived,
            )

    async def get_chat(self, chat_id: str) -> Optional[ChatSpec]:
        """Get chat spec by chat_id (UUID).

        Args:
            chat_id: Chat UUID

        Returns:
            Chat spec or None if not found
        """
        async with self._lock:
            return await self._repo.get_chat(chat_id)

    async def get_or_create_chat(
        self,
        session_id: str,
        user_id: str,
        channel: str = DEFAULT_CHANNEL,
        name: str = "New Chat",
        source: str | SessionSource = SessionSource.chat,
    ) -> ChatSpec:
        """Get existing chat or create new one.

        Useful for auto-registration when chats come from channels.

        Args:
            session_id: Session identifier (channel:user_id)
            user_id: User identifier
            channel: Channel name
            name: Chat name

        Returns:
            Chat specification (existing or newly created)
        """
        async with self._lock:
            # Try to find existing by session_id
            logger.debug(
                f"get_or_create_chat: Searching for existing chat: "
                f"session_id={session_id}, user_id={user_id}, "
                f"channel={channel}",
            )
            existing = await self._repo.get_chat_by_id(
                session_id,
                user_id,
                channel,
            )
            if existing:
                logger.debug(
                    f"get_or_create_chat: Found existing chat: {existing.id}",
                )
                return existing

            # Create new
            logger.debug(
                f"get_or_create_chat: Creating new chat for "
                f"session_id={session_id}, source={source}",
            )
            try:
                resolved_source = SessionSource(source)
            except ValueError:
                resolved_source = SessionSource.chat
            spec = ChatSpec(
                session_id=session_id,
                user_id=user_id,
                channel=channel,
                name=name,
                source=resolved_source,
            )
            logger.debug(f"get_or_create_chat: created spec={spec.id}")
            # Call internal create without lock (already locked)
            await self._repo.upsert_chat(spec)
            logger.info(
                f"Auto-registered new chat: {spec.id} -> {session_id}",
            )
            return spec

    async def create_chat(self, spec: ChatSpec) -> ChatSpec:
        """Create a new chat.

        Args:
            spec: Chat specification (chat_id will be generated if not set)

        Returns:
            Chat spec
        """
        async with self._lock:
            await self._repo.upsert_chat(spec)
            return spec

    async def patch_chat(
        self,
        chat_id: str,
        patch: ChatUpdate,
    ) -> Optional[ChatSpec]:
        """Merge a partial update into the latest persisted chat spec."""
        async with self._lock:
            return await self._patch_locked(chat_id, patch)

    async def patch_chat_if_name_matches(
        self,
        chat_id: str,
        expected_name: str,
        patch: ChatUpdate,
    ) -> Optional[ChatSpec]:
        """Atomic compare-and-set on ``ChatSpec.name``.

        Apply ``patch`` only when the persisted name still equals
        ``expected_name``. The read and write happen under a single lock
        acquisition so a concurrent rename cannot slip in between, which
        is what background tasks like async title generation rely on to
        avoid clobbering a user-chosen name.

        Returns the updated spec on success, ``None`` if the chat does
        not exist or its name no longer matches.
        """
        async with self._lock:
            existing = await self._repo.get_chat(chat_id)
            if existing is None or existing.name != expected_name:
                return None
            return await self._patch_locked(chat_id, patch, existing=existing)

    async def _patch_locked(
        self,
        chat_id: str,
        patch: ChatUpdate,
        *,
        existing: Optional[ChatSpec] = None,
    ) -> Optional[ChatSpec]:
        """Internal patch helper. Caller must hold ``self._lock``."""
        if existing is None:
            existing = await self._repo.get_chat(chat_id)
            if existing is None:
                return None

        updates = patch.model_dump(
            exclude_none=True,
            exclude_unset=True,
        )
        merged = existing.model_copy(update=updates)
        merged.updated_at = datetime.now(timezone.utc)
        await self._repo.upsert_chat(merged)
        return merged

    async def touch_chat(self, chat_id: str) -> Optional[ChatSpec]:
        """Refresh updated_at without rewriting other chat fields."""
        return await self.patch_chat(chat_id, ChatUpdate())

    async def delete_chats(self, chat_ids: list[str]) -> bool:
        """Delete a chat spec.

        Note: This only deletes the spec. Redis session state is NOT deleted.

        Args:
            chat_ids: List of chat IDs

        Returns:
            True if deleted, False if not found
        """
        async with self._lock:
            deleted = await self._repo.delete_chats(chat_ids)

            if deleted:
                logger.debug(f"Deleted chats: {chat_ids}")

            return deleted

    # ----- Archive Operations -----

    async def archive_chat(
        self,
        chat_id: str,
        *,
        check_status: Optional[str] = None,
    ) -> Optional[ChatSpec]:
        """Archive a single chat. Idempotent: already-archived chats are
        returned unchanged (archived_at is NOT refreshed).

        Args:
            chat_id: Chat UUID
            check_status: If provided and equals "running", raises ValueError

        Returns:
            Updated ChatSpec, or None if not found

        Raises:
            ValueError: If the chat is currently running (in_progress)
        """
        async with self._lock:
            existing = await self._repo.get_chat(chat_id)
            if existing is None:
                return None
            if check_status == "running":
                raise ValueError("in_progress")
            if existing.archived:
                return existing
            merged = existing.model_copy(
                update={"archived_at": datetime.now(timezone.utc)},
            )
            await self._repo.upsert_chat(merged)
            logger.debug(f"Archived chat: {chat_id}")
            return merged

    async def unarchive_chat(self, chat_id: str) -> Optional[ChatSpec]:
        """Unarchive a single chat. Idempotent: active chats unchanged.

        Args:
            chat_id: Chat UUID

        Returns:
            Updated ChatSpec, or None if not found
        """
        async with self._lock:
            existing = await self._repo.get_chat(chat_id)
            if existing is None:
                return None
            if not existing.archived:
                return existing
            merged = existing.model_copy(update={"archived_at": None})
            await self._repo.upsert_chat(merged)
            logger.debug(f"Unarchived chat: {chat_id}")
            return merged

    async def batch_archive(
        self,
        chat_ids: list[str],
        *,
        get_status: Optional[Callable[[str], Awaitable[Optional[str]]]] = None,
    ) -> BatchArchiveResult:
        """Archive multiple chats. Partial failures do not roll back.

        Args:
            chat_ids: List of chat IDs (max MAX_BATCH_SIZE)
            get_status: Optional async callable that returns chat status.
                If provided, running chats are skipped.

        Returns:
            BatchArchiveResult with succeeded and failed lists
        """
        result = BatchArchiveResult()
        async with self._lock:
            for chat_id in chat_ids:
                existing = await self._repo.get_chat(chat_id)
                if existing is None:
                    result.failed.append(
                        BatchFailure(
                            chat_id=chat_id,
                            reason="not_found",
                            message=f"Chat not found: {chat_id}",
                        ),
                    )
                    continue
                if get_status is not None:
                    status = await get_status(chat_id)
                    if status == "running":
                        result.failed.append(
                            BatchFailure(
                                chat_id=chat_id,
                                reason="in_progress",
                                message="Chat is running",
                            ),
                        )
                        continue
                if not existing.archived:
                    merged = existing.model_copy(
                        update={"archived_at": datetime.now(timezone.utc)},
                    )
                    await self._repo.upsert_chat(merged)
                result.succeeded.append(chat_id)
        logger.debug(
            f"batch_archive: {len(result.succeeded)} succeeded, "
            f"{len(result.failed)} failed",
        )
        return result

    async def batch_unarchive(
        self,
        chat_ids: list[str],
    ) -> BatchArchiveResult:
        """Unarchive multiple chats. Partial failures do not roll back.

        Args:
            chat_ids: List of chat IDs (max MAX_BATCH_SIZE)

        Returns:
            BatchArchiveResult with succeeded and failed lists
        """
        result = BatchArchiveResult()
        async with self._lock:
            for chat_id in chat_ids:
                existing = await self._repo.get_chat(chat_id)
                if existing is None:
                    result.failed.append(
                        BatchFailure(
                            chat_id=chat_id,
                            reason="not_found",
                            message=f"Chat not found: {chat_id}",
                        ),
                    )
                    continue
                if existing.archived:
                    merged = existing.model_copy(update={"archived_at": None})
                    await self._repo.upsert_chat(merged)
                result.succeeded.append(chat_id)
        logger.debug(
            f"batch_unarchive: {len(result.succeeded)} succeeded, "
            f"{len(result.failed)} failed",
        )
        return result

    # ----- Misc Operations -----

    async def count_chats(
        self,
        user_id: Optional[str] = None,
        channel: Optional[str] = None,
    ) -> int:
        """Count chats matching filters.

        Args:
            user_id: Optional user ID filter
            channel: Optional channel filter

        Returns:
            Number of matching chats
        """
        async with self._lock:
            chats = await self._repo.filter_chats(
                user_id=user_id,
                channel=channel,
            )
            return len(chats)

    async def get_chat_id_by_session(
        self,
        session_id: str,
        channel: str,
        user_id: str | None = None,
    ) -> str | None:
        """Get chat_id by session_id and channel.

        Args:
            session_id: Normalized session ID (e.g. "console:user1")
            channel: Channel name
            user_id: Optional user ID. When provided, only chats owned by
                this user are considered. This isolates users that share the
                same session_id (e.g. members of the same group chat, or
                different DM users whose conversation_id suffix collides), so
                a /stop from one user never cancels another user's task.
                When None/empty, all matching chats are considered
                (backward-compatible behavior).

        Returns:
            chat_id (UUID) of most recent chat if found, None otherwise

        Note:
            Returns most recently updated chat if multiple matches exist.
            O(N) scan of active chats. Future optimization: add index.
        """
        async with self._lock:
            chats = await self._repo.filter_chats(channel=channel)
            # Single pass: match session_id, and when a user_id is given,
            # also require it to match. An empty/None user_id means "no user
            # filter" (backward-compatible).
            matching_chats = [
                chat
                for chat in chats
                if chat.session_id == session_id
                and (not user_id or chat.user_id == user_id)
            ]

            if not matching_chats:
                logger.debug(
                    f"No chat found for session={session_id[:30]} "
                    f"channel={channel} user_id={user_id}",
                )
                return None

            most_recent = max(matching_chats, key=lambda c: c.updated_at)
            logger.debug(
                f"Found chat_id={most_recent.id} "
                f"for session={session_id[:30]} user_id={user_id} "
                f"(from {len(matching_chats)} matches)",
            )
            return most_recent.id
