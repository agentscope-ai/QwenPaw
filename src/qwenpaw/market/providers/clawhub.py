# -*- coding: utf-8 -*-
"""ClawHub market provider.

Two upstream endpoints via hub's shared async client:

    GET /api/v1/search?q=&limit=          keyword search (no stats)
    GET /api/v1/skills?limit=&cursor=&sort=  browse listing (carries
        stats: downloads / stars / installs)

"""

from __future__ import annotations

from ...agents.skill_system.hub import http_json_get, search_hub_skills
from ..schema import MarketResult
from .base import MARKET_SEARCH_TIMEOUT_S


_HOMEPAGE = "https://clawhub.ai"
_BROWSE_PATH = "/api/v1/skills"
_BROWSE_SORT = "recommended"

# The per-request ceiling we send to the keyword /search endpoint.
_OVERFETCH_LIMIT = 500
_MAX_PAGE_WALK = 50


class ClawHubProvider:
    key = "clawhub"
    label = "ClawHub"
    supports_browse = True

    def available(self) -> tuple[bool, str | None]:
        return True, None

    async def search(
        self,
        query: str,
        limit: int,
        page: int,
    ) -> tuple[list[MarketResult], bool, int | None]:
        needle = query.strip()
        if needle:
            return await self._search(needle, limit, page)
        return await self._browse(limit, page)

    async def _search(
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

    async def _browse(
        self,
        limit: int,
        page: int,
    ) -> tuple[list[MarketResult], bool, int | None]:
        target_page = max(1, int(page))
        if target_page > _MAX_PAGE_WALK:
            return [], False, None
        cursor: str | None = None
        page_items: list[dict[str, object]] = []
        next_cursor: str | None = None
        for current_page in range(1, target_page + 1):
            params: dict[str, str | int] = {
                "limit": max(1, int(limit)),
                "sort": _BROWSE_SORT,
            }
            if cursor:
                params["cursor"] = cursor
            body = await http_json_get(
                f"{_HOMEPAGE}{_BROWSE_PATH}",
                params=params,
                timeout=MARKET_SEARCH_TIMEOUT_S,
            )
            items = body.get("items") if isinstance(body, dict) else None
            page_items = (
                [i for i in items if isinstance(i, dict)]
                if isinstance(items, list)
                else []
            )
            raw_cursor = (
                body.get("nextCursor") if isinstance(body, dict) else None
            )
            next_cursor = raw_cursor if isinstance(raw_cursor, str) else None
            if current_page == target_page:
                break
            if not next_cursor:
                page_items = []
                break
            cursor = next_cursor
        results: list[MarketResult] = []
        for item in page_items:
            converted = _browse_to_result(item)
            if converted is not None:
                results.append(converted)
        # /skills has no total count; has_more rides on the cursor.
        return results, bool(next_cursor), None


def _browse_to_result(item: dict[str, object]) -> MarketResult | None:
    slug = _str(item.get("slug"))
    if not slug:
        return None
    stats: dict[str, str | int] = {}
    raw_stats = item.get("stats")
    if isinstance(raw_stats, dict):
        for stat_key in ("downloads", "stars", "installs"):
            value = raw_stats.get(stat_key)
            if isinstance(value, int) and not isinstance(value, bool):
                stats[stat_key] = value
    version = ""
    tags = item.get("tags")
    if isinstance(tags, dict):
        version = _str(tags.get("latest"))
    return MarketResult(
        source="clawhub",
        slug=slug,
        name=_str(item.get("displayName")) or slug,
        description=_str(item.get("summary"))
        or _str(item.get("description"))
        or None,
        source_url=f"{_HOMEPAGE}/{slug}",
        version=version or None,
        # /skills carries no owner or logo, so both stay null; the search
        # path supplies the owner avatar when a query is present.
        author=None,
        icon_url=None,
        stats=stats or None,
    )


def _str(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    return ""


provider = ClawHubProvider()
