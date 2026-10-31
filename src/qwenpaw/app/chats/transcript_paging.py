# -*- coding: utf-8 -*-
"""Bounded wire projections from canonical conversation messages."""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Iterator

from ...runtime.console_turn_state import TURN_STATE
from ...schemas import Message, RunStatus, TextContent
from .transcript_models import TranscriptCursor, PageSelection

_PAGE_ENVELOPE_RESERVE_BYTES = 1024


class TranscriptPageBudgetError(ValueError):
    """The page byte budget cannot hold one message fragment."""


def _enum_value(value: Any) -> str:
    return str(getattr(value, "value", value) or "")


class TranscriptPageBuilder:
    """Apply byte and block budgets without changing stored content."""

    def select(
        self,
        rows: Iterator[sqlite3.Row],
        *,
        connection: sqlite3.Connection,
        before: TranscriptCursor | None,
        snapshot_turn_seq: int,
        max_bytes: int,
        max_content_blocks: int,
        has_more: bool,
    ) -> PageSelection:
        """Select newest messages within the page's two resource bounds."""
        selected: list[Message] = []
        payload_bytes = 0
        content_blocks = 0
        page_budget = max(1, max_bytes - _PAGE_ENVELOPE_RESERVE_BYTES)
        oldest_position: TranscriptCursor | None = None
        for row in rows:
            remaining_blocks = max_content_blocks - content_blocks
            separator_bytes = 1 if selected else 0
            remaining_bytes = page_budget - payload_bytes - separator_bytes
            if remaining_blocks <= 0 or remaining_bytes <= 0:
                has_more = True
                break
            total = int(row["content_total"])
            continuing = (
                before is not None
                and before.turn_seq == row["turn_seq"]
                and before.ordinal == row["ordinal"]
                and before.content_before > 0
            )
            end = min(total, before.content_before) if continuing else total
            if selected and end > remaining_blocks:
                has_more = True
                break
            start, content = self._read_blocks(
                connection,
                row,
                end,
                remaining_blocks,
                remaining_bytes,
            )
            full_message = self._message_from_row(row, content)
            partial = start > 0 or end < total
            if partial:
                metadata = dict(full_message.metadata or {})
                metadata["qwenpaw_history_fragment"] = {
                    "content_start": start,
                    "content_end": end,
                    "content_total": total,
                }
                full_message = full_message.model_copy(
                    update={"metadata": metadata},
                )
            content_end = len(content)
            local_before = (
                TranscriptCursor(
                    turn_seq=before.turn_seq,
                    ordinal=before.ordinal,
                    content_before=content_end,
                    text_before=before.text_before,
                )
                if continuing
                else None
            )
            full_message_bytes = len(
                full_message.model_dump_json().encode("utf-8"),
            )
            if selected and (
                full_message_bytes > remaining_bytes
                or len(full_message.content) > remaining_blocks
            ):
                has_more = True
                break
            message, content_start, text_start = self._content_fragment(
                full_message,
                content_end=content_end,
                text_end=self._atomic_end(full_message, row, local_before),
                max_bytes=remaining_bytes,
                max_content_blocks=remaining_blocks,
            )
            content_start += start
            message_bytes = len(message.model_dump_json().encode("utf-8"))
            if selected and message_bytes > remaining_bytes:
                has_more = True
                break
            selected.append(message)
            payload_bytes += separator_bytes + message_bytes
            content_blocks += max(1, len(message.content))
            oldest_position = TranscriptCursor(
                turn_seq=int(row["turn_seq"]),
                ordinal=int(row["ordinal"]),
                content_before=content_start,
                text_before=text_start,
                snapshot_turn_seq=snapshot_turn_seq,
            )
            if content_start > 0 or text_start > 0:
                has_more = True
                break
        return PageSelection(selected, oldest_position, has_more)

    @staticmethod
    def _read_blocks(connection, row, end, limit, max_bytes):
        """Read descriptors first, then only the suffix bodies needed."""
        descriptors = connection.execute(
            "SELECT ordinal, byte_length FROM transcript_blocks "
            "WHERE session_id = ? AND message_id = ? AND ordinal < ? "
            "ORDER BY ordinal DESC LIMIT ?",
            (row["session_id"], row["message_id"], end, limit),
        )
        start = end
        size = 0
        for block in descriptors:
            if start < end and size + block["byte_length"] > max_bytes:
                break
            start = int(block["ordinal"])
            size += int(block["byte_length"])
        bodies = connection.execute(
            "SELECT payload_json FROM transcript_blocks "
            "WHERE session_id = ? AND message_id = ? "
            "AND ordinal >= ? AND ordinal < ? ORDER BY ordinal",
            (row["session_id"], row["message_id"], start, end),
        )
        return start, [json.loads(block[0]) for block in bodies]

    @staticmethod
    def _atomic_end(
        message: Message,
        row: sqlite3.Row,
        before: TranscriptCursor | None,
    ) -> int:
        """Return the boundary inside a continued atomic content block."""
        if before is None:
            return 0
        if (
            before.text_before <= 0
            or int(row["turn_seq"]) != before.turn_seq
            or int(row["ordinal"]) != before.ordinal
        ):
            return 0
        if before.content_before <= 0 or before.content_before > len(
            message.content,
        ):
            return 0
        content = message.content[before.content_before - 1]
        serialized = (
            content.text
            if isinstance(content, TextContent)
            else content.model_dump_json()
        )
        return min(len(serialized), before.text_before)

    @staticmethod
    def _with_content_fragment(
        message: Message,
        *,
        content_start: int,
        content_end: int,
    ) -> Message:
        """Project a complete content-block range from one message."""
        metadata = dict(message.metadata or {})
        source = metadata.get("qwenpaw_history_fragment") or {}
        origin = source.get("content_start", 0)
        metadata["qwenpaw_history_fragment"] = {
            "content_start": origin + content_start,
            "content_end": origin + content_end,
            "content_total": source.get("content_total", len(message.content)),
        }
        return message.model_copy(
            update={
                "content": message.content[content_start:content_end],
                "metadata": metadata,
            },
            deep=True,
        )

    @classmethod
    def _with_text_fragment(
        cls,
        message: Message,
        *,
        content_index: int,
        text_start: int,
        text_end: int,
    ) -> Message:
        """Project one complete UTF-8-safe text slice from a content block."""
        content = message.content[content_index]
        if not isinstance(content, TextContent):
            raise TypeError("text fragment requires TextContent")
        fragment = cls._with_content_fragment(
            message,
            content_start=content_index,
            content_end=content_index + 1,
        )
        metadata = dict(fragment.metadata or {})
        position = dict(metadata["qwenpaw_history_fragment"])
        position.update(
            {
                "text_content_index": position["content_start"],
                "text_start": text_start,
                "text_end": text_end,
                "text_total": len(content.text),
            },
        )
        return fragment.model_copy(
            update={
                "content": [
                    content.model_copy(
                        update={"text": content.text[text_start:text_end]},
                        deep=True,
                    ),
                ],
                "metadata": metadata | {"qwenpaw_history_fragment": position},
            },
            deep=True,
        )

    @classmethod
    def _text_fragment(
        cls,
        message: Message,
        *,
        content_index: int,
        text_end: int,
        max_bytes: int,
    ) -> tuple[Message, int]:
        """Return the largest text suffix that fits the page byte budget."""
        best: Message | None = None
        best_start = text_end
        low = 0
        high = text_end - 1
        while low <= high:
            text_start = (low + high) // 2
            candidate = cls._with_text_fragment(
                message,
                content_index=content_index,
                text_start=text_start,
                text_end=text_end,
            )
            if len(candidate.model_dump_json().encode("utf-8")) > max_bytes:
                low = text_start + 1
                continue
            best = candidate
            best_start = text_start
            high = text_start - 1
        if best is None:
            raise TranscriptPageBudgetError(
                "transcript page byte limit is too small",
            )
        return best, best_start

    @classmethod
    def _with_serialized_fragment(
        cls,
        message: Message,
        *,
        content_index: int,
        serialized: str,
        fragment_start: int,
        fragment_end: int,
    ) -> Message:
        """Project an opaque slice of one non-text content block."""
        fragment = cls._with_content_fragment(
            message,
            content_start=content_index,
            content_end=content_index + 1,
        )
        metadata = dict(fragment.metadata or {})
        position = dict(metadata["qwenpaw_history_fragment"])
        position.update(
            {
                "serialized_start": fragment_start,
                "serialized_end": fragment_end,
                "serialized_total": len(serialized),
                "serialized_fragment": serialized[fragment_start:fragment_end],
            },
        )
        return fragment.model_copy(
            update={
                "content": [],
                "metadata": metadata | {"qwenpaw_history_fragment": position},
            },
            deep=True,
        )

    @classmethod
    def _serialized_fragment(
        cls,
        message: Message,
        *,
        content_index: int,
        fragment_end: int,
        max_bytes: int,
    ) -> tuple[Message, int]:
        """Return the largest opaque block suffix within the byte budget."""
        serialized = message.content[content_index].model_dump_json()
        best: Message | None = None
        best_start = fragment_end
        low = 0
        high = fragment_end - 1
        while low <= high:
            fragment_start = (low + high) // 2
            candidate = cls._with_serialized_fragment(
                message,
                content_index=content_index,
                serialized=serialized,
                fragment_start=fragment_start,
                fragment_end=fragment_end,
            )
            if len(candidate.model_dump_json().encode("utf-8")) > max_bytes:
                low = fragment_start + 1
                continue
            best = candidate
            best_start = fragment_start
            high = fragment_start - 1
        if best is None:
            raise TranscriptPageBudgetError(
                "transcript page byte limit is too small",
            )
        return best, best_start

    @classmethod
    def _atomic_fragment(
        cls,
        message: Message,
        *,
        content_index: int,
        fragment_end: int,
        max_bytes: int,
    ) -> tuple[Message, int]:
        """Split text directly and other content through opaque JSON."""
        content = message.content[content_index]
        if isinstance(content, TextContent):
            return cls._text_fragment(
                message,
                content_index=content_index,
                text_end=fragment_end,
                max_bytes=max_bytes,
            )
        return cls._serialized_fragment(
            message,
            content_index=content_index,
            fragment_end=fragment_end,
            max_bytes=max_bytes,
        )

    @classmethod
    def _content_fragment(
        cls,
        message: Message,
        *,
        content_end: int,
        text_end: int,
        max_bytes: int,
        max_content_blocks: int,
    ) -> tuple[Message, int, int]:
        """Return the largest complete suffix within both page bounds."""
        if content_end <= 0 or not message.content:
            return message, 0, 0

        if text_end > 0:
            content_index = content_end - 1
            fragment, text_start = cls._atomic_fragment(
                message,
                content_index=content_index,
                fragment_end=text_end,
                max_bytes=max_bytes,
            )
            content_before = (
                content_index + 1 if text_start > 0 else content_index
            )
            return fragment, content_before, text_start

        minimum_start = max(0, content_end - max_content_blocks)
        if minimum_start == 0 and content_end == len(message.content):
            message_bytes = len(message.model_dump_json().encode("utf-8"))
            if message_bytes <= max_bytes:
                return message, 0, 0
        best_start = content_end - 1
        fragment = cls._with_content_fragment(
            message,
            content_start=best_start,
            content_end=content_end,
        )
        low = minimum_start
        high = content_end - 1
        while low <= high:
            content_start = (low + high) // 2
            candidate = cls._with_content_fragment(
                message,
                content_start=content_start,
                content_end=content_end,
            )
            if len(candidate.model_dump_json().encode("utf-8")) > max_bytes:
                low = content_start + 1
                continue
            best_start = content_start
            fragment = candidate
            high = content_start - 1
        fragment_bytes = len(fragment.model_dump_json().encode("utf-8"))
        content = message.content[content_end - 1]
        if fragment_bytes > max_bytes:
            serialized = (
                content.text
                if isinstance(content, TextContent)
                else content.model_dump_json()
            )
            text_fragment, text_start = cls._atomic_fragment(
                message,
                content_index=content_end - 1,
                fragment_end=len(serialized),
                max_bytes=max_bytes,
            )
            content_before = content_end if text_start > 0 else content_end - 1
            return text_fragment, content_before, text_start
        return fragment, best_start, 0

    @staticmethod
    def _message_from_row(
        row: sqlite3.Row,
        content: list[dict],
    ) -> Message:
        """Project normalized transcript columns into the wire contract."""
        message = Message.model_validate(
            json.loads(row["envelope_json"]) | {"content": content},
        )
        metadata = dict(message.metadata or {})
        metadata.setdefault("timestamp", row["message_created_at"])
        metadata["qwenpaw_transcript_position"] = {
            "turn_id": str(row["turn_id"]),
            "turn_seq": int(row["turn_seq"]),
            "ordinal": int(row["ordinal"]),
        }

        turn_status = str(row["turn_status"])
        terminal = turn_status != "running"
        if terminal and _enum_value(message.role) != "user":
            finished_at = row["message_finished_at"] or row["turn_finished_at"]
            if finished_at is not None:
                metadata.setdefault("finished_at", finished_at)

        if terminal and _enum_value(message.role) == "user":
            state_metadata = metadata
            nested_metadata = metadata.get("metadata")
            if isinstance(nested_metadata, dict):
                state_metadata = dict(nested_metadata)
                metadata["metadata"] = state_metadata
            state = {"status": turn_status}
            if (
                turn_status in {"failed", "cancelled"}
                and row["turn_finished_at"] is not None
            ):
                state["finished_at"] = row["turn_finished_at"]
            if turn_status == "cancelled":
                state["status"] = "canceled"
            if turn_status == "failed" and row["error_json"]:
                state["error"] = json.loads(row["error_json"])
            state_metadata.setdefault(TURN_STATE, state)

        updates: dict[str, Any] = {"metadata": metadata}
        if terminal:
            updates["status"] = RunStatus.Completed
        return message.model_copy(update=updates)
