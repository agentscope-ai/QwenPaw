# -*- coding: utf-8 -*-
"""Tests for StopHandler peer-gate reset on continuation."""
from __future__ import annotations

from typing import Any, Optional

import pytest

from qwenpaw.loop.gates.base import (
    StopAction,
    StopGate,
    StopHandlerResult,
)
from qwenpaw.loop.gates.handler import StopHandler


class _AlwaysContinueGate(StopGate):
    """Returns INTERRUPT_AND_CONTINUE with reset_peers."""

    def __init__(
        self,
        *,
        reset_peers: bool = False,
    ):
        self._reset_peers = reset_peers

    @property
    def name(self) -> str:
        return "always-continue"

    async def check(
        self,
        ctx: Any,
    ) -> Optional[StopHandlerResult]:
        return StopHandlerResult(
            action=StopAction.INTERRUPT_AND_CONTINUE,
            reason="test",
            reset_peers=self._reset_peers,
        )

    def build_continuation(self) -> str:
        return "keep going"


class _ResettableGate(StopGate):
    """Gate that tracks reset() calls."""

    def __init__(self, gate_name: str = "resettable"):
        self._name = gate_name
        self.reset_count = 0

    @property
    def name(self) -> str:
        return self._name

    async def check(
        self,
        ctx: Any,
    ) -> Optional[StopHandlerResult]:
        return None

    def reset(self) -> None:
        self.reset_count += 1


@pytest.mark.asyncio
async def test_reset_peers_true_resets_others():
    """CONTINUE with reset_peers=True resets other gates."""
    handler = StopHandler()
    trigger = _AlwaysContinueGate(reset_peers=True)
    peer = _ResettableGate("peer")
    handler.register(trigger)
    handler.register(peer)

    await handler({})
    assert peer.reset_count == 1


@pytest.mark.asyncio
async def test_reset_peers_true_skips_trigger():
    """The triggering gate itself is NOT reset."""
    handler = StopHandler()

    class _ContinueResettable(StopGate):
        def __init__(self):
            self.reset_count = 0

        @property
        def name(self):
            return "trigger"

        @property
        def priority(self):
            return 1

        async def check(self, ctx):
            return StopHandlerResult(
                action=StopAction.INTERRUPT_AND_CONTINUE,
                reason="test",
                reset_peers=True,
            )

        def build_continuation(self):
            return "go"

        def reset(self):
            self.reset_count += 1

    trigger = _ContinueResettable()
    handler.register(trigger)

    await handler({})
    assert trigger.reset_count == 0


@pytest.mark.asyncio
async def test_reset_peers_false_no_reset():
    """CONTINUE with reset_peers=False does NOT reset."""
    handler = StopHandler()
    trigger = _AlwaysContinueGate(reset_peers=False)
    peer = _ResettableGate("peer")
    handler.register(trigger)
    handler.register(peer)

    await handler({})
    assert peer.reset_count == 0


@pytest.mark.asyncio
async def test_multiple_peers_all_reset():
    """All peers (except trigger) are reset."""
    handler = StopHandler()
    trigger = _AlwaysContinueGate(reset_peers=True)
    p1 = _ResettableGate("p1")
    p2 = _ResettableGate("p2")
    handler.register(trigger)
    handler.register(p1)
    handler.register(p2)

    await handler({})
    assert p1.reset_count == 1
    assert p2.reset_count == 1


@pytest.mark.asyncio
async def test_gate_without_reset_method_skipped():
    """Gates without reset() are silently skipped."""
    handler = StopHandler()
    trigger = _AlwaysContinueGate(reset_peers=True)

    class _NoResetGate(StopGate):
        @property
        def name(self):
            return "no-reset"

        async def check(self, ctx):
            return None

    handler.register(trigger)
    handler.register(_NoResetGate())

    result = await handler({})
    assert result.action == StopAction.INTERRUPT_AND_CONTINUE
