# -*- coding: utf-8 -*-
"""Market search service.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any

from .categories import resolve as resolve_category
from .providers import PROVIDERS
from .schema import MarketResult, MarketSearchError, ProviderInfo


logger = logging.getLogger(__name__)


_MAX_LIMIT = 50


def list_providers() -> list[ProviderInfo]:
    out: list[ProviderInfo] = []
    for key, provider in PROVIDERS.items():
        is_available, reason = provider.available()
        out.append(
            ProviderInfo(
                key=key,
                label=provider.label,
                available=is_available,
                reason=reason,
                supports_browse=getattr(provider, "supports_browse", True),
            ),
        )
    return out


async def search_market(
    query: str,
    provider_pages: dict[str, int],
    limit: int = 10,
    lang: str = "en",
    category: str | None = None,
) -> tuple[
    list[MarketResult],
    list[MarketSearchError],
    dict[str, tuple[bool, int]],
]:
    """Search each requested provider at its own page; concat results."""
    capped_limit = max(1, min(int(limit or 1), _MAX_LIMIT))
    selected = [
        (key, max(1, int(provider_pages[key] or 1)))
        for key in PROVIDERS
        if key in provider_pages
    ]

    coros = [
        _run_one(key, query, capped_limit, page, lang, category)
        for key, page in selected
    ]
    paired = await asyncio.gather(*coros)

    results: list[MarketResult] = []
    errors: list[MarketSearchError] = []
    by_provider: dict[str, tuple[bool, int]] = {}
    for (key, _), outcome in zip(selected, paired):
        if isinstance(outcome, MarketSearchError):
            errors.append(outcome)
            continue
        sub_results, sub_has_more, sub_total = outcome
        results.extend(sub_results)
        total = (
            sub_total if isinstance(sub_total, int) and sub_total > 0 else 0
        )
        by_provider[key] = (sub_has_more, total)
    return results, errors, by_provider


async def _run_one(
    key: str,
    query: str,
    limit: int,
    page: int,
    lang: str,
    category: str | None = None,
) -> tuple[list[MarketResult], bool, int | None] | MarketSearchError:
    provider = PROVIDERS[key]
    is_available, reason = provider.available()
    if not is_available:
        return MarketSearchError(
            provider=key,
            message=reason or "provider unavailable",
        )
    # Native category filter where supported; otherwise fall back to
    # searching the category name when the user typed nothing.
    routing = resolve_category(category, key, lang)
    effective_query = query
    native_code = routing["native_code"]
    if native_code is None and routing["search_term"] and not query.strip():
        effective_query = routing["search_term"]
    # Search-only sources have no browse listing: an empty query would
    # return nothing. Skip the wasted upstream call (the UI prompts the
    # user to search) rather than fabricating a throwaway query.
    if (
        native_code is None
        and not effective_query.strip()
        and not getattr(provider, "supports_browse", True)
    ):
        return [], False, 0
    # Providers that don't declare `lang`/`category` kwargs ignore them.
    kwargs = _supported_kwargs(
        provider.search,
        lang=lang,
        category=native_code,
    )
    try:
        return await provider.search(effective_query, limit, page, **kwargs)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Market provider %s failed for query=%r: %s",
            key,
            query,
            exc,
        )
        return MarketSearchError(provider=key, message=str(exc) or repr(exc))


def _supported_kwargs(func: Any, **candidates: Any) -> dict[str, Any]:
    try:
        sig = inspect.signature(func)
    except (TypeError, ValueError):
        return {}
    params = sig.parameters
    accepts_var_kw = any(
        p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()
    )
    if accepts_var_kw:
        return candidates
    return {k: v for k, v in candidates.items() if k in params}
