# -*- coding: utf-8 -*-
"""Strict Engine replay parsing and deterministic assistant-text snapshots."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from qwenpaw.pawapp.tasks import ExecutorEvent, ExecutorRunRef, TaskStoreError
from qwenpaw.pawapp.tasks.contracts import content_digest


def _invalid() -> TaskStoreError:
    return TaskStoreError("invalid_engine_event")


def _nonfinite(_value: str) -> None:
    raise _invalid()


async def read_frames(lines: AsyncIterator[str]) -> AsyncIterator[dict]:
    """Require complete SSE frames; malformed/truncated data cannot succeed."""
    data: list[str] = []
    event_id = None
    event_type = None
    size = 0
    async for line in lines:
        if line:
            if line.startswith(":"):
                continue
            key, _, value = line.partition(":")
            value = value.removeprefix(" ")
            size += len(line.encode("utf-8"))
            if size > 4 * 1024 * 1024:
                raise TaskStoreError("engine_event_too_large")
            if key == "data":
                data.append(value)
            elif key == "id":
                event_id = value
            elif key == "event":
                event_type = value
            continue
        if data:
            try:
                frame = json.loads(
                    "\n".join(data),
                    parse_constant=_nonfinite,
                )
            except ValueError:
                raise _invalid() from None
            if not isinstance(frame, dict):
                raise _invalid()
            sequence = frame.get("sequence_number")
            if (
                type(sequence) is not int
                or sequence < 0
                or event_id != str(sequence)
                or (
                    event_type is not None
                    and event_type != frame.get("object")
                )
            ):
                raise _invalid()
            yield frame
        data, event_id, event_type, size = [], None, None, 0
    if data:
        raise TaskStoreError("incomplete_engine_event")


@dataclass
class _Message:
    role: str
    kind: str
    sequence: int
    blocks: dict[int, str] = field(default_factory=dict)

    @property
    def included(self) -> bool:
        return self.role == "assistant" and self.kind == "message"


class TextProjection:
    """Rebuild from sequence zero on attachment, without delta duplication.

    Message snapshots replace their content blocks. Reasoning, tool payloads,
    user echoes and non-text content never become the task's text result.
    """

    def __init__(self, run_ref: ExecutorRunRef):
        self.run_ref = run_ref
        self.sequence = -1
        self._messages: dict[str, _Message] = {}
        self.terminal = False

    @property
    def text(self) -> str:
        messages = sorted(self._messages.values(), key=lambda m: m.sequence)
        return "\n\n".join(
            "".join(message.blocks[index] for index in sorted(message.blocks))
            for message in messages
            if message.included and message.blocks
        )

    def apply(self, frame: dict[str, Any]) -> ExecutorEvent:
        if (
            frame.get("session_id") != self.run_ref.session_id
            or frame.get("chat_id") != self.run_ref.run_id
            or type(frame.get("sequence_number")) is not int
            or frame["sequence_number"] != self.sequence + 1
            or self.terminal
        ):
            raise TaskStoreError("engine_replay_conflict")
        self.sequence = frame["sequence_number"]
        before = self.text
        kind = frame.get("object")
        if not isinstance(kind, str):
            raise _invalid()
        status = None
        detail = {"object": kind, "source_digest": content_digest(frame)}
        if kind == "message":
            self._message(frame)
        elif kind == "content":
            self._content(frame)
        elif kind == "response":
            if not isinstance(frame.get("status"), str):
                raise _invalid()
            status = {
                "created": "running",
                "in_progress": "running",
                "completed": "succeeded",
                "failed": "failed",
                "cancelled": "cancelled",
            }.get(frame.get("status"))
            if status is None:
                raise _invalid()
            error = frame.get("error")
            if error is not None:
                if not isinstance(error, dict):
                    raise _invalid()
                details = error.get("details") or {}
                if not isinstance(details, dict):
                    raise _invalid()
                reason = details.get("reason")
                # Do not persist provider error bodies in Host delivery events.
                detail["error_code"] = error.get("code")
                detail["reason"] = reason
                if status == "cancelled" and reason == "executor_restarted":
                    status = "interrupted"
            self.terminal = status in {
                "succeeded",
                "failed",
                "cancelled",
                "interrupted",
            }
        elif kind not in {
            "error",
            "task_status",
            "biz_event",
            "segment",
            "artifact.registered",
            "followup.generated",
        }:
            raise _invalid()
        return ExecutorEvent(
            run_ref=self.run_ref,
            sequence=self.sequence,
            cursor=str(self.sequence),
            status=status,
            # A terminal response always carries the complete available prose;
            # an empty successful result is represented explicitly as "".
            text_result=self.text
            if self.text != before or self.terminal
            else None,
            detail=detail,
        )

    def _message(self, frame: dict) -> None:
        msg_id = frame.get("id")
        sequence = frame.get("sequence")
        role, kind = frame.get("role"), frame.get("type")
        if (
            not isinstance(msg_id, str)
            or not msg_id
            or type(sequence) is not int
            or sequence < 0
        ):
            raise _invalid()
        if (
            role not in ("assistant", "user", "system", "tool")
            or not isinstance(kind, str)
            or not isinstance(frame.get("content"), list)
        ):
            raise _invalid()
        previous = self._messages.get(msg_id)
        if previous is not None and (
            previous.role,
            previous.kind,
            previous.sequence,
        ) != (role, kind, sequence):
            raise TaskStoreError("engine_message_conflict")
        message = _Message(role, kind, sequence)
        self._messages[msg_id] = message
        if message.included:
            for index, block in enumerate(frame["content"]):
                if not isinstance(block, dict):
                    raise _invalid()
                if block.get("type") == "text":
                    text = block.get("text")
                    if not isinstance(text, str):
                        raise _invalid()
                    block_index = block.get("index", index)
                    if block_index is None:
                        block_index = index
                    if type(block_index) is not int or block_index < 0:
                        raise _invalid()
                    message.blocks[block_index] = text

    def _content(self, frame: dict) -> None:
        msg_id = frame.get("msg_id")
        if not isinstance(msg_id, str) or msg_id not in self._messages:
            raise _invalid()
        message = self._messages[msg_id]
        if not message.included or frame.get("type") != "text":
            return
        index, text = frame.get("index"), frame.get("text")
        delta = frame.get("delta", False)
        if (
            type(index) is not int
            or index < 0
            or not isinstance(text, str)
            or type(delta) is not bool
        ):
            raise _invalid()
        message.blocks[index] = (
            message.blocks.get(index, "") + text if delta else text
        )
