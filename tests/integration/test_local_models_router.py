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
def test_local_engines_endpoint_lists_llamacpp_and_mlx(app_server) -> None:
    """The engine catalog always exposes both built-in engines."""
    response = app_server.api_request("GET", "/api/local-models/engines")
    assert response.status_code == 200
    engines = response.json()
    assert {engine["id"] for engine in engines} == {"llamacpp", "mlx"}
    for engine in engines:
        assert "installable" in engine
        assert "installed" in engine
        assert "accelerator" in engine
        assert "device_name" in engine
        assert "version" in engine


@pytest.mark.integration
@pytest.mark.p1
def test_local_model_config_auto_update_round_trip(app_server) -> None:
    """The auto-update preference is exposed and persisted."""
    response = app_server.api_request(
        "PUT",
        "/api/local-models/config",
        json={"auto_update": True},
    )
    assert response.status_code == 200

    config = app_server.api_request("GET", "/api/local-models/config")
    assert config.status_code == 200
    assert config.json()["auto_update"] is True

    app_server.api_request(
        "PUT",
        "/api/local-models/config",
        json={"auto_update": False},
    )


@pytest.mark.integration
@pytest.mark.p1
def test_local_server_rejects_unknown_engine(app_server) -> None:
    """An unknown engine id is a client error, not a silent fallback."""
    response = app_server.api_request(
        "GET",
        "/api/local-models/server?engine=cuda",
    )
    assert response.status_code == 400
