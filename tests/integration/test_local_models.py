# -*- coding: utf-8 -*-
"""Integration tests for the local-model (llama.cpp) router."""
from __future__ import annotations

import pytest

_LOCAL_MODELS_HTTP_TIMEOUT = 15.0


@pytest.mark.integration
@pytest.mark.p1
def test_local_models_server_status_returns_contract(app_server) -> None:
    """Test purpose:
    - Verify GET /api/local-models/server returns the ServerStatus
      contract: the three boolean fields (available / installable /
      installed) are always present so the Console can render the
      local-model dashboard regardless of whether llama.cpp is installed.

    Test flow:
    1. GET /api/local-models/server.
    2. Assert 200 and the response contains the three boolean keys with
       boolean values.

    API endpoints:
    - GET /api/local-models/server
    """
    resp = app_server.api_request(
        "GET",
        "/api/local-models/server",
        timeout=_LOCAL_MODELS_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    payload = resp.json()
    for key in ("available", "installable", "installed"):
        assert key in payload, f"missing key: {key}"
        assert isinstance(payload[key], bool)


@pytest.mark.integration
@pytest.mark.p1
def test_local_models_models_list_returns_array(app_server) -> None:
    """Test purpose:
    - Verify GET /api/local-models/models returns an array of models
      (recommended + downloaded). Console populates the local-model
      picker from this list; a regression hides every local model.

    Test flow:
    1. GET /api/local-models/models.
    2. Assert 200 and the body is a list (may be empty in environments
       where neither recommendations nor downloaded models exist).

    API endpoints:
    - GET /api/local-models/models
    """
    resp = app_server.api_request(
        "GET",
        "/api/local-models/models",
        timeout=_LOCAL_MODELS_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    assert isinstance(resp.json(), list)


@pytest.mark.integration
@pytest.mark.p2
def test_local_models_delete_unknown_model_returns_404(app_server) -> None:
    """Test purpose:
    - Verify DELETE /api/local-models/models/{model_id:path} returns 404
      with a descriptive detail when the model has never been downloaded,
      so Console can surface a clear error to the user.

    Test flow:
    1. DELETE /api/local-models/models/<unknown-id>.
    2. Assert 404 status and a non-empty detail field.

    API endpoints:
    - DELETE /api/local-models/models/{model_id:path}
    """
    unknown_id = "integ-unknown-model-xyz"
    resp = app_server.api_request(
        "DELETE",
        f"/api/local-models/models/{unknown_id}",
        timeout=_LOCAL_MODELS_HTTP_TIMEOUT,
    )
    assert resp.status_code == 404, app_server.logs_tail()
    assert isinstance(resp.json().get("detail"), str) and resp.json()["detail"]


# ------------------------------------------------------------------ #
# Sprint 3.1-D additions
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p2
def test_local_models_config_roundtrip(app_server) -> None:
    """Test purpose:
    - Verify PUT /api/local-models/config persists max_context_length and
      GET returns the updated value.

    Test flow:
    1. GET baseline config.
    2. PUT a new max_context_length (must be >= 32768 per validator).
    3. GET and assert the new value is returned.
    4. Restore baseline.

    API endpoints:
    - GET /api/local-models/config
    - PUT /api/local-models/config
    """
    get_resp = app_server.api_request(
        "GET",
        "/api/local-models/config",
        timeout=_LOCAL_MODELS_HTTP_TIMEOUT,
    )
    assert get_resp.status_code == 200, app_server.logs_tail()
    baseline = get_resp.json()
    assert isinstance(baseline, dict), baseline
    original_ctx = baseline.get("max_context_length")

    new_ctx = 65536 if original_ctx != 65536 else 98304
    try:
        put_resp = app_server.api_request(
            "PUT",
            "/api/local-models/config",
            json={"max_context_length": new_ctx},
            timeout=_LOCAL_MODELS_HTTP_TIMEOUT,
        )
        assert put_resp.status_code == 200, app_server.logs_tail()
        assert put_resp.json().get("status") == "ok", put_resp.json()

        get_after = app_server.api_request(
            "GET",
            "/api/local-models/config",
            timeout=_LOCAL_MODELS_HTTP_TIMEOUT,
        )
        body = get_after.json()
        assert (
            body.get("max_context_length") == new_ctx
        ), f"max_context_length not persisted: {body}"
    finally:
        if original_ctx is not None:
            app_server.api_request(
                "PUT",
                "/api/local-models/config",
                json={"max_context_length": original_ctx},
                timeout=_LOCAL_MODELS_HTTP_TIMEOUT,
            )


@pytest.mark.integration
@pytest.mark.p2
def test_local_models_server_update_info_contract(app_server) -> None:
    """Test purpose:
    - Verify GET /api/local-models/server/update returns a structured
      response so Console can decide whether to prompt the user about
      a server upgrade. Endpoint must respond 200 even when no update is
      pending.

    Test flow:
    1. GET /api/local-models/server/update.
    2. Assert 200 and the response is a dict.

    API endpoints:
    - GET /api/local-models/server/update
    """
    resp = app_server.api_request(
        "GET",
        "/api/local-models/server/update",
        timeout=_LOCAL_MODELS_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    body = resp.json()
    assert isinstance(body, dict), body
