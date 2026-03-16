# -*- coding: utf-8 -*-
"""Tool that returns the current UTC time."""

from datetime import datetime, timezone

from agentscope.message import TextBlock
from agentscope.tool import ToolResponse


async def get_current_time() -> ToolResponse:
    """Get the current UTC time.

    Returns the current time in UTC in a human-readable format.
    Useful for time-sensitive tasks such as scheduling cron jobs.

    Returns:
        `ToolResponse`:
            The current UTC time string,
            e.g. "2026-02-13 11:30:45 UTC (Friday)".
    """
    now = datetime.now(timezone.utc)
    time_str = now.strftime("%Y-%m-%d %H:%M:%S UTC (%A)")

    return ToolResponse(
        content=[
            TextBlock(
                type="text",
                text=time_str,
            ),
        ],
    )
