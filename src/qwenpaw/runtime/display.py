# -*- coding: utf-8 -*-
"""Project runtime events for display without changing the raw stream."""

from typing import Any

from ..agents.context.scroll.scaffold_filter import strip_scaffold_blocks
from ..agents.context.scroll.serialize import strip_headline
from ..schemas import (
    AgentResponse,
    Message,
    MessageType,
    Role,
    RunStatus,
    TextContent,
)

TERMINAL_STREAM_STATUSES = {
    RunStatus.Completed,
    RunStatus.Failed,
    RunStatus.Cancelled,
}


def filter_display_blocks(blocks: list[str]) -> list[str]:
    """Filter an assistant message across its text blocks."""
    return [
        strip_headline(text) or "" for text in strip_scaffold_blocks(blocks)
    ]


def project_session_message(message: dict[str, Any]) -> dict[str, Any]:
    """Hide scaffolding in a persisted assistant message's display copy."""
    if message.get("role") != Role.ASSISTANT or message.get("type") not in (
        None,
        MessageType.MESSAGE,
    ):
        return message

    content = message.get("content")
    if isinstance(content, str):
        return {**message, "content": filter_display_blocks([content])[0]}
    if not isinstance(content, list):
        return message

    texts = {
        i: block["text"]
        for i, block in enumerate(content)
        if isinstance(block, dict)
        and block.get("type") == "text"
        and isinstance(block.get("text"), str)
    }
    if not texts:
        return message
    filtered = list(content)
    for i, text in zip(texts, filter_display_blocks(list(texts.values()))):
        filtered[i] = {**content[i], "text": text}
    return {**message, "content": filtered}


def _is_assistant_text(message: Message) -> bool:
    return (
        message.role == Role.ASSISTANT and message.type == MessageType.MESSAGE
    )


def _display_message(message: Message) -> Message:
    if not _is_assistant_text(message):
        return message
    content = list(message.content)
    blocks = {
        i: block
        for i, block in enumerate(content)
        if isinstance(block, TextContent)
    }
    if message.status in TERMINAL_STREAM_STATUSES:
        texts = filter_display_blocks(
            [block.text for block in blocks.values()],
        )
    else:
        texts = [""] * len(blocks)
    for (i, block), text in zip(blocks.items(), texts):
        if text != block.text:
            content[i] = block.model_copy(update={"text": text})
    return message.model_copy(update={"content": content})


class AssistantDisplayStream:
    """Defer assistant text until the authoritative message snapshot."""

    def __init__(self) -> None:
        self._messages: dict[str, bool] = {}

    def project(self, event: Any) -> list[Any]:
        """Return safe events in wire order, retaining non-reply payloads."""
        if isinstance(event, AgentResponse):
            if event.status in TERMINAL_STREAM_STATUSES:
                self._messages.clear()
            output = [_display_message(message) for message in event.output]
            return [event.model_copy(update={"output": output})]

        if isinstance(event, TextContent):
            role = getattr(event, "role", None)
            assistant = self._messages.get(
                event.msg_id or "",
                role in (None, Role.ASSISTANT),
            )
            if assistant:
                return [event.model_copy(update={"text": ""})]
            return [event]

        if not isinstance(event, Message):
            return [event]

        message = _display_message(event)
        if event.status not in TERMINAL_STREAM_STATUSES:
            self._messages[event.id] = _is_assistant_text(event)
            return [message]

        frames: list[Any] = []
        if self._messages.pop(event.id, False) and _is_assistant_text(event):
            for position, block in enumerate(message.content):
                if isinstance(block, TextContent) and block.text:
                    index = block.index
                    frames.append(
                        TextContent(
                            msg_id=message.id,
                            index=position if index is None else index,
                            delta=True,
                            text=block.text,
                        ),
                    )
        frames.append(message)
        return frames
