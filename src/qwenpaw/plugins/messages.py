# -*- coding: utf-8 -*-
"""Public, host-independent message and attachment values."""

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(frozen=True)
class Attachment:
    url: str
    mime_type: str = "application/octet-stream"
    name: str = ""
    preview_url: str = ""


@dataclass(frozen=True)
class ContentBlock:
    type: Literal[
        "text",
        "image",
        "audio",
        "video",
        "file",
        "thinking",
        "hint",
        "tool_call",
        "tool_result",
    ] = "text"
    text: str = ""
    attachment: Attachment | None = None
    id: str = ""
    name: str = ""
    arguments: str = ""
    output: str | tuple["ContentBlock", ...] = ()
    state: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Message:
    role: Literal["user", "assistant", "system"]
    content: tuple[ContentBlock, ...] = ()
    name: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    attributes: dict[str, Any] = field(default_factory=dict)
