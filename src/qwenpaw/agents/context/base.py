# -*- coding: utf-8 -*-
"""The pluggable context-manager interface.

A ``ContextManager`` is an injectable strategy that owns an agent's context
management. :class:`~qwenpaw.agents.react_agent.QwenPawAgent` delegates its two
AgentScope hooks to it:

* ``_save_to_context`` -> :meth:`on_save` (after the base append)
* ``compress_context`` -> :meth:`compress` (instead of the base compression)

When no manager is injected, the agent keeps its native AgentScope behavior —
so a strategy is purely additive and fully opt-in.
"""
from __future__ import annotations

from typing import Any, Protocol, Sequence, runtime_checkable


@runtime_checkable
class ContextManager(Protocol):
    """Strategy that drives an agent's context management."""

    async def compress(self, agent: Any, context_config: Any = None) -> None:
        """Compress ``agent.state.context`` when it exceeds the threshold.

        Called from ``QwenPawAgent.compress_context`` in place of the native
        AgentScope compression.
        """

    def on_save(self, agent: Any, blocks: Sequence[Any]) -> None:
        """React to blocks just appended to ``agent.state.context``.

        Called from ``QwenPawAgent._save_to_context`` after the base append,
        so the manager can write them through to durable storage.
        """
