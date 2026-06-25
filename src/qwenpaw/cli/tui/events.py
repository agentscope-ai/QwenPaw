# -*- coding: utf-8 -*-
"""Normalized TUI event types.

The ACP subprocess transport translates its wire format into this small union
so the UI layer is transport-agnostic. This is the ``TuiEvent`` contract
referenced in the design doc (§4.2/§4.3).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Connected:
    """Emitted once the transport has a live session."""

    session_id: str
    agent: str | None = None
    model: str | None = None
    qwenpaw_version: str | None = None
    warming: bool = False


@dataclass(frozen=True)
class BackendWarmed:
    """The backend completed its proactive first-turn warmup."""

    success: bool = True
    message: str | None = None


@dataclass(frozen=True)
class SessionTitle:
    """A human-readable title for the session (e.g. for the terminal tab)."""

    title: str


@dataclass(frozen=True)
class TextDelta:
    """A chunk of visible assistant text (already a delta, not cumulative)."""

    text: str


@dataclass(frozen=True)
class ThoughtDelta:
    """A chunk of agent thinking/reasoning."""

    text: str


@dataclass(frozen=True)
class FileLink:
    """A file the agent surfaced (e.g. via ``send_file_to_user``).

    Carried on a :class:`ToolCall` as an ACP ``resource_link`` content block;
    the UI renders it as a clickable link that opens the file.
    """

    uri: str
    name: str = ""
    mime_type: str | None = None


@dataclass(frozen=True)
class ToolCall:
    """Start or update of a tool call (keyed by ``tool_call_id``)."""

    tool_call_id: str
    title: str
    kind: str | None = None
    status: str | None = None  # pending | in_progress | completed | failed
    output: str | None = None
    params: str | None = None  # raw input parameters, rendered for display
    links: tuple[FileLink, ...] = ()  # file/resource links in the result


@dataclass(frozen=True)
class PlanEntry:
    content: str
    status: str = "pending"
    priority: str = "medium"


@dataclass(frozen=True)
class PlanUpdate:
    """The agent's current plan/todo list."""

    entries: list[PlanEntry] = field(default_factory=list)


@dataclass(frozen=True)
class Usage:
    """Token-usage metadata for the status bar."""

    used: int
    size: int


@dataclass(frozen=True)
class TokenUsage:
    """Incremental token counts from one LLM call.

    QwenPaw reports usage per LLM invocation, so the UI sums these to show
    the running input/output totals for the session. ``model`` is the model
    that produced the call (the session may bind it late, e.g. via a
    global fallback), so the UI can fill in the model name once known.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    model: str | None = None


@dataclass(frozen=True)
class PermissionOption:
    option_id: str
    name: str
    kind: str  # allow_once | allow_always | reject_once | reject_always


@dataclass(frozen=True)
class PermissionRequest:
    """A tool is awaiting the user's approval. ``request_id`` resolves it."""

    request_id: str
    title: str
    options: list[PermissionOption] = field(default_factory=list)
    tool_kind: str | None = None
    params: str | None = None


@dataclass(frozen=True)
class SlashCommand:
    """One agent slash command, used to drive input auto-suggestions."""

    name: str
    description: str = ""


@dataclass(frozen=True)
class AvailableCommands:
    """The set of slash commands the agent currently advertises."""

    commands: list[SlashCommand] = field(default_factory=list)


@dataclass(frozen=True)
class PushMessage:
    """A server-initiated proactive message (ACP ext push-message)."""

    text: str


@dataclass(frozen=True)
class UserTurn:
    """A user message replayed from a resumed session's saved transcript.

    Only emitted during ``session/load`` history replay — live user input is
    rendered directly by the UI, not round-tripped through the transport.
    """

    text: str


@dataclass(frozen=True)
class SessionSummary:
    """One resumable past session, for the /resume picker."""

    session_id: str
    title: str = ""
    cwd: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class TurnEnded:
    """The current prompt turn finished."""

    stop_reason: str | None = None


@dataclass(frozen=True)
class TransportError:
    """A transport/agent error to surface in the transcript."""

    message: str


# The normalized union the UI consumes.
TuiEvent = (
    Connected
    | BackendWarmed
    | SessionTitle
    | TextDelta
    | ThoughtDelta
    | ToolCall
    | PlanUpdate
    | Usage
    | TokenUsage
    | PermissionRequest
    | AvailableCommands
    | PushMessage
    | UserTurn
    | TurnEnded
    | TransportError
)
