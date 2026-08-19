# -*- coding: utf-8 -*-
"""Short-lived routing capabilities for managed OAuth callbacks."""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass

_RELAY_TTL_SECONDS = 600


@dataclass(frozen=True)
class OAuthRelay:
    """Route one public OAuth callback to one managed runtime endpoint."""

    runtime_id: str
    callback_path: str
    expires_at: float


class OAuthRelayStore:
    """Keep one-time OAuth callback routes in control-plane memory."""

    def __init__(self) -> None:
        self._relays: dict[str, OAuthRelay] = {}

    def create(self, runtime_id: str, callback_path: str) -> str:
        """Create and return an opaque callback route token."""
        self._purge_expired()
        token = secrets.token_urlsafe(32)
        self._relays[token] = OAuthRelay(
            runtime_id=runtime_id,
            callback_path=callback_path,
            expires_at=time.monotonic() + _RELAY_TTL_SECONDS,
        )
        return token

    def take(self, token: str) -> OAuthRelay | None:
        """Consume a relay token if it is present and unexpired."""
        self._purge_expired()
        return self._relays.pop(token, None)

    def _purge_expired(self) -> None:
        now = time.monotonic()
        expired = [
            token
            for token, relay in self._relays.items()
            if relay.expires_at <= now
        ]
        for token in expired:
            del self._relays[token]
