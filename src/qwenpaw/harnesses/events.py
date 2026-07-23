# -*- coding: utf-8 -*-
"""Provider-neutral third-party agent models."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class HarnessEventKind(str, Enum):
    """Events emitted by every third-party agent adapter."""

    TEXT_DELTA = "text_delta"
    REASONING_DELTA = "reasoning_delta"
    TOOL_STARTED = "tool_started"
    TOOL_PROGRESS = "tool_progress"
    TOOL_COMPLETED = "tool_completed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ERROR = "error"


class HarnessHistoryKind(str, Enum):
    """Kinds stored when a provider can replay an existing thread."""

    USER = "user"
    MESSAGE = "message"
    REASONING = "reasoning"
    TOOL_CALL = "tool_call"
    TOOL_OUTPUT = "tool_output"


class HarnessEvent(BaseModel):
    """One normalized provider event."""

    kind: HarnessEventKind
    text: str = ""
    item_id: str = ""
    tool_name: str = ""
    data: dict[str, Any] = Field(default_factory=dict)


class HarnessHistoryItem(BaseModel):
    """One provider-neutral item reconstructed from thread history."""

    kind: HarnessHistoryKind
    text: str = ""
    item_id: str = ""
    tool_name: str = ""
    data: dict[str, Any] = Field(default_factory=dict)


class HarnessCommand(BaseModel):
    """One slash command exposed by a third-party agent backend."""

    name: str
    description: str = ""
    accepts_arguments: bool = False


class HarnessApprovalPreset(BaseModel):
    """One provider-owned execution approval preset."""

    id: str
    name: str
    description: str = ""
    settings: dict[str, Any] = Field(default_factory=dict)


class HarnessCapabilities(BaseModel):
    """Features exposed by one third-party agent backend."""

    authentication: bool = False
    model_selection: bool = False
    reasoning_effort: bool = False
    reasoning_stream: bool = False
    tool_stream: bool = False
    session_resume: bool = False
    workspace_ui: bool = False
    native_skills_ui: bool = False
    native_tools_ui: bool = False
    native_mcp_ui: bool = False
    loop_modes: bool = False
    attachments: bool = False
    context_usage: bool = False
    skills_commands: bool = False
    commands: list[HarnessCommand] = Field(default_factory=list)
    approval_presets: list[HarnessApprovalPreset] = Field(
        default_factory=list,
    )


class HarnessModel(BaseModel):
    """Provider-neutral model picker entry."""

    id: str
    name: str
    description: str = ""
    is_default: bool = False
    reasoning_efforts: list[str] = Field(default_factory=list)
    default_reasoning_effort: str | None = None


class HarnessProvider(BaseModel):
    """Static provider metadata combined with runtime status."""

    id: str
    name: str
    available: bool
    coming_soon: bool = False
    installed: bool = False
    authenticated: bool = False
    account: dict[str, Any] | None = None
    error: str | None = None
    capabilities: HarnessCapabilities = Field(
        default_factory=HarnessCapabilities,
    )


__all__ = [
    "HarnessApprovalPreset",
    "HarnessCapabilities",
    "HarnessCommand",
    "HarnessEvent",
    "HarnessEventKind",
    "HarnessHistoryItem",
    "HarnessHistoryKind",
    "HarnessModel",
    "HarnessProvider",
]
