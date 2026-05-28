# -*- coding: utf-8 -*-
"""Shims for the agentscope 1.x memory layer (``InMemoryMemory``, ``_MemoryMark``).

In agentscope 2.0 the memory abstraction was folded into
:class:`agentscope.state.AgentState` (the agent's ``state.context``).  The
old standalone :class:`agentscope.memory.InMemoryMemory` class — a list of
``(Msg, marks)`` tuples with ``add`` / ``state_dict`` / ``load_state_dict``
methods — is gone, as is the private ``_MemoryMark`` enum used to tag
hint / compressed messages.

qwenpaw's :class:`~qwenpaw.agents.context.agent_context.AgentContext`
subclasses the old ``InMemoryMemory`` and relies on the tuple-list
``self.content`` plus mark filtering.  Until ``AgentContext`` is rewritten
on top of ``AgentState``, this module provides a faithful stand-in.

TODO(as2-migration): delete once ``AgentContext`` no longer inherits from
``InMemoryMemory`` and the ``marks=`` API is dropped from call sites.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Iterable, List, Tuple

try:
    from agentscope.message import Msg
except ImportError:  # pragma: no cover - keeps the shim importable in isolation
    Msg = Any  # type: ignore[assignment, misc]


class _MemoryMark(str, Enum):
    """Tags qwenpaw stores alongside each message in :class:`InMemoryMemory`.

    Values come from the 1.x runtime; we keep them as strings so any
    serialized session that round-tripped through this enum keeps parsing.
    """

    HINT = "hint"
    COMPRESSED = "compressed"


class InMemoryMemory:  # pragma: no cover - migration stub
    """Tuple-list memory store mirroring the 1.x agentscope API.

    Exposes:

    * ``self.content`` — ``list[tuple[Msg, list[_MemoryMark]]]``
    * ``self._compressed_summary`` — running summary string
    * async ``add(msg | iterable, marks=...)``, ``clear()``
    * ``state_dict()`` / ``load_state_dict()`` — used by the JSON session
      store; ``AgentContext`` overrides both with richer behavior so the
      base implementations only need to be self-consistent.
    """

    def __init__(self) -> None:
        self.content: List[Tuple[Any, List[_MemoryMark]]] = []
        self._compressed_summary: str = ""

    async def add(
        self,
        messages: Any,
        marks: Iterable[_MemoryMark] | _MemoryMark | None = None,
    ) -> None:
        """Append one or many messages with optional marks."""
        if marks is None:
            mark_list: List[_MemoryMark] = []
        elif isinstance(marks, _MemoryMark):
            mark_list = [marks]
        else:
            mark_list = list(marks)

        if isinstance(messages, (list, tuple)):
            for msg in messages:
                self.content.append((msg, list(mark_list)))
        else:
            self.content.append((messages, list(mark_list)))

    async def get_memory(self, **_kwargs: Any) -> list:
        """Return all stored messages (marks dropped).

        Subclasses (``AgentContext``) override this to filter by marks.
        """
        return [msg for msg, _ in self.content]

    async def clear(self) -> None:
        self.content.clear()

    def state_dict(self) -> dict:
        """Serialize the content list and compressed summary."""
        return {
            "content": [
                [
                    msg.to_dict() if hasattr(msg, "to_dict") else msg,
                    [m.value if isinstance(m, _MemoryMark) else m for m in marks],
                ]
                for msg, marks in self.content
            ],
            "_compressed_summary": self._compressed_summary,
        }

    def load_state_dict(  # noqa: D401 - mirrors agentscope 1.x signature
        self,
        state_dict: dict,
        strict: bool = True,
    ) -> None:
        """Restore ``content`` and ``_compressed_summary`` from a dict."""
        if strict and "content" not in state_dict:
            raise KeyError(
                "state_dict missing 'content' key required for InMemoryMemory.",
            )

        from .message import msg_from_dict

        self.content = []
        for item in state_dict.get("content", []):
            if isinstance(item, (tuple, list)) and len(item) == 2:
                msg_payload, marks = item
                msg = (
                    msg_from_dict(msg_payload)
                    if isinstance(msg_payload, dict)
                    else msg_payload
                )
                self.content.append((msg, list(marks)))
            else:
                msg = msg_from_dict(item) if isinstance(item, dict) else item
                self.content.append((msg, []))

        self._compressed_summary = state_dict.get("_compressed_summary", "")
