# -*- coding: utf-8 -*-
"""Crash-recoverable deletion across chat, session, and Scroll stores."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from ...agents.context.scroll.history import (
    delete_history_sessions,
    history_session_watermarks,
)
from ...utils.io_utils import run_sync_io
from .manager import ChatManager
from .models import ChatSpec, PendingChatDeletion
from .repo import JsonChatRepository
from .session import SafeJSONSession, session_relative_path

if TYPE_CHECKING:
    from ..task_tracker import TaskTracker

logger = logging.getLogger(__name__)


class ChatDeletionInProgressError(RuntimeError):
    """One or more selected chats still have an active or reserved run."""

    def __init__(self, chat_ids: list[str]) -> None:
        self.chat_ids = chat_ids
        super().__init__(f"chat deletion blocked by active runs: {chat_ids}")


class ChatDeletionCleanupError(RuntimeError):
    """A durable tombstone exists, but physical cleanup is incomplete."""


def history_db_path(workspace) -> Path:
    """Return the configured Scroll database path for one workspace."""
    filename = "history.db"
    try:
        filename = (
            workspace.config.running.light_context_config.scroll_config
        ).db_filename
    except (AttributeError, TypeError):
        pass
    return Path(workspace.workspace_dir) / filename


async def _build_deletion(
    selected: list[ChatSpec],
    retained: list[ChatSpec],
    db_path: Path,
) -> PendingChatDeletion:
    """Build exact unreferenced file targets and bounded history targets."""
    retained_paths = {
        path
        for chat in retained
        for path in (
            session_relative_path(chat.session_id, chat.user_id),
            session_relative_path(
                chat.session_id,
                chat.user_id,
                chat.channel,
            ),
        )
    }
    retained_sessions = {chat.session_id for chat in retained}

    selected_paths = {
        path
        for chat in selected
        for path in (
            session_relative_path(chat.session_id, chat.user_id),
            session_relative_path(
                chat.session_id,
                chat.user_id,
                chat.channel,
            ),
        )
    }
    session_paths = selected_paths - retained_paths
    history_sessions: set[str] = set()
    for chat in selected:
        if chat.session_id not in retained_sessions:
            history_sessions.add(chat.session_id)

    watermarks = await run_sync_io(
        history_session_watermarks,
        db_path,
        history_sessions,
    )
    return PendingChatDeletion(
        chats=selected,
        session_paths=sorted(session_paths),
        history_watermarks=watermarks,
    )


async def execute_pending_deletion(
    manager: ChatManager,
    session: SafeJSONSession,
    db_path: Path,
    deletion: PendingChatDeletion,
) -> None:
    """Idempotently finish one durable deletion tombstone."""
    await session.stage_deletion(deletion.id, deletion.session_paths)
    removed = await run_sync_io(
        delete_history_sessions,
        db_path,
        deletion.history_watermarks,
    )
    await session.discard_staged_deletion(deletion.id)
    await manager.finalize_deletion(deletion.id)
    logger.info(
        "Deleted %d chat(s), %d history row(s) via tombstone %s",
        len(deletion.chats),
        removed,
        deletion.id,
    )


class ChatDeletionService:
    """Coordinates live task exclusion and durable cross-store cleanup."""

    def __init__(
        self,
        *,
        manager: ChatManager,
        session: SafeJSONSession,
        task_tracker: "TaskTracker",
        db_path: Path,
    ) -> None:
        self._manager = manager
        self._session = session
        self._task_tracker = task_tracker
        self._db_path = db_path

    async def delete(self, chat_ids: list[str]) -> bool:
        """Delete selected chats, or resume their pending deletion."""
        requested = {chat_id for chat_id in chat_ids if chat_id}
        if not requested:
            return False
        conflicts = await self._task_tracker.reserve_for_deletion(requested)
        if conflicts:
            raise ChatDeletionInProgressError(conflicts)
        try:

            async def planner(
                selected: list[ChatSpec],
                retained: list[ChatSpec],
            ) -> PendingChatDeletion:
                return await _build_deletion(
                    selected,
                    retained,
                    self._db_path,
                )

            deletions = await self._manager.prepare_deletion(
                sorted(requested),
                planner,
            )
            if not deletions:
                return False
            for deletion in deletions:
                try:
                    await execute_pending_deletion(
                        self._manager,
                        self._session,
                        self._db_path,
                        deletion,
                    )
                except Exception as exc:
                    raise ChatDeletionCleanupError(
                        "chat deletion cleanup is pending retry",
                    ) from exc
            return True
        finally:
            await self._task_tracker.release_deletion_reservation(requested)


async def recover_pending_chat_deletions() -> set[Path]:
    """Finish deletion tombstones before startup session migration.

    Returns workspace paths whose registry or cleanup could not be processed;
    session migration must skip them for this boot.
    """
    from ...config import load_config
    from ...config.config import load_agent_config

    blocked: set[Path] = set()
    config = load_config()
    for agent_id, agent_ref in config.agents.profiles.items():
        workspace = Path(agent_ref.workspace_dir).expanduser()
        manager = ChatManager(
            repo=JsonChatRepository(workspace / "chats.json"),
        )
        session = SafeJSONSession(str(workspace / "sessions"))
        try:
            pending = await manager.list_pending_deletions()
            if not pending:
                continue
            agent_config = load_agent_config(agent_id)
            filename = "history.db"
            try:
                filename = (
                    agent_config.running.light_context_config.scroll_config
                ).db_filename
            except (AttributeError, TypeError):
                pass
            db_path = workspace / filename
            for deletion in pending:
                await execute_pending_deletion(
                    manager,
                    session,
                    db_path,
                    deletion,
                )
        except Exception:  # noqa: BLE001 - isolate one workspace
            blocked.add(workspace.resolve(strict=False))
            logger.exception(
                "Failed to recover pending chat deletion for agent %s",
                agent_id,
            )
    return blocked
