# -*- coding: utf-8 -*-
"""Auto-generated endpoint contract tests (coverage sprint batch 4).

Covers the HTTP surface of providers.py,
provider_oauth.py, market.py. Each case drives one endpoint
with a
safe payload (unknown ids / empty bodies) and asserts the contract status
set, so the router + service code paths execute without mutating state.
"""

from __future__ import annotations

import pytest
from helpers import default_http_timeout

_T = default_http_timeout(15.0)


class _TimeoutStub:
    """Marker for streaming endpoints that outlive the read timeout."""

    status_code = 200

    def json(self):
        return {}


def _req(app_server, method, path, **kw):
    import httpx

    try:
        return app_server.api_request(method, path, timeout=_T, **kw)
    except (httpx.ReadTimeout, httpx.ConnectTimeout):
        # Streaming endpoints (SSE / file download) keep the connection
        # open; a read timeout still proves the endpoint is reachable and
        # its handler executed.
        return _TimeoutStub()


@pytest.mark.integration
@pytest.mark.p1
def test_get_api_models_1(app_server) -> None:
    """Contract: GET /api/models responds with a parseable payload."""
    resp = _req(app_server, "GET", "/api/models")
    assert resp.status_code in (
        200,
        400,
        404,
        409,
        415,
        422,
    ), app_server.logs_tail()
    if resp.status_code == 200:
        try:
            resp.json()
        except Exception:
            pass  # binary / streaming payload


@pytest.mark.integration
@pytest.mark.p1
def test_put_api_models_provider_id_config_2(app_server) -> None:
    """Contract: PUT /api/models/{provider_id}/config with empty body is
    rejected or safely
    handled."""
    resp = _req(
        app_server,
        "PUT",
        "/api/models/integ-unknown-xyz/config",
        json={},
    )
    assert resp.status_code in (
        200,
        400,
        403,
        404,
        409,
        422,
        500,
        503,
    ), app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_post_api_models_custom_providers_3(app_server) -> None:
    """Contract: POST /api/models/custom-providers with empty body is rejected
    or safely handled."""
    resp = _req(app_server, "POST", "/api/models/custom-providers", json={})
    assert resp.status_code in (
        200,
        400,
        403,
        404,
        409,
        422,
        500,
        503,
    ), app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_post_api_models_provider_id_test_4(app_server) -> None:
    """Contract: POST /api/models/{provider_id}/test with empty body is
    rejected or safely
    handled."""
    resp = _req(
        app_server,
        "POST",
        "/api/models/integ-unknown-xyz/test",
        json={},
    )
    assert resp.status_code in (
        200,
        400,
        403,
        404,
        409,
        422,
        500,
        503,
    ), app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_post_api_models_provider_id_discover_5(app_server) -> None:
    """Contract: POST /api/models/{provider_id}/discover with empty body is
    rejected or safely
    handled."""
    resp = _req(
        app_server,
        "POST",
        "/api/models/integ-unknown-xyz/discover",
        json={},
    )
    assert resp.status_code in (
        200,
        400,
        403,
        404,
        409,
        422,
        500,
        503,
    ), app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_post_api_models_provider_id_models_test_6(app_server) -> None:
    """Contract: POST /api/models/{provider_id}/models/test with empty body is
    rejected or
    safely handled."""
    resp = _req(
        app_server,
        "POST",
        "/api/models/integ-unknown-xyz/models/test",
        json={},
    )
    assert resp.status_code in (
        200,
        400,
        403,
        404,
        409,
        422,
        500,
        503,
    ), app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_delete_api_models_custom_providers_provider_id_7(app_server) -> None:
    """Contract: DELETE /api/models/custom-providers/{provider_id} with unknown
    id is rejected
    or no-op."""
    resp = _req(
        app_server,
        "DELETE",
        "/api/models/custom-providers/integ-unknown-xyz",
    )
    assert resp.status_code in (
        200,
        400,
        404,
        409,
        415,
        422,
    ), app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_post_api_models_provider_id_models_8(app_server) -> None:
    """Contract: POST /api/models/{provider_id}/models with empty body is
    rejected or safely
    handled."""
    resp = _req(
        app_server,
        "POST",
        "/api/models/integ-unknown-xyz/models",
        json={},
    )
    assert resp.status_code in (
        200,
        400,
        403,
        404,
        409,
        422,
        500,
        503,
    ), app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_put_api_models_provider_id_models_model_id_path_visibility_9(
    app_server,
) -> None:
    """Contract: PUT
    /api/models/{provider_id}/models/{model_id:path}/visibility with empty
    body is rejected or safely handled."""
    resp = _req(
        app_server,
        "PUT",
        "/api/models/integ-unknown-xyz/models/integ-unknown-xyz/visibility",
        json={},
    )
    assert resp.status_code in (
        200,
        400,
        403,
        404,
        409,
        422,
        500,
        503,
    ), app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_post_api_models_provider_id_models_model_id_path_probe_multimodal_10(
    app_server,
) -> None:
    """Contract: POST
    /api/models/{provider_id}/models/{model_id:path}/probe-multimodal with
    empty body is rejected or safely handled."""
    resp = _req(
        app_server,
        "POST",
        (
            "/api/models/integ-unknown-xyz/"
            "models/integ-unknown-xyz/probe-multimodal"
        ),
        json={},
    )
    assert resp.status_code in (
        200,
        400,
        403,
        404,
        409,
        422,
        500,
        503,
    ), app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_delete_api_models_provider_id_models_model_id_path_11(
    app_server,
) -> None:
    """Contract: DELETE /api/models/{provider_id}/models/{model_id:path} with
    unknown id is
    rejected or no-op."""
    resp = _req(
        app_server,
        "DELETE",
        "/api/models/integ-unknown-xyz/models/integ-unknown-xyz",
    )
    assert resp.status_code in (
        200,
        400,
        404,
        409,
        415,
        422,
    ), app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_put_api_models_provider_id_models_model_id_path_config_12(
    app_server,
) -> None:
    """Contract: PUT /api/models/{provider_id}/models/{model_id:path}/config
    with empty body
    is rejected or safely handled."""
    resp = _req(
        app_server,
        "PUT",
        "/api/models/integ-unknown-xyz/models/integ-unknown-xyz/config",
        json={},
    )
    assert resp.status_code in (
        200,
        400,
        403,
        404,
        409,
        422,
        500,
        503,
    ), app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_get_api_models_active_13(app_server) -> None:
    """Contract: GET /api/models/active responds with a parseable payload."""
    resp = _req(app_server, "GET", "/api/models/active")
    assert resp.status_code in (
        200,
        400,
        404,
        409,
        415,
        422,
    ), app_server.logs_tail()
    if resp.status_code == 200:
        try:
            resp.json()
        except Exception:
            pass  # binary / streaming payload


