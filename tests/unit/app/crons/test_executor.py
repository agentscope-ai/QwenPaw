# -*- coding: utf-8 -*-
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from qwenpaw.app.crons.executor import CronExecutor
from qwenpaw.app.crons.models import CronJobSpec


def _text_job() -> CronJobSpec:
    return CronJobSpec.model_validate(
        {
            "id": "job-1",
            "name": "strict delivery",
            "enabled": True,
            "schedule": {
                "type": "cron",
                "cron": "0 0 1 1 *",
                "timezone": "UTC",
            },
            "task_type": "text",
            "text": "hello",
            "dispatch": {
                "type": "channel",
                "channel": "dingtalk",
                "target": {
                    "user_id": "user-1",
                    "session_id": "session-1",
                },
                "mode": "stream",
                "meta": {"custom": "value"},
            },
        },
    )


@pytest.mark.asyncio
async def test_text_cron_marks_channel_delivery_as_strict():
    """Cron delivery failures should be visible in job history."""
    channel_manager = AsyncMock()
    executor = CronExecutor(
        workspace=AsyncMock(),
        channel_manager=channel_manager,
    )

    result = await executor.execute(_text_job())

    assert result["delivery_status"] == "success"
    send_text_kwargs = channel_manager.send_text.await_args.kwargs
    assert send_text_kwargs["meta"] == {
        "custom": "value",
        "_strict_delivery_errors": True,
    }
