# -*- coding: utf-8 -*-
"""Short-lived, one-time tickets for pairing trusted mobile clients."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Callable


PAIRING_TTL_SECONDS = 120
# Mobile bindings remain valid until their token is explicitly revoked.
MOBILE_TOKEN_EXPIRY_SECONDS = 0


@dataclass(frozen=True)
class PairingTicket:
    """Server-side ticket metadata without the redeemable secret."""

    secret_digest: str
    username: str
    expires_at: int


class PairingTicketStore:
    """Thread-safe, bounded in-memory store for one-time tickets."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.time,
        ttl_seconds: int = PAIRING_TTL_SECONDS,
    ) -> None:
        self._clock = clock
        self._ttl_seconds = ttl_seconds
        self._tickets: dict[str, PairingTicket] = {}
        self._lock = threading.Lock()

    def create(self, username: str) -> tuple[str, int]:
        """Create a redeemable ticket and return it with its expiry."""
        ticket_id = secrets.token_urlsafe(12)
        secret = secrets.token_urlsafe(32)
        expires_at = int(self._clock()) + self._ttl_seconds
        record = PairingTicket(
            secret_digest=self._digest(secret),
            username=username,
            expires_at=expires_at,
        )
        with self._lock:
            self._prune_locked()
            self._tickets[ticket_id] = record
        return f"{ticket_id}.{secret}", expires_at

    def redeem(self, ticket: str) -> str | None:
        """Consume a valid ticket and return its bound username."""
        try:
            ticket_id, secret = ticket.split(".", 1)
        except ValueError:
            return None
        if not ticket_id or not secret:
            return None
        with self._lock:
            self._prune_locked()
            record = self._tickets.get(ticket_id)
            if record is None:
                return None
            if not hmac.compare_digest(
                record.secret_digest,
                self._digest(secret),
            ):
                return None
            self._tickets.pop(ticket_id, None)
            return record.username

    def _prune_locked(self) -> None:
        now = int(self._clock())
        expired = [
            ticket_id
            for ticket_id, record in self._tickets.items()
            if record.expires_at <= now
        ]
        for ticket_id in expired:
            self._tickets.pop(ticket_id, None)

    @staticmethod
    def _digest(secret: str) -> str:
        return hashlib.sha256(secret.encode("utf-8")).hexdigest()


pairing_ticket_store = PairingTicketStore()
