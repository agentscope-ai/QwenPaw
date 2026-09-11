# -*- coding: utf-8 -*-
"""Tests for ChannelManager lifecycle and session-id extraction.

Covers _extract_session_id (normalized/session-id precedence and the
debounce-key fallback), get_channel lookup, replace_channel (swap with
old-stop, add-when-absent, start-failure rollback), restart_channel
error paths, and stop_all task cancellation, using mock channel
instances so no real I/O occurs.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from qwenpaw.app.channels.manager import ChannelManager


def _make_channel(name: str, *, uses_queue: bool = True) -> MagicMock:
    channel = MagicMock(name=f"channel_{name}")
    channel.channel = name
    channel.start = AsyncMock()
    channel.stop = AsyncMock()
    channel.set_enqueue = MagicMock()
    channel.uses_manager_queue = uses_queue
    channel.get_debounce_key = MagicMock(return_value=f"{name}:fallback")
    return channel


def _manager(*channels) -> ChannelManager:
    return ChannelManager(list(channels))


# ---------------------------------------------------------------------------
# _extract_session_id
# ---------------------------------------------------------------------------


class TestExtractSessionId:
    def test_dict_with_session_id_used_directly(self):
        manager = _manager()
        channel = _make_channel("dingtalk")
        payload = {"session_id": "dingtalk:user1", "text": "hi"}
        result = manager._extract_session_id(channel, payload)
        assert result == "dingtalk:user1"
        channel.get_debounce_key.assert_not_called()

    def test_dict_without_session_id_falls_to_debounce(self):
        manager = _manager()
        channel = _make_channel("dingtalk")
        result = manager._extract_session_id(channel, {"text": "hi"})
        assert result == "dingtalk:fallback"
        channel.get_debounce_key.assert_called_once()

    def test_empty_session_id_falls_to_debounce(self):
        manager = _manager()
        channel = _make_channel("dingtalk")
        result = manager._extract_session_id(channel, {"session_id": ""})
        assert result == "dingtalk:fallback"

    def test_object_with_session_id_attribute(self):
        manager = _manager()
        channel = _make_channel("telegram")
        payload = SimpleNamespace(session_id="telegram:obj", text="x")
        result = manager._extract_session_id(channel, payload)
        assert result == "telegram:obj"
        channel.get_debounce_key.assert_not_called()

    def test_object_without_session_id_falls_to_debounce(self):
        manager = _manager()
        channel = _make_channel("telegram")
        payload = SimpleNamespace(text="x")
        result = manager._extract_session_id(channel, payload)
        assert result == "telegram:fallback"


# ---------------------------------------------------------------------------
# get_channel
# ---------------------------------------------------------------------------


class TestGetChannel:
    @pytest.mark.asyncio
    async def test_found_by_name(self):
        channel = _make_channel("qq")
        manager = _manager(channel)
        result = await manager.get_channel("qq")
        assert result is channel

    @pytest.mark.asyncio
    async def test_not_found_returns_none(self):
        manager = _manager(_make_channel("qq"))
        assert await manager.get_channel("ghost") is None

    @pytest.mark.asyncio
    async def test_empty_manager_returns_none(self):
        manager = _manager()
        assert await manager.get_channel("any") is None


# ---------------------------------------------------------------------------
# replace_channel
# ---------------------------------------------------------------------------


class TestReplaceChannel:
    @pytest.mark.asyncio
    async def test_swap_stops_old_channel(self):
        old = _make_channel("dingtalk")
        new = _make_channel("dingtalk")
        manager = _manager(old)
        await manager.replace_channel(new)
        assert manager.channels == [new]
        old.stop.assert_awaited_once()
        new.start.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_add_when_channel_absent(self):
        existing = _make_channel("qq")
        new = _make_channel("telegram")
        manager = _manager(existing)
        await manager.replace_channel(new)
        assert manager.channels == [existing, new]
        new.start.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_start_failure_stops_new_and_raises(self):
        new = _make_channel("dingtalk")
        new.start.side_effect = RuntimeError("connect failed")
        manager = _manager()
        with pytest.raises(RuntimeError, match="connect failed"):
            await manager.replace_channel(new)
        new.stop.assert_awaited_once()
        assert manager.channels == []

    @pytest.mark.asyncio
    async def test_start_failure_with_stop_failure_still_raises(self):
        new = _make_channel("dingtalk")
        new.start.side_effect = RuntimeError("connect failed")
        new.stop.side_effect = RuntimeError("stop also failed")
        manager = _manager()
        with pytest.raises(RuntimeError, match="connect failed"):
            await manager.replace_channel(new)

    @pytest.mark.asyncio
    async def test_old_stop_failure_is_swallowed(self):
        old = _make_channel("dingtalk")
        old.stop.side_effect = RuntimeError("old stop failed")
        new = _make_channel("dingtalk")
        manager = _manager(old)
        await manager.replace_channel(new)  # must not raise
        assert manager.channels == [new]

    @pytest.mark.asyncio
    async def test_old_cancelled_error_is_swallowed(self):
        old = _make_channel("dingtalk")
        old.stop.side_effect = asyncio.CancelledError()
        new = _make_channel("dingtalk")
        manager = _manager(old)
        await manager.replace_channel(new)
        assert manager.channels == [new]

    @pytest.mark.asyncio
    async def test_enqueue_cb_set_before_start(self):
        new = _make_channel("dingtalk")
        manager = _manager()
        await manager.replace_channel(new)
        new.set_enqueue.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_enqueue_cb_for_non_queue_channel(self):
        new = _make_channel("console", uses_queue=False)
        manager = _manager()
        await manager.replace_channel(new)
        new.set_enqueue.assert_not_called()


# ---------------------------------------------------------------------------
# restart_channel error paths
# ---------------------------------------------------------------------------


class TestRestartChannelErrors:
    @pytest.mark.asyncio
    async def test_unknown_channel_raises_keyerror(self):
        manager = _manager(_make_channel("qq"))
        with pytest.raises(KeyError, match="Channel not found"):
            await manager.restart_channel("ghost")

    @pytest.mark.asyncio
    async def test_restart_without_workspace_raises(self):
        channel = _make_channel("qq")
        manager = _manager(channel)
        manager._workspace = None
        with pytest.raises(RuntimeError, match="workspace not set"):
            await manager.restart_channel("qq")


# ---------------------------------------------------------------------------
# stop_all
# ---------------------------------------------------------------------------


class TestStopAll:
    @pytest.mark.asyncio
    async def test_stops_all_channels(self):
        a = _make_channel("qq")
        b = _make_channel("telegram")
        manager = _manager(a, b)
        await manager.stop_all()
        a.stop.assert_awaited_once()
        b.stop.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cancels_start_tasks(self):
        manager = _manager()

        async def sleeper():
            await asyncio.sleep(10)

        loop = asyncio.get_running_loop()
        task = loop.create_task(sleeper())
        manager._start_tasks.add(task)
        await manager.stop_all()
        assert task.cancelled()
        assert manager._start_tasks == set()

    @pytest.mark.asyncio
    async def test_empty_manager_no_error(self):
        manager = _manager()
        await manager.stop_all()  # must not raise

    @pytest.mark.asyncio
    async def test_channel_stop_failure_does_not_block_others(self):
        a = _make_channel("qq")
        a.stop.side_effect = RuntimeError("stop failed")
        b = _make_channel("telegram")
        manager = _manager(a, b)
        await manager.stop_all()  # must not raise
        b.stop.assert_awaited_once()
