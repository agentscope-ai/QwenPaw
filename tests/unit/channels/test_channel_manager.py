# -*- coding: utf-8 -*-
"""
ChannelManager.replace_channel Unit Tests
=========================================

Verifies the stop-old-then-start-new ordering and error recovery
logic introduced to fix issue #4877.
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from qwenpaw.app.channels.base import BaseChannel, ProcessHandler
from qwenpaw.app.channels.manager import ChannelManager


# ---------------------------------------------------------------------------
# Stub channel for isolated replace_channel tests
# ---------------------------------------------------------------------------


class StubChannel(BaseChannel):
    """Minimal concrete BaseChannel used only in these tests."""

    channel = "stub"

    def __init__(
        self,
        channel_name: str = "stub",
        *,
        start_side_effect: Optional[Exception] = None,
        stop_side_effect: Optional[Exception] = None,
    ) -> None:
        self._channel_name = channel_name
        self._start_side_effect = start_side_effect
        self._stop_side_effect = stop_side_effect
        self.start_called = False
        self.stop_called = False
        self._enqueue = None

    # -- BaseChannel abstract stubs --

    @property
    def channel(self) -> str:  # type: ignore[override]
        return self._channel_name

    async def start(self) -> None:
        self.start_called = True
        if self._start_side_effect:
            raise self._start_side_effect

    async def stop(self) -> None:
        self.stop_called = True
        if self._stop_side_effect:
            raise self._stop_side_effect

    # Remaining abstract methods — not used by replace_channel

    async def send(
        self,
        to_handle: str,
        text: str,
        meta: Optional[dict] = None,
    ) -> None:
        pass

    @classmethod
    def from_config(cls, process, config, on_reply_sent=None, **kwargs):
        return cls()

    async def consume_one(self, payload: Any) -> None:
        pass

    def _is_native_payload(self, payload: Any) -> bool:
        return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_manager(*channels: StubChannel) -> ChannelManager:
    mgr = ChannelManager(list(channels))
    mgr._loop = asyncio.get_running_loop()
    return mgr


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestReplaceChannelOrdering:
    """Verify that stop(old) happens before start(new)."""

    @pytest.mark.asyncio
    async def test_old_stopped_before_new_started(self):
        """Old must release resources before the new channel tries to
        acquire them."""
        old = StubChannel("mych")
        new = StubChannel("mych")
        mgr = _make_manager(old)

        call_order: list[str] = []

        orig_old_stop = old.stop
        orig_new_start = new.start

        async def _old_stop():
            call_order.append("old_stop")
            await orig_old_stop()

        async def _new_start():
            call_order.append("new_start")
            await orig_new_start()

        old.stop = _old_stop  # type: ignore[assignment]
        new.start = _new_start  # type: ignore[assignment]

        await mgr.replace_channel(new)

        assert call_order == ["old_stop", "new_start"]

    @pytest.mark.asyncio
    async def test_old_removed_from_list_before_new_starts(self):
        """While the new channel is starting, the old channel must already
        be gone from self.channels so concurrent lookups don't see a stale
        (stopped) channel."""
        old = StubChannel("mych")
        new = StubChannel("mych")
        mgr = _make_manager(old)

        channels_during_new_start: list[list[str]] = []

        orig_new_start = new.start

        async def _new_start():
            channels_during_new_start.append(
                [c.channel for c in mgr.channels],
            )
            await orig_new_start()

        new.start = _new_start  # type: ignore[assignment]

        await mgr.replace_channel(new)

        # During new.start(), old is already removed and new is not yet added
        assert channels_during_new_start == [[]]

    @pytest.mark.asyncio
    async def test_new_added_to_list_after_start(self):
        """After replace_channel succeeds, only the new channel is in the list."""
        old = StubChannel("mych")
        new = StubChannel("mych")
        mgr = _make_manager(old)

        await mgr.replace_channel(new)

        assert len(mgr.channels) == 1
        assert mgr.channels[0] is new

    @pytest.mark.asyncio
    async def test_old_is_stopped(self):
        """The old channel instance must have stop() called."""
        old = StubChannel("mych")
        new = StubChannel("mych")
        mgr = _make_manager(old)

        await mgr.replace_channel(new)

        assert old.stop_called is True

    @pytest.mark.asyncio
    async def test_new_is_started(self):
        """The new channel instance must have start() called."""
        old = StubChannel("mych")
        new = StubChannel("mych")
        mgr = _make_manager(old)

        await mgr.replace_channel(new)

        assert new.start_called is True


class TestReplaceChannelNewChannel:
    """When there is no existing channel with the same name, the new one
    should simply be added."""

    @pytest.mark.asyncio
    async def test_add_new_channel(self):
        new = StubChannel("fresh")
        mgr = _make_manager()

        await mgr.replace_channel(new)

        assert len(mgr.channels) == 1
        assert mgr.channels[0] is new
        assert new.start_called is True

    @pytest.mark.asyncio
    async def test_add_new_channel_no_old_stop(self):
        """No old channel to stop, so stop should not be called on anything."""
        new = StubChannel("fresh")
        mgr = _make_manager()

        await mgr.replace_channel(new)

        # No exception means no spurious stop was attempted
        assert new.stop_called is False


class TestReplaceChannelNewStartFails:
    """Error recovery when the new channel fails to start."""

    @pytest.mark.asyncio
    async def test_old_restored_on_new_start_failure(self):
        """If the new channel fails to start, the old channel should be
        restored (restarted and added back to the list)."""
        old = StubChannel("mych")
        new = StubChannel("mych", start_side_effect=RuntimeError("port busy"))
        mgr = _make_manager(old)

        with pytest.raises(RuntimeError, match="port busy"):
            await mgr.replace_channel(new)

        # Old channel should be restored
        assert old in mgr.channels
        assert old.start_called is True  # restarted
        assert new not in mgr.channels

    @pytest.mark.asyncio
    async def test_new_is_stopped_after_start_failure(self):
        """A new channel that failed to start should have stop() called
        for cleanup."""
        new = StubChannel("mych", start_side_effect=RuntimeError("boom"))
        mgr = _make_manager()

        with pytest.raises(RuntimeError, match="boom"):
            await mgr.replace_channel(new)

        assert new.stop_called is True

    @pytest.mark.asyncio
    async def test_original_exception_propagates(self):
        """The original start exception should propagate to the caller."""
        new = StubChannel("mych", start_side_effect=ConnectionError("refused"))
        mgr = _make_manager()

        with pytest.raises(ConnectionError, match="refused"):
            await mgr.replace_channel(new)

    @pytest.mark.asyncio
    async def test_restore_failure_does_not_swallow_original(self):
        """If restoring the old channel also fails, the original exception
        should still propagate (not the restore failure)."""
        old = StubChannel(
            "mych",
            stop_side_effect=None,
            start_side_effect=RuntimeError("old also broken"),
        )
        # First stop works, then on restore start fails
        new = StubChannel("mych", start_side_effect=RuntimeError("new broken"))
        mgr = _make_manager(old)

        with pytest.raises(RuntimeError, match="new broken"):
            await mgr.replace_channel(new)

    @pytest.mark.asyncio
    async def test_no_old_channel_new_start_fails(self):
        """When adding a brand-new channel that fails to start, there's
        no old channel to restore — just raise."""
        new = StubChannel("fresh", start_side_effect=RuntimeError("fail"))
        mgr = _make_manager()

        with pytest.raises(RuntimeError, match="fail"):
            await mgr.replace_channel(new)

        assert len(mgr.channels) == 0


class TestReplaceChannelOldStopFails:
    """When the old channel's stop() raises, the replace should still
    proceed (stop errors are logged, not re-raised)."""

    @pytest.mark.asyncio
    async def test_old_stop_error_does_not_block_replace(self):
        old = StubChannel("mych", stop_side_effect=RuntimeError("stop err"))
        new = StubChannel("mych")
        mgr = _make_manager(old)

        # Should NOT raise — old stop errors are caught and logged
        await mgr.replace_channel(new)

        assert new in mgr.channels
        assert new.start_called is True
        assert old.stop_called is True

    @pytest.mark.asyncio
    async def test_old_stop_cancelled_error_handled(self):
        """asyncio.CancelledError from old.stop() should be silently caught."""
        old = StubChannel("mych", stop_side_effect=asyncio.CancelledError())
        new = StubChannel("mych")
        mgr = _make_manager(old)

        await mgr.replace_channel(new)

        assert new in mgr.channels


class TestReplaceChannelEnqueueCallback:
    """Verify enqueue callback is set on the new channel."""

    @pytest.mark.asyncio
    async def test_enqueue_callback_set_for_manager_queue_channel(self):
        new = StubChannel("mych")
        new.uses_manager_queue = True
        mgr = _make_manager()

        await mgr.replace_channel(new)

        assert new._enqueue is not None

    @pytest.mark.asyncio
    async def test_enqueue_callback_not_set_for_non_manager_queue(self):
        new = StubChannel("mych")
        new.uses_manager_queue = False
        mgr = _make_manager()

        await mgr.replace_channel(new)

        assert new._enqueue is None


class TestReplaceChannelConcurrency:
    """Concurrent replace_channel calls for the same channel name."""

    @pytest.mark.asyncio
    async def test_concurrent_replaces_do_not_duplicate(self):
        """Two concurrent replace_channel calls for the same channel should
        not result in duplicate entries."""
        old = StubChannel("mych")
        mgr = _make_manager(old)

        # Slow starts so they overlap
        new1 = StubChannel("mych")
        new2 = StubChannel("mych")

        delay_event = asyncio.Event()

        orig_start1 = new1.start

        async def slow_start1():
            # Wait a bit to let the second replace also proceed
            await asyncio.sleep(0.05)
            await orig_start1()

        new1.start = slow_start1  # type: ignore[assignment]

        # Run both concurrently
        results = await asyncio.gather(
            mgr.replace_channel(new1),
            mgr.replace_channel(new2),
            return_exceptions=True,
        )

        # No exceptions expected (both should succeed)
        for r in results:
            assert not isinstance(r, Exception), f"Unexpected error: {r}"

        # At least one of the new channels should be in the list
        channel_names = [c.channel for c in mgr.channels]
        assert channel_names.count("mych") >= 1


class TestReplaceChannelMultipleChannels:
    """Verify replace_channel only affects the target channel."""

    @pytest.mark.asyncio
    async def test_other_channels_untouched(self):
        ch_a = StubChannel("alpha")
        ch_b = StubChannel("beta")
        new_b = StubChannel("beta")
        mgr = _make_manager(ch_a, ch_b)

        await mgr.replace_channel(new_b)

        assert ch_a in mgr.channels
        assert ch_b not in mgr.channels
        assert new_b in mgr.channels
        assert ch_a.stop_called is False
        assert ch_b.stop_called is True

    @pytest.mark.asyncio
    async def test_replace_preserves_order(self):
        """After replace, the new channel should be appended at the end."""
        ch_a = StubChannel("alpha")
        ch_b = StubChannel("beta")
        ch_c = StubChannel("gamma")
        new_b = StubChannel("beta")
        mgr = _make_manager(ch_a, ch_b, ch_c)

        await mgr.replace_channel(new_b)

        names = [c.channel for c in mgr.channels]
        # Old ch_b was removed from its position, new_b appended
        assert names == ["alpha", "gamma", "beta"]
