# -*- coding: utf-8 -*-
"""In-memory registry for active ACP chat sessions."""
from __future__ import annotations

import asyncio

from .types import ACPConversationSession, utc_now


class ACPSessionStore:
    """Store active ACP runtime state keyed by chat and harness."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._sessions: dict[tuple[str, str], ACPConversationSession] = {}

    async def get(
        self,
        chat_id: str,
        harness: str,
    ) -> ACPConversationSession | None:
        async with self._lock:
            return self._sessions.get((chat_id, harness))

    async def save(self, session: ACPConversationSession) -> None:
        async with self._lock:
            session.updated_at = utc_now()
            self._sessions[(session.chat_id, session.harness)] = session

    async def delete(self, chat_id: str, harness: str) -> ACPConversationSession | None:
        async with self._lock:
            return self._sessions.pop((chat_id, harness), None)
