# -*- coding: utf-8 -*-
"""存储无关的完整会话记录与 Repository 契约。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Literal, Mapping
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

ConversationStatus = Literal["active", "archived", "deleted"]
RunStatus = Literal[
    "queued",
    "running",
    "waiting_input",
    "waiting_approval",
    "completed",
    "failed",
    "cancelled",
]
AttachmentLifecycle = Literal["temporary", "saved", "deleted"]


class _Record(BaseModel):
    model_config = ConfigDict(frozen=True)


class ConversationRecord(_Record):
    id: UUID
    agent_id: UUID
    owner_user_id: UUID
    title: str
    status: ConversationStatus
    model_override_id: UUID | None = None
    shared_app_id: UUID | None = None
    publication_id: UUID | None = None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None


ConversationAccessRole = Literal["owner", "viewer"]


class ConversationAccessRecord(_Record):
    """会话及当前用户访问角色。"""

    conversation: ConversationRecord
    access_role: ConversationAccessRole
    shared_by_username: str | None = None

    @property
    def read_only(self) -> bool:
        return self.access_role == "viewer"


class ConversationMemberRecord(_Record):
    """会话的只读分享成员。"""

    conversation_id: UUID
    user_id: UUID
    username: str
    role: Literal["viewer"] = "viewer"
    granted_by: UUID
    created_at: datetime


class ShareCandidate(_Record):
    """已具备当前 Agent 使用资格、可被加入会话的用户。"""

    user_id: UUID
    username: str
    platform_role: Literal["admin", "member"]


class MessageRecord(_Record):
    id: UUID
    conversation_id: UUID
    run_id: UUID | None = None
    sequence: int
    role: str
    message_type: str
    content: dict[str, Any]
    status: str
    created_by: UUID | None = None
    created_at: datetime


class RunRecord(_Record):
    id: UUID
    conversation_id: UUID
    initiated_by: UUID
    status: RunStatus
    started_at: datetime
    finished_at: datetime | None = None
    error_summary: str | None = None


class RunEventRecord(_Record):
    id: UUID
    run_id: UUID
    sequence: int
    event_type: str
    payload: dict[str, Any]
    tool_call_id: UUID | None = None
    created_at: datetime


class ToolCallRecord(_Record):
    id: UUID
    run_id: UUID
    call_id: str
    source: str
    tool_name: str
    status: str
    redacted_arguments: dict[str, Any] = Field(default_factory=dict)
    approval_id: UUID | None = None
    output_ref: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class AttachmentRecord(_Record):
    id: UUID
    agent_id: UUID
    conversation_id: UUID | None = None
    message_id: UUID | None = None
    owner_user_id: UUID
    storage_key: str
    original_name: str
    media_type: str
    size: int
    content_hash: str
    created_at: datetime
    lifecycle: AttachmentLifecycle = "temporary"
    saved_path: str | None = None
    saved_at: datetime | None = None
    deleted_at: datetime | None = None
    updated_at: datetime

    @model_validator(mode="before")
    @classmethod
    def _default_legacy_updated_at(cls, value: Any) -> Any:
        """兼容生命周期字段引入前写入的 JSON 附件记录。"""
        if isinstance(value, Mapping) and not value.get("updated_at"):
            created_at = value.get("created_at")
            if created_at is not None:
                return {**value, "updated_at": created_at}
        return value


class RepositoryConflictError(RuntimeError):
    """同一逻辑键收到不同内容时拒绝覆盖。"""


class ConversationShareEligibilityError(RuntimeError):
    """目标用户不满足当前 Agent 的会话分享资格。"""


class ConversationRepository(ABC):

    async def bind_publication(
        self,
        conversation_id: UUID,
        *,
        expected_agent_id: UUID,
        shared_app_id: UUID,
        publication_id: UUID,
        updated_at: datetime,
    ) -> ConversationRecord | None:
        """将普通会话一次性绑定到不可变发布版本。"""
        raise NotImplementedError

    async def set_model_override(
        self,
        conversation_id: UUID,
        *,
        expected_agent_id: UUID,
        model_override_id: UUID | None,
        updated_at: datetime,
    ) -> ConversationRecord | None:
        """Atomically change only the selected model of an owned conversation."""
        raise NotImplementedError

    @abstractmethod
    async def create_conversation(
        self, record: ConversationRecord
    ) -> ConversationRecord: ...

    @abstractmethod
    async def get_conversation(
        self, conversation_id: UUID
    ) -> ConversationRecord | None: ...

    @abstractmethod
    async def list_conversations(
        self, *, owner_user_id: UUID, include_deleted: bool = False
    ) -> list[ConversationRecord]: ...

    async def list_conversations_for_user(
        self,
        *,
        user_id: UUID,
        scope: Literal["all", "owned", "shared"] = "all",
    ) -> list[ConversationAccessRecord]:
        """List conversations visible to a user under the repository policy."""
        raise NotImplementedError

    async def get_conversation_for_user(
        self,
        *,
        conversation_id: UUID,
        user_id: UUID,
    ) -> ConversationAccessRecord | None:
        """Return one visible conversation and the caller's access role."""
        raise NotImplementedError

    async def list_members(
        self,
        *,
        conversation_id: UUID,
        owner_user_id: UUID,
    ) -> list[ConversationMemberRecord]:
        raise NotImplementedError

    async def list_share_candidates(
        self,
        *,
        conversation_id: UUID,
        owner_user_id: UUID,
    ) -> list[ShareCandidate]:
        raise NotImplementedError

    async def add_viewer(
        self,
        *,
        conversation_id: UUID,
        user_id: UUID,
        granted_by: UUID,
    ) -> ConversationMemberRecord:
        raise NotImplementedError

    async def remove_viewer(
        self,
        *,
        conversation_id: UUID,
        user_id: UUID,
        owner_user_id: UUID,
    ) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def update_conversation(
        self,
        conversation_id: UUID,
        *,
        title: str | None = None,
        status: ConversationStatus | None = None,
        updated_at: datetime,
    ) -> ConversationRecord | None: ...

    @abstractmethod
    async def save_message(self, record: MessageRecord) -> MessageRecord: ...

    @abstractmethod
    async def list_messages(self, conversation_id: UUID) -> list[MessageRecord]: ...

    @abstractmethod
    async def create_run(self, record: RunRecord) -> RunRecord: ...

    @abstractmethod
    async def get_run(self, run_id: UUID) -> RunRecord | None: ...

    @abstractmethod
    async def finish_run(
        self,
        run_id: UUID,
        *,
        status: RunStatus,
        finished_at: datetime,
        error_summary: str | None = None,
    ) -> RunRecord | None: ...

    @abstractmethod
    async def append_event(self, record: RunEventRecord) -> RunEventRecord: ...

    @abstractmethod
    async def list_events(self, run_id: UUID) -> list[RunEventRecord]: ...

    @abstractmethod
    async def upsert_tool_call(self, record: ToolCallRecord) -> ToolCallRecord: ...

    @abstractmethod
    async def list_tool_calls(self, run_id: UUID) -> list[ToolCallRecord]: ...

    @abstractmethod
    async def add_attachment(self, record: AttachmentRecord) -> AttachmentRecord: ...

    @abstractmethod
    async def get_attachment(
        self,
        *,
        attachment_id: UUID,
        owner_user_id: UUID,
    ) -> AttachmentRecord | None: ...

    @abstractmethod
    async def bind_attachment(
        self,
        *,
        attachment_id: UUID,
        owner_user_id: UUID,
        agent_id: UUID,
        conversation_id: UUID,
        message_id: UUID,
    ) -> AttachmentRecord: ...

    @abstractmethod
    async def list_attachments(
        self, conversation_id: UUID
    ) -> list[AttachmentRecord]: ...

    @abstractmethod
    async def list_owned_attachments(
        self,
        *,
        owner_user_id: UUID,
        agent_id: UUID,
        lifecycle: AttachmentLifecycle | None = None,
        conversation_id: UUID | None = None,
    ) -> list[AttachmentRecord]: ...

    @abstractmethod
    async def update_attachment_lifecycle(
        self,
        *,
        attachment_id: UUID,
        owner_user_id: UUID,
        lifecycle: AttachmentLifecycle,
        storage_key: str,
        saved_path: str | None,
        saved_at: datetime | None,
        deleted_at: datetime | None,
        updated_at: datetime,
    ) -> AttachmentRecord | None: ...
