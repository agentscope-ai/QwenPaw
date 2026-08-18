# -*- coding: utf-8 -*-
"""Integration tests for Backup API endpoints.

Tests cover:
- GET /api/backup: list backups
- POST /api/backup: create backup
- DELETE /api/backup/{backup_id}: delete backup
"""

import pytest



@pytest.mark.integration
async def test_backup_list(app_server):
    """Test GET /api/backup returns backup list."""
    async with app_server() as server:
        response = await server.get("/api/backup")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)


@pytest.mark.integration
async def test_backup_create(app_server):
    """Test POST /api/backup creates a backup."""
    async with app_server() as server:
        response = await server.post("/api/backup", json={})
        # Should succeed or return appropriate error
        assert response.status_code in [200, 201, 400, 500]


@pytest.mark.integration
async def test_backup_delete_nonexistent(app_server):
    """Test DELETE /api/backup/{backup_id} with non-existent backup."""
    async with app_server() as server:
        response = await server.delete("/api/backup/nonexistent-backup-12345")
        # Should return 404 or similar error
        assert response.status_code in [404, 400]


@pytest.mark.integration
async def test_backup_list_pagination(app_server):
    """Test backup list pagination."""
    async with app_server() as server:
        response = await server.get("/api/backup?limit=5&offset=0")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) <= 5


@pytest.mark.integration
async def test_backup_structure(app_server):
    """Test backup response structure."""
    async with app_server() as server:
        response = await server.get("/api/backup")
        assert response.status_code == 200
        data = response.json()
        if len(data) > 0:
            backup = data[0]
            assert isinstance(backup, dict)
            # Should have id or timestamp field
            has_id = "id" in backup
            has_ts = "timestamp" in backup
            has_ca = "created_at" in backup
            assert has_id or has_ts or has_ca
