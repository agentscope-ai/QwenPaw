# -*- coding: utf-8 -*-
"""Optional user-callable actions exposed by a memory backend."""

from typing import Any, Protocol, TypedDict, runtime_checkable


class MemoryActionSpec(TypedDict):
    """Description and JSON Schema for one memory action."""

    description: str
    parameters: dict[str, Any]


class MemoryActionResult(Protocol):
    """Structural result returned by a memory action."""

    success: bool
    answer: Any
    metadata: dict[str, Any] | None


@runtime_checkable
class MemoryActionProvider(Protocol):
    """Optional capability for backends that expose callable actions."""

    async def list_actions(self) -> dict[str, MemoryActionSpec]:
        """Return the actions currently available to callers."""
        ...

    async def run_action(
        self,
        action: str,
        **kwargs: Any,
    ) -> MemoryActionResult | None:
        """Validate and execute an available action."""
        ...
