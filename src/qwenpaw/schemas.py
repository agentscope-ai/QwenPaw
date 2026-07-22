# -*- coding: utf-8 -*-
"""QwenPaw streaming envelope schema.

Defines the ``Message`` / ``Content`` / ``AgentRequest`` / ``AgentResponse``
types that ``stream_query`` produces and all channels consume.  These are
qwenpaw's own envelope protocol — independent of agentscope's internal
event types.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional, Union
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ---------------------------------------------------------------------------
# Enums.
# ---------------------------------------------------------------------------


class Role(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class MessageType(str, Enum):
    MESSAGE = "message"
    REASONING = "reasoning"
    PLUGIN_CALL = "plugin_call"
    PLUGIN_CALL_OUTPUT = "plugin_call_output"
    FUNCTION_CALL = "function_call"
    FUNCTION_CALL_OUTPUT = "function_call_output"
    MCP_TOOL_CALL = "mcp_tool_call"
    MCP_TOOL_CALL_OUTPUT = "mcp_tool_call_output"
    PROGRESS = "progress"
    RESULT = "result"


class RunStatus(str, Enum):
    Created = "created"
    InProgress = "in_progress"
    Completed = "completed"
    Failed = "failed"
    Cancelled = "cancelled"


class ContentType(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    DATA = "data"
    FILE = "file"
    REFUSAL = "refusal"


# ---------------------------------------------------------------------------
# Content blocks.
# Each variant carries its modality-specific fields plus the streaming
# bookkeeping (``delta`` / ``index``) the runtime emitted.
# ---------------------------------------------------------------------------


class _ContentBase(BaseModel):
    model_config = ConfigDict(extra="allow")
    type: ContentType
    delta: bool = False
    index: Optional[int] = None
    status: Optional[RunStatus] = None
    object: str = "content"
    msg_id: Optional[str] = None

    def in_progress(self) -> "_ContentBase":
        self.status = RunStatus.InProgress
        return self

    def completed(self) -> "_ContentBase":
        self.status = RunStatus.Completed
        return self


class TextContent(_ContentBase):
    type: ContentType = ContentType.TEXT
    text: str = ""


class ImageContent(_ContentBase):
    type: ContentType = ContentType.IMAGE
    image_url: Optional[str] = None


class AudioContent(_ContentBase):
    type: ContentType = ContentType.AUDIO
    data: Optional[str] = None
    format: Optional[str] = None


class VideoContent(_ContentBase):
    type: ContentType = ContentType.VIDEO
    video_url: Optional[str] = None


class FileContent(_ContentBase):
    type: ContentType = ContentType.FILE
    filename: Optional[str] = None
    file_url: Optional[str] = None


class DataContent(_ContentBase):
    type: ContentType = ContentType.DATA
    data: Any = None


class RefusalContent(_ContentBase):
    type: ContentType = ContentType.REFUSAL
    refusal: str = ""


Content = Union[
    TextContent,
    ImageContent,
    AudioContent,
    VideoContent,
    FileContent,
    DataContent,
    RefusalContent,
]


# ---------------------------------------------------------------------------
# Function / tool call payloads (embedded inside ``DataContent.data``).
# ---------------------------------------------------------------------------


class FunctionCall(BaseModel):
    model_config = ConfigDict(extra="allow")
    call_id: Optional[str] = None
    name: Optional[str] = None
    arguments: Optional[str] = None


class FunctionCallOutput(BaseModel):
    model_config = ConfigDict(extra="allow")
    call_id: Optional[str] = None
    name: Optional[str] = None
    output: Optional[str] = None


# ---------------------------------------------------------------------------
# Message envelope.
# qwenpaw's runner constructs an empty ``Message`` then calls
# ``add_content(new_content=...)`` repeatedly and ``completed()`` once the
# stream ends.  The original carried streaming bookkeeping (status,
# in-progress flag); we keep the same shape so callers that serialize the
# whole envelope still see familiar fields.
# ---------------------------------------------------------------------------


_CONTENT_TYPE_REGISTRY: Dict[str, type] = {
    ContentType.TEXT.value: TextContent,
    ContentType.IMAGE.value: ImageContent,
    ContentType.AUDIO.value: AudioContent,
    ContentType.VIDEO.value: VideoContent,
    ContentType.FILE.value: FileContent,
    ContentType.DATA.value: DataContent,
    ContentType.REFUSAL.value: RefusalContent,
}


def _coerce_content_item(item: Any) -> Any:
    """Coerce a raw dict content item to its typed ``*Content`` subclass.

    Channels access content via ``getattr(c, "type")`` / ``getattr(c,
    "text")``;
    raw JSON dicts arriving through the HTTP layer would silently fail those
    checks (e.g. ``_apply_no_text_debounce`` would buffer the message and never
    process it) because dict attribute access returns ``None``.  Coerce here so
    every downstream caller sees a pydantic model with real attributes.
    """
    if not isinstance(item, dict):
        return item
    type_value = item.get("type")
    if hasattr(type_value, "value"):
        type_value = type_value.value
    cls = _CONTENT_TYPE_REGISTRY.get(type_value)
    if cls is None:
        # Unknown type — leave the dict so the downstream layer can decide.
        return item
    try:
        return cls(**item)
    except Exception:  # pragma: no cover - keep coercion best-effort
        return item


class Message(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(default_factory=lambda: uuid4().hex)
    type: MessageType = MessageType.MESSAGE
    role: Optional[Role] = None
    content: List[Any] = Field(default_factory=list)
    status: RunStatus = RunStatus.InProgress
    metadata: Optional[Dict[str, Any]] = None

    @field_validator("content", mode="before")
    @classmethod
    def _coerce_content(cls, value: Any) -> Any:
        if not isinstance(value, list):
            return value
        return [_coerce_content_item(item) for item in value]

    def add_content(self, *, new_content: Any) -> "Message":
        """Append a content block, mirroring the 1.x runtime contract."""
        self.content.append(new_content)
        return self

    def completed(self) -> "Message":
        """Mark the message as finished and return self (chain-friendly)."""
        self.status = RunStatus.Completed
        return self

    def in_progress(self) -> "Message":
        self.status = RunStatus.InProgress
        return self


# ---------------------------------------------------------------------------
# Top-level event / request / response envelopes.
# These are constructed by qwenpaw rather than parsed from external input
# in the console mainline; the shapes below cover the constructor kwargs
# observed in src/.
# ---------------------------------------------------------------------------


class Event(BaseModel):
    model_config = ConfigDict(extra="allow")

    object: Optional[str] = None
    status: Optional[RunStatus] = None
    data: Optional[Dict[str, Any]] = None


class AgentRequest(BaseModel):
    """Incoming request envelope.

    The original surface mirrored OpenAI's chat-completion request (input
    list of ``Message``, stream flag, tools, sampling params).  We keep
    ``extra="allow"`` so unknown fields from existing callers and on-disk
    fixtures don't raise.
    """

    model_config = ConfigDict(extra="allow")

    input: List[Message] = Field(default_factory=list)
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    stream: bool = True
    metadata: Optional[Dict[str, Any]] = None


class AgentResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: Optional[str] = None
    output: List[Message] = Field(default_factory=list)
    status: RunStatus = RunStatus.Completed
    created_at: Optional[str] = None
    completed_at: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


__all__ = [
    "AgentRequest",
    "AgentResponse",
    "AudioContent",
    "Content",
    "ContentType",
    "DataContent",
    "Event",
    "FileContent",
    "FunctionCall",
    "FunctionCallOutput",
    "ImageContent",
    "Message",
    "MessageType",
    "RefusalContent",
    "Role",
    "RunStatus",
    "TextContent",
    "VideoContent",
]
