# -*- coding: utf-8 -*-
"""The transport interface shared by all TUI back-ends."""

from __future__ import annotations

from typing import AsyncIterator, Protocol, runtime_checkable

from ..events import Connected, SessionSummary, TuiEvent


@runtime_checkable
class TuiTransport(Protocol):
    """Drives one agent conversation and yields normalized ``TuiEvent``s.

    Implementation: :class:`~qwenpaw.cli.tui.transport.acp.AcpTransport`
    (spawns ``qwenpaw acp``). The UI layer only ever sees this interface.
    """

    async def start(self) -> Connected:
        """Connect / spawn the agent and open a session."""

    async def send(self, text: str) -> None:
        """Send a user turn (plain text). Returns once the turn is queued."""

    async def interrupt(self) -> None:
        """Cancel the in-flight turn, if any."""

    async def list_sessions(self) -> list[SessionSummary]:
        """Return resumable past sessions (most recent first)."""

    async def load_session(self, session_id: str) -> None:
        """Switch to a past session and replay its saved transcript."""

    def events(self) -> AsyncIterator[TuiEvent]:
        """Yield events until the transport is closed."""

    async def resolve_permission(
        self,
        request_id: str,
        option_id: str | None,
    ) -> None:
        """Answer a pending permission request (``None`` = deny/cancel)."""

    async def close(self) -> None:
        """Tear down the session and any subprocess."""
