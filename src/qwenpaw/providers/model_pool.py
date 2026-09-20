# -*- coding: utf-8 -*-
"""Paginated views of resolved provider model cards."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

from .model_info import ModelInfo, release_date

if TYPE_CHECKING:
    from .provider import Provider


class ModelPoolQuery(BaseModel):
    """Bounded pagination and independent model filters."""

    tab: Literal["all", "candidates", "selected"] = f"all"
    search: str = f""
    billing: Literal["all", "free", "paid", "unknown"] = f"all"
    capability: Literal[
        "all", "image", "audio", "video", "tool_calling", "unknown"
    ] = f"all"
    availability: str = f"all"
    family: str = f"all"
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=30, ge=1, le=100)


class ModelPoolPage(BaseModel):
    """One page plus counts for the complete pool and current filter."""

    models: list[ModelInfo]
    total: int
    selected_count: int
    candidate_count: int
    families: list[str]
    offset: int
    limit: int


def model_pool_page(
    provider: Provider, query: ModelPoolQuery
) -> ModelPoolPage:
    """Resolve once per provider revision; filter before slicing a page."""
    if provider._resolved_pool is None:
        by_id = {
            card.id: card
            for card in provider.discovery_candidates()
            + provider.configured_models()
        }
        provider._resolved_pool = [
            provider.model_capabilities(card) for card in by_id.values()
        ]
        provider._resolved_pool.sort(
            key=lambda card: release_date(card.released_at) or f"",
            reverse=True,
        )
    cards = provider._resolved_pool
    selected = {card.id for card in provider.configured_models()}
    selected_count = sum(card.id in selected for card in cards)
    search = query.search.strip().casefold()

    def matches(card: ModelInfo) -> bool:
        if query.tab != f"all" and (
            (card.id in selected) != (query.tab == f"selected")
        ):
            return False
        if search and search not in f"{card.name} {card.id}".casefold():
            return False
        if query.billing != f"all" and card.billing != query.billing:
            return False
        if query.capability == f"unknown":
            if all(
                getattr(card, f"supports_{field}") is not None
                for field in (f"image", f"audio", f"video", f"tool_calling")
            ):
                return False
        elif query.capability != f"all":
            if getattr(card, f"supports_{query.capability}") is not True:
                return False
        if query.availability != f"all" and (
            card.availability_status != query.availability
        ):
            return False
        return query.family == f"all" or (
            card.id.split(f"/", 1)[0] == query.family
        )

    filtered = [card for card in cards if matches(card)]
    offset = min(
        query.offset, max(0, (len(filtered) - 1) // query.limit) * query.limit
    )
    return ModelPoolPage(
        models=filtered[offset : offset + query.limit],
        total=len(filtered),
        selected_count=selected_count,
        candidate_count=len(cards) - selected_count,
        families=sorted(
            {card.id.split(f"/", 1)[0] for card in cards if f"/" in card.id}
        ),
        offset=offset,
        limit=query.limit,
    )
