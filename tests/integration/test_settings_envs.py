# -*- coding: utf-8 -*-
"""Integration tests for settings and env management APIs."""
from __future__ import annotations


def test_settings_language_default_en(app_server) -> None:
    """Language should default to English in a fresh workspace."""
    response = app_server.api_request("GET", "/api/settings/language")
    assert response.status_code == 200, app_server.logs_tail()
    assert response.json() == {"language": "en"}


def test_settings_language_put_get_roundtrip(app_server) -> None:
    """PUT language should persist and be visible in next GET."""
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


def test_settings_language_reject_invalid(app_server) -> None:
    """Invalid language should return 400 with meaningful message."""
    response = app_server.api_request(
        "PUT",
        "/api/settings/language",
        json={"language": "xx"},
    )
    assert response.status_code == 400, app_server.logs_tail()
    detail = response.json().get("detail", "")
    assert "Invalid language" in detail


def test_envs_put_get_roundtrip(app_server) -> None:
    """Batch PUT should replace envs and GET should return saved entries."""
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


def test_envs_delete_key(app_server) -> None:
    """Deleting an existing env key should remove it from stored envs."""
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
