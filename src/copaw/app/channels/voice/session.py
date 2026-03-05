# -*- coding: utf-8 -*-
"""Call session management for the Voice channel."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .conversation_relay import ConversationRelayHandler

logger = logging.getLogger(__name__)


@dataclass
class CallSession:
    """One active or ended phone call."""

    call_sid: str
    from_number: str
    to_number: str
    started_at: datetime
    handler: ConversationRelayHandler
    status: str = "active"  # active | ended | failed


class CallSessionManager:
    """Registry of active call sessions."""

    def __init__(self) -> None:
        self._sessions: dict[str, CallSession] = {}

    def create_session(
        self,
        call_sid: str,
        handler: "ConversationRelayHandler",
        from_number: str = "",
        to_number: str = "",
    ) -> CallSession:
        session = CallSession(
            call_sid=call_sid,
            from_number=from_number,
            to_number=to_number,
            started_at=datetime.now(timezone.utc),
            handler=handler,
        )
        self._sessions[call_sid] = session
        logger.info(
            "Call session created: call_sid=%s from=%s",
            call_sid,
            from_number,
        )
        return session

    def get_session(self, call_sid: str) -> Optional[CallSession]:
        return self._sessions.get(call_sid)

    def end_session(self, call_sid: str) -> None:
        session = self._sessions.pop(call_sid, None)
        if session:
            session.status = "ended"
            logger.info("Call session ended: call_sid=%s", call_sid)

    def active_sessions(self) -> list[CallSession]:
        return [s for s in self._sessions.values() if s.status == "active"]

    def active_count(self) -> int:
        return sum(1 for s in self._sessions.values() if s.status == "active")

    def all_sessions(self) -> list[CallSession]:
        return list(self._sessions.values())
