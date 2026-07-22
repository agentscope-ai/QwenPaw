# -*- coding: utf-8 -*-
"""Common third-party agent adapter contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from .events import HarnessEvent, HarnessProvider


class HarnessAdapter(ABC):
    """Provider adapter used by the workspace harness runtime."""

    @abstractmethod
    async def status(self) -> HarnessProvider:
        """Return installation and authentication status."""

    @abstractmethod
    async def start_login(self, device_code: bool = False) -> dict[str, Any]:
        """Start a provider-owned login flow."""

    @abstractmethod
    async def logout(self) -> None:
        """Remove the provider-owned login."""

    @abstractmethod
    def run_turn(
        self,
        *,
        session_id: str,
        prompt: str,
        cwd: Path,
    ) -> AsyncIterator[HarnessEvent]:
        """Run one turn and stream normalized events."""

    @abstractmethod
    async def stop(self) -> None:
        """Release provider processes and other resources."""


__all__ = ["HarnessAdapter"]
