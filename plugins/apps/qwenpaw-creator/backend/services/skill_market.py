# -*- coding: utf-8 -*-
"""Market search adapter for Creator skills.

Reuses the host QwenPaw market infrastructure (``qwenpaw.market.service``)
so that Creator's skill browser sees the same providers and results as the
main console's market page. Only reading/searching is delegated; install
still flows through ``services.skill_hub``, so the single-SKILL.md-only
rule stays enforced.

Every host symbol is reached through ``qwenpaw.market.service``, the one
module every release line ships; provider availability comes from
``list_providers`` rather than the host's provider registry, which does not
exist on all lines.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_MAX_MARKET_LIMIT = 20
_DEFAULT_PAGE = 1


@dataclass(frozen=True)
class MarketSkillResult:
    source: str
    source_label: str | None
    slug: str
    name: str
    description: str | None
    source_url: str
    version: str | None
    author: str | None
    icon_url: str | None
    stats: dict[str, str | int] | None


@dataclass(frozen=True)
class MarketProviderInfo:
    key: str
    label: str
    available: bool
    reason: str | None
    supports_browse: bool


class MarketUnavailable(RuntimeError):
    """The running QwenPaw build exposes no market search capability."""


def _resolve_market_service():
    try:
        from qwenpaw.market.service import (  # pylint: disable=import-outside-toplevel
            list_providers,
            search_market,
        )
    except Exception as exc:  # noqa: BLE001 - host layout, not our bug
        logger.warning("market service unavailable: %s", exc)
        raise MarketUnavailable(
            "当前 QwenPaw 运行时未提供技能市场搜索能力，" "请改用 URL 导入或手动创建技能",
        ) from exc
    return list_providers, search_market


async def search_skills(
    query: str = "",
    page: int = _DEFAULT_PAGE,
    limit: int = _MAX_MARKET_LIMIT,
    lang: str = "en",
) -> tuple[list[MarketSkillResult], bool, dict[str, int]]:
    """Search skill market providers; returns results, has_more, totals."""
    list_providers_fn, search_market_fn = _resolve_market_service()
    capped_limit = max(
        1,
        min(int(limit or _MAX_MARKET_LIMIT), _MAX_MARKET_LIMIT),
    )
    page_num = max(1, int(page or _DEFAULT_PAGE))

    # Build provider_pages for every browsable provider so the user sees
    # results from all markets in one call.  ``list_providers`` is the host's
    # own view of availability and browse support, which keeps Creator free
    # of the host's provider-registry layout (absent on some release lines).
    # Availability can read the environment and import optional backends, so
    # it runs off the event loop exactly like the /market/providers route.
    discovered = await asyncio.to_thread(list_providers_fn)
    provider_pages: dict[str, int] = {
        info.key: page_num
        for info in discovered
        if info.available and info.supports_browse
    }

    results, errors, by_provider = await search_market_fn(
        query=query,
        provider_pages=provider_pages,
        limit=capped_limit,
        lang=lang,
    )
    for err in errors:
        logger.warning(
            "market provider %s failed: %s",
            err.provider,
            err.message,
        )

    converted = [
        MarketSkillResult(
            source=r.source,
            source_label=getattr(r, "source_label", None),
            slug=r.slug,
            name=r.name,
            description=r.description,
            source_url=r.source_url,
            version=r.version,
            author=r.author,
            icon_url=r.icon_url,
            stats=dict(r.stats) if r.stats else None,
        )
        for r in results
    ]

    has_more = any(has for has, _total in by_provider.values())
    totals: dict[str, int] = {
        key: total for key, (_has, total) in by_provider.items()
    }
    return converted, has_more, totals


def list_market_providers() -> list[MarketProviderInfo]:
    """List registered market providers and their status."""
    list_providers_fn, _ = _resolve_market_service()
    raw = list_providers_fn()
    return [
        MarketProviderInfo(
            key=p.key,
            label=p.label,
            available=p.available,
            reason=p.reason,
            supports_browse=p.supports_browse,
        )
        for p in raw
    ]


__all__ = [
    "MarketProviderInfo",
    "MarketSkillResult",
    "MarketUnavailable",
    "list_market_providers",
    "search_skills",
]
