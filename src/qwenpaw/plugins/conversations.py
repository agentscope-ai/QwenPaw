# -*- coding: utf-8 -*-
"""Limited saved text from the main conversation selected by the caller."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TYPE_CHECKING

from .errors import SDKError

if TYPE_CHECKING:
    from .apps import AppContext


@dataclass(frozen=True)
class ConversationMessage:
    role: Literal["user", "assistant"]
    content: str


class ConversationService:
    """Use app.conversations; no arbitrary session lookup is exposed.

    The host binds the authenticated request's X-Chat-Id selection. Only
    saved user/assistant text is returned, excluding tool calls, reasoning,
    attachments and internal metadata. Unsaved in-flight output is excluded.
    """

    def __init__(self, context: AppContext):
        self._context = context

    async def history(
        self,
        *,
        limit: int = 20,
    ) -> tuple[ConversationMessage, ...]:
        """Recent messages in chronological order; limit is 1–100."""
        if type(limit) is not int or not 1 <= limit <= 100:
            raise SDKError(
                "Conversation history limit must be between 1 and 100",
            )
        services = self._context._services
        workspace, chat = await services.selected_conversation()
        state = await workspace.session.get_session_state_dict(
            session_id=chat.session_id,
            user_id=chat.user_id,
            channel=chat.channel,
            allow_not_exist=True,
        )
        services.guard()
        agent = state.get("agent", {})
        raw = agent.get("state", {}).get("context")
        if raw is None:
            raw = agent.get("memory", {}).get("content", ())
        result = []
        for group in raw or ():
            for item in group if isinstance(group, list) else [group]:
                if not isinstance(item, dict) or item.get("role") not in {
                    "user",
                    "assistant",
                }:
                    continue
                content = item.get("content", "")
                if isinstance(content, list):
                    content = "".join(
                        block["text"]
                        for block in content
                        if isinstance(block, dict)
                        and block.get("type") == "text"
                        and isinstance(block.get("text"), str)
                    )
                if isinstance(content, str) and content:
                    result.append(ConversationMessage(item["role"], content))
        return tuple(result[-limit:])
