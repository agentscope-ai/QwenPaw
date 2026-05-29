# -*- coding: utf-8 -*-
"""ModelScope market provider.

Public OpenAPI (no auth required for GET) via hub's shared async client:

    GET https://www.modelscope.cn/openapi/v1/skills
        ?search=&page_number=&page_size=

"""

from __future__ import annotations

import urllib.parse

import httpx

from ...agents.skill_system.hub import http_json_get
from ..schema import MarketResult
from .base import MARKET_SEARCH_TIMEOUT_S


_BASE_URL = "https://www.modelscope.cn"
_SEARCH_PATH = "/openapi/v1/skills"
# Upstream hard limit: `page_size > 100` returns HTTP 400 with message
# "page_size should be between 1 and 100". Keep in sync with upstream.
_MAX_PAGE_SIZE = 100


class ModelScopeProvider:
    key = "modelscope"
    label = "ModelScope"

    def available(self) -> tuple[bool, str | None]:
        return True, None

    async def search(
        self,
        query: str,
        limit: int,
        page: int,
        lang: str = "en",
    ) -> tuple[list[MarketResult], bool, int | None]:
        url = f"{_BASE_URL}{_SEARCH_PATH}"
        page_size = max(1, min(int(limit), _MAX_PAGE_SIZE))
        params: dict[str, str | int] = {
            "page_size": page_size,
            "page_number": max(1, int(page)),
        }
        needle = query.strip()
        if needle:
            params["search"] = needle
        try:
            body = await http_json_get(
                url,
                params=params,
                timeout=MARKET_SEARCH_TIMEOUT_S,
            )
        except httpx.HTTPStatusError as e:
            raise RuntimeError(
                f"ModelScope search returned HTTP {e.response.status_code}",
            ) from e
        if not isinstance(body, dict) or not body.get("success", True):
            message = (
                body.get("message", "unknown error")
                if isinstance(body, dict)
                else "non-JSON response"
            )
            raise RuntimeError(f"ModelScope search failed: {message}")

        data = body.get("data") if isinstance(body, dict) else None
        items: list[dict[str, object]] = []
        upstream_total: int | None = None
        if isinstance(data, dict):
            if isinstance(data.get("skills"), list):
                items = [s for s in data["skills"] if isinstance(s, dict)]
            raw_total = data.get("total")
            if isinstance(raw_total, int) and raw_total >= 0:
                upstream_total = raw_total

        results: list[MarketResult] = []
        for item in items:
            converted = _to_market_result(item, lang)
            if converted is not None:
                results.append(converted)

        total = upstream_total if upstream_total is not None else len(results)
        has_more = page * page_size < total
        return results, has_more, total


def _to_market_result(
    item: dict[str, object],
    lang: str,
) -> MarketResult | None:
    skill_id = _str(item.get("id"))
    if not skill_id:
        return None
    display_name = _str(item.get("display_name")) or skill_id
    description = _localized(item, "description", lang) or _opt_str(
        item.get("description"),
    )
    developer = _str(item.get("developer"))
    owner = _str(item.get("owner"))
    if not developer and skill_id.startswith("@") and "/" in skill_id:
        developer = skill_id.split("/", 1)[0].lstrip("@")
    elif not developer:
        developer = owner
    quoted_id = urllib.parse.quote(skill_id, safe="@/")
    source_url = f"https://modelscope.cn/skills/{quoted_id}"
    stats: dict[str, str | int] = {}
    downloads = _opt_int(item.get("downloads"))
    if downloads is not None:
        stats["downloads"] = downloads
    views = _opt_int(item.get("view_count"))
    if views is not None:
        stats["views"] = views
    category = _localized(item, "category", lang) or _opt_str(
        item.get("category"),
    )
    if category:
        stats["category"] = category
    return MarketResult(
        source="modelscope",
        slug=skill_id,
        name=display_name,
        description=description,
        source_url=source_url,
        version=_opt_str(item.get("version")),
        author=developer or None,
        icon_url=_opt_str(item.get("logo_url")),
        stats=stats or None,
    )


def _localized(
    item: dict[str, object],
    field: str,
    lang: str,
) -> str | None:
    """Pick `locales[lang][field]`, falling back to the other locale.

    Upstream returns `{en: {...}, zh: {...}}` for description and
    category. Trying the requested lang first.
    """
    locales = item.get("locales")
    if not isinstance(locales, dict):
        return None
    primary = "zh" if str(lang).lower().startswith("zh") else "en"
    fallback = "en" if primary == "zh" else "zh"
    for code in (primary, fallback):
        entry = locales.get(code)
        if isinstance(entry, dict):
            text = _opt_str(entry.get(field))
            if text:
                return text
    return None


def _str(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    return ""


def _opt_str(value: object) -> str | None:
    s = _str(value)
    return s or None


def _opt_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    return None


provider = ModelScopeProvider()
