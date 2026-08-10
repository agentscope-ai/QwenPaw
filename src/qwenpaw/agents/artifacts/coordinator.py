# -*- coding: utf-8 -*-
"""Coordinate artifact attribution without serializing complete turns."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .models import ArtifactRoot


@dataclass(slots=True, eq=False)
class ArtifactTurnHandle:
    """Track overlap state for one active artifact turn."""

    turn_id: str
    roots: tuple[Path, ...]
    overlapped: bool = False
    active: bool = True


def _roots_overlap(first: Path, second: Path) -> bool:
    """Return whether two canonical roots contain shared paths."""
    return (
        first == second
        or first.is_relative_to(second)
        or second.is_relative_to(first)
    )


class ArtifactCoordinator:
    """Track overlapping turns while allowing their work to run in parallel."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._active: set[ArtifactTurnHandle] = set()

    async def begin(
        self,
        turn_id: str,
        roots: Mapping[ArtifactRoot, Path],
    ) -> ArtifactTurnHandle:
        """Register a turn and mark all intersecting turns ambiguous."""
        handle = ArtifactTurnHandle(
            turn_id=turn_id,
            roots=tuple(path.resolve() for path in roots.values()),
        )
        async with self._lock:
            for current in self._active:
                if any(
                    _roots_overlap(first, second)
                    for first in handle.roots
                    for second in current.roots
                ):
                    handle.overlapped = True
                    current.overlapped = True
            self._active.add(handle)
        return handle

    async def finish(self, handle: ArtifactTurnHandle | None) -> None:
        """Remove a turn from overlap tracking exactly once."""
        if handle is None or not handle.active:
            return
        async with self._lock:
            self._active.discard(handle)
            handle.active = False


__all__ = ["ArtifactCoordinator", "ArtifactTurnHandle"]
