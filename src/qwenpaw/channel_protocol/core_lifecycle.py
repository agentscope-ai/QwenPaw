# -*- coding: utf-8 -*-
"""Immutable authorization snapshots for shared Channel endpoint routing."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CoreSlotSnapshot:
    """Immutable Core view of one active or candidate generation."""

    generation: int
    epoch: int
    phase: str
    capabilities: frozenset[str]
    lease_token: str | None = None
    lease_expires_at_ms: int | None = None


@dataclass(frozen=True)
class CoreAuthorizationSnapshot:
    """Immutable route authorization published by the Core authority."""

    active: CoreSlotSnapshot | None = None
    candidate: CoreSlotSnapshot | None = None
    highest_generation: int = -1
    fenced_generation: int | None = None


__all__ = ["CoreAuthorizationSnapshot", "CoreSlotSnapshot"]
