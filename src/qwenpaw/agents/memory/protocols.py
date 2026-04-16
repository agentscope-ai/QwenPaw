# -*- coding: utf-8 -*-
"""Protocols for memory system components."""
from typing import Protocol, runtime_checkable


@runtime_checkable
class InMemoryMemoryProtocol(Protocol):
    """Protocol for the in-memory conversation memory object.

    This protocol decouples the agent from concrete memory implementations
    like ``ReMeInMemoryMemory``, allowing external backends to provide their
    own in-memory memory objects.
    """

    _long_term_memory: str

    def load_state_dict(self, state: dict, **kwargs) -> None:
        """Load state from a dictionary."""
        ...

    def get_compressed_summary(self) -> str | None:
        """Return the compressed summary of compacted messages."""
        ...

    async def get_memory(self, prepend_summary: bool = ...) -> list:
        """Return the list of messages in memory."""
        ...

    async def mark_messages_compressed(self, messages: list) -> int:
        """Mark messages as compressed and return the count."""
        ...

    async def update_compressed_summary(self, summary: str) -> None:
        """Update the compressed summary."""
        ...
