# -*- coding: utf-8 -*-
"""Integration tests for Local Models API endpoints.

Tests cover:
- GET /api/local-models: list local models
- GET /api/local-models/{model_id}: get model details
- POST /api/local-models/download: download model
"""

import pytest

from conftest import app_server


@pytest.mark.integration
async def test_local_models_list():
    """Test GET /api/local-models returns model list."""
    async with app_server() as server:
        response = await server.get("/api/local-models")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)


@pytest.mark.integration
async def test_local_models_get_nonexistent():
    """Test GET /api/local-models/{model_id} with non-existent model."""
    async with app_server() as server:
        url = "/api/local-models/nonexistent-model-12345"
        response = await server.get(url)
        # Should return 404 or similar error
        assert response.status_code in [404, 400]


@pytest.mark.integration
async def test_local_models_download_invalid():
    """Test POST /api/local-models/download with invalid model."""
    async with app_server() as server:
        response = await server.post(
            "/api/local-models/download",
            json={"model_id": "no-such-model"},
        )
        # Should fail gracefully
        assert response.status_code in [400, 404, 422]


@pytest.mark.integration
async def test_local_models_list_pagination():
    """Test local models list pagination."""
    async with app_server() as server:
        response = await server.get("/api/local-models?limit=5&offset=0")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) <= 5


@pytest.mark.integration
async def test_local_models_structure():
    """Test local model response structure."""
    async with app_server() as server:
        response = await server.get("/api/local-models")
        assert response.status_code == 200
        data = response.json()
        if len(data) > 0:
            model = data[0]
            assert isinstance(model, dict)
            # Should have id or name field
            assert "id" in model or "name" in model


@pytest.mark.integration
async def test_local_models_download_missing_id():
    """Test POST /api/local-models/download without model_id."""
    async with app_server() as server:
        response = await server.post("/api/local-models/download", json={})
        # Should return 400 or 422
        assert response.status_code in [400, 422]
