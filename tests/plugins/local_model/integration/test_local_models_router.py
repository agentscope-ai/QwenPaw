# -*- coding: utf-8 -*-
"""Integration tests for Local Models API endpoints.

Tests cover:
- GET /api/local-models: list local models
- GET /api/local-models/{model_id}: get model details
- POST /api/local-models/download: download model
"""

import pytest

pytestmark = pytest.mark.usefixtures("local_model_plugin")


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
def test_local_models_list_preserves_decision_roles(app_server) -> None:
    """The catalog is unpaginated and must preserve decision model roles."""
    response = app_server.api_request("GET", "/api/local-models/models")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len({model["id"] for model in data}) == len(data)
    for model in data:
        if model["id"].startswith("agentscope-ai/Piccolo-"):
            assert model["model_type"] == "decision"
            assert model["source"] == "huggingface"


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


@pytest.mark.integration
@pytest.mark.p1
def test_local_server_status_reports_accelerator_fields(app_server) -> None:
    """The local status payload exposes accelerator metadata."""
    response = app_server.api_request("GET", "/api/local-models/server")
    assert response.status_code == 200
    data = response.json()
    for field in ("accelerator", "device_name", "version"):
        assert field in data


@pytest.mark.integration
@pytest.mark.p1
def test_local_model_config_auto_update_round_trip(app_server) -> None:
    """The auto-update preference is exposed and persisted."""
    response = app_server.api_request(
        "PUT",
        "/api/local-models/config",
        json={"auto_update": False},
    )
    assert response.status_code == 200

    config = app_server.api_request("GET", "/api/local-models/config")
    assert config.status_code == 200
    data = config.json()
    assert data["auto_update"] is False
    assert data["gpu_acceleration"] is True

    restore = app_server.api_request(
        "PUT",
        "/api/local-models/config",
        json={"auto_update": True},
    )
    assert restore.status_code == 200
