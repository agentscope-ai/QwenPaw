# -*- coding: utf-8 -*-
"""本人历史会话的轻量只读视图，不初始化任何 Agent 运行服务。"""

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from ...access.agent_repository import agent_database_id
from ...identity.runtime import get_identity_schema
from ..task_tracker import TaskTracker
from .manager import ChatManager
from .repo.json_repo import JsonChatRepository
from .repo.postgres_repo import PostgresConversationRepository
from .run_persistence import PostgresChatRunPersistence
from .session import SafeJSONSession, sanitize_filename, session_filename


class OwnerHistoryRepository:
    """仅暴露本人、指定 Agent 的会话读取；不转发任何写接口。"""

    def __init__(self, repository, *, user_id: UUID, agent_id: UUID):
        self._repository = repository.with_user(user_id)
        self._user_id = user_id
        self._agent_id = agent_id

    def with_user(self, user_id: UUID):
        if user_id != self._user_id:
            raise ValueError("historical_owner_mismatch")
        return self

    async def get_conversation_for_user(self, *, conversation_id, user_id):
        if user_id != self._user_id:
            return None
        access = await self._repository.get_conversation_for_user(
            conversation_id=conversation_id,
            user_id=user_id,
        )
        if access is None or (
            access.conversation.owner_user_id != self._user_id
            or access.conversation.agent_id != self._agent_id
        ):
            return None
        return access.model_copy(update={"historical_read_only": True})

    async def list_conversations_for_user(self, *, user_id, scope="all", **filters):
        if user_id != self._user_id or scope == "shared":
            return []
        if filters.get("agent_id", self._agent_id) != self._agent_id:
            return []
        rows = await self._repository.list_conversations_for_user(
            user_id=user_id,
            scope="owned",
            **(filters | {"agent_id": self._agent_id}),
        )
        return [
            row.model_copy(update={"historical_read_only": True})
            for row in rows
            if row.conversation.owner_user_id == self._user_id
            and row.conversation.agent_id == self._agent_id
        ]

    async def _read(self, method, conversation_id, *args, **kwargs):
        access = await self.get_conversation_for_user(
            conversation_id=conversation_id,
            user_id=self._user_id,
        )
        if access is None:
            raise RuntimeError("chat_not_found")
        return await getattr(self._repository, method)(conversation_id, *args, **kwargs)

    async def list_messages(self, conversation_id):
        return await self._read("list_messages", conversation_id)

    async def list_history_page(self, conversation_id, **kwargs):
        return await self._read("list_history_page", conversation_id, **kwargs)

    async def has_messages(self, conversation_id):
        return await self._read("has_messages", conversation_id)

    async def get_message(self, conversation_id, message_id):
        return await self._read("get_message", conversation_id, message_id)

    async def list_attachments(self, conversation_id):
        return await self._read("list_attachments", conversation_id)


class _ReadOnlySession(SafeJSONSession):
    """旧会话只读寻址，避免 SafeJSONSession 读取时迁移或创建目录。"""

    def _get_save_path(self, session_id, user_id, channel=""):
        filename = session_filename(session_id, user_id)
        legacy = Path(self.save_dir) / filename
        if not channel:
            return str(legacy)
        safe_channel = sanitize_filename(channel)
        if safe_channel in {".", ".."}:
            raise ValueError("invalid_session_channel")
        scoped = Path(self.save_dir) / safe_channel / filename
        return str(scoped if scoped.exists() or not legacy.exists() else legacy)


@dataclass(frozen=True)
class HistoricalWorkspace:
    agent_id: str
    workspace_dir: Path
    chat_manager: ChatManager
    session: SafeJSONSession
    task_tracker: TaskTracker
    config: object


def create_historical_workspace(*, agent_id: str, workspace_dir: str, user_id: UUID):
    """只组装既有磁盘与 PostgreSQL 读取入口，不启动/回填/修改运行状态。"""
    root = Path(workspace_dir).expanduser().resolve()
    if not root.is_dir():
        raise ValueError("historical_workspace_unavailable")
    database_id = agent_database_id(agent_id)
    repository = OwnerHistoryRepository(
        PostgresConversationRepository(schema=get_identity_schema()),
        user_id=user_id,
        agent_id=database_id,
    )
    persistence = PostgresChatRunPersistence(
        repository=repository,
        agent_id=database_id,
        payload_storage_dir=root / ".qwenpaw" / "chat-event-payloads",
    )
    return HistoricalWorkspace(
        agent_id=agent_id,
        workspace_dir=root,
        chat_manager=ChatManager(
            repo=JsonChatRepository(root / "chats.json"),
            conversation_repository=repository,
            run_persistence=persistence,
        ),
        session=_ReadOnlySession(save_dir=str(root / "sessions")),
        task_tracker=TaskTracker(),
        # Legacy 只读取原始状态，绝不调用第三方 harness hydrate。
        config=SimpleNamespace(backend="qwenpaw", backend_settings={}),
    )
