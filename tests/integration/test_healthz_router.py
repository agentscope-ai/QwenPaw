# -*- coding: utf-8 -*-
"""Integration tests for Health Check API endpoints.

Tests cover:
- GET /api/healthz: health check
- GET /api/healthz/ready: readiness check
- GET /api/healthz/live: liveness check
"""

import pytest


@pytest.mark.integration
@pytest.mark.p1
def test_healthz(app_server) -> None:
    """Test GET /api/healthz returns health status."""
    response = app_server.api_request("GET", "/api/healthz")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, dict)
    assert "status" in data or "healthy" in data


@pytest.mark.integration
@pytest.mark.p1
def test_healthz_ready(app_server) -> None:
    """Test GET /api/healthz/ready returns readiness status."""
    response = app_server.api_request("GET", "/api/healthz/ready")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, dict)


@pytest.mark.integration
@pytest.mark.p1
def test_healthz_live(app_server) -> None:
    """Test GET /api/healthz/live returns liveness status."""
    response = app_server.api_request("GET", "/api/healthz/live")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, dict)


@pytest.mark.integration
@pytest.mark.p1
def test_healthz_structure(app_server) -> None:
    """Test health check response structure."""
    response = app_server.api_request("GET", "/api/healthz")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, dict)
    # Should have status-related fields
    assert len(data) > 0


@pytest.mark.integration
@pytest.mark.p1
def test_healthz_ready_structure(app_server) -> None:
    """Test readiness check response structure."""
    response = app_server.api_request("GET", "/api/healthz/ready")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, dict)
