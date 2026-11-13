# -*- coding: utf-8 -*-
"""Session ownership facts for a provider BrowserContext."""

from __future__ import annotations

from dataclasses import dataclass

from ..sdk.contracts import Owner


@dataclass
class Session:
    """One owner-scoped browser context and its currently active page."""

    owner: Owner
    variant: str
    context: str
    identity: str = "guest"
    page_id: str | None = None
    connected: bool = True
    headless: bool = False

    @property
    def session_id(self) -> str:
        """Expose the context key without duplicating owner identity."""
        return self.owner.session_id

    @property
    def workspace_id(self) -> str:
        """Expose the workspace process/profile key."""
        return self.owner.workspace_id

    def is_valid(self) -> bool:
        """Return whether the session remains connected and owner-scoped."""
        return self.connected and self.owner.is_valid()
