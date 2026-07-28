# -*- coding: utf-8 -*-
"""Translate normalized third-party events into QwenPaw stream objects."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

from ..schemas import (
    AgentResponse,
    ContentType,
    DataContent,
    FunctionCall,
    FunctionCallOutput,
    Message,
    MessageType,
    Role,
    RunStatus,
    TextContent,
)
from .events import HarnessEvent


def _new_message(message_type: MessageType, role: Role) -> Message:
    message = Message(
        id=f"msg_{uuid.uuid4().hex}",
        type=message_type,
        role=role,
        status=RunStatus.InProgress,
    )
    message.object = "message"
    message.name = "assistant"
    return message


class TextStream:
    """Preserve ordered assistant text and reasoning segments."""

    def __init__(self, response: AgentResponse) -> None:
        self._response = response
        self._kind: MessageType | None = None
        self._message: Message | None = None
        self._text = ""

    def push(self, kind: MessageType, text: str) -> list[Any]:
        emitted: list[Any] = []
        if self._kind is not None and self._kind != kind:
            emitted.extend(self.finish())
        if self._message is None:
            self._kind = kind
            self._message = _new_message(kind, Role.ASSISTANT)
            emitted.append(self._message.model_copy(deep=True))
        self._text += text
        emitted.append(
            TextContent(
                type=ContentType.TEXT,
                text=text,
                delta=True,
                index=0,
                msg_id=self._message.id,
            ),
        )
        return emitted

    def finish(self) -> list[Any]:
        if self._message is None:
            return []
        self._message.content = [
            TextContent(
                type=ContentType.TEXT,
                text=self._text,
                index=0,
            ),
        ]
        self._message.status = RunStatus.Completed
        self._response.output.append(self._message)
        emitted = [self._message.model_copy(deep=True)]
        self._kind = None
        self._message = None
        self._text = ""
        return emitted


@dataclass
class _ToolState:
    """Streaming state for one normalized tool call."""

    name: str
    output_message: Message
    output_text: str = ""


class ToolStream:
    """Emit native plugin call and output envelopes for third-party tools."""

    def __init__(self, response: AgentResponse) -> None:
        self._response = response
        self._states: dict[str, _ToolState] = {}

    def start(self, event: HarnessEvent) -> list[Any]:
        if not event.item_id or event.item_id in self._states:
            return []
        arguments = json.dumps(
            event.data.get("arguments") or {},
            ensure_ascii=False,
            default=str,
        )
        call_message = _new_message(
            MessageType.PLUGIN_CALL,
            Role.ASSISTANT,
        )
        call_content = DataContent(
            type=ContentType.DATA,
            data=FunctionCall(
                call_id=event.item_id,
                name=event.tool_name,
                arguments=arguments,
            ).model_dump(),
            delta=False,
            index=0,
            msg_id=call_message.id,
            status=RunStatus.Completed,
        )
        emitted: list[Any] = [call_message.model_copy(deep=True), call_content]
        call_message.content = [call_content]
        call_message.status = RunStatus.Completed
        self._response.output.append(call_message)
        emitted.append(call_message.model_copy(deep=True))

        output_message = _new_message(
            MessageType.PLUGIN_CALL_OUTPUT,
            Role.TOOL,
        )
        output_stub = self._output_content(
            event,
            output_message.id,
            "",
            RunStatus.InProgress,
        )
        emitted.extend(
            [output_message.model_copy(deep=True), output_stub],
        )
        self._states[event.item_id] = _ToolState(
            name=event.tool_name,
            output_message=output_message,
        )
        return emitted

    def progress(self, event: HarnessEvent) -> list[Any]:
        state = self._states.get(event.item_id)
        if state is None or not event.text:
            return []
        state.output_text += event.text
        return [
            self._output_content(
                event,
                state.output_message.id,
                state.output_text,
                RunStatus.InProgress,
                name=state.name,
            ),
        ]

    def complete(self, event: HarnessEvent) -> list[Any]:
        emitted = self.start(event)
        state = self._states.pop(event.item_id, None)
        if state is None:
            return emitted
        output = event.text or state.output_text
        final_content = self._output_content(
            event,
            state.output_message.id,
            output,
            RunStatus.Completed,
            name=state.name,
        )
        state.output_message.content = [final_content]
        state.output_message.status = RunStatus.Completed
        self._response.output.append(state.output_message)
        emitted.extend(
            [final_content, state.output_message.model_copy(deep=True)],
        )
        return emitted

    @staticmethod
    def _output_content(
        event: HarnessEvent,
        message_id: str,
        output: str,
        status: RunStatus,
        *,
        name: str | None = None,
    ) -> DataContent:
        payload = FunctionCallOutput(
            call_id=event.item_id,
            name=name or event.tool_name,
            output=output,
        ).model_dump()
        payload.update(
            {
                key: value
                for key, value in event.data.items()
                if key not in {"arguments"} and value is not None
            },
        )
        return DataContent(
            type=ContentType.DATA,
            data=payload,
            delta=False,
            index=0,
            msg_id=message_id,
            status=status,
        )


__all__ = ["TextStream", "ToolStream"]
