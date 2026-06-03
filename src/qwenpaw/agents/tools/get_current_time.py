# -*- coding: utf-8 -*-
"""Tools for getting and setting the user timezone."""

import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from agentscope.message import TextBlock
from agentscope.tool import ToolResponse

from ...config import load_config, save_config

logger = logging.getLogger(__name__)


async def get_current_time() -> ToolResponse:
    """Get the current time in format `%Y-%m-%d %H:%M:%S TZ (Day)`,
    e.g. "2026-02-13 19:30:45 Asia/Shanghai (Friday)".

    Call this tool when the user asks for the current time or when
    the current time is needed for other operations.

    Returns:
        `ToolResponse`:
            The current time string,
            e.g. "2026-02-13 19:30:45 Asia/Shanghai (Friday)".
    """
    user_tz = load_config().user_timezone or "UTC"
    try:
        now = datetime.now(ZoneInfo(user_tz))
    except (ZoneInfoNotFoundError, KeyError):
        logger.warning("Invalid timezone %r, falling back to UTC", user_tz)
        now = datetime.now(timezone.utc)
        user_tz = "UTC"

    time_str = (
        f"{now.strftime('%Y-%m-%d %H:%M:%S')} {user_tz} ({now.strftime('%A')})"
    )

    return ToolResponse(
        content=[
            TextBlock(
                type="text",
                text=time_str,
            ),
        ],
    )


async def set_user_timezone(timezone_name: str) -> ToolResponse:
    """Set the user timezone.
    Only call this tool when the user explicitly asks to change their timezone.

    Args:
        timezone_name: IANA timezone name (e.g. "Asia/Shanghai",
            "America/New_York", "Europe/London", "UTC").

    Returns:
        `ToolResponse`: Confirmation with the new timezone and current time.
    """
    tz_name = timezone_name.strip()
    if not tz_name:
        return ToolResponse(
            content=[TextBlock(type="text", text="Error: timezone is empty.")],
        )

    try:
        now = datetime.now(ZoneInfo(tz_name))
    except (ZoneInfoNotFoundError, KeyError):
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"Error: invalid timezone '{tz_name}'.",
                ),
            ],
        )

    config = load_config()
    config.user_timezone = tz_name
    save_config(config)

    time_str = (
        f"{now.strftime('%Y-%m-%d %H:%M:%S')} {tz_name} ({now.strftime('%A')})"
    )
    return ToolResponse(
        content=[
            TextBlock(
                type="text",
                text=f"Timezone set to {tz_name}. Current time: {time_str}",
            ),
        ],
    )
