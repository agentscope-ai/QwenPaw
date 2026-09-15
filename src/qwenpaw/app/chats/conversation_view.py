"""Bounded, rebuildable public conversation context owned by a Chat."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict, dataclass, replace
from typing import Any, Iterable

from agentscope.message import Msg, TextBlock

from ...constant import (
    EXTERNAL_USER_QUERY_MESSAGE_TAG,
    QWENPAW_CLIENT_MESSAGE_ID_KEY,
    QWENPAW_MESSAGE_TAG_KEY,
)
from .replies import ChatReply, project_replies

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ConversationItem:
    id: str
    order: int
    role: str
    text: str
    input_ids: tuple[str, ...]
    source: str
    generation: str = ""
    persisted: bool = False
    truncated: bool = False
    query_target_input_ids: tuple[str, ...] = ()


def reply_item(reply: ChatReply) -> ConversationItem:
    return ConversationItem(
        reply.identity,
        reply.order,
        "assistant",
        reply.text,
        reply.input_ids,
        "agent",
        reply.phase,
        reply.persisted,
    )


def conversation_items(message: Msg) -> Iterable[ConversationItem]:
    """Only public text with source ownership; never tool/reasoning blocks."""
    metadata = message.metadata or {}
    if metadata.get("request_termination"):
        return
    native = bool(metadata.get("realtime_voice_turn_id"))
    external = (
        metadata.get(QWENPAW_MESSAGE_TAG_KEY)
        == EXTERNAL_USER_QUERY_MESSAGE_TAG
    )
    if native or (message.role == "user" and external):
        text = "\n".join(
            block.text
            for block in message.content or []
            if isinstance(block, TextBlock)
        )
        identity = str(
            metadata.get(QWENPAW_CLIENT_MESSAGE_ID_KEY) or message.id
        )
        targets = metadata.get("query_target_input_ids")
        yield ConversationItem(
            identity,
            metadata.get("timeline_order", 0),
            message.role,
            text,
            tuple(metadata.get("responds_to_input_ids") or (identity,)),
            "voice" if native else "user",
            str(metadata.get("voice_generation_status", "")),
            query_target_input_ids=(
                tuple(dict.fromkeys(targets))
                if native
                and message.role == "user"
                and isinstance(targets, list)
                and all(
                    isinstance(target, str) and target for target in targets
                )
                else ()
            ),
        )
    else:
        for reply in project_replies([message]).values():
            yield reply_item(reply)


class ChatConversationView:
    """One cold snapshot plus bounded source upserts.

    This is not another history store.

    All mutations occur on the owning event loop. Loading constructs a separate
    bounded snapshot off-loop; newer source records win its handoff. A false
    persisted flag means unconfirmed, not proof that storage failed.
    """

    def __init__(self, *, max_items: int = 256, max_chars: int = 64_000):
        self._max_items = max_items
        self._max_chars = max_chars
        self._items: dict[str, ConversationItem] = {}
        self._omitted = False
        self._floor = 0
        self._loaded = False
        self._closed = False
        self._load_task: asyncio.Task | None = None

    def observe(self, items: Iterable[ConversationItem]) -> None:
        if self._closed:
            return
        for item in items:
            if (
                not isinstance(item.order, int)
                or isinstance(item.order, bool)
                or item.order <= 0
                or not item.text
                or item.order < self._floor
            ):
                continue
            if len(item.text) > self._max_chars:
                item = replace(
                    item, text=item.text[: self._max_chars], truncated=True
                )
            previous = self._items.get(item.id)
            if (
                previous
                and replace(previous, persisted=item.persisted) == item
            ):
                item = replace(
                    item, persisted=previous.persisted or item.persisted
                )
            self._items[item.id] = item
        retained, size = {}, 0
        for item in reversed(self._ordered()):
            if (
                len(retained) >= self._max_items
                or size + len(item.text) > self._max_chars
            ):
                self._omitted = True
                break
            retained[item.id] = item
            size += len(item.text)
        self._items = dict(reversed(tuple(retained.items())))
        if self._omitted and self._items:
            self._floor = min(item.order for item in self._items.values())

    def observe_message(
        self, message: Msg, *, persisted: bool = False
    ) -> None:
        self.observe(
            replace(item, persisted=persisted)
            for item in conversation_items(message)
        )

    def mark_saved(self, messages: Iterable[Msg]) -> None:
        # A late save of an older source revision cannot overwrite a newer one.
        for message in messages:
            for item in conversation_items(message):
                current = self._items.get(item.id)
                if current and replace(current, persisted=False) == item:
                    self._items[item.id] = replace(current, persisted=True)

    def _ordered(self) -> list[ConversationItem]:
        return sorted(
            self._items.values(),
            key=lambda item: (item.order, item.role != "user"),
        )

    def _snapshot(self, state: dict[str, Any]) -> ChatConversationView:
        view = ChatConversationView(
            max_items=self._max_items, max_chars=self._max_chars
        )
        context = ((state.get("agent") or {}).get("state") or {}).get(
            "context"
        ) or []
        pending = (state.get("chat_timeline") or {}).get("pending") or []
        for raw in (*context, *pending):
            view.observe_message(Msg.model_validate(raw), persisted=True)
        view._loaded = True
        return view

    async def _load(self, session: Any, chat: Any, replies: Any) -> None:
        state = await session.get_session_state_dict(
            chat.session_id, chat.user_id, chat.channel
        )
        baseline = await asyncio.to_thread(self._snapshot, state)
        if self._closed:
            return
        # A Voice connection may start after an Agent has already replied but
        # before it saved. Seed from its existing live result projection too.
        if replies is not None:
            self.observe(reply_item(reply) for reply in replies.capture({}))
        baseline._floor = max(baseline._floor, self._floor)
        baseline._items = {
            k: v
            for k, v in baseline._items.items()
            if v.order >= baseline._floor
        }
        baseline.observe(self._items.values())
        self._items = baseline._items
        self._omitted |= baseline._omitted
        self._floor = baseline._floor
        self._loaded = True

    async def read_before(
        self,
        session: Any,
        chat: Any,
        *,
        turn_id: str,
        order: int | None,
        max_turns: int,
        max_chars: int,
        replies: Any = None,
    ) -> str:
        """Return bounded JSON with explicit unavailable/omitted state."""
        if not self._loaded and not self._closed:
            if self._load_task is None:
                self._load_task = asyncio.create_task(
                    self._load(session, chat, replies)
                )
            try:
                await asyncio.shield(self._load_task)
            except Exception:
                logger.warning(
                    "Conversation context load failed for %s",
                    chat.id,
                    exc_info=True,
                )
                self._load_task = None  # A later user turn may retry, no loop.
        return self._encode(turn_id, order, max_turns, max_chars)

    def _encode(
        self, turn_id: str, order: int | None, max_turns: int, max_chars: int
    ) -> str:
        if max_chars < 256:
            raise ValueError("conversation context budget is too small")
        payload = {
            "available": self._loaded and not self._closed,
            "omitted": self._omitted,
            "messages": [],
        }

        def encoded() -> str:
            return json.dumps(
                payload, ensure_ascii=False, separators=(",", ":")
            )

        turns: set[str] = set()
        for item in reversed(self._ordered()):
            if (order is not None and item.order >= order) or (
                turn_id and turn_id in item.input_ids
            ):
                continue
            if item.generation in {"failed", "incomplete"}:
                payload["omitted"] = True
                continue
            if len(turns | set(item.input_ids)) > max_turns:
                payload["omitted"] = True
                break
            turns.update(item.input_ids)
            row = asdict(item)
            if not item.query_target_input_ids:
                row.pop("query_target_input_ids")
            payload["messages"].insert(0, row)
            if len(encoded()) > max_chars:
                payload["omitted"] = True
                row["truncated"] = True
                text = row["text"]
                low, high = 0, len(text)
                while low < high:
                    mid = (low + high + 1) // 2
                    row["text"] = text[:mid]
                    if len(encoded()) <= max_chars:
                        low = mid
                    else:
                        high = mid - 1
                row["text"] = text[:low]
                if not low:
                    payload["messages"].pop(0)
                break
        return encoded()

    async def close(self) -> None:
        self._closed = True
        if self._load_task is not None and not self._load_task.done():
            self._load_task.cancel()
            await asyncio.gather(self._load_task, return_exceptions=True)
        self._items.clear()
