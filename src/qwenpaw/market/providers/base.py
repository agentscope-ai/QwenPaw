# -*- coding: utf-8 -*-
"""Provider protocol and shared constants for market providers."""

from __future__ import annotations

from typing import Any, Awaitable, Protocol, runtime_checkable

from ..schema import MarketResult

# Single source of truth for the budget any market provider has to answer a
# search call.
MARKET_SEARCH_TIMEOUT_S = 15.0


@runtime_checkable
class MarketProvider(Protocol):
    """One source of remote skills (e.g. ClawHub, ModelScope, Aliyun)."""

    key: str
    label: str
    supports_browse: bool

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


@runtime_checkable
class MarketInstallProvider(Protocol):
    """Download contract; Hub plugins implement it alongside MarketProvider.

    The host retains bundle validation, scanning and installation. Providers
    handle their own endpoints, authentication and version resolution.
    """

    def matches_url(self, url: str) -> bool:
        """Recognize this hub's URLs without network I/O."""

    def fetch_bundle(
        self,
        url: str,
        requested_version: str,
    ) -> Awaitable[tuple[dict[str, Any], str]]:
        """Return (bundle, resolved_url), raising on download errors.

        Bundle shape: {"name": "...", "files": {"SKILL.md": "..."}}.
        """
