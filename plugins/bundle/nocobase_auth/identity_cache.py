# -*- coding: utf-8 -*-
"""Short-TTL cache mapping a NocoBase user token to a resolved identity."""
from __future__ import annotations

import time
from typing import Callable, Dict, Optional, Tuple


class TokenIdentityCache:
    """Cache ``token -> sender_id`` with a short TTL and lazy expiry.

    A cached value of ``None`` is a *negative* entry (token was definitively
    invalid), distinct from a miss. ``time_fn`` is injectable for tests.
    """

    def __init__(
        self,
        ttl_seconds: float = 60.0,
        time_fn: Callable[[], float] = time.time,
    ) -> None:
        self._ttl = ttl_seconds
        self._time = time_fn
        self._entries: Dict[str, Tuple[Optional[str], float]] = {}

    def get(self, token: str) -> Tuple[bool, Optional[str]]:
        """Return ``(hit, value)``; ``hit`` is False on miss or expiry."""
        entry = self._entries.get(token)
        if entry is None:
            return (False, None)
        value, expires_at = entry
        if self._time() >= expires_at:
            self._entries.pop(token, None)
            return (False, None)
        return (True, value)

    def put(self, token: str, value: Optional[str]) -> None:
        """Cache ``value`` (an identity, or ``None`` for a negative entry)."""
        self._entries[token] = (value, self._time() + self._ttl)
