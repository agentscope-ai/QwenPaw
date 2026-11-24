# -*- coding: utf-8 -*-
"""Request ownership inherited by model calls and their streams."""

from contextvars import Context, ContextVar, copy_context
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..plugins.sdk import _RunStreams
    from .provider_turn import ProviderTurn

current_provider_turn: ContextVar["ProviderTurn | None"] = ContextVar(
    "provider_turn_usage",
    default=None,
)
current_run_streams: ContextVar["_RunStreams | None"] = ContextVar(
    "sdk_run_stream_tasks",
    default=None,
)


def detached_turn_context() -> Context:
    """Keep ambient context while releasing the submitting run and turn."""
    context = copy_context()
    context.run(current_provider_turn.set, None)
    context.run(current_run_streams.set, None)
    return context
