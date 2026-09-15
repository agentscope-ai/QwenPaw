"""Read-only projection of ordinary Chat replies for non-Timeline consumers."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from agentscope.message import DataBlock, Msg, TextBlock, URLSource

from .utils import clean_display_text


@dataclass(frozen=True)
class ChatReply:
    message_id: str
    block_id: str
    run_id: str
    input_ids: tuple[str, ...]
    order: int
    phase: str
    text: str
    persisted: bool = False
    media_refs: tuple[tuple[str, str], ...] = ()
    reply_error: str = ""

    @property
    def identity(self) -> str:
        return f"{self.message_id}:{self.block_id}"

    @property
    def content_signature(self) -> tuple:
        return self.text, self.media_refs, self.reply_error

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.identity,
            "input_ids": list(self.input_ids),
            "phase": self.phase,
            "text": self.text,
            "persisted": self.persisted,
            **(
                {"error": {
                    "code": self.reply_error,
                    "stage": (
                        "answer_generation"
                        if self.reply_error == "empty_response"
                        else "unknown"
                    ),
                }}
                if self.reply_error else {}
            ),
            **(
                {
                    "attachments": [
                        {"media_type": kind, "url": url}
                        for kind, url in self.media_refs
                    ]
                }
                if self.media_refs
                else {}
            ),
        }


def project_replies(
    messages: list[Msg], *, persisted: bool = False
) -> dict[str, ChatReply]:
    """Project owned assistant content, never raw tool output."""
    replies = {}
    for message in messages:
        for block in message.content or []:
            reply = _project_block(message, block, persisted=persisted)
            if reply is not None:
                replies[reply.identity] = reply
    return replies


def _project_block(
    message: Msg, block: Any, *, persisted: bool = False
) -> ChatReply | None:
    meta = getattr(block, "metadata", None) or {}
    ids = meta.get("responds_to_input_ids")
    if (
        message.role != "assistant"
        or (message.metadata or {}).get("request_termination")
        or not isinstance(block, (TextBlock, DataBlock))
        or not ids
        or not meta.get("reply_phase")
    ):
        return None
    media = ()
    if isinstance(block, DataBlock):
        # Keep binary data in ordinary Chat; speech only receives a reference.
        url = str(block.source.url) if isinstance(block.source, URLSource) else ""
        media = ((block.media_type, url),)
    return ChatReply(
        message.id,
        block.id,
        str(meta.get("run_id", "")),
        tuple(ids),
        int(meta.get("timeline_order", 0)),
        str(meta["reply_phase"]),
        clean_display_text(block.text, message.role)
        if isinstance(block, TextBlock) else "",
        persisted,
        media,
        meta.get("reply_error", "")
        if isinstance(meta.get("reply_error", ""), str) else "",
    )


class ChatReplyView:
    """Live references until a successful save AND equal disk readback.

    No second message store: active entries point to the Agent's messages.
    Persisted content is projected afresh from the existing session snapshot.
    """

    def __init__(self) -> None:
        self._live: dict[str, tuple[Msg, TextBlock | DataBlock, str]] = {}
        self._saved_runs: set[str] = set()
        self._read_lock = asyncio.Lock()

    async def read(self, session: Any, chat: Any) -> tuple[ChatReply, ...]:
        # One ordered read boundary prevents a delayed older disk read from
        # replacing the live/durable handoff of another consumer.
        async with self._read_lock:
            state = await session.get_session_state_dict(
                chat.session_id,
                chat.user_id,
                chat.channel,
            )
            disk = await asyncio.to_thread(self._disk_replies, state)
            return self._merge(disk)

    def observe(self, message: Msg, run_id: str = "") -> None:
        for block in message.content or []:
            reply = _project_block(message, block)
            if reply is not None:
                self._live[reply.identity] = (
                    message, block, run_id or reply.run_id
                )

    def saved(self, run_id: str) -> None:
        self._saved_runs.add(run_id)

    def capture(self, state: dict[str, Any]) -> tuple[ChatReply, ...]:
        return self._merge(self._disk_replies(state))

    @staticmethod
    def _disk_replies(state: dict[str, Any]) -> dict[str, ChatReply]:
        raw_context = ((state.get("agent") or {}).get("state") or {}).get(
            "context"
        ) or []
        return project_replies(
            [Msg.model_validate(raw) for raw in raw_context], persisted=True
        )

    def _merge(self, disk: dict[str, ChatReply]) -> tuple[ChatReply, ...]:
        merged = dict(disk)
        for identity, (message, block, owner) in tuple(self._live.items()):
            reply = _project_block(message, block)
            if reply is None:
                self._live.pop(identity)
                continue
            durable = disk.get(identity)
            equal = durable is not None and (
                durable.content_signature,
                durable.input_ids,
                durable.phase,
            ) == (reply.content_signature, reply.input_ids, reply.phase)
            if equal and (owner in self._saved_runs or reply.run_id != owner):
                self._live.pop(identity)
                continue
            merged[identity] = reply
        retained_runs = {owner for _, _, owner in self._live.values()}
        self._saved_runs.intersection_update(retained_runs)
        return tuple(sorted(merged.values(), key=lambda r: r.order))
