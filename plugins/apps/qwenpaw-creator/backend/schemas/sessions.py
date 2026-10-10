# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from .common import ContentPart, StrictModel
from .status import AgentStatusBarView


CreatorSessionStatus = Literal[
    "IDLE",
    "RUNNING",
    "WAITING_RUNTIME",
    "INTERRUPT_REQUESTED",
    "WAITING_USER_INPUT",
    "WAITING_EXECUTION_AUTH",
    "PENDING_REVIEW",
    "RESUMING",
    "CANCELLED",
    "ERROR",
]


class CreatorSessionView(StrictModel):
    id: str
    project_id: str = Field(alias="projectId")
    status: CreatorSessionStatus
    active_goal_id: str | None = Field(None, alias="activeGoalId")
    last_message_seq: int = Field(alias="lastMessageSeq", ge=0)
    last_consumed_message_seq: int = Field(
        alias="lastConsumedMessageSeq",
        ge=0,
    )
    last_event_seq: int = Field(alias="lastEventSeq", ge=0)
    error: dict[str, Any] | None = None


class CreatorSessionResponse(StrictModel):
    session: CreatorSessionView
    agent_status_bar: AgentStatusBarView = Field(alias="agentStatusBar")


class CreatorConversationView(StrictModel):
    conversation_id: str = Field(alias="conversationId")
    title: str
    is_default: bool = Field(alias="isDefault")
    created_at: str = Field(alias="createdAt")


class ConversationPage(StrictModel):
    items: list[CreatorConversationView]
    next_cursor: int | None = Field(None, alias="nextCursor")


class ConversationCreated(StrictModel):
    conversation_id: str = Field(alias="conversationId")
    creator_session_id: str = Field(alias="creatorSessionId")
    title: str
    created_at: str = Field(alias="createdAt")


class CreatorMessageView(StrictModel):
    message_id: str = Field(alias="messageId")
    message_seq: int = Field(alias="messageSeq", ge=1)
    role: Literal["system", "user", "assistant", "tool"]
    content: list[dict[str, Any]]
    source: str | None = None
    metadata: dict[str, Any]
    created_at: str = Field(alias="createdAt")


class MessagePage(StrictModel):
    items: list[CreatorMessageView]
    next_after: int | None = Field(None, alias="nextAfter")
    # Backward-pagination cursor: the smallest seq of this page when older
    # history exists (``before``/``tail`` requests only).
    next_before: int | None = Field(None, alias="nextBefore")


class CreatorMessageRequest(StrictModel):
    client_message_id: str = Field(alias="clientMessageId")
    creator_session_id: str | None = Field(None, alias="creatorSessionId")
    conversation_id: str = Field(alias="conversationId")
    message: str | None = None
    content: list[ContentPart] = Field(default_factory=list)
    asset_version_refs: list[str] = Field(
        default_factory=list,
        alias="assetVersionRefs",
    )
    context: dict[str, Any] = Field(default_factory=dict)


class CreatorMessageAccepted(StrictModel):
    message_seq: int = Field(alias="messageSeq")
    event_seq: int = Field(alias="eventSeq")
    classification: Literal[
        "read_only_question",
        "mutation_instruction",
        "review_comment",
        "review_revise",
        "workspace_command",
    ]
    append_state: Literal["appended", "queued_until_message_boundary"] = Field(
        alias="appendState",
    )
    creator_session_id: str = Field(alias="creatorSessionId")
    conversation_id: str = Field(alias="conversationId")
