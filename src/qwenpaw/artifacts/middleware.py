"""Collect controlled session outputs after actual tool execution."""
from __future__ import annotations

import logging
import asyncio

from agentscope.middleware import MiddlewareBase

logger = logging.getLogger(__name__)
_pending_collections: set[asyncio.Task] = set()


async def collect_safely(context: dict) -> None:
    """Keep output files recoverable without masking the tool/run result."""
    task = asyncio.create_task(_collect_and_log(context))
    _pending_collections.add(task)
    task.add_done_callback(_pending_collections.discard)
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        # The original turn still propagates cancellation; its final status
        # and close hooks must not be skipped by this best-effort archive.
        logger.info("artifact collection continuing after turn cancellation")


async def _collect_and_log(context: dict) -> None:
    from .collection import collect_current_session_artifacts

    try:
        result = await collect_current_session_artifacts(context)
        if result.failures:
            logger.warning(
                "artifact collection incomplete: conversation=%s failures=%d; "
                "files retained for retry from the artifacts page",
                context.get("conversation_id"), len(result.failures),
            )
    except Exception:
        logger.warning(
            "artifact collection failed; files retained for retry",
            exc_info=True,
        )


class ArtifactCollectionMiddleware(MiddlewareBase):
    """Run inside the tool coordinator, including background executions."""

    async def on_acting(self, agent, input_kwargs, next_handler):
        try:
            async for item in next_handler():
                yield item
        finally:
            await collect_safely(getattr(agent, "_request_context", None) or {})
