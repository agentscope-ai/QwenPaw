# -*- coding: utf-8 -*-
"""Integration tests for Skill Market search and categories endpoints.

 Supplements test_market.py (providers list + unknown provider rejection)
and test_market_categories.py (category listing). Covers search flow,
pagination, limit boundaries, category filtering, and lang parameter.
"""

from __future__ import annotations

import pytest
from helpers import default_http_timeout

_MARKET_HTTP_TIMEOUT = default_http_timeout(15.0)


# ------------------------------------------------------------------ #
# Search: basic flow
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_market_search_empty_query_contract(app_server) -> None:
    """Test purpose:
    - Verify POST /api/market/search with an empty query and a known
      provider returns the MarketSearchResponse contract (results list,
      errors list, by_provider dict). Console renders this on initial
      market open; a regression breaks the landing page.

    Test flow:
    1. GET /api/market/providers to find a registered provider key.
    2. POST /api/market/search with empty query and that provider at
       page 1.
    3. Assert 200 and response has results (list), errors (list), and
       by_provider (dict).

    API endpoints:
    - GET /api/market/providers
    - POST /api/market/search
    """
    providers_resp = app_server.api_request(
        "GET",
        "/api/market/providers",
        timeout=_MARKET_HTTP_TIMEOUT,
    )
    assert providers_resp.status_code == 200, app_server.logs_tail()
    providers = providers_resp.json()
    assert len(providers) > 0

    provider_key = providers[0]["key"]
    resp = app_server.api_request(
        "POST",
        "/api/market/search",
        json={
            "query": "",
            "provider_pages": {provider_key: 1},
            "limit": 5,
            "lang": "en",
        },
        timeout=_MARKET_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    payload = resp.json()
    assert isinstance(payload.get("results"), list)
    assert isinstance(payload.get("errors"), list)
    assert isinstance(payload.get("by_provider"), dict)


@pytest.mark.integration
@pytest.mark.p1
def test_market_search_with_query_returns_result_schema(app_server) -> None:
    """Test purpose:
    - Verify search results conform to MarketResultSpec schema when a
      real query is provided. Each result must have source, slug, name,
      source_url at minimum.

    Test flow:
    1. GET providers to find a key.
    2. POST search with a common query term.
    3. If results are returned, verify each has required fields.

    API endpoints:
    - GET /api/market/providers
    - POST /api/market/search
    """
    providers_resp = app_server.api_request(
        "GET",
        "/api/market/providers",
        timeout=_MARKET_HTTP_TIMEOUT,
    )
    assert providers_resp.status_code == 200
    providers = providers_resp.json()
    provider_key = providers[0]["key"]

    resp = app_server.api_request(
        "POST",
        "/api/market/search",
        json={
            "query": "test",
            "provider_pages": {provider_key: 1},
            "limit": 10,
            "lang": "en",
        },
        timeout=_MARKET_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    payload = resp.json()
    for item in payload.get("results", []):
        assert isinstance(item.get("source"), str) and item["source"]
        assert isinstance(item.get("slug"), str) and item["slug"]
        assert isinstance(item.get("name"), str) and item["name"]
        assert isinstance(item.get("source_url"), str) and item["source_url"]


# ------------------------------------------------------------------ #
# Search: limit boundaries
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_market_search_limit_min_1(app_server) -> None:
    """Test purpose:
    - Verify limit=1 is accepted and returns at most 1 result per
      provider. Boundary: minimum valid limit.

    Test flow:
    1. POST search with limit=1.
    2. Assert 200 and results list length <= number of providers.

    API endpoints:
    - POST /api/market/search
    """
    providers_resp = app_server.api_request(
        "GET",
        "/api/market/providers",
        timeout=_MARKET_HTTP_TIMEOUT,
    )
    provider_key = providers_resp.json()[0]["key"]

    resp = app_server.api_request(
        "POST",
        "/api/market/search",
        json={
            "query": "",
            "provider_pages": {provider_key: 1},
            "limit": 1,
        },
        timeout=_MARKET_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    payload = resp.json()
    # limit=1 means at most 1 result per provider
    assert len(payload.get("results", [])) <= 1


@pytest.mark.integration
@pytest.mark.p1
def test_market_search_limit_max_50(app_server) -> None:
    """Test purpose:
    - Verify limit=50 (maximum) is accepted. Boundary: maximum valid
      limit per the API schema (le=50).

    Test flow:
    1. POST search with limit=50.
    2. Assert 200.

    API endpoints:
    - POST /api/market/search
    """
    providers_resp = app_server.api_request(
        "GET",
        "/api/market/providers",
        timeout=_MARKET_HTTP_TIMEOUT,
    )
    provider_key = providers_resp.json()[0]["key"]

    resp = app_server.api_request(
        "POST",
        "/api/market/search",
        json={
            "query": "",
            "provider_pages": {provider_key: 1},
            "limit": 50,
        },
        timeout=_MARKET_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_market_search_limit_exceeds_max_rejected(app_server) -> None:
    """Test purpose:
    - Verify limit>50 is rejected by the API schema validation. The
      schema caps at le=50; exceeding should return 422.

    Test flow:
    1. POST search with limit=51.
    2. Assert 422 (validation error).

    API endpoints:
    - POST /api/market/search
    """
    providers_resp = app_server.api_request(
        "GET",
        "/api/market/providers",
        timeout=_MARKET_HTTP_TIMEOUT,
    )
    provider_key = providers_resp.json()[0]["key"]

    resp = app_server.api_request(
        "POST",
        "/api/market/search",
        json={
            "query": "",
            "provider_pages": {provider_key: 1},
            "limit": 51,
        },
        timeout=_MARKET_HTTP_TIMEOUT,
    )
    assert resp.status_code == 422, app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_market_search_limit_zero_rejected(app_server) -> None:
    """Test purpose:
    - Verify limit=0 is rejected (ge=1 constraint).

    Test flow:
    1. POST search with limit=0.
    2. Assert 422.

    API endpoints:
    - POST /api/market/search
    """
    providers_resp = app_server.api_request(
        "GET",
        "/api/market/providers",
        timeout=_MARKET_HTTP_TIMEOUT,
    )
    provider_key = providers_resp.json()[0]["key"]

    resp = app_server.api_request(
        "POST",
        "/api/market/search",
        json={
            "query": "",
            "provider_pages": {provider_key: 1},
            "limit": 0,
        },
        timeout=_MARKET_HTTP_TIMEOUT,
    )
    assert resp.status_code == 422, app_server.logs_tail()


# ------------------------------------------------------------------ #
# Search: empty provider_pages
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_market_search_empty_provider_pages_returns_empty(app_server) -> None:
    """Test purpose:
    - Verify POST /api/market/search with empty provider_pages returns
      empty results (no providers to query). Edge case: user deselects
      all provider chips.

    Test flow:
    1. POST search with empty provider_pages.
    2. Assert 200 and results is empty list.

    API endpoints:
    - POST /api/market/search
    """
    resp = app_server.api_request(
        "POST",
        "/api/market/search",
        json={
            "query": "test",
            "provider_pages": {},
            "limit": 10,
        },
        timeout=_MARKET_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    payload = resp.json()
    assert payload.get("results", []) == []
    assert payload.get("by_provider", {}) == {}


# ------------------------------------------------------------------ #
# Search: multiple providers
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_market_search_multiple_providers_aggregates(app_server) -> None:
    """Test purpose:
    - Verify search with multiple providers aggregates results from all
      of them. Console shows combined results from selected sources.

    Test flow:
    1. GET providers, take up to 3 keys.
    2. POST search with all selected providers.
    3. Assert by_provider has entries for each requested provider.

    API endpoints:
    - GET /api/market/providers
    - POST /api/market/search
    """
    providers_resp = app_server.api_request(
        "GET",
        "/api/market/providers",
        timeout=_MARKET_HTTP_TIMEOUT,
    )
    providers = providers_resp.json()
    selected = {p["key"]: 1 for p in providers[:3]}

    resp = app_server.api_request(
        "POST",
        "/api/market/search",
        json={
            "query": "",
            "provider_pages": selected,
            "limit": 5,
        },
        timeout=_MARKET_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    payload = resp.json()
    by_provider = payload.get("by_provider", {})
    # Each requested provider should appear in by_provider
    # (either with results or errors)
    for key in selected:
        assert key in by_provider or any(
            e.get("provider") == key for e in payload.get("errors", [])
        )


# ------------------------------------------------------------------ #
# Search: lang parameter
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_market_search_lang_zh(app_server) -> None:
    """Test purpose:
    - Verify lang=zh is accepted and returns valid response. Console
      switches UI language; market should respect it.

    Test flow:
    1. POST search with lang=zh.
    2. Assert 200 and valid response structure.

    API endpoints:
    - POST /api/market/search
    """
    providers_resp = app_server.api_request(
        "GET",
        "/api/market/providers",
        timeout=_MARKET_HTTP_TIMEOUT,
    )
    provider_key = providers_resp.json()[0]["key"]

    resp = app_server.api_request(
        "POST",
        "/api/market/search",
        json={
            "query": "",
            "provider_pages": {provider_key: 1},
            "limit": 5,
            "lang": "zh",
        },
        timeout=_MARKET_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    payload = resp.json()
    assert isinstance(payload.get("results"), list)


# ------------------------------------------------------------------ #
# Search: category parameter
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_market_search_with_category(app_server) -> None:
    """Test purpose:
    - Verify search with a category filter returns valid response.
      Console category browsing depends on this.

    Test flow:
    1. GET /api/market/categories to find a valid category id.
    2. POST search with that category.
    3. Assert 200 and valid response.

    API endpoints:
    - GET /api/market/categories
    - POST /api/market/search
    """
    cats_resp = app_server.api_request(
        "GET",
        "/api/market/categories",
        timeout=_MARKET_HTTP_TIMEOUT,
    )
    assert cats_resp.status_code == 200
    categories = cats_resp.json()
    if not categories:
        pytest.skip("No categories available")

    category_id = categories[0]["id"]
    providers_resp = app_server.api_request(
        "GET",
        "/api/market/providers",
        timeout=_MARKET_HTTP_TIMEOUT,
    )
    provider_key = providers_resp.json()[0]["key"]

    resp = app_server.api_request(
        "POST",
        "/api/market/search",
        json={
            "query": "",
            "provider_pages": {provider_key: 1},
            "limit": 10,
            "category": category_id,
        },
        timeout=_MARKET_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()


# ------------------------------------------------------------------ #
# Search: by_provider pagination info
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_market_search_by_provider_has_pagination_info(app_server) -> None:
    """Test purpose:
    - Verify by_provider entries contain has_more (bool) and total (int)
      for pagination. Console uses these for "load more" button.

    Test flow:
    1. POST search with a known provider.
    2. Assert by_provider entries have has_more and total fields.

    API endpoints:
    - POST /api/market/search
    """
    providers_resp = app_server.api_request(
        "GET",
        "/api/market/providers",
        timeout=_MARKET_HTTP_TIMEOUT,
    )
    provider_key = providers_resp.json()[0]["key"]

    resp = app_server.api_request(
        "POST",
        "/api/market/search",
        json={
            "query": "",
            "provider_pages": {provider_key: 1},
            "limit": 5,
        },
        timeout=_MARKET_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    payload = resp.json()
    by_provider = payload.get("by_provider", {})
    for _key, info in by_provider.items():
        assert isinstance(info.get("has_more"), bool)
        assert isinstance(info.get("total"), int)


# ------------------------------------------------------------------ #
# Providers: supports_browse field
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_market_providers_supports_browse_field(app_server) -> None:
    """Test purpose:
    - Verify providers include supports_browse field. Console uses this
      to enable/disable category browsing per provider.

    Test flow:
    1. GET /api/market/providers.
    2. Assert each entry has supports_browse (bool).

    API endpoints:
    - GET /api/market/providers
    """
    resp = app_server.api_request(
        "GET",
        "/api/market/providers",
        timeout=_MARKET_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    for item in resp.json():
        assert "supports_browse" in item
        assert isinstance(item["supports_browse"], bool)
