# -*- coding: utf-8 -*-
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from qwenpaw.app.crons.executor import CronExecutor
from qwenpaw.app.crons.models import (
    CronJobSpec,
    ScheduleSpec,
    DispatchSpec,
    DispatchTarget,
    JobRuntimeSpec,
    CronJobRequest,
)


@pytest.mark.asyncio
async def test_cron_executor_clear_context():
    # Mock runner and channel_manager
    runner = MagicMock()

    # stream_query is an async generator
    async def mock_stream_query(_req):
        yield {"type": "text", "text": "done"}

    runner.stream_query.side_effect = mock_stream_query

    channel_manager = AsyncMock()

    executor = CronExecutor(runner=runner, channel_manager=channel_manager)

    # Create a job spec with clear_context_before_run=True
    job = CronJobSpec(
        id="test-job",
        name="Test Job",
        schedule=ScheduleSpec(type="cron", cron="0 0 * * *"),
        task_type="agent",
        request=CronJobRequest(input="hello"),
        dispatch=DispatchSpec(
            target=DispatchTarget(user_id="user1", session_id="session1"),
            channel="console",
        ),
        runtime=JobRuntimeSpec(clear_context_before_run=True),
    )

    with patch(
        "qwenpaw.app.crons.executor.read_session_messages",
        AsyncMock(return_value=[]),
    ), patch("qwenpaw.app.crons.executor.create_trace", AsyncMock()), patch(
        "qwenpaw.app.crons.executor.append_trace_from_session_delta",
        AsyncMock(),
    ), patch(
        "qwenpaw.app.crons.executor.finalize_trace",
        AsyncMock(),
    ):
        await executor.execute(job)

    # Verify stream_query was called twice
    assert runner.stream_query.call_count == 2

    # Check first call is /clear
    first_call_args = runner.stream_query.call_args_list[0][0][0]
    assert first_call_args["input"][0]["content"][0]["text"] == "/clear"

    # Check second call is the main task
    second_call_args = runner.stream_query.call_args_list[1][0][0]
    assert second_call_args["input"] == "hello"


@pytest.mark.asyncio
async def test_cron_executor_no_clear_context():
    # Mock runner and channel_manager
    runner = MagicMock()

    async def mock_stream_query(_req):
        yield {"type": "text", "text": "done"}

    runner.stream_query.side_effect = mock_stream_query

    channel_manager = AsyncMock()

    executor = CronExecutor(runner=runner, channel_manager=channel_manager)

    # Create a job spec with clear_context_before_run=False (default)
    job = CronJobSpec(
        id="test-job-no-clear",
        name="Test Job No Clear",
        schedule=ScheduleSpec(type="cron", cron="0 0 * * *"),
        task_type="agent",
        request=CronJobRequest(input="hello"),
        dispatch=DispatchSpec(
            target=DispatchTarget(user_id="user1", session_id="session1"),
            channel="console",
        ),
        runtime=JobRuntimeSpec(clear_context_before_run=False),
    )

    with patch(
        "qwenpaw.app.crons.executor.read_session_messages",
        AsyncMock(return_value=[]),
    ), patch("qwenpaw.app.crons.executor.create_trace", AsyncMock()), patch(
        "qwenpaw.app.crons.executor.append_trace_from_session_delta",
        AsyncMock(),
    ), patch(
        "qwenpaw.app.crons.executor.finalize_trace",
        AsyncMock(),
    ):
        await executor.execute(job)

    # Verify stream_query was called ONLY ONCE
    assert runner.stream_query.call_count == 1

    # Check the call is the main task
    call_args = runner.stream_query.call_args_list[0][0][0]
    assert call_args["input"] == "hello"
