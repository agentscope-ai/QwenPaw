# -*- coding: utf-8 -*-
"""Order adapter for gates in declarative loop modes."""
from __future__ import annotations

from typing import Any

from .base import StopGate, StopHandlerResult


class ConfiguredGate(StopGate):
    """Bind one built-in gate to user-defined identity and order."""

    def __init__(
        self,
        *,
        instance_id: str,
        order: int,
        gate: StopGate,
    ) -> None:
        self._instance_id = instance_id
        self._order = order
        self._gate = gate

    @property
    def name(self) -> str:
        return self._instance_id

    @property
    def priority(self) -> int:
        return self._order

    async def check(self, ctx: Any) -> StopHandlerResult | None:
        """Delegate evaluation to the configured gate."""
        return await self._gate.check(ctx)

    def build_continuation(self) -> str:
        """Delegate continuation construction."""
        return self._gate.build_continuation()

    def reset_turn(self) -> None:
        """Delegate turn reset."""
        self._gate.reset_turn()

    def reset_session(self) -> None:
        """Delegate session reset."""
        self._gate.reset_session()


__all__ = ["ConfiguredGate"]
