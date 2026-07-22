# -*- coding: utf-8 -*-
"""File/media processing hook.

Processes uploaded file and media blocks in input messages before
agent execution — downloads remote content to local media_dir and
rewrites blocks to file:// URLs.
"""

from __future__ import annotations

import logging

from ..base import LifecycleHook
from ...runtime.hooks import HookContext, HookResult
from ...runtime.phases import Phase

logger = logging.getLogger(__name__)


class MediaProcessHook(LifecycleHook):
    """Process file/media blocks in input messages before execution."""

    phase = Phase.PRE_EXECUTE
    name = "media_process"
    priority = 5

    async def run(self, ctx: HookContext) -> HookResult:
        if not ctx.input_msgs:
            return HookResult()
        try:
            from ...agents.utils import (
                process_file_and_media_blocks_in_message,
            )

            await process_file_and_media_blocks_in_message(ctx.input_msgs)
        except Exception:
            logger.warning(
                "media_process: failed; user uploads may not be visible",
                exc_info=True,
            )
        return HookResult()


__all__ = ["MediaProcessHook"]
