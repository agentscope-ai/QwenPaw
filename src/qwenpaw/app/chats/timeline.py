"""Crash-safe admission of non-Agent messages into the Chat timeline."""

from __future__ import annotations

import logging
from typing import Any

from agentscope.message import Msg, TextBlock
from agentscope.state import AgentState
from pydantic import ValidationError

from ...constant import (
    EXTERNAL_USER_QUERY_MESSAGE_TAG,
    QWENPAW_MESSAGE_TAG_KEY,
)
from ...runtime.reply_cycle import TIMELINE_ORDER_METADATA_KEY
from ...schemas import Message
from .conversation_view import ChatConversationView
from .utils import agentscope_msg_to_message

logger = logging.getLogger(__name__)
_JOURNAL_KEY = "chat_timeline"
_PENDING_KEY = "pending"
_NEXT_ORDER_KEY = "next_order"


def _message_order(message: Msg) -> int | None:
    metadata = message.metadata or {}
    value = metadata.get(TIMELINE_ORDER_METADATA_KEY)
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


def _max_message_order(message: Msg) -> int:
    """Return the highest persisted message or content-block order."""
    highest = _message_order(message) or 0
    if isinstance(message.content, list):
        for block in message.content:
            metadata = getattr(block, "metadata", None)
            if not isinstance(metadata, dict):
                continue
            value = metadata.get(TIMELINE_ORDER_METADATA_KEY)
            if (
                isinstance(value, int)
                and not isinstance(value, bool)
                and value > highest
            ):
                highest = value
    return highest


def _runtime_message_order(message: Message) -> int | None:
    metadata = message.metadata or {}
    value = metadata.get(TIMELINE_ORDER_METADATA_KEY)
    nested = metadata.get("metadata")
    if value is None and isinstance(nested, dict):
        value = nested.get(TIMELINE_ORDER_METADATA_KEY)
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


def order_timeline_messages(messages: list[Message]) -> list[Message]:
    """Project ordered runtime messages without disturbing legacy history.

    Messages before the first authoritative order are an immutable legacy
    prefix. From that point on, ordered messages use their server-allocated
    occurrence order; an unannotated message stays immediately after the last
    ordered occurrence that physically preceded it.
    """
    first_ordered = next(
        (
            index
            for index, message in enumerate(messages)
            if _runtime_message_order(message) is not None
        ),
        None,
    )
    if first_ordered is None:
        return list(messages)

    prefix = list(messages[:first_ordered])
    last_order = 0
    sortable: list[tuple[int, int, int, Message]] = []
    for index, message in enumerate(messages[first_ordered:]):
        order = _runtime_message_order(message)
        if order is not None:
            last_order = order
            sortable.append((order, 0, index, message))
        else:
            sortable.append((last_order, 1, index, message))
    sortable.sort(key=lambda item: item[:3])
    return prefix + [item[3] for item in sortable]


def merge_timeline_messages(
    context: list[Msg],
    pending: list[Msg],
) -> list[Msg]:
    """Insert journaled messages by authoritative admission order.

    Agent context remains the durable source of truth. This helper only inserts
    not-yet-reconciled messages before the first later ordered group, while
    retaining the physical order of legacy messages that have no order.
    """
    merged = list(context)
    known = {message.id for message in merged}
    for message in pending:
        if message.id in known:
            continue
        order = _message_order(message)
        insert_at = len(merged)
        if order is not None:
            for index, current in enumerate(merged):
                current_order = _message_order(current)
                if current_order is not None and current_order > order:
                    insert_at = index
                    break
        merged.insert(insert_at, message)
        known.add(message.id)
    return merged


def pending_timeline_messages(state: dict[str, Any]) -> list[Msg]:
    """Validate journaled messages from one already-loaded session state."""
    raw_timeline = state.get(_JOURNAL_KEY)
    if not isinstance(raw_timeline, dict):
        return []
    raw_pending = raw_timeline.get(_PENDING_KEY)
    if not isinstance(raw_pending, list):
        return []
    messages: list[Msg] = []
    for raw in raw_pending:
        try:
            messages.append(Msg.model_validate(raw))
        except ValidationError:
            logger.warning("Ignoring an invalid pending Chat timeline message")
    return messages


def voice_exchange_messages(
    turn_id: str,
    user_text: str,
    assistant_text: str = "",
    *,
    timeline_order: int,
    generation_status: str = "",
) -> list[Msg]:
    """One native record shape for generated context and durable history."""
    if not user_text.strip():
        return []
    metadata = {
        "realtime_voice_turn_id": turn_id,
        "timeline_group_id": turn_id,
        TIMELINE_ORDER_METADATA_KEY: timeline_order,
    }
    messages = [
        Msg(
            id=turn_id,
            name="user",
            role="user",
            content=[TextBlock(id=turn_id, type="text", text=user_text.strip())],
            metadata={
                **metadata,
                QWENPAW_MESSAGE_TAG_KEY: EXTERNAL_USER_QUERY_MESSAGE_TAG,
            },
        )
    ]
    if assistant_text.strip():
        messages.append(
            Msg(
                id=f"{turn_id}_assistant",
                name="QwenPaw Voice",
                role="assistant",
                content=[
                    TextBlock(
                        id=f"{turn_id}_assistant", type="text",
                        text=assistant_text.strip(),
                    ),
                ],
                metadata={
                    **metadata,
                    "responds_to_input_ids": [turn_id],
                    **(
                        {"voice_generation_status": generation_status}
                        if generation_status
                        else {}
                    ),
                },
            )
        )
    return messages


