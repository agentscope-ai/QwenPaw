# -*- coding: utf-8 -*-
"""Model-provider contracts independent of AgentScope and host internals."""

from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Awaitable, AsyncIterator

from .messages import ContentBlock, Message
from .tools import ToolContext


@dataclass(frozen=True)
class ModelInfo:
    id: str
    name: str
    max_input_length: int = 32768
    max_output_length: int | None = None
    supports_image: bool = False
    supports_video: bool = False
    is_free: bool = False


@dataclass(frozen=True)
class ModelUsage:
    input_tokens: int
    output_tokens: int
    time: float = 0
    cache_creation_input_tokens: int = 0
    cache_input_tokens: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelToolChoice:
    mode: str
    tools: tuple[str, ...] | None = None


@dataclass(frozen=True)
class ModelRequest:
    model_id: str
    messages: tuple[Message, ...]
    tools: tuple[dict[str, Any], ...] = ()
    tool_choice: ModelToolChoice | None = None
    options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelChunk:
    """Incremental content, including content on the final chunk.

    The adapter emits the complete accumulated response required by the host.
    A final chunk may have empty content and carry only usage/finish metadata.
    """

    content: tuple[ContentBlock, ...]
    is_last: bool = False
    usage: ModelUsage | None = None
    finished_reason: Literal["completed", "interrupted"] = "completed"
    id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderContext(ToolContext):
    provider_id: str = ""
    base_url: str = ""
    headers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ConnectionResult:
    success: bool
    message: str = ""


@dataclass(frozen=True)
class ProviderSpec:
    id: str
    label: str
    generate: Callable[
        [ProviderContext, ModelRequest],
        ModelChunk | Awaitable[ModelChunk] | AsyncIterator[ModelChunk],
    ]
    models: tuple[ModelInfo, ...] = ()
    discover: (
        Callable[
            [ProviderContext, float],
            tuple[ModelInfo, ...] | Awaitable[tuple[ModelInfo, ...]],
        ]
        | None
    ) = None
    check_connection: (
        Callable[
            [ProviderContext, float],
            ConnectionResult | Awaitable[ConnectionResult],
        ]
        | None
    ) = None
    base_url: str = ""
    require_api_key: bool = True
