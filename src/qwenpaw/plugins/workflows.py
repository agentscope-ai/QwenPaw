# -*- coding: utf-8 -*-
"""Workspace service jobs scheduled and cancelled by the host (SDK 1.2)."""

from dataclasses import dataclass, field
from typing import Awaitable, Callable, Mapping

from .events import JSONValue
from .tools import ToolContext


@dataclass(frozen=True)
class WorkflowSchedule:
    """Five-field cron, using the workspace timezone unless overridden.

    Empty workspace_ids means all enabled workspaces. Scheduled work has no
    user or chat identity and cannot access a user's conversation. This is a
    workspace service declaration, not a user-created personal reminder.
    """

    cron: str
    timezone: str | None = None
    workspace_ids: tuple[str, ...] = ()


@dataclass(frozen=True, kw_only=True)
class WorkflowContext(ToolContext):
    scheduled: bool = True


@dataclass(frozen=True)
class WorkflowNotification:
    """Workspace-wide inbox message; native cron notification preferences apply."""

    title: str
    body: str


@dataclass(frozen=True)
class WorkflowResult:
    success: bool = True
    text: str = ""
    notification: WorkflowNotification | None = None


@dataclass(frozen=True)
class WorkflowSpec:
    """One non-overlapping job per workspace, with immutable JSON parameters.

    No manual-run API, personal recipient selection or workflow DAG is implied.
    Missed occurrences coalesce, with a 60-second grace period. The timeout
    requests cancellation; resource cleanup must finish before a new run.
    """

    name: str
    handler: Callable[
        [WorkflowContext, Mapping[str, JSONValue]],
        Awaitable[WorkflowResult],
    ]
    schedule: WorkflowSchedule
    parameters: Mapping[str, JSONValue] = field(default_factory=dict)
    timeout: float = 300.0
