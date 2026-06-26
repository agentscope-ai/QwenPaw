# -*- coding: utf-8 -*-
"""Shared data types for the context-management package."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(frozen=True)
class LogEntry:
    """One durable row appended to ``conversation_history``.

    Beyond the flattened ``content``, an entry carries the structured payload
    of its turn so the row can reconstruct the exact wire-format Msg later:
    ``blocks`` holds the serialized block dicts, ``tool_input`` the tool args,
    ``tool_call_id`` links a call to its result, ``tool_state`` the result
    state. Structured fields default to empty.
    """

    kind: Literal["model_turn", "context_msg", "tool_result"]
    role: str | None = None
    name: str | None = None  # tool name (for tool_call/tool_result)
    content: str | None = None  # text body
    metadata: dict[str, Any] = field(default_factory=dict)
    tool_call_id: str | None = None  # links tool_call <-> tool_result
    tool_input: Any = None
    tool_state: str | None = None
    headline: str | None = None  # the turn's ``⟦ … ⟧`` index line, if any
    blocks: list[dict[str, Any]] | None = None  # exact serialized block dicts
    created_at: str | None = None  # append() falls back to write-time now()


@dataclass(frozen=True)
class ExecutionResult:
    """What a single recall_history_python call returns."""

    stdout: str
    stderr: str
    error: str | None = None
