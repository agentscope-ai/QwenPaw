# -*- coding: utf-8 -*-
"""Tests for refreshing the date in long-lived agent prompts."""

from datetime import datetime

import pytest

from qwenpaw.agents.middlewares import CurrentDateMiddleware


@pytest.mark.asyncio
async def test_refreshes_stale_date_with_configured_timezone() -> None:
    prompt = (
        "====================\n"
        "- Session ID: long-lived\n"
        "- Current date: 2026-08-05 Asia/Shanghai (Wednesday)\n"
        "- Important: keep this line\n"
        "===================="
    )
    middleware = CurrentDateMiddleware(
        "Asia/Shanghai",
        clock=lambda tz: datetime(2026, 8, 6, 9, 30, tzinfo=tz),
    )

    result = await middleware.on_system_prompt(None, prompt)

    assert "- Current date: 2026-08-06 Asia/Shanghai (Thursday)" in result
    assert "- Current date: 2026-08-05" not in result
    assert "- Important: keep this line" in result


@pytest.mark.asyncio
async def test_invalid_timezone_falls_back_to_utc() -> None:
    middleware = CurrentDateMiddleware(
        "Invalid/Timezone",
        clock=lambda tz: datetime(2026, 8, 6, 1, 30, tzinfo=tz),
    )

    result = await middleware.on_system_prompt(
        None,
        "- Current date: 2026-08-05 Invalid/Timezone (Wednesday)",
    )

    assert result == "- Current date: 2026-08-06 UTC (Thursday)"


@pytest.mark.asyncio
async def test_prompt_without_current_date_is_unchanged() -> None:
    middleware = CurrentDateMiddleware(
        "UTC",
        clock=lambda tz: datetime(2026, 8, 6, tzinfo=tz),
    )
    prompt = "System prompt without an environment date."

    assert await middleware.on_system_prompt(None, prompt) == prompt
