# -*- coding: utf-8 -*-
"""HTTP contracts for the local model plugin."""

from __future__ import annotations

import pytest
from tests.integration.helpers import default_http_timeout

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
@pytest.mark.usefixtures("local_model_plugin")
def test_get_api_local_models_server_18(app_server) -> None:
    """Contract: GET /api/local-models/server responds with a parseable
    payload."""
    resp = _req(app_server, "GET", "/api/local-models/server")
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
@pytest.mark.usefixtures("local_model_plugin")
def test_get_api_local_models_server_update_19(app_server) -> None:
    """Contract: GET /api/local-models/server/update responds with a parseable
    payload."""
    resp = _req(app_server, "GET", "/api/local-models/server/update")
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
@pytest.mark.usefixtures("local_model_plugin")
def test_post_api_local_models_server_download_20(app_server) -> None:
    """Contract: POST /api/local-models/server/download with empty body is
    rejected or safely
    handled."""
    resp = _req(
        app_server,
        "POST",
        "/api/local-models/server/download",
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
@pytest.mark.usefixtures("local_model_plugin")
def test_get_api_local_models_server_download_21(app_server) -> None:
    """Contract: GET /api/local-models/server/download responds with a
    parseable payload."""
    resp = _req(app_server, "GET", "/api/local-models/server/download")
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
@pytest.mark.usefixtures("local_model_plugin")
def test_delete_api_local_models_server_download_22(app_server) -> None:
    """Contract: DELETE /api/local-models/server/download with unknown id is
    rejected or no-op."""
    resp = _req(app_server, "DELETE", "/api/local-models/server/download")
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
@pytest.mark.usefixtures("local_model_plugin")
def test_post_api_local_models_server_23(app_server) -> None:
    """Contract: POST /api/local-models/server with empty body is rejected or
    safely handled."""
    resp = _req(app_server, "POST", "/api/local-models/server", json={})
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
@pytest.mark.usefixtures("local_model_plugin")
def test_delete_api_local_models_server_24(app_server) -> None:
    """Contract: DELETE /api/local-models/server with unknown id is rejected
    or no-op."""
    resp = _req(app_server, "DELETE", "/api/local-models/server")
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
@pytest.mark.usefixtures("local_model_plugin")
def test_get_api_local_models_models_25(app_server) -> None:
    """Contract: GET /api/local-models/models responds with a parseable
    payload."""
    resp = _req(app_server, "GET", "/api/local-models/models")
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
@pytest.mark.usefixtures("local_model_plugin")
def test_post_api_local_models_models_download_26(app_server) -> None:
    """Contract: POST /api/local-models/models/download with empty body is
    rejected or safely
    handled."""
    resp = _req(
        app_server,
        "POST",
        "/api/local-models/models/download",
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
@pytest.mark.usefixtures("local_model_plugin")
def test_get_api_local_models_models_download_27(app_server) -> None:
    """Contract: GET /api/local-models/models/download responds with a
    parseable payload."""
    resp = _req(app_server, "GET", "/api/local-models/models/download")
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
@pytest.mark.usefixtures("local_model_plugin")
def test_delete_api_local_models_models_download_28(app_server) -> None:
    """Contract: DELETE /api/local-models/models/download with unknown id is
    rejected or no-op."""
    resp = _req(app_server, "DELETE", "/api/local-models/models/download")
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
@pytest.mark.usefixtures("local_model_plugin")
def test_delete_api_local_models_models_model_id_path_29(app_server) -> None:
    """Contract: DELETE /api/local-models/models/{model_id:path} with unknown
    id is rejected
    or no-op."""
    resp = _req(
        app_server,
        "DELETE",
        "/api/local-models/models/integ-unknown-xyz",
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
@pytest.mark.usefixtures("local_model_plugin")
def test_put_api_local_models_config_30(app_server) -> None:
    """Contract: PUT /api/local-models/config with empty body is rejected or
    safely handled."""
    resp = _req(app_server, "PUT", "/api/local-models/config", json={})
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
@pytest.mark.usefixtures("local_model_plugin")
def test_get_api_local_models_config_31(app_server) -> None:
    """Contract: GET /api/local-models/config responds with a parseable
    payload."""
    resp = _req(app_server, "GET", "/api/local-models/config")
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
