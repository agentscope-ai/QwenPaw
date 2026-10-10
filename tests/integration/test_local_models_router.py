# -*- coding: utf-8 -*-
"""Integration tests for Local Models API endpoints.

Tests cover:
- GET /api/local-models: list local models
- GET /api/local-models/{model_id}: get model details
- POST /api/local-models/download: download model
"""

import pytest


@pytest.mark.integration
@pytest.mark.p1
def test_local_models_list(app_server) -> None:
    """Test GET /api/local-models returns model list."""
    response = app_server.api_request("GET", "/api/local-models/models")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


@pytest.mark.integration
@pytest.mark.p1
def test_local_models_get_nonexistent(app_server) -> None:
    """Test GET /api/local-models/{model_id} with non-existent model."""
    url = "/api/local-models/nonexistent-model-12345"
    response = app_server.api_request("GET", url)
    # Should return 404 or similar error
    assert response.status_code in [404, 400]


@pytest.mark.integration
@pytest.mark.p1
def test_local_models_download_invalid(app_server) -> None:
    """Test POST /api/local-models/download with invalid model."""
    response = app_server.api_request(
        "POST",
        "/api/local-models/models/download",
        json={"model_id": "no-such-model"},
    )
    # Should fail gracefully
    assert response.status_code in [400, 404, 422]


@pytest.mark.integration
@pytest.mark.p1
def test_local_models_list_pagination(app_server) -> None:
    """Test local models list pagination."""
    response = app_server.api_request("GET", "/api/local-models/models")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) <= 5


@pytest.mark.integration
@pytest.mark.p1
def test_local_models_structure(app_server) -> None:
    """Test local model response structure."""
    response = app_server.api_request("GET", "/api/local-models/models")
    assert response.status_code == 200
    data = response.json()
    if len(data) > 0:
        model = data[0]
        assert isinstance(model, dict)
        # Should have id or name field
        assert "id" in model or "name" in model


@pytest.mark.integration
@pytest.mark.p1
def test_local_models_download_missing_id(app_server) -> None:
    """Test POST /api/local-models/download without model_id."""
    response = app_server.api_request(
        "POST",
        "/api/local-models/models/download",
        json={},
    )
    # Should return 400 or 422
    assert response.status_code in [400, 422]
