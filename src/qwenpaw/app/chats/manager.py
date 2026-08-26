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
    ChatGroup,
    ChatGroupKind,
    ChatSpec,
    ChatUpdate,
    SOURCE_CHAT_GROUP_IDS,
    SessionSource,
)
from .repo import BaseChatRepository
from ..channels.schema import DEFAULT_CHANNEL
from ...utils.logging import sanitize_log_value

logger = logging.getLogger(__name__)

MAX_BATCH_SIZE = 500


def _default_group_id(source: SessionSource) -> str:
    """Return the built-in group for a chat source."""
    return SOURCE_CHAT_GROUP_IDS[source]


def _source_order(group: ChatGroup) -> int:
    """Return a stable tail order for source-driven groups."""
    if group.kind == ChatGroupKind.cron:
        return list(SessionSource).index(SessionSource.cron)
    if group.kind == ChatGroupKind.subagents:
        return list(SessionSource).index(SessionSource.subagent)
    return -1


def _is_fixed_source_group(group: ChatGroup) -> bool:
    """Return whether a group represents an automated session source."""
    return group.kind in {ChatGroupKind.cron, ChatGroupKind.subagents}


def _ordered_groups(groups: list[ChatGroup]) -> list[ChatGroup]:
    """Sort pinned groups first and keep source groups at the end."""
    return sorted(
        groups,
        key=lambda group: (
            _is_fixed_source_group(group),
            _source_order(group)
            if _is_fixed_source_group(group)
            else (not group.pinned, group.order),
        ),
    )


