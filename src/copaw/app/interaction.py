# -*- coding: utf-8 -*-
"""Interaction manager for interactive tool calls.

Coordinates async tool functions that need user input from the frontend.
Uses asyncio.Event for signaling between the tool coroutine and the
HTTP handler that receives the user's response.
"""

import asyncio
import contextvars
import logging
from typing import Optional

logger = logging.getLogger(__name__)

current_session_id: contextvars.ContextVar[
    Optional[str]
] = contextvars.ContextVar("copaw_interaction_session_id", default=None)


class _PendingInteraction:
    __slots__ = ("event", "result")

    def __init__(self) -> None:
        self.event = asyncio.Event()
        self.result: Optional[str] = None


class InteractionManager:
    """Manages pending interactive tool calls awaiting user responses."""

    _pending: dict[str, _PendingInteraction] = {}

    @classmethod
    def create(cls, session_id: str) -> _PendingInteraction:
        old = cls._pending.pop(session_id, None)
        if old is not None:
            old.event.set()
        interaction = _PendingInteraction()
        cls._pending[session_id] = interaction
        return interaction

    @classmethod
    def resolve(cls, session_id: str, result: str) -> bool:
        interaction = cls._pending.get(session_id)
        if interaction is None:
            return False
        interaction.result = result
        interaction.event.set()
        return True

    @classmethod
    def cleanup(cls, session_id: str) -> None:
        cls._pending.pop(session_id, None)
