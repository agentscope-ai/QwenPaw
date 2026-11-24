# -*- coding: utf-8 -*-
"""
Immutable observations; subscribers never participate in business decisions.
"""

from dataclasses import dataclass, field
from typing import Callable, Mapping, Union, Awaitable
from .tools import ToolContext

JSONValue = Union[
    None,
    bool,
    int,
    float,
    str,
    tuple["JSONValue", ...],
    Mapping[str, "JSONValue"],
]


@dataclass(frozen=True)
class StreamContent:
    type: str
    text: str = ""
    delta: bool = False
    index: int | None = None
    status: str | None = None
    object: str = "content"
    msg_id: str | None = None
    data: JSONValue = None
    attributes: Mapping[str, JSONValue] = field(default_factory=dict)


@dataclass(frozen=True)
class StreamMessage:
    id: str
    type: str
    role: str | None
    status: str | None
    content: tuple[StreamContent, ...]
    metadata: Mapping[str, JSONValue] = field(default_factory=dict)
    attributes: Mapping[str, JSONValue] = field(default_factory=dict)


@dataclass(frozen=True)
class ChatEvent:
    object: str
    id: str = ""
    type: str = ""
    status: str | None = None
    output: tuple[StreamMessage, ...] = ()
    content: tuple[StreamContent, ...] = ()
    data: JSONValue = None
    attributes: Mapping[str, JSONValue] = field(default_factory=dict)


@dataclass(frozen=True)
class ApprovalDisplay:
    tool_display_name: str = ""
    tool_source: str = ""
    exact_target: str = ""
    similar_target: str = ""
    is_generalized: bool = False


@dataclass(frozen=True)
class ApprovalSnapshot:
    request_id: str
    session_id: str
    root_session_id: str
    owner_agent_id: str
    workspace_id: str
    user_id: str
    channel: str
    name: str
    status: str
    created_at: float
    resolved_at: float | None
    timeout_seconds: float
    severity: str
    findings_count: int
    result_summary: str
    source_type: str
    scope: str | None
    display: ApprovalDisplay


@dataclass(frozen=True)
class RunEvent:
    kind: str
    run_id: str
    workspace_id: str
    session_id: str
    user_id: str
    channel: str
    sequence: int
    timestamp: float
    event: ChatEvent | None = None
    reason: str = ""


@dataclass(frozen=True)
class ApprovalEvent:
    kind: str
    approval: ApprovalSnapshot
    sequence: int
    timestamp: float

    @property
    def workspace_id(self):
        return self.approval.workspace_id

    @property
    def session_id(self):
        return self.approval.session_id


@dataclass(frozen=True)
class SubscriptionGap:
    kind: str = "gap"
    lost: int = 0
    disconnected: bool = False


Observation = RunEvent | ApprovalEvent | SubscriptionGap


@dataclass(frozen=True)
class EventSubscription:
    handler: Callable[[ToolContext, Observation], None | Awaitable[None]]
    kinds: tuple[str, ...] = ()
    workspace_id: str | None = None
    session_id: str | None = None
    capacity: int = 128
