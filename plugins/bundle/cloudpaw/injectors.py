# -*- coding: utf-8 -*-
"""Synthetic module injectors for CloudPaw plugin."""

import logging
import sys

logger = logging.getLogger("qwenpaw").getChild(
    __name__.replace("plugin_cloudpaw.", ""),
)


def inject_interaction_module() -> None:
    """Inject the interaction module into the qwenpaw.app namespace."""
    import types
    import asyncio
    from uuid import uuid4

    module_name = "qwenpaw.app.interaction"
    if module_name in sys.modules:
        return

    mod = types.ModuleType(module_name)
    mod.__package__ = "qwenpaw.app"

    class _PendingInteraction:
        __slots__ = ("event", "result", "id", "names", "proposals")

        def __init__(self, names, proposals):
            self.event = asyncio.Event()
            self.result = None
            self.id = str(uuid4())
            self.names = names
            self.proposals = proposals

    class InteractionManager:
        _pending: dict = {}

        @staticmethod
        def _key(session_id):
            from qwenpaw.plugins.http_scope import runtime_plugin_scope
            return runtime_plugin_scope(), session_id

        @classmethod
        def create(cls, session_id: str, names=(), proposals=()):
            session_id = cls._key(session_id)
            old = cls._pending.pop(session_id, None)
            if old is not None:
                old.event.set()
            interaction = _PendingInteraction(names, proposals)
            cls._pending[session_id] = interaction
            return interaction

        @classmethod
        def pending(cls, session_id):
            return cls._pending.get(cls._key(session_id))

        @classmethod
        def resolve(cls, session_id: str, result: str, pending_id: str | None = None) -> bool:
            interaction = cls.pending(session_id)
            if interaction is None or interaction.event.is_set() or interaction.id != pending_id:
                return False
            interaction.result = result
            interaction.event.set()
            return True

        @classmethod
        def cleanup(cls, session_id: str, interaction) -> None:
            key = cls._key(session_id)
            if cls._pending.get(key) is interaction:
                cls._pending.pop(key, None)

    mod.InteractionManager = InteractionManager
    # pylint: disable-next=protected-access
    mod._PendingInteraction = _PendingInteraction
    sys.modules[module_name] = mod
    logger.info("Injected synthetic module: %s", module_name)