class ChatManager:  # pylint: disable=too-many-public-methods
    """Manages chat specifications in repository.

    Only handles ChatSpec CRUD operations.
    Does NOT manage Redis session state - that's handled by SafeJSONSession.

    Similar to CronManager's role in crons module.
    """

    def __init__(
        self,
        *,
        repo: BaseChatRepository,
        on_session_closed: Callable[[str], Awaitable[None]] | None = None,
    ):
        """Initialize chat manager.

        Args:
            repo: Chat spec repository for persistence
        """
        self._repo = repo
        self._on_session_closed = on_session_closed
        self._lock = asyncio.Lock()
        logger.debug(
            f"ChatManager created with repo path: {repo.path}",
        )

    def set_on_session_closed(
        self,
        callback: Callable[[str], Awaitable[None]] | None,
    ) -> None:
        """Update the browser lifecycle callback when a service is reused."""
        self._on_session_closed = callback

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
        group_id: str | None = None,
        parent_session_id: str | None = None,
        root_session_id: str | None = None,
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
            try:
                resolved_source = SessionSource(source)
            except ValueError:
                resolved_source = SessionSource.chat
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
            spec = ChatSpec(
                session_id=session_id,
                user_id=user_id,
                channel=channel,
                name=name,
                source=resolved_source,
                group_id=group_id or _default_group_id(resolved_source),
                parent_session_id=parent_session_id,
                root_session_id=root_session_id,
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
            if spec.group_id is None:
                spec = spec.model_copy(
                    update={"group_id": _default_group_id(spec.source)},
                )
            await self._validate_group_id_locked(spec.group_id)
            await self._repo.upsert_chat(spec)
            return spec

    async def _validate_group_id_locked(self, group_id: str | None) -> None:
        """Validate a group ID while the manager lock is held."""
        chats_file = await self._repo.load()
        if group_id not in {group.id for group in chats_file.groups}:
            raise ValueError(f"Unknown chat group: {group_id}")

    async def list_groups(self) -> list[ChatGroup]:
        """List persisted groups in display order."""
        async with self._lock:
            chats_file = await self._repo.load()
            return _ordered_groups(chats_file.groups)

    async def create_group(self, name: str) -> ChatGroup:
        """Create a custom group after the current final group."""
        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("Group name cannot be empty")
        async with self._lock:
            chats_file = await self._repo.load()
            next_order = (
                max(
                    (group.order for group in chats_file.groups),
                    default=-1,
                )
                + 1
            )
            group = ChatGroup(name=normalized_name, order=next_order)
            chats_file.groups.append(group)
            await self._repo.save(chats_file)
            return group

    async def update_group(
        self,
        group_id: str,
        *,
        name: str | None = None,
        pinned: bool | None = None,
    ) -> ChatGroup | None:
        """Rename or pin a mutable group."""
        if name is None and pinned is None:
            raise ValueError("At least one group field must be provided")
        normalized_name = name.strip() if name is not None else None
        if normalized_name == "":
            raise ValueError("Group name cannot be empty")
        async with self._lock:
            chats_file = await self._repo.load()
            for index, group in enumerate(chats_file.groups):
                if group.id != group_id:
                    continue
                if _is_fixed_source_group(group):
                    raise ValueError("Source groups cannot be changed")
                updates = {}
                if normalized_name is not None:
                    updates["name"] = normalized_name
                if pinned is not None:
                    updates["pinned"] = pinned
                updated = group.model_copy(update=updates)
                chats_file.groups[index] = updated
                await self._repo.save(chats_file)
                return updated
            return None

    async def reorder_groups(self, group_ids: list[str]) -> list[ChatGroup]:
        """Persist a complete, duplicate-free group order."""
        async with self._lock:
            chats_file = await self._repo.load()
            current = {group.id: group for group in chats_file.groups}
            if len(group_ids) != len(set(group_ids)):
                raise ValueError("Group order contains duplicate IDs")
            if set(group_ids) != set(current):
                raise ValueError("Group order must contain every group ID")
            fixed_ids = [
                group.id
                for group in _ordered_groups(list(current.values()))
                if _is_fixed_source_group(group)
            ]
            if group_ids[-len(fixed_ids) :] != fixed_ids:
                raise ValueError("Source groups must remain at the end")
            chats_file.groups = [
                current[group_id].model_copy(update={"order": index})
                for index, group_id in enumerate(group_ids)
            ]
            await self._repo.save(chats_file)
            return _ordered_groups(chats_file.groups)

    async def delete_group(self, group_id: str) -> bool:
        """Delete a custom group and return chats to their system group."""
        async with self._lock:
            chats_file = await self._repo.load()
            target = next(
                (group for group in chats_file.groups if group.id == group_id),
                None,
            )
            if target is None:
                return False
            if target.kind != ChatGroupKind.custom:
                raise ValueError("Built-in chat groups cannot be deleted")

            chats_file.groups = [
                group for group in chats_file.groups if group.id != group_id
            ]
            for index, chat in enumerate(chats_file.chats):
                if chat.group_id != group_id:
                    continue
                chats_file.chats[index] = chat.model_copy(
                    update={"group_id": _default_group_id(chat.source)},
                )
            for index, group in enumerate(
                sorted(chats_file.groups, key=lambda item: item.order),
            ):
                group.order = index
            await self._repo.save(chats_file)
            return True

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

        if "group_id" in patch.model_fields_set:
            await self._validate_group_id_locked(patch.group_id)

        updates = patch.model_dump(
            exclude_none=True,
            exclude_unset=True,
        )
        merged = existing.model_copy(update=updates)
        if patch.model_fields_set != {"group_id"}:
            merged.updated_at = datetime.now(timezone.utc)
        await self._repo.upsert_chat(merged)
        return merged

    async def touch_chat(self, chat_id: str) -> Optional[ChatSpec]:
        """Refresh updated_at without rewriting other chat fields."""
        return await self.patch_chat(chat_id, ChatUpdate())

    async def mark_chat_finished(
        self,
        chat_id: str,
        finished_at: datetime,
    ) -> Optional[ChatSpec]:
        """Persist the newest task completion marker for one chat."""
        async with self._lock:
            existing = await self._repo.get_chat(chat_id)
            if existing is None:
                return None
            if (
                existing.last_finished_at is not None
                and existing.last_finished_at >= finished_at
            ):
                return existing
            updated = existing.model_copy(
                update={
                    "last_finished_at": finished_at,
                    "updated_at": max(existing.updated_at, finished_at),
                },
            )
            await self._repo.upsert_chat(updated)
            return updated

    async def set_project_dir(
        self,
        chat_id: str,
        project_dir: str | None,
    ) -> Optional[ChatSpec]:
        """Set or clear the controlled Session project directory override."""
        async with self._lock:
            existing = await self._repo.get_chat(chat_id)
            if existing is None:
                return None
            meta = dict(existing.meta)
            runtime_context = dict(meta.get("runtime_context") or {})
            if project_dir is None:
                runtime_context.pop("project_dir", None)
            else:
                runtime_context["project_dir"] = project_dir
            if runtime_context:
                meta["runtime_context"] = runtime_context
            else:
                meta.pop("runtime_context", None)
            updated = existing.model_copy(update={"meta": meta})
            updated.updated_at = datetime.now(timezone.utc)
            await self._repo.upsert_chat(updated)
            return updated

    async def set_session_project_dirs(
        self,
        chat_id: str,
        project_dirs: Optional[list[dict]],
    ) -> Optional[ChatSpec]:
        """Set or clear this chat's project-directory list override.

        ``project_dirs`` is the whole list, primary first (each entry
        ``{"path": str, "label": str | None}``); the stored value
        replaces whatever was there before. Passing ``None`` removes the
        override so the chat goes back to inheriting the agent default.

        The value lives in the controlled ``meta["runtime_context"]``
        namespace, and the read-modify-write happens under the manager
        lock to avoid losing a concurrent update to a sibling key.

        Migration is deliberately **one-way**. Writing the list drops the
        pre-multi-root scalar ``project_dir``, so a build that only knows
        the scalar (i.e. before this feature) reads no override at all and
        falls back to the agent default — the user has to pick the
        directory again. Reading in the other direction is safe: a chat
        still holding the scalar is understood as a one-entry list (see
        ``session_project_dirs_from_meta``). Keep it one-way: writing both
        keys would leave two sources of truth with no way to tell which
        one is newer, and the stale list would silently win.

        Returns the updated spec, or ``None`` if the chat does not exist.
        """
        async with self._lock:
            existing = await self._repo.get_chat(chat_id)
            if existing is None:
                return None

            meta = dict(existing.meta or {})
            runtime_context = dict(meta.get("runtime_context") or {})
            if project_dirs:
                runtime_context["project_dirs"] = project_dirs
            else:
                runtime_context.pop("project_dirs", None)
            # Legacy single-value chats: the list supersedes the scalar.
            runtime_context.pop("project_dir", None)
            # Dropped feature: a chat written by an earlier build may still
            # carry a display name nothing reads. Clear it rather than
            # leaving a key that keeps the namespace alive forever.
            runtime_context.pop("project_name", None)

            if runtime_context:
                meta["runtime_context"] = runtime_context
            else:
                # Drop the namespace entirely once it is empty, so a chat
                # that never used an override has no leftover scaffolding.
                meta.pop("runtime_context", None)

            merged = existing.model_copy(update={"meta": meta})
            merged.updated_at = datetime.now(timezone.utc)
            await self._repo.upsert_chat(merged)
            return merged

    async def delete_chats(self, chat_ids: list[str]) -> bool:
        """Delete a chat spec.

        Note: This only deletes the spec. Redis session state is NOT deleted.

        Args:
            chat_ids: List of chat IDs

        Returns:
            True if deleted, False if not found
        """
        session_ids: set[str] = set()
        async with self._lock:
            for chat_id in chat_ids:
                chat = await self._repo.get_chat(chat_id)
                if chat is not None:
                    session_ids.add(chat.session_id)
            deleted = await self._repo.delete_chats(chat_ids)

            if deleted:
                logger.debug(f"Deleted chats: {chat_ids}")

        if deleted:
            for session_id in session_ids:
                await self._close_browser_session(session_id)
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
        archived: ChatSpec | None
        async with self._lock:
            existing = await self._repo.get_chat(chat_id)
            if existing is None:
                return None
            if check_status == "running":
                raise ValueError("in_progress")
            if existing.archived:
                archived = existing
            else:
                archived = existing.model_copy(
                    update={"archived_at": datetime.now(timezone.utc)},
                )
                assert archived is not None
                await self._repo.upsert_chat(archived)
                logger.debug("Archived chat: %s", sanitize_log_value(chat_id))
        await self._close_browser_session(archived.session_id)
        return archived

    async def _close_browser_session(self, session_id: str) -> None:
        """Ask the optional lifecycle owner to close one chat's browser."""
        if self._on_session_closed is None:
            return
        try:
            await self._on_session_closed(session_id)
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "chat browser cleanup failed for session=%s",
                session_id[:30],
                exc_info=True,
            )

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
        session_ids: set[str] = set()
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
                session_ids.add(existing.session_id)
        for session_id in session_ids:
            await self._close_browser_session(session_id)
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

    async def touch_chat_by_session(
        self,
        session_id: str,
        channel: str,
        user_id: str | None = None,
    ) -> Optional[ChatSpec]:
        """Find and touch a chat with one repository load and save.

        This is the message-path variant of :meth:`touch_chat`. It avoids a
        separate session lookup followed by another read-modify-write cycle.
        """
        async with self._lock:
            touched = await self._repo.touch_chat_by_session(
                session_id=session_id,
                channel=channel,
                user_id=user_id,
            )
            if touched is None:
                logger.debug(
                    f"No chat to touch for session={session_id[:30]} "
                    f"channel={channel} user_id={user_id}",
                )
            return touched
