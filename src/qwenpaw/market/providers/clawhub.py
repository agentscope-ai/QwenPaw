# -*- coding: utf-8 -*-
"""ClawHub market provider.

Flat /search endpoint via hub's shared async client:

    GET https://clawhub.ai/api/v1/search?q=&limit=    (no paging)

"""

from __future__ import annotations

from ...agents.skill_system.hub import search_hub_skills
from ..schema import MarketResult
from .base import MARKET_SEARCH_TIMEOUT_S


_HOMEPAGE = "https://clawhub.ai"

# The per-request ceiling we send to upstream.
_OVERFETCH_LIMIT = 500


class ClawHubProvider:
    key = "clawhub"
    label = "ClawHub"
    # Upstream only exposes /search; an empty query returns nothing, so
    # there is no browse listing. The UI prompts the user to search.
    supports_browse = False

    def available(self) -> tuple[bool, str | None]:
        return True, None

    async def search(
        self,
        query: str,
        limit: int,
        page: int,
    ) -> tuple[list[MarketResult], bool, int | None]:
        raw = await search_hub_skills(
            query,
            limit=_OVERFETCH_LIMIT,
            timeout=MARKET_SEARCH_TIMEOUT_S,
        )
        all_results: list[MarketResult] = []
        for item in raw:
            slug = (item.slug or "").strip()
            if not slug:
                continue
            source_url = item.source_url or f"{_HOMEPAGE}/{slug}"
            all_results.append(
                MarketResult(
                    source=self.key,
                    slug=slug,
                    name=item.name or slug,
                    description=item.description or None,
                    source_url=source_url,
                    version=item.version or None,
                    author=item.author or None,
                    icon_url=item.icon_url or None,
                ),
            )
        start = (page - 1) * limit
        end = start + limit
        total = len(all_results)
        return all_results[start:end], end < total, total


provider = ClawHubProvider()