class ChatTimelineJournal:
    """Journal messages, then fold them into Agent context at an idle edge."""

    def __init__(self, workspace: Any, chat: Any) -> None:
        self._workspace = workspace
        self._chat = chat
        self._view: ChatConversationView | None = None

    def conversation_view(self) -> ChatConversationView:
        if self._view is None:
            self._view = (
                self._workspace.task_tracker.conversation_views.setdefault(
                    self._chat.id,
                    ChatConversationView(),
                )
            )
        return self._view

    def observe_voice_exchange(self, *args: Any, **kwargs: Any) -> None:
        for message in voice_exchange_messages(*args, **kwargs):
            self.conversation_view().observe_message(message)

    async def read_context(
        self,
        *,
        turn_id: str = "",
        order: int | None = None,
        max_turns: int,
        max_chars: int,
    ) -> str:
        return await self.conversation_view().read_before(
            self._workspace.session,
            self._chat,
            turn_id=turn_id,
            order=order,
            max_turns=max_turns,
            max_chars=max_chars,
            replies=self._workspace.task_tracker.reply_views.get(
                self._chat.id
            ),
        )

    async def reserve_order(self) -> int:
        """Atomically reserve the next Chat-wide monotonic timeline order."""

        def reserve(state: dict[str, Any]) -> int:
            timeline = state.get(_JOURNAL_KEY)
            if not isinstance(timeline, dict):
                timeline = {}
                state[_JOURNAL_KEY] = timeline
            highest = 0
            raw_agent = state.get("agent", {}).get("state")
            if isinstance(raw_agent, dict):
                try:
                    agent_state = AgentState.model_validate(raw_agent)
                except ValidationError:
                    logger.warning(
                        "Ignoring invalid Agent state while seeding timeline",
                    )
                else:
                    highest = (
                        max(
                            _max_message_order(item)
                            for item in agent_state.context
                        )
                        if agent_state.context
                        else 0
                    )
            pending = pending_timeline_messages(state)
            if pending:
                highest = max(
                    highest,
                    max((_message_order(item) or 0) for item in pending),
                )
            raw_next = timeline.get(_NEXT_ORDER_KEY)
            next_order = (
                raw_next
                if isinstance(raw_next, int)
                and not isinstance(raw_next, bool)
                and raw_next > 0
                else 1
            )
            order = max(next_order, highest + 1)
            timeline[_NEXT_ORDER_KEY] = order + 1
            return order

        return await self._workspace.session.mutate_session_state(
            self._chat.session_id,
            reserve,
            self._chat.user_id,
            self._chat.channel,
        )

    async def append_voice_exchange(
        self,
        turn_id: str,
        user_text: str,
        assistant_text: str = "",
        *,
        timeline_order: int,
        generation_status: str = "",
    ) -> list[Message]:
        """Durably append one user-visible Voice exchange."""
        messages = voice_exchange_messages(
            turn_id,
            user_text,
            assistant_text,
            timeline_order=timeline_order,
            generation_status=generation_status,
        )
        if not messages:
            return []
        view = self.conversation_view()
        for message in messages:
            view.observe_message(message)
        serialized = [message.model_dump(mode="json") for message in messages]

        def append(state: dict[str, Any]) -> None:
            timeline = state.get(_JOURNAL_KEY)
            if not isinstance(timeline, dict):
                timeline = {}
                state[_JOURNAL_KEY] = timeline
            pending = timeline.get(_PENDING_KEY)
            if not isinstance(pending, list):
                pending = []
                timeline[_PENDING_KEY] = pending
            known = {
                str(raw.get("id") or "")
                for raw in pending
                if isinstance(raw, dict)
            }
            pending.extend(
                raw
                for raw in serialized
                if str(raw.get("id") or "") not in known
            )

        await self._workspace.session.mutate_session_state(
            self._chat.session_id,
            append,
            self._chat.user_id,
            self._chat.channel,
        )
        view.mark_saved(messages)
        await self._workspace.chat_manager.touch_chat(self._chat.id)
        return agentscope_msg_to_message(messages)

    async def reconcile(self) -> int:
        """Move journaled messages into Agent context without racing a run."""
        async with self._workspace.task_tracker.idle_guard(self._chat.id):

            def merge(state: dict[str, Any]) -> int:
                pending = pending_timeline_messages(state)
                if not pending:
                    timeline = state.get(_JOURNAL_KEY)
                    if isinstance(timeline, dict):
                        timeline.pop(_PENDING_KEY, None)
                    return 0
                agent = state.setdefault("agent", {})
                raw_agent_state = agent.get("state")
                try:
                    agent_state = (
                        AgentState.model_validate(raw_agent_state)
                        if isinstance(raw_agent_state, dict)
                        else AgentState(session_id=self._chat.session_id)
                    )
                except ValidationError:
                    logger.exception(
                        "Cannot reconcile Chat timeline into invalid Agent state"
                    )
                    return 0
                before = len(agent_state.context)
                agent_state.context = merge_timeline_messages(
                    list(agent_state.context),
                    pending,
                )
                agent["state"] = agent_state.model_dump(mode="json")
                timeline = state.get(_JOURNAL_KEY)
                if isinstance(timeline, dict):
                    timeline.pop(_PENDING_KEY, None)
                return len(agent_state.context) - before

            return await self._workspace.session.mutate_session_state(
                self._chat.session_id,
                merge,
                self._chat.user_id,
                self._chat.channel,
            )


__all__ = [
    "ChatTimelineJournal",
    "merge_timeline_messages",
    "order_timeline_messages",
    "pending_timeline_messages",
]
