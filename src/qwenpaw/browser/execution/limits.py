# -*- coding: utf-8 -*-
"""Bound active multi-user Browser workspace sessions."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass


@dataclass(slots=True)
class _Lease:
    user_id: str
    touched_at: float


class BrowserSessionLimiter:
    """Count active workspace leases globally and per actual user."""

    def __init__(
        self,
        *,
        global_limit: int,
        per_user_limit: int,
        idle_ttl: float,
    ) -> None:
        self._global_limit = max(1, global_limit)
        self._per_user_limit = max(1, per_user_limit)
        self._idle_ttl = idle_ttl
        self._leases: dict[str, _Lease] = {}
        self._condition = asyncio.Condition()

    def _prune(self, now: float) -> None:
        stale = [
            key
            for key, lease in self._leases.items()
            if now - lease.touched_at >= self._idle_ttl
        ]
        for key in stale:
            self._leases.pop(key, None)

    def _has_capacity(self, user_id: str) -> bool:
        user_count = sum(
            lease.user_id == user_id for lease in self._leases.values()
        )
        return (
            len(self._leases) < self._global_limit
            and user_count < self._per_user_limit
        )

    async def acquire(
        self,
        workspace_key: str,
        user_id: str,
        *,
        timeout: float,
    ) -> bool:
        async with self._condition:
            now = time.monotonic()
            self._prune(now)
            existing = self._leases.get(workspace_key)
            if existing is not None:
                if existing.user_id != user_id:
                    return False
                existing.touched_at = now
                return True

            async def wait_for_capacity() -> None:
                while not self._has_capacity(user_id):
                    await self._condition.wait()

            if not self._has_capacity(user_id):
                try:
                    await asyncio.wait_for(wait_for_capacity(), timeout)
                except TimeoutError:
                    self._prune(time.monotonic())
                    if not self._has_capacity(user_id):
                        return False
            self._leases[workspace_key] = _Lease(
                user_id=user_id,
                touched_at=time.monotonic(),
            )
            return True

    async def release(self, workspace_key: str) -> None:
        async with self._condition:
            if self._leases.pop(workspace_key, None) is not None:
                self._condition.notify_all()

    async def release_workspace(self, workspace_id: str) -> None:
        async with self._condition:
            prefix = f"{workspace_id}/"
            removed = False
            for key in [key for key in self._leases if key.startswith(prefix)]:
                self._leases.pop(key, None)
                removed = True
            if removed:
                self._condition.notify_all()
