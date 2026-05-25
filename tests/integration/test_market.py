# -*- coding: utf-8 -*-
"""Integration tests for the Skill Market router."""
from __future__ import annotations

import pytest

_MARKET_HTTP_TIMEOUT = 15.0


@pytest.mark.integration
@pytest.mark.p1
def test_market_providers_list_returns_array_contract(app_server) -> None:
    """Test purpose:
    - Verify GET /api/market/providers returns the ProviderInfoSpec
      contract list (key/label/available/reason). Console renders the
      Skill Market provider chips from this; a regression hides every
      provider source and the user cannot browse the market.

    Test flow:
    1. GET /api/market/providers.
    2. Assert 200 and the body is a non-empty list (built-in providers
       are always registered, even when their availability is False).
    3. Assert each entry exposes ``key`` (str), ``label`` (str), and
       ``available`` (bool).

    API endpoints:
    - GET /api/market/providers
    """
    resp = app_server.api_request(
        "GET",
        "/api/market/providers",
        timeout=_MARKET_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    payload = resp.json()
    assert isinstance(payload, list)
    assert len(payload) > 0, "built-in market providers must be registered"
    for item in payload:
        assert isinstance(item.get("key"), str) and item["key"]
        assert isinstance(item.get("label"), str) and item["label"]
        assert isinstance(item.get("available"), bool)


@pytest.mark.integration
@pytest.mark.p2
def test_market_search_rejects_unknown_provider_400(app_server) -> None:
    """Test purpose:
    - Verify POST /api/market/search returns 400 with a detail listing
      the offending provider keys when the request specifies
      ``provider_pages`` keys that are not registered, so the client can
      surface a clear "unknown provider" error rather than a silent
      empty search.

    Test flow:
    1. POST /api/market/search with provider_pages containing an unknown
       provider key.
    2. Assert 400 status and detail mentions ``unknown providers`` or
       includes the offending key.

    API endpoints:
    - POST /api/market/search
    """
    unknown_provider = "integ_unknown_market_provider_xyz"
    resp = app_server.api_request(
        "POST",
        "/api/market/search",
        json={
            "query": "any",
            "provider_pages": {unknown_provider: 1},
            "limit": 5,
            "lang": "en",
        },
        timeout=_MARKET_HTTP_TIMEOUT,
    )
    assert resp.status_code == 400, app_server.logs_tail()
    detail = resp.json().get("detail", "")
    assert "unknown providers" in detail.lower() or unknown_provider in detail
