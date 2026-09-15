# -*- coding: utf-8 -*-
"""ClawHub market provider.

Two upstream endpoints via hub's shared async client:

    GET /api/v1/search?q=&limit=          keyword search (no stats)
    GET /api/v1/trending?kind=skills&limit=&cursor=  owner-qualified browse

"""

from __future__ import annotations

from urllib.parse import unquote, urljoin, urlparse

from ...agents.skill_system.hub import http_json_get, search_hub_skills
from ..schema import MarketResult
from .base import MARKET_SEARCH_TIMEOUT_S


_HOMEPAGE = "https://clawhub.ai"
_BROWSE_PATH = "/api/v1/trending"
_BROWSE_LIMIT = 100

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
                    slug=_skill_reference(source_url) or slug,
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
        page_size = max(1, int(limit))
        start = (target_page - 1) * page_size
        end = start + page_size
        cursor: str | None = None
        results: dict[str, MarketResult] = {}
        # Replay upstream cursors for the numbered market page. Filter before
        # slicing: Trending mixes ClawHub and skills.sh in the same snapshot.
        for _ in range(_MAX_PAGE_WALK):
            params: dict[str, str | int] = {
                "limit": _BROWSE_LIMIT,
                "kind": "skills",
            }
            if cursor:
                params["cursor"] = cursor
            body = await http_json_get(
                f"{_HOMEPAGE}{_BROWSE_PATH}",
                params=params,
                timeout=MARKET_SEARCH_TIMEOUT_S,
            )
            items = body.get("items") if isinstance(body, dict) else None
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict):
                        converted = _browse_to_result(item)
                        if converted is not None:
                            results.setdefault(converted.slug, converted)
            raw_cursor = (
                body.get("nextCursor") if isinstance(body, dict) else None
            )
            cursor = raw_cursor if isinstance(raw_cursor, str) else None
            if len(results) > end or not cursor:
                break
        else:
            raise RuntimeError("ClawHub Trending pagination limit exceeded")
        # The upstream total includes skills.sh and is not our filtered total.
        return list(results.values())[start:end], len(results) > end, None


def _browse_to_result(item: dict[str, object]) -> MarketResult | None:
    if item.get("source") != "clawhub":
        return None
    source_url = urljoin(_HOMEPAGE, _str(item.get("canonicalUrl")))
    reference = _skill_reference(source_url)
    if not reference:
        return None
    stats: dict[str, str | int] = {}
    metrics = item.get("metrics")
    if isinstance(metrics, dict):
        # Trending downloads cover the last 24 hours; installs are lifetime.
        for stat_key, metric_key in (
            ("downloads", "trending24hDownloads"),
            ("installs", "lifetimeInstalls"),
        ):
            value = metrics.get(metric_key)
            if isinstance(value, int) and not isinstance(value, bool):
                stats[stat_key] = value
    publisher = item.get("publisher")
    publisher = publisher if isinstance(publisher, dict) else {}
    return MarketResult(
        source="clawhub",
        slug=reference,
        name=_str(item.get("displayName")) or _str(item.get("slug")),
        description=_str(item.get("summary")) or None,
        source_url=source_url,
        # Trending carries no version; the installer resolves latest by owner.
        version=None,
        author=_str(publisher.get("displayName"))
        or _str(publisher.get("handle"))
        or reference.split("/", 1)[0],
        icon_url=_str(publisher.get("image")) or None,
        stats=stats or None,
    )


def _skill_reference(source_url: str) -> str:
    """Use owner/slug as the market identity without changing display names."""
    parsed = urlparse(source_url)
    if parsed.hostname not in {"clawhub.ai", "www.clawhub.ai"}:
        return ""
    parts = [unquote(part) for part in parsed.path.split("/") if part]
    if len(parts) == 3 and parts[1] == "skills":
        return f"{parts[0]}/{parts[2]}"
    if len(parts) == 2 and parts[0] != "skills":
        return "/".join(parts)
    return ""


def _str(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    return ""


provider = ClawHubProvider()
