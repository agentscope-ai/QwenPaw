# -*- coding: utf-8 -*-
"""Integration tests for the environment variables router.

Covers GET /api/envs (list), PUT /api/envs (batch save), and
DELETE /api/envs/{key} (delete single).
"""

from __future__ import annotations

import json

import pytest
from helpers import default_http_timeout

_ENVS_TIMEOUT = default_http_timeout(15.0)


# ------------------------------------------------------------------ #
# List envs
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_envs_list_returns_array(app_server) -> None:
    """Test purpose:
    - Verify GET /api/envs returns a list of EnvVar objects. Settings
      page renders environment variables from this endpoint.

    Test flow:
    1. GET /api/envs.
    2. Assert 200 and response is a list.

    API endpoints:
    - GET /api/envs
    """
    resp = app_server.api_request(
        "GET",
        "/api/envs",
        timeout=_ENVS_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    payload = resp.json()
    assert isinstance(payload, list)


@pytest.mark.integration
@pytest.mark.p1
def test_envs_list_item_schema(app_server) -> None:
    """Test purpose:
    - Verify each env var entry has key and value fields.

    Test flow:
    1. GET /api/envs.
    2. If entries exist, verify schema.

    API endpoints:
    - GET /api/envs
    """
    resp = app_server.api_request(
        "GET",
        "/api/envs",
        timeout=_ENVS_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    for item in resp.json():
        assert "key" in item
        assert "value" in item
        assert isinstance(item["key"], str)
        assert isinstance(item["value"], str)


# ------------------------------------------------------------------ #
# Batch save
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_envs_batch_save_roundtrip(app_server) -> None:
    """Test purpose:
    - Verify PUT /api/envs saves variables and GET returns them.
      Settings page saves user-configured env vars through this flow.

    Test flow:
    1. PUT /api/envs with test variables.
    2. GET /api/envs and verify they appear.
    3. Clean up by saving empty dict.

    API endpoints:
    - PUT /api/envs
    - GET /api/envs
    """
    test_vars = {
        "INTEG_TEST_VAR_1": "value1",
        "INTEG_TEST_VAR_2": "value2",
    }
    put_resp = app_server.api_request(
        "PUT",
        "/api/envs",
        json=test_vars,
        timeout=_ENVS_TIMEOUT,
    )
    assert put_resp.status_code == 200, (
        put_resp.logs_tail() if hasattr(put_resp, "logs_tail") else ""
    )

    get_resp = app_server.api_request(
        "GET",
        "/api/envs",
        timeout=_ENVS_TIMEOUT,
    )
    assert get_resp.status_code == 200, app_server.logs_tail()
    envs = {item["key"]: item["value"] for item in get_resp.json()}
    assert envs.get("INTEG_TEST_VAR_1") == "value1"
    assert envs.get("INTEG_TEST_VAR_2") == "value2"

    # Clean up
    app_server.api_request(
        "PUT",
        "/api/envs",
        json={},
        timeout=_ENVS_TIMEOUT,
    )


@pytest.mark.integration
@pytest.mark.p1
def test_envs_batch_save_replaces_all(app_server) -> None:
    """Test purpose:
    - Verify PUT /api/envs replaces all variables (not merges).
      Keys not in the new dict are removed.

    Test flow:
    1. PUT with var A.
    2. PUT with var B (no A).
    3. GET and verify only B exists.

    API endpoints:
    - PUT /api/envs
    - GET /api/envs
    """
    # Save var A
    app_server.api_request(
        "PUT",
        "/api/envs",
        json={"INTEG_REPLACE_TEST_A": "a"},
        timeout=_ENVS_TIMEOUT,
    )

    # Save var B (replaces all)
    app_server.api_request(
        "PUT",
        "/api/envs",
        json={"INTEG_REPLACE_TEST_B": "b"},
        timeout=_ENVS_TIMEOUT,
    )

    get_resp = app_server.api_request(
        "GET",
        "/api/envs",
        timeout=_ENVS_TIMEOUT,
    )
    envs = {item["key"]: item["value"] for item in get_resp.json()}
    assert "INTEG_REPLACE_TEST_A" not in envs
    assert envs.get("INTEG_REPLACE_TEST_B") == "b"

    # Clean up
    app_server.api_request(
        "PUT",
        "/api/envs",
        json={},
        timeout=_ENVS_TIMEOUT,
    )


@pytest.mark.integration
@pytest.mark.p1
def test_envs_batch_save_empty_key_rejected(app_server) -> None:
    """Test purpose:
    - Verify PUT /api/envs rejects empty keys.

    Test flow:
    1. PUT with empty key.
    2. Assert 400.

    API endpoints:
    - PUT /api/envs
    """
    resp = app_server.api_request(
        "PUT",
        "/api/envs",
        json={"": "value"},
        timeout=_ENVS_TIMEOUT,
    )
    assert resp.status_code == 400, app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_envs_patch_preserves_omitted_values(app_server) -> None:
    """PATCH merges values instead of replacing the environment store."""
    app_server.api_request(
        "PUT",
        "/api/envs",
        json={"INTEG_PATCH_KEEP": "keep"},
        timeout=_ENVS_TIMEOUT,
    )

    response = app_server.api_request(
        "PATCH",
        "/api/envs",
        json={"INTEG_PATCH_ADD": "add"},
        timeout=_ENVS_TIMEOUT,
    )
    assert response.status_code == 200, app_server.logs_tail()
    envs = {item["key"]: item["value"] for item in response.json()}
    assert envs["INTEG_PATCH_KEEP"] == "keep"
    assert envs["INTEG_PATCH_ADD"] == "add"

    app_server.api_request(
        "PUT",
        "/api/envs",
        json={},
        timeout=_ENVS_TIMEOUT,
    )


@pytest.mark.integration
@pytest.mark.p1
def test_envs_catalog_exposes_runtime_and_readonly_settings(
    app_server,
) -> None:
    """Catalog distinguishes hot settings from initialization defaults."""
    response = app_server.api_request(
        "GET",
        "/api/envs/catalog",
        timeout=_ENVS_TIMEOUT,
    )
    assert response.status_code == 200, app_server.logs_tail()
    specs = {item["key"]: item for item in response.json()}
    assert specs["QWENPAW_LLM_STREAM_IDLE_TIMEOUT"]["editable"] is True
    assert specs["QWENPAW_LLM_MAX_RETRIES"]["editable"] is False
    assert (
        specs["QWENPAW_LLM_MAX_RETRIES"]["readonly_reason_code"]
        == "initial_default"
    )


@pytest.mark.integration
@pytest.mark.p1
def test_envs_reset_removes_persisted_readonly_setting(app_server) -> None:
    """A persisted known setting remains removable after becoming read-only."""
    envs_path = app_server.working_dir.parent / "working.secret" / "envs.json"
    envs_path.write_text(
        json.dumps({"QWENPAW_WORKING_DIR": "/not/active"}),
        encoding="utf-8",
    )

    response = app_server.api_request(
        "POST",
        "/api/envs/QWENPAW_WORKING_DIR/reset",
        timeout=_ENVS_TIMEOUT,
    )

    assert response.status_code == 200, app_server.logs_tail()
    assert response.json() == []


# ------------------------------------------------------------------ #
# Delete single
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_envs_delete_existing(app_server) -> None:
    """Test purpose:
    - Verify DELETE /api/envs/{key} removes a variable.

    Test flow:
    1. PUT a test variable.
    2. DELETE it.
    3. GET and verify it's gone.

    API endpoints:
    - PUT /api/envs
    - DELETE /api/envs/{key}
    - GET /api/envs
    """
    # Create
    app_server.api_request(
        "PUT",
        "/api/envs",
        json={"INTEG_DELETE_TEST": "to_delete"},
        timeout=_ENVS_TIMEOUT,
    )

    # Delete
    del_resp = app_server.api_request(
        "DELETE",
        "/api/envs/INTEG_DELETE_TEST",
        timeout=_ENVS_TIMEOUT,
    )
    assert del_resp.status_code == 200, app_server.logs_tail()

    # Verify gone
    get_resp = app_server.api_request(
        "GET",
        "/api/envs",
        timeout=_ENVS_TIMEOUT,
    )
    envs = {item["key"] for item in get_resp.json()}
    assert "INTEG_DELETE_TEST" not in envs


@pytest.mark.integration
@pytest.mark.p1
def test_envs_delete_nonexistent_404(app_server) -> None:
    """Test purpose:
    - Verify DELETE /api/envs/{nonexistent} returns 404.

    Test flow:
    1. DELETE a key that doesn't exist.
    2. Assert 404.

    API endpoints:
    - DELETE /api/envs/{key}
    """
    resp = app_server.api_request(
        "DELETE",
        "/api/envs/INTEG_NONEXISTENT_KEY_XYZ",
        timeout=_ENVS_TIMEOUT,
    )
    assert resp.status_code == 404, app_server.logs_tail()
