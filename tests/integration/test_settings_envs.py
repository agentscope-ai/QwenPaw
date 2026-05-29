# -*- coding: utf-8 -*-
"""Integration tests for settings and env management APIs."""
from __future__ import annotations

import pytest


@pytest.mark.integration
@pytest.mark.p1
def test_settings_language_default_en(app_server) -> None:
    """Test purpose:
    - Verify the default language value in a fresh workspace.

    Test flow:
    1. Read language settings.
    2. Assert status is 200 and value is ``en``.

    API endpoints:
    - GET /api/settings/language
    """
    response = app_server.api_request("GET", "/api/settings/language")
    assert response.status_code == 200, app_server.logs_tail()
    assert response.json() == {"language": "en"}


@pytest.mark.integration
@pytest.mark.p1
def test_settings_language_put_get_roundtrip(app_server) -> None:
    """Test purpose:
    - Verify language updates persist and can be read back.

    Test flow:
    1. PUT language=zh.
    2. Assert PUT returns 200 and ``{"language": "zh"}``.
    3. GET again and verify value is still ``zh``.

    API endpoints:
    - PUT /api/settings/language
    - GET /api/settings/language
    """
    put_response = app_server.api_request(
        "PUT",
        "/api/settings/language",
        json={"language": "zh"},
    )
    assert put_response.status_code == 200, app_server.logs_tail()
    assert put_response.json() == {"language": "zh"}

    get_response = app_server.api_request("GET", "/api/settings/language")
    assert get_response.status_code == 200, app_server.logs_tail()
    assert get_response.json() == {"language": "zh"}


@pytest.mark.integration
@pytest.mark.p2
def test_settings_language_reject_invalid(app_server) -> None:
    """Test purpose:
    - Verify invalid language values are rejected with a readable error.

    Test flow:
    1. PUT an invalid language value (xx).
    2. Assert status is 400.
    3. Assert ``detail`` contains ``Invalid language``.

    API endpoints:
    - PUT /api/settings/language
    """
    response = app_server.api_request(
        "PUT",
        "/api/settings/language",
        json={"language": "xx"},
    )
    assert response.status_code == 400, app_server.logs_tail()
    detail = response.json().get("detail", "")
    assert "Invalid language" in detail


@pytest.mark.integration
@pytest.mark.p0
def test_envs_put_get_roundtrip(app_server) -> None:
    """Test purpose:
    - Verify batch env writes can be fully read back.

    Test flow:
    1. PUT two env entries.
    2. Assert PUT returns a list with expected count.
    3. GET env list and verify key/value pairs match.

    API endpoints:
    - PUT /api/envs
    - GET /api/envs
    """
    put_response = app_server.api_request(
        "PUT",
        "/api/envs",
        json={"INTEGRATION_TEST_KEY": "value_1", "ANOTHER_KEY": "value_2"},
    )
    assert put_response.status_code == 200, app_server.logs_tail()
    saved_items = put_response.json()
    assert isinstance(saved_items, list)
    assert len(saved_items) == 2

    get_response = app_server.api_request("GET", "/api/envs")
    assert get_response.status_code == 200, app_server.logs_tail()
    items = get_response.json()
    item_map = {item["key"]: item["value"] for item in items}
    assert item_map["INTEGRATION_TEST_KEY"] == "value_1"
    assert item_map["ANOTHER_KEY"] == "value_2"


@pytest.mark.integration
@pytest.mark.p2
def test_envs_delete_key(app_server) -> None:
    """Test purpose:
    - Verify deleting one env key does not affect other keys.

    Test flow:
    1. Seed envs with DELETE_ME and KEEP_ME.
    2. DELETE DELETE_ME.
    3. Assert DELETE_ME is removed while KEEP_ME remains.

    API endpoints:
    - PUT /api/envs
    - DELETE /api/envs/{key}
    """
    seed_response = app_server.api_request(
        "PUT",
        "/api/envs",
        json={"DELETE_ME": "x", "KEEP_ME": "y"},
    )
    assert seed_response.status_code == 200, app_server.logs_tail()

    delete_response = app_server.api_request("DELETE", "/api/envs/DELETE_ME")
    assert delete_response.status_code == 200, app_server.logs_tail()
    item_map = {item["key"]: item["value"] for item in delete_response.json()}
    assert "DELETE_ME" not in item_map
    assert item_map["KEEP_ME"] == "y"
