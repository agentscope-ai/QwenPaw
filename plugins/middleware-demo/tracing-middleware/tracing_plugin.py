# -*- coding: utf-8 -*-
"""Tracing Middleware Demo Plugin.

Demonstrates `on_acting` middleware that logs every tool call with
timing information to a trace file in the workspace.

The middleware factory conditionally activates: it returns None (skip)
unless the ``QWENPAW_TRACE`` environment variable is set.
"""

import logging
import os
import time
from pathlib import Path
from typing import Any, AsyncGenerator, Callable

from agentscope.middleware import MiddlewareBase

from qwenpaw.plugins.api import PluginApi

logger = logging.getLogger(__name__)


class TracingMiddleware(MiddlewareBase):
    """Logs tool call name, input, and execution duration."""

    def __init__(self, trace_file: Path) -> None:
        self._trace_file = trace_file
        self._trace_file.parent.mkdir(parents=True, exist_ok=True)

    async def on_acting(  # pylint: disable=unused-argument
        self,
        agent: Any,
        input_kwargs: dict[str, Any],
        next_handler: Callable[..., AsyncGenerator[Any, None]],
    ) -> AsyncGenerator[Any, None]:
        tool_call = input_kwargs["tool_call"]
        tool_name = getattr(tool_call, "name", str(tool_call))
        tool_input = getattr(tool_call, "input", "")

        start = time.perf_counter()
        try:
            async for item in next_handler():
                yield item
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000
            line = (
                f"[{time.strftime('%H:%M:%S')}] "
                f"{tool_name}({tool_input[:100]}) — {elapsed_ms:.1f}ms\n"
            )
            try:
                with open(self._trace_file, "a", encoding="utf-8") as f:
                    f.write(line)
            except OSError:
                logger.debug("Failed to write trace log")


def _tracing_factory(ctx: Any, agent_config: Any) -> TracingMiddleware | None:
    """Create TracingMiddleware when QWENPAW_TRACE env var is set."""
    del agent_config
    if not os.environ.get("QWENPAW_TRACE"):
        return None

    workspace_dir = getattr(ctx, "workspace_dir", None)
    if workspace_dir is None:
        return None

    trace_file = Path(workspace_dir) / ".qwenpaw" / "trace.log"
    return TracingMiddleware(trace_file=trace_file)


class TracingPlugin:
    """Plugin entry point."""

    def register(self, api: PluginApi) -> None:
        api.register_middleware(_tracing_factory, priority=50)


plugin = TracingPlugin()
