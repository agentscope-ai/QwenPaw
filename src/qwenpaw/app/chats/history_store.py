# -*- coding: utf-8 -*-
"""Storage-independent reads for user-visible conversation history."""

from __future__ import annotations

import base64
import sqlite3
import struct
from dataclasses import dataclass
from typing import Protocol

from ...schemas import Message
from .transcript import TranscriptCursor

_CURSOR = struct.Struct(">QQQQQQ")
_SNAPSHOT = struct.Struct(">QQ")


@dataclass(frozen=True)
class ConversationHistoryPage:
    """One stable, byte-bounded page in chronological display order."""

    messages: list[Message]
    next_before: str | None
    has_more: bool
    snapshot: str


@dataclass(frozen=True)
class ConversationUserMessage:
    """One lightweight user-message navigation entry."""

    message_id: str
    preview: str
    created_at: str
    anchor: str
    client_message_id: str | None = None


@dataclass(frozen=True)
class ConversationUserMessagePage:
    """One stable page of user-message navigation entries."""

    items: list[ConversationUserMessage]
    next_before: str | None
    has_more: bool
    snapshot: str
    total: int = 0


class ConversationHistoryStore(Protocol):
    """Read contract independent from a concrete persistence engine."""

    def get_page(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
        before: str | None = None,
        after_message_id: str | None = None,
        before_message_id: str | None = None,
        limit: int = 5,
        max_bytes: int = 2 * 1024 * 1024,
        max_content_blocks: int = 40,
    ) -> ConversationHistoryPage | None:
        """Read one stable page using an opaque continuation cursor."""

    def get_user_message_text(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
        message_id: str,
    ) -> str | None:
        """Read a complete user input by its stable message identity."""

    def get_user_message_page(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
        before: str | None = None,
        limit: int = 200,
    ) -> ConversationUserMessagePage | None:
        """Read one stable page of lightweight navigation entries."""


class ConversationHistoryError(RuntimeError):
    """A history backend failed after its request was validated."""


def _encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    try:
        return base64.b64decode(
            f"{value}{padding}",
            altchars=b"-_",
            validate=True,
        )
    except (ValueError, TypeError) as exc:
        raise ValueError("invalid history cursor") from exc


def _encode_cursor(value: TranscriptCursor | None) -> str | None:
    if value is None:
        return None
    snapshot = value.snapshot_turn_seq
    if snapshot is None:
        raise ValueError("history cursor is missing its snapshot")
    if value.snapshot_event_seq is None:
        raise ValueError("history cursor is missing its event snapshot")
    return _encode(
        _CURSOR.pack(
            snapshot,
            value.turn_seq,
            value.ordinal,
            value.content_before,
            value.text_before,
            value.snapshot_event_seq,
        ),
    )


def _decode_cursor(value: str | None) -> TranscriptCursor | None:
    if value is None:
        return None
    raw = _decode(value)
    if len(raw) != _CURSOR.size:
        raise ValueError("invalid history cursor")
    (
        snapshot,
        turn_seq,
        ordinal,
        content_before,
        text_before,
        event_seq,
    ) = _CURSOR.unpack(raw)
    # A user-message anchor points at the exclusive start of the next turn.
    # The newest visible turn therefore needs one virtual boundary immediately
    # after the snapshot watermark.
    if snapshot < 1 or turn_seq < 1 or turn_seq > snapshot + 1:
        raise ValueError("invalid history cursor")
    return TranscriptCursor(
        turn_seq=turn_seq,
        ordinal=ordinal,
        content_before=content_before,
        text_before=text_before,
        snapshot_turn_seq=snapshot,
        snapshot_event_seq=event_seq,
    )


class TranscriptHistoryStore:
    """Adapt the current transcript catalog to the public read contract."""

    def __init__(self, transcript_store) -> None:
        self._transcript_store = transcript_store

    def get_page(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
        before: str | None = None,
        after_message_id: str | None = None,
        before_message_id: str | None = None,
        limit: int = 5,
        max_bytes: int = 2 * 1024 * 1024,
        max_content_blocks: int = 40,
    ) -> ConversationHistoryPage | None:
        cursor = _decode_cursor(before)
        try:
            page = self._transcript_store.get_page(
                session_id=session_id,
                user_id=user_id,
                channel=channel,
                before=cursor,
                after_message_id=after_message_id,
                before_message_id=before_message_id,
                limit=limit,
                max_bytes=max_bytes,
                max_content_blocks=max_content_blocks,
            )
        except (OSError, sqlite3.Error, TypeError) as exc:
            raise ConversationHistoryError("history read failed") from exc
        if page is None:
            return None
        return ConversationHistoryPage(
            messages=page.messages,
            next_before=_encode_cursor(page.next_before),
            has_more=page.has_more,
            snapshot=_encode(
                _SNAPSHOT.pack(
                    page.snapshot_turn_seq,
                    page.snapshot_event_seq,
                ),
            ),
        )

    def get_user_message_text(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
        message_id: str,
    ) -> str | None:
        try:
            return self._transcript_store.get_user_message_text(
                session_id=session_id,
                user_id=user_id,
                channel=channel,
                message_id=message_id,
            )
        except (OSError, sqlite3.Error, TypeError) as exc:
            raise ConversationHistoryError("history read failed") from exc

    def get_user_message_page(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
        before: str | None = None,
        limit: int = 200,
    ) -> ConversationUserMessagePage | None:
        cursor = _decode_cursor(before)
        try:
            page = self._transcript_store.get_user_message_page(
                session_id=session_id,
                user_id=user_id,
                channel=channel,
                before=cursor,
                limit=limit,
            )
        except (OSError, sqlite3.Error, TypeError) as exc:
            raise ConversationHistoryError("history read failed") from exc
        if page is None:
            return None
        return ConversationUserMessagePage(
            items=[
                ConversationUserMessage(
                    message_id=item.message_id,
                    client_message_id=item.client_message_id,
                    preview=item.preview,
                    created_at=item.created_at,
                    anchor=_encode_cursor(item.anchor) or "",
                )
                for item in page.items
            ],
            next_before=_encode_cursor(page.next_before),
            has_more=page.has_more,
            snapshot=_encode(
                _SNAPSHOT.pack(
                    page.snapshot_turn_seq,
                    page.snapshot_event_seq,
                ),
            ),
            total=page.total,
        )


__all__ = [
    "ConversationHistoryPage",
    "ConversationUserMessage",
    "ConversationUserMessagePage",
    "ConversationHistoryError",
    "ConversationHistoryStore",
    "TranscriptHistoryStore",
]
