# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""The market adapter talks to the host through ``qwenpaw.market.service``.

Provider availability is read from ``list_providers`` only.  The host's
provider registry is a newer-line internal: release lines without it must
still get a working search instead of an ImportError at request time.
"""

from __future__ import annotations

import asyncio
import sys
import threading
import types
from dataclasses import dataclass

import pytest

from services import skill_market

pytestmark = pytest.mark.unit


@dataclass(frozen=True)
class _Provider:
    """Stands in for the host's ``ProviderInfo``."""

    key: str
    label: str = "Market"
    available: bool = True
    reason: str | None = None
    supports_browse: bool = True


@dataclass(frozen=True)
class _Result:
    """Stands in for the host's ``MarketResult``."""

    source: str = "acme"
    slug: str = "demo-skill"
    name: str = "Demo"
    description: str | None = "does the thing"
    source_url: str = "https://market.example/acme/demo-skill"
    version: str | None = "1.0.0"
    author: str | None = "acme"
    icon_url: str | None = None
    stats: dict | None = None


@dataclass(frozen=True)
class _Error:
    """Stands in for the host's ``MarketSearchError``."""

    provider: str = "acme"
    message: str = "boom"


def _install_fake_service(monkeypatch, providers, capture):
    """Publish a fake ``qwenpaw.market.service`` and record its calls."""

    async def search_market(
        query,
        provider_pages,
        limit=10,
        lang="en",
        category=None,
    ):
        capture["query"] = query
        capture["provider_pages"] = provider_pages
        capture["limit"] = limit
        capture["lang"] = lang
        return (
            [_Result()],
            [_Error()],
            {"acme": (True, 42)},
        )

    module = types.ModuleType("qwenpaw.market.service")

    def list_providers():
        capture["providers_thread"] = threading.current_thread()
        return list(providers)

    module.list_providers = list_providers
    module.search_market = search_market
    monkeypatch.setitem(sys.modules, "qwenpaw.market.service", module)


def _run(coro):
    return asyncio.run(coro)


def test_search_survives_a_host_without_a_provider_registry(
    monkeypatch,
) -> None:
    """A release line shipping no market registry still searches.

    ``sys.modules`` set to None makes any import of the registry raise, so a
    stray hard dependency would surface here as an ImportError instead of a
    result.  This is the regression guard for that coupling.
    """

    monkeypatch.setitem(sys.modules, "qwenpaw.market.registry", None)
    capture: dict = {}
    _install_fake_service(monkeypatch, [_Provider("acme")], capture)

    results, has_more, totals = _run(skill_market.search_skills("demo"))

    assert capture["provider_pages"] == {"acme": 1}
    assert [r.slug for r in results] == ["demo-skill"]
    assert has_more is True
    assert totals == {"acme": 42}


def test_provider_discovery_runs_off_the_event_loop(
    monkeypatch,
) -> None:
    """Asking providers whether they are usable never blocks the loop.

    ``available()`` can read the environment and import an optional backend.
    The providers route already offloads that lookup; search has to match, or
    one slow provider would stall every other request in the process.
    """

    capture: dict = {}
    _install_fake_service(monkeypatch, [_Provider("acme")], capture)

    async def scenario() -> threading.Thread:
        loop_thread = threading.current_thread()
        await skill_market.search_skills("demo")
        return loop_thread

    loop_thread = _run(scenario())

    assert capture["providers_thread"] is not loop_thread


def test_unavailable_and_unbrowsable_providers_are_excluded(
    monkeypatch,
) -> None:
    """Only markets that can answer a paged browse are asked."""

    capture: dict = {}
    _install_fake_service(
        monkeypatch,
        [
            _Provider("live", available=True, supports_browse=True),
            _Provider("down", available=False, supports_browse=True),
            _Provider("search_only", available=True, supports_browse=False),
        ],
        capture,
    )

    _run(skill_market.search_skills("demo", page=3))

    assert capture["provider_pages"] == {"live": 3}


def test_limit_is_capped_and_page_floor_applied(monkeypatch) -> None:
    """The adapter owns the caps, so a huge client page cannot leak through."""

    capture: dict = {}
    _install_fake_service(monkeypatch, [_Provider("acme")], capture)

    _run(skill_market.search_skills("demo", page=0, limit=9999))

    assert capture["limit"] == skill_market._MAX_MARKET_LIMIT
    assert capture["provider_pages"] == {"acme": 1}


def test_missing_market_service_becomes_a_clean_refusal(monkeypatch) -> None:
    """A host without market search fails as 501 material, not a crash."""

    monkeypatch.setitem(sys.modules, "qwenpaw.market.service", None)
    with pytest.raises(skill_market.MarketUnavailable):
        _run(skill_market.search_skills("demo"))
    with pytest.raises(skill_market.MarketUnavailable):
        _run(asyncio.to_thread(skill_market.list_market_providers))


def test_provider_listing_maps_host_fields(monkeypatch) -> None:
    """The UI sees the host's availability and browse flags verbatim."""

    capture: dict = {}
    _install_fake_service(
        monkeypatch,
        [_Provider("acme", label="Acme", available=False, reason="no key")],
        capture,
    )

    info = skill_market.list_market_providers()[0]

    assert info.key == "acme"
    assert info.label == "Acme"
    assert info.available is False
    assert info.reason == "no key"
    assert info.supports_browse is True
