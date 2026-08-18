# -*- coding: utf-8 -*-
"""Integration tests for Coding Mode API endpoints.

Tests cover:
- GET /api/coding-mode: retrieve coding mode state
- POST /api/coding-mode: toggle coding mode on/off
"""
import pytest

from .conftest import app_server


@pytest.mark.integration
async def test_coding_mode_get_default():
    """Test GET /api/coding-mode returns default state."""
    async with app_server() as server:
        response = await server.get("/api/coding-mode")
        assert response.status_code == 200
        data = response.json()
        assert "enabled" in data
        assert "agent_id" in data
        assert isinstance(data["enabled"], bool)


@pytest.mark.integration
async def test_coding_mode_toggle_enable():
    """Test POST /api/coding-mode to enable coding mode."""
    async with app_server() as server:
        # Enable coding mode
        response = await server.post("/api/coding-mode", json={"enabled": True})
        assert response.status_code == 200
        data = response.json()
        assert data["enabled"] is True
        
        # Verify state persisted
        get_response = await server.get("/api/coding-mode")
        assert get_response.status_code == 200
        assert get_response.json()["enabled"] is True


@pytest.mark.integration
async def test_coding_mode_toggle_disable():
    """Test POST /api/coding-mode to disable coding mode."""
    async with app_server() as server:
        # First enable
        await server.post("/api/coding-mode", json={"enabled": True})
        
        # Then disable
        response = await server.post("/api/coding-mode", json={"enabled": False})
        assert response.status_code == 200
        data = response.json()
        assert data["enabled"] is False
        
        # Verify state persisted
        get_response = await server.get("/api/coding-mode")
        assert get_response.status_code == 200
        assert get_response.json()["enabled"] is False


@pytest.mark.integration
async def test_coding_mode_toggle_idempotent():
    """Test toggling to same state is idempotent."""
    async with app_server() as server:
        # Enable twice
        response1 = await server.post("/api/coding-mode", json={"enabled": True})
        response2 = await server.post("/api/coding-mode", json={"enabled": True})
        
        assert response1.status_code == 200
        assert response2.status_code == 200
        assert response1.json()["enabled"] == response2.json()["enabled"]


@pytest.mark.integration
async def test_coding_mode_invalid_request():
    """Test POST /api/coding-mode with invalid request body."""
    async with app_server() as server:
        # Missing 'enabled' field
        response = await server.post("/api/coding-mode", json={})
        assert response.status_code == 422


@pytest.mark.integration
async def test_coding_mode_agent_isolation():
    """Test coding mode is per-agent."""
    async with app_server() as server:
        # Enable for default agent
        response = await server.post("/api/coding-mode", json={"enabled": True})
        assert response.status_code == 200
        agent_id = response.json()["agent_id"]
        
        # Verify state
        get_response = await server.get("/api/coding-mode")
        assert get_response.json()["agent_id"] == agent_id
        assert get_response.json()["enabled"] is True
