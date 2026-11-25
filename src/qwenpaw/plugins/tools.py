# -*- coding: utf-8 -*-
"""Tool declarations, per-call context and streaming result protocol."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import (
    Any,
    Callable,
    Literal,
    TypedDict,
    Awaitable,
    AsyncIterator,
    TYPE_CHECKING,
)

from .messages import ContentBlock
from .resources import ResourceScope
from .storage import PluginConfig, PluginStorage, MediaStore
from .context import RequestContext

if TYPE_CHECKING:
    from .logging import PluginLogger
    from .models import ModelService
    from .workspace import WorkspaceService
    from .checkpoints import CheckpointService
    from .sdk import PluginContext


@dataclass(frozen=True)
class ToolResult:
    content: tuple[ContentBlock, ...] = ()
    is_error: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def text(cls, text: str, *, is_error: bool = False) -> ToolResult:
        return cls((ContentBlock(text=text),), is_error=is_error)


@dataclass(frozen=True)
class ToolEvent:
    kind: Literal["delta", "result", "end"]
    content: tuple[ContentBlock, ...] = ()
    result: ToolResult | None = None


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[
        [ToolContext, dict[str, Any]],
        ToolResult | Awaitable[ToolResult] | AsyncIterator[ToolEvent],
    ]
    enabled: bool = False
    tool_type: str = "network"
    target_param: str = ""
    icon: str = "🔧"
    config_fields: tuple[ConfigField, ...] = ()
    timeout: float | None = None


@dataclass(frozen=True)
class ToolContext:
    plugin_id: str
    generation: int
    workspace_id: str
    session_id: str
    config: PluginConfig
    storage: PluginStorage
    media: MediaStore
    resources: ResourceScope
    deadline: float | None = None
    identity: RequestContext = field(
        default_factory=RequestContext,
        kw_only=True,
    )
    _is_cancelled: Callable[[], bool] = field(
        default=lambda: False,
        repr=False,
        compare=False,
    )

    _plugin: PluginContext | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    @property
    def logger(self) -> PluginLogger:
        from .logging import PluginLogger

        return PluginLogger(self)

    @property
    def checkpoints(self) -> CheckpointService:
        from .checkpoints import CheckpointService

        return CheckpointService(self)

    @property
    def models(self) -> ModelService:
        from .models import ModelService

        return ModelService(self)

    @property
    def workspace_ops(self) -> WorkspaceService:
        from .workspace import WorkspaceService

        return WorkspaceService(self)

    async def select_shell_backend(self, name: str | None) -> None:
        """Select an owned backend for this chat, or explicitly return to local."""
        from ._shell import select_backend

        await select_backend(self, name)

    @property
    def cancelled(self) -> bool:
        return self._is_cancelled()

    def check_cancelled(self) -> None:
        if self.cancelled:
            raise asyncio.CancelledError


class ConfigField(TypedDict, total=False):
    """Tool settings rendered by the existing configuration UI."""

    name: str
    label: str
    type: Literal["text", "password", "number", "select", "boolean"]
    required: bool
    default: Any
    options: list[str]
    help: str
    placeholder: str
    min: float
    max: float
