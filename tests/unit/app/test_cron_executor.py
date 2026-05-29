# -*- coding: utf-8 -*-
"""Tests for CronExecutor share_session fix (GitHub issue #4818).

Covers:
- ``_is_session_busy()`` delegation to TaskTracker
- Auto-fallback when ``share_session=True`` and session is busy
- ``session_source`` values: ``"cron"`` vs ``"cron:shared"``
- Empty delta detection and ``"warning"`` trace status
- Return dict fields: ``trace_event_count``, ``session_fell_back``
- ``JobRuntimeSpec.share_session`` default is now ``False``
- ``SessionSource.cron_shared`` enum value
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from qwenpaw.app.crons.executor import CronExecutor
from qwenpaw.app.crons.models import (
    CronJobRequest,
    CronJobSpec,
    DispatchSpec,
    DispatchTarget,
    JobRuntimeSpec,
    ScheduleSpec,
)
from qwenpaw.app.runner.models import SessionSource


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_job(
    *,
    share_session: bool = False,
    task_type: str = "agent",
    text: str | None = None,
    request: CronJobRequest | None = None,
) -> CronJobSpec:
    """Build a minimal CronJobSpec for testing."""
    target = DispatchTarget(user_id="user-1", session_id="sess-1")
    if task_type == "agent" and request is None:
        request = CronJobRequest(input="hello")
    return CronJobSpec(
        id="job-1",
        name="test-job",
        schedule=ScheduleSpec(type="cron", cron="0 9 * * mon"),
        task_type=task_type,
        text=text,
        request=request,
        dispatch=DispatchSpec(channel="test", target=target),
        runtime=JobRuntimeSpec(share_session=share_session),
    )


def _make_executor(
    *,
    has_task_tracker: bool = True,
    session_busy: bool = False,
) -> tuple[CronExecutor, MagicMock]:
    """Build a CronExecutor with a mocked runner and channel_manager.

    Returns (executor, runner_mock).
    """
    runner = MagicMock()
    # pylint: disable=protected-access
    if has_task_tracker:
        task_tracker = AsyncMock()
        task_tracker.has_active_tasks = AsyncMock(
            return_value=session_busy,
        )
        runner._task_tracker = task_tracker
    else:
        runner._task_tracker = None
    # pylint: enable=protected-access

    # stream_query must be an async generator
    async def _fake_stream(_req):
        yield {"type": "text", "content": "ok"}

    runner.stream_query = MagicMock(return_value=_fake_stream({}))

    channel_manager = MagicMock()
    channel_manager.send_text = AsyncMock()
    channel_manager.send_event = AsyncMock()

    executor = CronExecutor(runner=runner, channel_manager=channel_manager)
    return executor, runner


# ---------------------------------------------------------------------------
# _is_session_busy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_is_session_busy_no_tracker():
    """Returns False when runner has no _task_tracker attribute."""
    executor, _ = _make_executor(has_task_tracker=False)
    # pylint: disable=protected-access
    result = await executor._is_session_busy()
    assert result is False


@pytest.mark.asyncio
async def test_is_session_busy_tracker_says_idle():
    """Returns False when TaskTracker has no active tasks."""
    executor, _ = _make_executor(has_task_tracker=True, session_busy=False)
    # pylint: disable=protected-access
    result = await executor._is_session_busy()
    assert result is False


@pytest.mark.asyncio
async def test_is_session_busy_tracker_says_busy():
    """Returns True when TaskTracker has active tasks."""
    executor, _ = _make_executor(has_task_tracker=True, session_busy=True)
    # pylint: disable=protected-access
    result = await executor._is_session_busy()
    assert result is True


@pytest.mark.asyncio
async def test_is_session_busy_tracker_exception():
    """Returns False if TaskTracker.has_active_tasks() raises."""
    executor, runner = _make_executor(
        has_task_tracker=True,
        session_busy=False,
    )
    # pylint: disable=protected-access
    runner._task_tracker.has_active_tasks = AsyncMock(
        side_effect=RuntimeError("boom"),
    )
    # pylint: disable=protected-access
    result = await executor._is_session_busy()
    assert result is False


# ---------------------------------------------------------------------------
# share_session auto-fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("qwenpaw.app.crons.executor.finalize_trace", new_callable=AsyncMock)
@patch("qwenpaw.app.crons.executor.append_trace_from_session_delta")
@patch("qwenpaw.app.crons.executor.create_trace", new_callable=AsyncMock)
@patch(
    "qwenpaw.app.crons.executor.read_session_messages",
    new_callable=AsyncMock,
)
async def test_share_session_fallback_when_busy(
    mock_read,
    _mock_create,
    mock_delta,
    _mock_finalize,
):
    """When share_session=True and session is busy, falls back to isolated."""
    mock_read.return_value = []
    mock_delta.return_value = [{"role": "assistant", "content": "hi"}]

    executor, runner = _make_executor(session_busy=True)
    job = _make_job(share_session=True)

    result = await executor.execute(job)

    # Should have fallen back
    assert result["session_fell_back"] is True

    # Verify the request used the isolated session_id pattern
    call_args = runner.stream_query.call_args
    req = call_args[0][0]
    assert req["session_id"] == "sess-1:cron:job-1"
    assert req["session_source"] == "cron"


@pytest.mark.asyncio
@patch("qwenpaw.app.crons.executor.finalize_trace", new_callable=AsyncMock)
@patch("qwenpaw.app.crons.executor.append_trace_from_session_delta")
@patch("qwenpaw.app.crons.executor.create_trace", new_callable=AsyncMock)
@patch(
    "qwenpaw.app.crons.executor.read_session_messages",
    new_callable=AsyncMock,
)
async def test_share_session_no_fallback_when_idle(
    mock_read,
    _mock_create,
    mock_delta,
    _mock_finalize,
):
    """When share_session=True and session is idle, uses shared session."""
    mock_read.return_value = []
    mock_delta.return_value = [{"role": "assistant", "content": "hi"}]

    executor, runner = _make_executor(session_busy=False)
    job = _make_job(share_session=True)

    result = await executor.execute(job)

    assert result["session_fell_back"] is False

    call_args = runner.stream_query.call_args
    req = call_args[0][0]
    assert req["session_id"] == "sess-1"
    assert req["session_source"] == "cron:shared"


@pytest.mark.asyncio
@patch("qwenpaw.app.crons.executor.finalize_trace", new_callable=AsyncMock)
@patch("qwenpaw.app.crons.executor.append_trace_from_session_delta")
@patch("qwenpaw.app.crons.executor.create_trace", new_callable=AsyncMock)
@patch(
    "qwenpaw.app.crons.executor.read_session_messages",
    new_callable=AsyncMock,
)
async def test_isolated_session_default_no_fallback(
    mock_read,
    _mock_create,
    mock_delta,
    _mock_finalize,
):
    """When share_session=False (default), no fallback logic runs."""
    mock_read.return_value = []
    mock_delta.return_value = [{"role": "assistant", "content": "hi"}]

    executor, runner = _make_executor(session_busy=True)
    job = _make_job(share_session=False)

    result = await executor.execute(job)

    assert result["session_fell_back"] is False

    call_args = runner.stream_query.call_args
    req = call_args[0][0]
    assert req["session_id"] == "sess-1:cron:job-1"
    assert req["session_source"] == "cron"


# ---------------------------------------------------------------------------
# session_source values
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("qwenpaw.app.crons.executor.finalize_trace", new_callable=AsyncMock)
@patch("qwenpaw.app.crons.executor.append_trace_from_session_delta")
@patch("qwenpaw.app.crons.executor.create_trace", new_callable=AsyncMock)
@patch(
    "qwenpaw.app.crons.executor.read_session_messages",
    new_callable=AsyncMock,
)
async def test_session_source_cron_shared(
    mock_read,
    _mock_create,
    mock_delta,
    _mock_finalize,
):
    """share_session=True + idle session sets session_source=cron:shared."""
    mock_read.return_value = []
    mock_delta.return_value = [{"role": "assistant", "content": "x"}]

    executor, runner = _make_executor(session_busy=False)
    job = _make_job(share_session=True)

    await executor.execute(job)

    req = runner.stream_query.call_args[0][0]
    assert req["session_source"] == "cron:shared"


@pytest.mark.asyncio
@patch("qwenpaw.app.crons.executor.finalize_trace", new_callable=AsyncMock)
@patch("qwenpaw.app.crons.executor.append_trace_from_session_delta")
@patch("qwenpaw.app.crons.executor.create_trace", new_callable=AsyncMock)
@patch(
    "qwenpaw.app.crons.executor.read_session_messages",
    new_callable=AsyncMock,
)
async def test_session_source_cron_isolated(
    mock_read,
    _mock_create,
    mock_delta,
    _mock_finalize,
):
    """share_session=False sets session_source=cron."""
    mock_read.return_value = []
    mock_delta.return_value = [{"role": "assistant", "content": "x"}]

    executor, runner = _make_executor(session_busy=False)
    job = _make_job(share_session=False)

    await executor.execute(job)

    req = runner.stream_query.call_args[0][0]
    assert req["session_source"] == "cron"


# ---------------------------------------------------------------------------
# Empty delta detection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("qwenpaw.app.crons.executor.finalize_trace", new_callable=AsyncMock)
@patch("qwenpaw.app.crons.executor.append_trace_from_session_delta")
@patch("qwenpaw.app.crons.executor.create_trace", new_callable=AsyncMock)
@patch(
    "qwenpaw.app.crons.executor.read_session_messages",
    new_callable=AsyncMock,
)
async def test_empty_delta_sets_warning_status(
    mock_read,
    _mock_create,
    mock_delta,
    mock_finalize,
):
    """When delta is empty, finalize_trace is called with status='warning'."""
    mock_read.return_value = []
    mock_delta.return_value = []  # empty delta

    executor, _ = _make_executor(session_busy=False)
    job = _make_job(share_session=False)

    result = await executor.execute(job)

    assert result["trace_event_count"] == 0
    mock_finalize.assert_called_once()
    call_kwargs = mock_finalize.call_args
    assert (
        call_kwargs[1]["status"] == "warning" or call_kwargs[0][1] == "warning"
    )


@pytest.mark.asyncio
@patch("qwenpaw.app.crons.executor.finalize_trace", new_callable=AsyncMock)
@patch("qwenpaw.app.crons.executor.append_trace_from_session_delta")
@patch("qwenpaw.app.crons.executor.create_trace", new_callable=AsyncMock)
@patch(
    "qwenpaw.app.crons.executor.read_session_messages",
    new_callable=AsyncMock,
)
async def test_nonempty_delta_sets_success_status(
    mock_read,
    _mock_create,
    mock_delta,
    mock_finalize,
):
    """When delta is non-empty, finalize_trace has status='success'."""
    mock_read.return_value = []
    mock_delta.return_value = [{"role": "assistant", "content": "hi"}]

    executor, _ = _make_executor(session_busy=False)
    job = _make_job(share_session=False)

    result = await executor.execute(job)

    assert result["trace_event_count"] == 1
    mock_finalize.assert_called_once()
    call_kwargs = mock_finalize.call_args
    assert (
        call_kwargs[1]["status"] == "success" or call_kwargs[0][1] == "success"
    )


# ---------------------------------------------------------------------------
# Return dict fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("qwenpaw.app.crons.executor.finalize_trace", new_callable=AsyncMock)
@patch("qwenpaw.app.crons.executor.append_trace_from_session_delta")
@patch("qwenpaw.app.crons.executor.create_trace", new_callable=AsyncMock)
@patch(
    "qwenpaw.app.crons.executor.read_session_messages",
    new_callable=AsyncMock,
)
async def test_agent_return_fields(
    mock_read,
    _mock_create,
    mock_delta,
    _mock_finalize,
):
    """Agent result includes trace_event_count and session_fell_back."""
    mock_read.return_value = []
    mock_delta.return_value = [{"role": "assistant", "content": "hi"}]

    executor, _ = _make_executor(session_busy=False)
    job = _make_job(share_session=False)

    result = await executor.execute(job)

    assert result["task_type"] == "agent"
    assert "run_id" in result
    assert "trace_event_count" in result
    assert "session_fell_back" in result
    assert result["trace_event_count"] == 1
    assert result["session_fell_back"] is False


# ---------------------------------------------------------------------------
# text task_type (unchanged behavior)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_text_task_does_not_check_session():
    """Text tasks bypass session-busy check entirely."""
    executor, runner = _make_executor(session_busy=True)
    job = _make_job(task_type="text", text="hello world")

    result = await executor.execute(job)

    assert result["task_type"] == "text"
    assert result["delivery_status"] == "success"
    # stream_query should NOT have been called for text tasks
    runner.stream_query.assert_not_called()


# ---------------------------------------------------------------------------
# Model defaults
# ---------------------------------------------------------------------------


def test_job_runtime_share_session_default_is_false():
    """JobRuntimeSpec.share_session defaults to False."""
    runtime = JobRuntimeSpec()
    assert runtime.share_session is False


def test_session_source_cron_shared_enum():
    """SessionSource has cron_shared with value 'cron:shared'."""
    assert SessionSource.cron_shared.value == "cron:shared"
    # Round-trip through string construction
    assert SessionSource("cron:shared") is SessionSource.cron_shared
