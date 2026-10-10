# -*- coding: utf-8 -*-
"""User-callable capabilities exposed by memory backends."""

from dataclasses import dataclass
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


@dataclass
class MemoryActionResponse:
    """Backend-independent response for host-managed memory actions."""

    success: bool
    answer: Any = None
    metadata: dict[str, Any] | None = None


@runtime_checkable
class MemoryActionProvider(Protocol):
    """Contract for backends that expose callable memory actions."""

    async def list_actions(self) -> dict[str, MemoryActionSpec]:
        """Return the actions currently available to callers."""

    async def run_action(
        self,
        action: str,
        **kwargs: Any,
    ) -> MemoryActionResult | None:
        """Validate and execute an available action."""