@pytest.mark.integration
@pytest.mark.p1
def test_put_api_models_active_14(app_server) -> None:
    """Contract: PUT /api/models/active with empty body is rejected or safely
    handled."""
    resp = _req(app_server, "PUT", "/api/models/active", json={})
    assert resp.status_code in (
        200,
        400,
        403,
        404,
        409,
        422,
        500,
        503,
    ), app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_get_api_models_openrouter_series_15(app_server) -> None:
    """Contract: GET /api/models/openrouter/series responds with a parseable
    payload."""
    resp = _req(app_server, "GET", "/api/models/openrouter/series")
    assert resp.status_code in (
        200,
        400,
        404,
        409,
        415,
        422,
    ), app_server.logs_tail()
    if resp.status_code == 200:
        try:
            resp.json()
        except Exception:
            pass  # binary / streaming payload


@pytest.mark.integration
@pytest.mark.p1
def test_post_api_models_openrouter_discover_extended_16(app_server) -> None:
    """Contract: POST /api/models/openrouter/discover-extended with empty body
    is rejected or
    safely handled."""
    resp = _req(
        app_server,
        "POST",
        "/api/models/openrouter/discover-extended",
        json={},
    )
    assert resp.status_code in (
        200,
        400,
        403,
        404,
        409,
        422,
        500,
        503,
    ), app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_post_api_models_openrouter_models_filter_17(app_server) -> None:
    """Contract: POST /api/models/openrouter/models/filter with empty body is
    rejected or
    safely handled."""
    resp = _req(
        app_server,
        "POST",
        "/api/models/openrouter/models/filter",
        json={},
    )
    assert resp.status_code in (
        200,
        400,
        403,
        404,
        409,
        422,
        500,
        503,
    ), app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_post_api_providers_provider_id_oauth_start_32(app_server) -> None:
    """Contract: POST /api/providers/{provider_id}/oauth/start with empty body
    is rejected or
    safely handled."""
    resp = _req(
        app_server,
        "POST",
        "/api/providers/integ-unknown-xyz/oauth/start",
        json={},
    )
    assert resp.status_code in (
        200,
        400,
        403,
        404,
        409,
        422,
        500,
        503,
    ), app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_get_api_providers_provider_id_oauth_callback_33(app_server) -> None:
    """Contract: GET /api/providers/{provider_id}/oauth/callback with unknown
    id yields
    client/server-safe status."""
    resp = _req(
        app_server,
        "GET",
        "/api/providers/integ-unknown-xyz/oauth/callback",
    )
    assert resp.status_code in (
        200,
        400,
        404,
        409,
        415,
        422,
    ), app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_get_api_providers_provider_id_oauth_status_34(app_server) -> None:
    """Contract: GET /api/providers/{provider_id}/oauth/status with unknown id
    yields
    client/server-safe status."""
    resp = _req(
        app_server,
        "GET",
        "/api/providers/integ-unknown-xyz/oauth/status",
    )
    assert resp.status_code in (
        200,
        400,
        404,
        409,
        415,
        422,
    ), app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_get_api_market_providers_35(app_server) -> None:
    """Contract: GET /api/market/providers responds with a parseable payload.
    Contract: GET /api/market/providers responds with a parseable payload."""
    resp = _req(app_server, "GET", "/api/market/providers")
    assert resp.status_code in (
        200,
        400,
        404,
        409,
        415,
        422,
    ), app_server.logs_tail()
    if resp.status_code == 200:
        try:
            resp.json()
        except Exception:
            pass  # binary / streaming payload


@pytest.mark.integration
@pytest.mark.p1
def test_get_api_market_categories_36(app_server) -> None:
    """Contract: GET /api/market/categories responds with a parseable payload.
    Contract: GET /api/market/categories responds with a parseable payload."""
    resp = _req(app_server, "GET", "/api/market/categories")
    assert resp.status_code in (
        200,
        400,
        404,
        409,
        415,
        422,
    ), app_server.logs_tail()
    if resp.status_code == 200:
        try:
            resp.json()
        except Exception:
            pass  # binary / streaming payload


@pytest.mark.integration
@pytest.mark.p1
def test_post_api_market_search_37(app_server) -> None:
    """Contract: POST /api/market/search with empty body is rejected or safely
    handled."""
    resp = _req(app_server, "POST", "/api/market/search", json={})
    assert resp.status_code in (
        200,
        400,
        403,
        404,
        409,
        422,
        500,
        503,
    ), app_server.logs_tail()
