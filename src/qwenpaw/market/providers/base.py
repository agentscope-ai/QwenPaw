# -*- coding: utf-8 -*-
"""Provider protocol and shared constants for market providers.
"""

from __future__ import annotations

from typing import Awaitable, Protocol, runtime_checkable

from ..schema import MarketResult


# Single source of truth for the budget any market provider has to answer a
# search call.
MARKET_SEARCH_TIMEOUT_S = 15.0


@runtime_checkable
class MarketProvider(Protocol):
    """One source of remote skills (e.g. ClawHub, ModelScope, Aliyun)."""

    key: str
    label: str

    def available(self) -> tuple[bool, str | None]:
        """Return (is_available, reason_if_not).

        Reason is shown verbatim to the user in the UI tooltip.
        """

    def search(
        self,
        query: str,
        limit: int,
        page: int,
    ) -> Awaitable[tuple[list[MarketResult], bool, int | None]]:
        """Search this provider. Returns `(results, has_more, total)`.

        Always async; the underlying transport is provider-specific
        (httpx for ClawHub/ModelScope, signed SDK client for Aliyun).
        `has_more` drives the Load More button; `total` is the upstream
        filtered count for display only (None when unknown).
        """
