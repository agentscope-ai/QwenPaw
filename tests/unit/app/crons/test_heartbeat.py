# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from qwenpaw.app.crons.heartbeat import (
    _extract_message_preview,
    is_cron_expression,
    parse_heartbeat_every,
    run_heartbeat_once,
)

# ---------------------------------------------------------------------------
# is_cron_expression
# ---------------------------------------------------------------------------


def test_is_cron_expression_valid_5_field():
    assert is_cron_expression("0 9 * * 1") is True


def test_is_cron_expression_rejects_non_cron():
    assert is_cron_expression("30m") is False


def test_is_cron_expression_rejects_empty():
    assert is_cron_expression("") is False


def test_is_cron_expression_rejects_4_fields():
    assert is_cron_expression("0 9 * *") is False


def test_is_cron_expression_accepts_named_dow():
    """Named DOW abbreviations (mon–sun) are valid in POSIX cron and
    APScheduler ``CronTrigger``."""
    assert is_cron_expression("0 9 * * mon") is True
    assert is_cron_expression("0 9 * * MON") is True
    assert is_cron_expression("0 9 * * fri") is True


def test_is_cron_expression_accepts_named_dow_range():
    assert is_cron_expression("0 9 * * mon-fri") is True


def test_is_cron_expression_accepts_named_dow_with_step():
    assert is_cron_expression("0 9 * * tue/2") is True
    assert is_cron_expression("0 9 * * mon-fri/2") is True


def test_is_cron_expression_rejects_invalid_named_dow():
    assert is_cron_expression("0 9 * * xyz") is False
    assert is_cron_expression("0 9 * * monday") is False


# ---------------------------------------------------------------------------
# parse_heartbeat_every
# ---------------------------------------------------------------------------


def test_parse_heartbeat_every_minutes():
    assert parse_heartbeat_every("5m") == 300


def test_parse_heartbeat_every_hours():
    assert parse_heartbeat_every("1h") == 3600


def test_parse_heartbeat_every_seconds():
    assert parse_heartbeat_every("30s") == 30


def test_parse_heartbeat_every_combined():
    assert parse_heartbeat_every("1h30m") == 5400


def test_parse_heartbeat_every_empty_defaults_to_30m():
    assert parse_heartbeat_every("") == 1800


def test_parse_heartbeat_every_invalid_defaults_to_30m():
    assert parse_heartbeat_every("bogus") == 1800


# ---------------------------------------------------------------------------
# _extract_message_preview
# ---------------------------------------------------------------------------


def test_extract_message_preview_text_block():
    msg = {
        "content": [
            {"type": "text", "text": "Hello world"},
        ],
    }
    assert _extract_message_preview(msg) == "Hello world"


def test_extract_message_preview_empty_content_returns_none():
    assert _extract_message_preview({"content": []}) is None


def test_extract_message_preview_non_list_content_returns_none():
    assert _extract_message_preview({"content": "not a list"}) is None


def test_extract_message_preview_truncates_long_text():
    long_text = "x" * 5000
    msg = {"content": [{"type": "text", "text": long_text}]}
    result = _extract_message_preview(msg)
    assert result == long_text


# ---------------------------------------------------------------------------
# run_heartbeat_once turn usage
# ---------------------------------------------------------------------------


class _FakePath:
    def is_file(self):
        return True


async def _run_sync_directly(fn, *args, **kwargs):
    result = fn(*args, **kwargs)
    if asyncio.iscoroutine(result):
        return await result
    return result


def _patch_heartbeat_env(monkeypatch, *, stream):
    monkeypatch.setattr(
        "qwenpaw.app.crons.heartbeat.get_heartbeat_config",
        lambda agent_id: SimpleNamespace(
            active_hours=None,
            timeout_seconds=0.5,
            target="",
        ),
    )
    monkeypatch.setattr(
        "qwenpaw.app.crons.heartbeat.get_heartbeat_query_path",
        lambda: _FakePath(),
    )
    monkeypatch.setattr(
        "qwenpaw.app.crons.heartbeat.read_text_file_with_encoding_fallback",
        lambda path: "hello",
    )
    monkeypatch.setattr(
        "qwenpaw.app.crons.heartbeat.load_config",
        lambda: SimpleNamespace(last_dispatch=None),
    )
    monkeypatch.setattr(
        "qwenpaw.app.crons.heartbeat.run_sync_io",
        _run_sync_directly,
    )
    return SimpleNamespace(stream_query=stream)


@pytest.mark.asyncio
async def test_heartbeat_cancellation_clears_only_its_own_usage(monkeypatch):
    from qwenpaw.token_usage.model_wrapper import TokenRecordingModelWrapper

    wrapper = TokenRecordingModelWrapper
    chat_usage = {"total_tokens": 10}
    monkeypatch.setitem(wrapper._usage_by_session, "main", chat_usage)
    started = asyncio.get_running_loop().create_future()
    buffers = []

    async def stream(req):
        assert req["session_id"] == "main"
        assert wrapper.peek_usage_for_session("main") is None
        buffer = wrapper._usage_buffer()
        buffers.append(buffer)
        buffer["main"] = {"total_tokens": 2}
        started.set_result(None)
        await asyncio.Event().wait()
        yield

    workspace = _patch_heartbeat_env(monkeypatch, stream=stream)
    run = asyncio.create_task(
        run_heartbeat_once(workspace=workspace, channel_manager=AsyncMock()),
    )
    await asyncio.wait((started, run), return_when=asyncio.FIRST_COMPLETED)
    if run.done():
        await run
        pytest.fail("Heartbeat finished before cancellation")

    run.cancel()
    with pytest.raises(asyncio.CancelledError):
        await run
    assert buffers == [{}]
    assert wrapper.peek_usage_for_session("main") == chat_usage
