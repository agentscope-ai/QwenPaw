# -*- coding: utf-8 -*-
"""Integration tests for LLM provider/model APIs."""
from __future__ import annotations

import pytest

_PROVIDERS_HTTP_TIMEOUT = 15.0


@pytest.mark.integration
@pytest.mark.p0
def test_providers_list_returns_baseline_providers(app_server) -> None:
    """Test purpose:
    - Verify GET /api/models returns a non-empty list of providers so the
      console can render the model picker and agents can attach a model.
      A failure here means users cannot pick any LLM, which makes the
      product unusable.

    Test flow:
    1. GET /api/models.
    2. Assert 200 status and that the response is a non-empty list whose
       items expose ``id`` and ``name`` fields.

    API endpoints:
    - GET /api/models
    """
    resp = app_server.api_request(
        "GET",
        "/api/models",
        timeout=_PROVIDERS_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    payload = resp.json()
    assert isinstance(payload, list)
    assert len(payload) > 0
    for provider in payload:
        assert isinstance(provider.get("id"), str) and provider["id"]
        assert isinstance(provider.get("name"), str) and provider["name"]


@pytest.mark.integration
@pytest.mark.p2
def test_active_model_get_global_scope_contract(app_server) -> None:
    """Test purpose:
    - Verify GET /api/models/active?scope=global returns the
      ActiveModelsInfo contract (object with ``active_llm`` field) even
      when no model has been activated yet.

    Test flow:
    1. GET /api/models/active?scope=global.
    2. Assert 200 and the response is a JSON object containing the
       ``active_llm`` key (value may be null on a fresh workspace).

    API endpoints:
    - GET /api/models/active
    """
    resp = app_server.api_request(
        "GET",
        "/api/models/active",
        params={"scope": "global"},
        timeout=_PROVIDERS_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    payload = resp.json()
    assert isinstance(payload, dict)
    assert "active_llm" in payload


@pytest.mark.integration
@pytest.mark.p2
def test_set_active_model_rejects_unknown_provider_404(app_server) -> None:
    """Test purpose:
    - Verify PUT /api/models/active rejects activation requests pointing
      to a non-existent provider with 404 instead of corrupting state.

    Test flow:
    1. PUT /api/models/active with scope=global and an unknown provider_id.
    2. Assert 404 response and a ``detail`` mentioning the missing provider.

    API endpoints:
    - PUT /api/models/active
    """
    resp = app_server.api_request(
        "PUT",
        "/api/models/active",
        json={
            "provider_id": "integ_unknown_provider_xyz",
            "model": "integ_model_zzz",
            "scope": "global",
        },
        timeout=_PROVIDERS_HTTP_TIMEOUT,
    )
    assert resp.status_code == 404, app_server.logs_tail()
    detail = resp.json().get("detail", "")
    assert (
        "integ_unknown_provider_xyz" in detail or "not found" in detail.lower()
    )


@pytest.mark.integration
@pytest.mark.p0
def test_active_model_get_effective_scope_contract(app_server) -> None:
    """Test purpose:
    - Verify GET /api/models/active (default scope=effective) returns the
      ActiveModelsInfo contract. Console calls this on every page load
      to render the current-model selector; a regression makes the whole
      Console appear broken from a user's perspective.

    Test flow:
    1. GET /api/models/active without scope query param (router default
       is ``effective``).
    2. Assert 200 and the response is a JSON object with the
       ``active_llm`` key (value may be null on a fresh workspace).

    API endpoints:
    - GET /api/models/active
    """
    resp = app_server.api_request(
        "GET",
        "/api/models/active",
        timeout=_PROVIDERS_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    payload = resp.json()
    assert isinstance(payload, dict)
    assert "active_llm" in payload
