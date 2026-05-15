# -*- coding: utf-8 -*-
"""Synthetic module injectors for CloudPaw plugin."""

import logging
import sys

logger = logging.getLogger(__name__)


def inject_interaction_module() -> None:
    """Inject the interaction module into the qwenpaw.app namespace."""
    import types
    import asyncio

    module_name = "qwenpaw.app.interaction"
    if module_name in sys.modules:
        return

    mod = types.ModuleType(module_name)
    mod.__package__ = "qwenpaw.app"

    class _PendingInteraction:
        __slots__ = ("event", "result")

        def __init__(self):
            self.event = asyncio.Event()
            self.result = None

    class InteractionManager:
        _pending: dict = {}

        @classmethod
        def create(cls, session_id: str):
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

    mod.InteractionManager = InteractionManager
    # pylint: disable-next=protected-access
    mod._PendingInteraction = _PendingInteraction
    sys.modules[module_name] = mod
    logger.info("Injected synthetic module: %s", module_name)
