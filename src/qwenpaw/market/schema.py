# -*- coding: utf-8 -*-
"""Unified schemas for the skill market.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MarketResult:
    source: str
    slug: str
    name: str
    description: str | None
    source_url: str
    version: str | None
    author: str | None
    icon_url: str | None
    # Optional per-provider key→value pairs surfaced on the detail page
    # (e.g. downloads, likes, category, updated_at). Keys with known
    # labels are translated in the UI; unknown keys render as-is.
    stats: dict[str, str | int] | None = None


@dataclass(frozen=True)
class MarketSearchError:
    provider: str
    message: str


@dataclass(frozen=True)
class ProviderInfo:
    key: str
    label: str
    available: bool
    reason: str | None
