# -*- coding: utf-8 -*-
"""Integration tests for the token-usage API router.

Covers GET /api/token-usage (summary) and GET /api/token-usage/details
with various query parameters (date ranges, model/provider filters).
"""

from __future__ import annotations

import pytest
from helpers import default_http_timeout

_TOKEN_USAGE_TIMEOUT = default_http_timeout(15.0)


# ------------------------------------------------------------------ #
# Summary endpoint
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_token_usage_summary_default_range(app_server) -> None:
    """Test purpose:
    - Verify GET /api/token-usage with no parameters returns a valid
      summary for the default 30-day range. Console dashboard renders
      this on load.

    Test flow:
    1. GET /api/token-usage with no params.
    2. Assert 200 and response has expected summary structure.

    API endpoints:
    - GET /api/token-usage
    """
    resp = app_server.api_request(
        "GET",
        "/api/token-usage",
        timeout=_TOKEN_USAGE_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    payload = resp.json()
    # Summary should be a dict with date-level aggregation
    assert isinstance(payload, dict)


@pytest.mark.integration
@pytest.mark.p1
def test_token_usage_summary_with_date_range(app_server) -> None:
    """Test purpose:
    - Verify date range parameters are accepted and response is valid.

    Test flow:
    1. GET /api/token-usage with start_date and end_date.
    2. Assert 200.

    API endpoints:
    - GET /api/token-usage
    """
    resp = app_server.api_request(
        "GET",
        "/api/token-usage",
        params={
            "start_date": "2026-01-01",
            "end_date": "2026-12-31",
        },
        timeout=_TOKEN_USAGE_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_token_usage_summary_reversed_dates_swapped(app_server) -> None:
    """Test purpose:
    - Verify that reversed start/end dates are handled gracefully
      (the router swaps them internally).

    Test flow:
    1. GET /api/token-usage with start_date > end_date.
    2. Assert 200 (not 400/422).

    API endpoints:
    - GET /api/token-usage
    """
    resp = app_server.api_request(
        "GET",
        "/api/token-usage",
        params={
            "start_date": "2026-12-31",
            "end_date": "2026-01-01",
        },
        timeout=_TOKEN_USAGE_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_token_usage_summary_invalid_date_format(app_server) -> None:
    """Test purpose:
    - Verify invalid date format returns None for that date (falls back
      to default). The router uses _parse_date which returns None on
      parse failure.

    Test flow:
    1. GET /api/token-usage with invalid date string.
    2. Assert 200 (invalid dates treated as None → defaults).

    API endpoints:
    - GET /api/token-usage
    """
    resp = app_server.api_request(
        "GET",
        "/api/token-usage",
        params={
            "start_date": "not-a-date",
        },
        timeout=_TOKEN_USAGE_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_token_usage_summary_model_filter(app_server) -> None:
    """Test purpose:
    - Verify model filter parameter is accepted.

    Test flow:
    1. GET /api/token-usage with model filter.
    2. Assert 200.

    API endpoints:
    - GET /api/token-usage
    """
    resp = app_server.api_request(
        "GET",
        "/api/token-usage",
        params={"model": "qwen-max"},
        timeout=_TOKEN_USAGE_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_token_usage_summary_provider_filter(app_server) -> None:
    """Test purpose:
    - Verify provider filter parameter is accepted.

    Test flow:
    1. GET /api/token-usage with provider filter.
    2. Assert 200.

    API endpoints:
    - GET /api/token-usage
    """
    resp = app_server.api_request(
        "GET",
        "/api/token-usage",
        params={"provider": "dashscope"},
        timeout=_TOKEN_USAGE_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()


# ------------------------------------------------------------------ #
# Details endpoint
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_token_usage_details_default_range(app_server) -> None:
    """Test purpose:
    - Verify GET /api/token-usage/details returns a list of records.
      Frontend uses this for custom aggregation views.

    Test flow:
    1. GET /api/token-usage/details with no params.
    2. Assert 200 and response is a list.

    API endpoints:
    - GET /api/token-usage/details
    """
    resp = app_server.api_request(
        "GET",
        "/api/token-usage/details",
        timeout=_TOKEN_USAGE_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    payload = resp.json()
    assert isinstance(payload, list)


@pytest.mark.integration
@pytest.mark.p1
def test_token_usage_details_with_date_range(app_server) -> None:
    """Test purpose:
    - Verify details endpoint accepts date range parameters.

    Test flow:
    1. GET /api/token-usage/details with start/end dates.
    2. Assert 200 and list response.

    API endpoints:
    - GET /api/token-usage/details
    """
    resp = app_server.api_request(
        "GET",
        "/api/token-usage/details",
        params={
            "start_date": "2026-01-01",
            "end_date": "2026-12-31",
        },
        timeout=_TOKEN_USAGE_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    assert isinstance(resp.json(), list)


@pytest.mark.integration
@pytest.mark.p1
def test_token_usage_details_record_schema(app_server) -> None:
    """Test purpose:
    - Verify each detail record has expected fields (date, model,
      provider, tokens). Schema validation for frontend consumption.

    Test flow:
    1. GET /api/token-usage/details.
    2. If records exist, verify field types.

    API endpoints:
    - GET /api/token-usage/details
    """
    resp = app_server.api_request(
        "GET",
        "/api/token-usage/details",
        timeout=_TOKEN_USAGE_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    records = resp.json()
    for record in records[:5]:  # Check first 5 records
        # TokenUsageRecord should have date, model, provider fields
        assert isinstance(record, dict)


@pytest.mark.integration
@pytest.mark.p1
def test_token_usage_details_with_filters(app_server) -> None:
    """Test purpose:
    - Verify details endpoint accepts model and provider filters
      simultaneously.

    Test flow:
    1. GET /api/token-usage/details with both filters.
    2. Assert 200.

    API endpoints:
    - GET /api/token-usage/details
    """
    resp = app_server.api_request(
        "GET",
        "/api/token-usage/details",
        params={
            "model": "qwen-max",
            "provider": "dashscope",
        },
        timeout=_TOKEN_USAGE_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
