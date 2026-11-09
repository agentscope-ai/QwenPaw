# -*- coding: utf-8 -*-
"""Search and download contracts; the host validates and installs bundles."""

from dataclasses import dataclass, field
from typing import Callable, Awaitable

from .tools import ToolContext


@dataclass(frozen=True)
class MarketContext(ToolContext):
    market_id: str = ""


@dataclass(frozen=True)
class Availability:
    available: bool = True
    reason: str | None = None


@dataclass(frozen=True)
class MarketResult:
    slug: str
    name: str
    source_url: str
    description: str | None = None
    version: str | None = None
    author: str | None = None
    icon_url: str | None = None
    stats: dict[str, str | int] = field(default_factory=dict)


@dataclass(frozen=True)
class SearchPage:
    items: tuple[MarketResult, ...] = ()
    has_more: bool = False
    total: int | None = None


@dataclass(frozen=True)
class SkillBundle:
    name: str
    files: dict[str, str]
    resolved_url: str
    version: str = ""


@dataclass(frozen=True)
class MarketSpec:
    key: str
    label: str
    search: Callable[
        [MarketContext, str, int, int],
        SearchPage | Awaitable[SearchPage],
    ]
    fetch: Callable[
        [MarketContext, str, str],
        SkillBundle | Awaitable[SkillBundle],
    ]
    matches_url: Callable[[str], bool]
    available: Callable[[], Availability] = Availability
    supports_browse: bool = True
    priority: int = 100
