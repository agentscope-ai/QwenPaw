# -*- coding: utf-8 -*-
"""Skill Market HTTP routes.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...market import (
    MarketResult,
    MarketSearchError,
    ProviderInfo,
    list_categories,
    list_providers,
    search_market,
)
from ...market.providers import PROVIDERS


router = APIRouter(prefix="/market", tags=["market"])


class ProviderInfoSpec(BaseModel):
    key: str
    label: str
    available: bool
    reason: str | None = None
    supports_browse: bool = True


class MarketResultSpec(BaseModel):
    source: str
    slug: str
    name: str
    description: str | None = None
    source_url: str
    version: str | None = None
    author: str | None = None
    icon_url: str | None = None
    stats: dict[str, str | int] | None = None


class MarketSearchErrorSpec(BaseModel):
    provider: str
    message: str


class CategorySpec(BaseModel):
    id: str
    label: str


class MarketSearchRequest(BaseModel):
    query: str = Field("", description="User-typed search string")
    provider_pages: dict[str, int] = Field(
        default_factory=dict,
        description="provider key → page number to request from that provider",
    )
    limit: int = Field(10, ge=1, le=50)
    lang: str = Field("en", description="UI language for locale-aware fields")
    category: str | None = Field(
        None,
        description="Logical category id to browse (see /market/categories)",
    )


class ProviderPageInfo(BaseModel):
    has_more: bool = False
    total: int = 0


class MarketSearchResponse(BaseModel):
    results: list[MarketResultSpec]
    errors: list[MarketSearchErrorSpec]
    by_provider: dict[str, ProviderPageInfo] = Field(default_factory=dict)


@router.get("/providers", response_model=list[ProviderInfoSpec])
async def get_market_providers() -> list[ProviderInfoSpec]:
    return [_provider_info_to_spec(p) for p in list_providers()]


@router.get("/categories", response_model=list[CategorySpec])
async def get_market_categories(lang: str = "en") -> list[CategorySpec]:
    return [CategorySpec(**c) for c in list_categories(lang)]


@router.post("/search", response_model=MarketSearchResponse)
async def market_search(body: MarketSearchRequest) -> MarketSearchResponse:
    unknown = [k for k in body.provider_pages if k not in PROVIDERS]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"unknown providers: {sorted(unknown)}",
        )

    results, errors, by_provider = await search_market(
        query=body.query,
        provider_pages=body.provider_pages,
        limit=body.limit,
        lang=body.lang,
        category=body.category,
    )
    return MarketSearchResponse(
        results=[_result_to_spec(r) for r in results],
        errors=[_error_to_spec(e) for e in errors],
        by_provider={
            key: ProviderPageInfo(has_more=has_more, total=total)
            for key, (has_more, total) in by_provider.items()
        },
    )


def _provider_info_to_spec(info: ProviderInfo) -> ProviderInfoSpec:
    return ProviderInfoSpec(
        key=info.key,
        label=info.label,
        available=info.available,
        reason=info.reason,
        supports_browse=info.supports_browse,
    )


def _result_to_spec(item: MarketResult) -> MarketResultSpec:
    return MarketResultSpec(
        source=item.source,
        slug=item.slug,
        name=item.name,
        description=item.description,
        source_url=item.source_url,
        version=item.version,
        author=item.author,
        icon_url=item.icon_url,
        stats=item.stats,
    )


def _error_to_spec(item: MarketSearchError) -> MarketSearchErrorSpec:
    return MarketSearchErrorSpec(
        provider=item.provider,
        message=item.message,
    )
