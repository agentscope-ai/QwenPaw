# -*- coding: utf-8 -*-
"""Integration tests for Coding Mode API endpoints.

Tests cover:
- GET /api/coding-mode: retrieve coding mode state
- POST /api/coding-mode: toggle coding mode on/off
"""

import pytest


@pytest.mark.integration
@pytest.mark.p1
def test_coding_mode_get_default(app_server) -> None:
    """Test GET /api/coding-mode returns default state."""
    response = app_server.api_request("GET", "/api/coding-mode")
    assert response.status_code == 200
    data = response.json()
    assert "enabled" in data
    assert "agent_id" in data
    assert isinstance(data["enabled"], bool)


@pytest.mark.integration
@pytest.mark.p1
def test_coding_mode_toggle_enable(app_server) -> None:
    """Test POST /api/coding-mode to enable coding mode."""
    # Enable coding mode
    payload = {"enabled": True}
    response = app_server.api_request("POST", "/api/coding-mode", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["enabled"] is True

    # Verify state persisted
    get_response = app_server.api_request("GET", "/api/coding-mode")
    assert get_response.status_code == 200
    assert get_response.json()["enabled"] is True


@pytest.mark.integration
@pytest.mark.p1
def test_coding_mode_toggle_disable(app_server) -> None:
    """Test POST /api/coding-mode to disable coding mode."""
    # First enable
    app_server.api_request("POST", "/api/coding-mode", json={"enabled": True})

    # Then disable
    payload = {"enabled": False}
    response = app_server.api_request("POST", "/api/coding-mode", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["enabled"] is False

    # Verify state persisted
    get_response = app_server.api_request("GET", "/api/coding-mode")
    assert get_response.status_code == 200
    assert get_response.json()["enabled"] is False


@pytest.mark.integration
@pytest.mark.p1
def test_coding_mode_toggle_idempotent(app_server) -> None:
    """Test toggling to same state is idempotent."""
    # Enable twice
    payload = {"enabled": True}
    response1 = app_server.api_request(
        "POST",
        "/api/coding-mode",
        json=payload,
    )
    response2 = app_server.api_request(
        "POST",
        "/api/coding-mode",
        json=payload,
    )

    assert response1.status_code == 200
    assert response2.status_code == 200
    assert response1.json()["enabled"] == response2.json()["enabled"]


@pytest.mark.integration
@pytest.mark.p1
def test_coding_mode_invalid_request(app_server) -> None:
    """Test POST /api/coding-mode with invalid request body."""
    # Missing 'enabled' field
    response = app_server.api_request("POST", "/api/coding-mode", json={})
    assert response.status_code == 422


@pytest.mark.integration
@pytest.mark.p1
def test_coding_mode_agent_isolation(app_server) -> None:
    """Test coding mode is per-agent."""
    # Enable for default agent
    payload = {"enabled": True}
    response = app_server.api_request("POST", "/api/coding-mode", json=payload)
    assert response.status_code == 200
    agent_id = response.json()["agent_id"]

    # Verify state
    get_response = app_server.api_request("GET", "/api/coding-mode")
    assert get_response.json()["agent_id"] == agent_id
    assert get_response.json()["enabled"] is True
