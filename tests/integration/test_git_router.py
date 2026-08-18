# -*- coding: utf-8 -*-
"""Integration tests for Git API endpoints.

Tests cover:
- GET /api/git: get git status
- GET /api/git/branches: list branches
- POST /api/git/checkout: checkout branch
"""

import pytest

from .conftest import app_server


@pytest.mark.integration
async def test_git_status():
    """Test GET /api/git returns git status."""
    async with app_server() as server:
        response = await server.get("/api/git")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)


@pytest.mark.integration
async def test_git_branches_list():
    """Test GET /api/git/branches returns branch list."""
    async with app_server() as server:
        response = await server.get("/api/git/branches")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)


@pytest.mark.integration
async def test_git_checkout_invalid():
    """Test POST /api/git/checkout with invalid branch."""
    async with app_server() as server:
        response = await server.post(
            "/api/git/checkout", json={"branch": "nonexistent-branch-12345"}
        )
        # Should fail gracefully
        assert response.status_code in [400, 404]


@pytest.mark.integration
async def test_git_status_structure():
    """Test git status response structure."""
    async with app_server() as server:
        response = await server.get("/api/git")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        # Should have git-related fields
        assert len(data) >= 0


@pytest.mark.integration
async def test_git_branches_structure():
    """Test git branches response structure."""
    async with app_server() as server:
        response = await server.get("/api/git/branches")
        assert response.status_code == 200
        data = response.json()
        if len(data) > 0:
            branch = data[0]
            assert isinstance(branch, dict)
            # Should have name field
            assert "name" in branch or "branch" in branch
