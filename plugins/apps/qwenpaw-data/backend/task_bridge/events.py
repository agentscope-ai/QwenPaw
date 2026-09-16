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
        self._waiting_request: str | None = None

    @property
    def text(self) -> str:
        messages = sorted(self._messages.values(), key=lambda m: m.sequence)
        return "\n\n".join(
            "".join(message.blocks[index] for index in sorted(message.blocks))
            for message in messages
            if message.included and message.blocks
        )

    def apply(  # pylint: disable=too-many-branches
        self,
        frame: dict[str, Any],
    ) -> ExecutorEvent:
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
            request = _input_request(frame)
            if request is not None:
                self._waiting_request = request["request_id"]
                status = "waiting_for_input"
                detail["input_request"] = request
            elif (
                frame.get("type") == "plugin_call_output"
                and frame.get("source_id") == self._waiting_request
            ):
                self._waiting_request = None
                status = "running"
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
            text_result=(
                _render_input_request(detail["input_request"])
                if status == "waiting_for_input"
                else self.text
                if self.text != before or self.terminal
                else None
            ),
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


# pylint: disable-next=too-many-return-statements,too-many-branches
def _input_request(
    frame: dict[str, Any],
) -> dict[str, Any] | None:
    if (
        frame.get("type") != "plugin_call"
        or frame.get("status") != "completed"
    ):
        return None
    blocks = frame.get("content")
    if not isinstance(blocks, list):
        return None
    data = next(
        (
            block.get("data")
            for block in blocks
            if isinstance(block, dict) and block.get("type") == "data"
        ),
        None,
    )
    if not isinstance(data, dict) or data.get("name") != "ask_user_question":
        return None
    request_id, arguments = data.get("call_id"), data.get("arguments")
    if (
        not isinstance(request_id, str)
        or not request_id
        or frame.get("source_id") != request_id
    ):
        raise _invalid()
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except ValueError:
            raise _invalid() from None
    if not isinstance(arguments, dict):
        raise _invalid()
    raw_questions = arguments.get("questions")
    if not isinstance(raw_questions, list) or not raw_questions:
        raise _invalid()
    questions = []
    for raw in raw_questions:
        if not isinstance(raw, dict):
            raise _invalid()
        question, options = raw.get("question"), raw.get("options")
        multi_select = raw.get("multiSelect", False)
        description = raw.get("description") or ""
        if (
            not isinstance(question, str)
            or not question
            or not isinstance(options, list)
            or not isinstance(multi_select, bool)
            or not isinstance(description, str)
        ):
            raise _invalid()
        normalized = []
        for option in options:
            if not isinstance(option, dict):
                raise _invalid()
            label = option.get("label")
            option_description = option.get("description") or ""
            if (
                not isinstance(label, str)
                or not label
                or not isinstance(option_description, str)
            ):
                raise _invalid()
            normalized.append(
                {
                    "label": label,
                    "description": option_description,
                },
            )
        questions.append(
            {
                "question": question,
                "description": description,
                "multi_select": multi_select,
                "options": normalized,
            },
        )
    title = arguments.get("title") or ""
    if not isinstance(title, str):
        raise _invalid()
    return {
        "request_id": request_id,
        "title": title,
        "questions": questions,
    }


def _render_input_request(request: dict[str, Any]) -> str:
    lines = [request["title"]] if request.get("title") else []
    multiple = len(request["questions"]) > 1
    for index, question in enumerate(request["questions"], start=1):
        prefix = f"{index}. " if multiple else ""
        lines.append(prefix + question["question"])
        for option_index, option in enumerate(question["options"], start=1):
            lines.append(f"{option_index}) {option['label']}")
    return "\n".join(lines)
