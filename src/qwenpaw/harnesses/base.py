# -*- coding: utf-8 -*-
"""Common third-party agent adapter contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from .events import (
    HarnessAttachment,
    HarnessEvent,
    HarnessEventKind,
    HarnessHistoryItem,
    HarnessModel,
    HarnessProvider,
)


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

    async def models(self) -> list[HarnessModel]:
        """Return models available to the authenticated account."""
        return []

    async def history(self, session_id: str) -> list[HarnessHistoryItem]:
        """Return provider history for best-effort session recovery."""
        del session_id
        return []

    async def run_command(
        self,
        *,
        session_id: str,
        command: str,
        arguments: str,
        cwd: Path,
        settings: dict[str, Any],
    ) -> list[HarnessEvent]:
        """Run one provider-owned slash command."""
        del session_id, command, arguments, cwd, settings
        return [
            HarnessEvent(
                kind=HarnessEventKind.ERROR,
                text="This command is not supported by the backend.",
            ),
        ]

    async def reset_session(self, session_id: str) -> None:
        """Forget provider state associated with one QwenPaw session."""
        del session_id

    @abstractmethod
    def run_turn(
        self,
        *,
        session_id: str,
        prompt: str,
        cwd: Path,
        settings: dict[str, Any],
        attachments: list[HarnessAttachment] | None = None,
    ) -> AsyncIterator[HarnessEvent]:
        """Run one turn and stream normalized events."""

    @abstractmethod
    async def stop(self) -> None:
        """Release provider processes and other resources."""


__all__ = ["HarnessAdapter"]
