# -*- coding: utf-8 -*-
"""Model-provider contracts independent of AgentScope and host internals."""

from dataclasses import dataclass, field
from contextlib import AbstractAsyncContextManager
from typing import Any, Callable, Literal, Awaitable, AsyncIterator

from .messages import ContentBlock, Message
from .tools import ToolContext
from .resources import Registration


# TODO: Define shared model facts for cloud Provider plugins: model type,
# limits, thinking/tool capabilities and pricing. Keep user settings and
# derived availability, billing policy and ranking in the host.
@dataclass(frozen=True)
class ModelInfo:
    id: str
    name: str
    max_input_length: int | None = 32768
    max_output_length: int | None = None
    supports_image: bool | None = False
    supports_video: bool | None = False
    is_free: bool | None = False
    supports_multimodal: bool | None = None
    probe_source: str | None = None


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
    """Provider identity, configuration, model catalog and inference hooks.

    Declare generate or a native protocol. Native providers may acquire
    a per-use base URL through connect. Discovery and connection
    checks may override host defaults. Installation and service management
    remain plugin responsibilities.
    """

    id: str
    label: str
    generate: (
        Callable[
            [ProviderContext, ModelRequest],
            ModelChunk | Awaitable[ModelChunk] | AsyncIterator[ModelChunk],
        ]
        | None
    ) = None
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
    protocol: Literal["openai-chat"] | None = None
    connect: (
        Callable[[ProviderContext, str], AbstractAsyncContextManager[str]]
        | None
    ) = None
    is_local: bool = False


class ProviderHandle(Registration):
    """Manage only the provider registered by this handle."""

    _provider: Any

    async def select(self, model_id: str) -> None:
        """Select this provider's model as the default chat model."""
        await self._provider.select(model_id)

    async def clear_selection(self) -> bool:
        """Clear the default chat selection if it uses this provider."""
        return await self._provider.clear_selection()

    async def update(
        self,
        *,
        base_url: str | None = None,
        models: tuple[ModelInfo, ...] | None = None,
        generate_kwargs: dict[str, Any] | None = None,
    ) -> None:
        """Persist supplied fields; None leaves a field unchanged.

        models replaces the dynamic model list and retains saved per-model
        settings. Spec.models stays unchanged. None-valued metadata retains
        stored values.
        """
        await self._provider.update(
            base_url=base_url,
            models=models,
            generate_kwargs=generate_kwargs,
        )
