# -*- coding: utf-8 -*-
"""The pluggable context-manager interface.

A ``ContextManager`` is an injectable strategy that owns an agent's context
management. :class:`~qwenpaw.agents.react_agent.QwenPawAgent` delegates its
AgentScope hooks and provider-overflow recovery to it:

* ``_save_to_context`` -> :meth:`on_save` (after the base append)
* ``_compress_context_impl`` -> :meth:`compress`
  (instead of native compression)
* overflow retry -> :meth:`recover_from_context_overflow`

When no manager is injected, the agent keeps its native AgentScope behavior —
so a strategy is purely additive and fully opt-in.
"""
from __future__ import annotations

from typing import Any, Protocol, Sequence, runtime_checkable


@runtime_checkable
class ContextManager(Protocol):
    """Strategy that drives an agent's context management."""

    async def recover_from_context_overflow(self, agent: Any) -> bool:
        """Try to shorten an input rejected by the model provider.

        Return ``True`` only when recovery changed the model input enough to
        justify rebuilding it and retrying the provider request once.
        """

    async def compress(
        self,
        agent: Any,
        context_config: Any = None,
        instructions: Any = None,
    ) -> None:
        """Compress ``agent.state.context`` when it exceeds the threshold.

        Called from ``QwenPawAgent._compress_context_impl`` after AgentScope's
        compression middleware chain. ``instructions`` is optional, one-shot
        guidance for a manual compaction and must not be persisted as active
        conversation state.
        """

    def on_save(self, agent: Any, blocks: Sequence[Any]) -> None:
        """React to blocks just appended to ``agent.state.context``.

        Called from ``QwenPawAgent._save_to_context`` after the base append,
        so the manager can write them through to durable storage.
        """
