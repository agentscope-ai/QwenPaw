# -*- coding: utf-8 -*-
"""Common third-party agent adapter contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from .events import (
    HarnessAttachment,
    HarnessDiscoveredSkill,
    HarnessEvent,
    HarnessEventKind,
    HarnessHistoryItem,
    HarnessDiscoveredMCPServer,
    HarnessModel,
    HarnessProvider,
)


class HarnessOperationNotSupportedError(RuntimeError):
    """Raised when a provider cannot perform a requested operation."""


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

    async def discover_mcp(
        self,
        cwd: Path,
    ) -> list[HarnessDiscoveredMCPServer]:
        """Return read-only Provider-owned MCP configuration."""
        del cwd
        return []

    async def discover_skills(
        self,
        cwd: Path,
    ) -> list[HarnessDiscoveredSkill]:
        """Return read-only Provider-owned Skills."""
        del cwd
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


class MissingDependencyAdapter(HarnessAdapter):
    """Report an optional provider dependency without breaking startup."""

    def __init__(self, provider_id: str, provider_name: str) -> None:
        self._provider_id = provider_id
        self._provider_name = provider_name
        self._message = (
            f"Install qwenpaw[{provider_id}] to enable {provider_name}."
        )

    async def status(self) -> HarnessProvider:
        """Return an unavailable status with an actionable install hint."""
        return HarnessProvider(
            id=self._provider_id,
            name=self._provider_name,
            available=False,
            installed=False,
            error=self._message,
        )

    async def start_login(self, device_code: bool = False) -> dict[str, Any]:
        """Reject login until the provider dependency is installed."""
        del device_code
        raise RuntimeError(self._message)

    async def logout(self) -> None:
        """Reject logout until the provider dependency is installed."""
        raise RuntimeError(self._message)

    def run_turn(
        self,
        *,
        session_id: str,
        prompt: str,
        cwd: Path,
        settings: dict[str, Any],
        attachments: list[HarnessAttachment] | None = None,
    ) -> AsyncIterator[HarnessEvent]:
        """Reject turns until the provider dependency is installed."""
        del session_id, prompt, cwd, settings, attachments

        async def unavailable_events() -> AsyncIterator[HarnessEvent]:
            if self._message:
                raise RuntimeError(self._message)
            yield HarnessEvent(kind=HarnessEventKind.ERROR)

        return unavailable_events()

    async def stop(self) -> None:
        """Release no resources for an unavailable provider."""


__all__ = [
    "HarnessAdapter",
    "HarnessOperationNotSupportedError",
    "MissingDependencyAdapter",
]
