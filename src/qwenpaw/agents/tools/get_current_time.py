# -*- coding: utf-8 -*-
"""Tools for getting and setting the user timezone."""

import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from agentscope.message import TextBlock
from agentscope.tool import ToolChunk
from agentscope.message import ToolResultState

from ...config import load_config, save_config
from ...runtime.tool_registry import tool_descriptor

logger = logging.getLogger(__name__)


@tool_descriptor(
    async_execution=True,
    tool_type="internal",
    policy_name="GetCurrentTime",
    ui_description="Get current date and time",
    ui_icon="🕐",
)
async def get_current_time() -> ToolChunk:
    """Get the current time in format `%Y-%m-%d %H:%M:%S TZ (Day)`,
    e.g. "2026-02-13 19:30:45 Asia/Shanghai (Friday)".

    Call this tool when the user asks for the current time or when
    the current time is needed for other operations.

    Returns:
        `ToolChunk`:
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

    return ToolChunk(
        is_last=True,
        state=ToolResultState.SUCCESS,
        content=[
            TextBlock(
                type="text",
                text=time_str,
            ),
        ],
    )


@tool_descriptor(
    async_execution=True,
    # Config/internal op — not a filesystem tool. Using tool_type="file"
    # would make extract_target() join workspace_dir onto timezone names.
    tool_type="internal",
    target_param="timezone_name",
    policy_name="SetUserTimezone",
    ui_description="Set user timezone",
    ui_icon="🌍",
)
async def set_user_timezone(timezone_name: str) -> ToolChunk:
    """Set the user timezone.
    Only call this tool when the user explicitly asks to change their timezone.

    Args:
        timezone_name: IANA timezone name (e.g. "Asia/Shanghai",
            "America/New_York", "Europe/London", "UTC").

    Returns:
        `ToolChunk`: Confirmation with the new timezone and current time.
    """
    tz_name = timezone_name.strip()
    if not tz_name:
        return ToolChunk(
            is_last=True,
            state=ToolResultState.SUCCESS,
            content=[TextBlock(type="text", text="Error: timezone is empty.")],
        )

    try:
        now = datetime.now(ZoneInfo(tz_name))
    except (ZoneInfoNotFoundError, KeyError):
        return ToolChunk(
            is_last=True,
            state=ToolResultState.SUCCESS,
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
    return ToolChunk(
        is_last=True,
        state=ToolResultState.SUCCESS,
        content=[
            TextBlock(
                type="text",
                text=f"Timezone set to {tz_name}. Current time: {time_str}",
            ),
        ],
    )
