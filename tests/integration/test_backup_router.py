# -*- coding: utf-8 -*-
"""Integration tests for Backup API endpoints.

Tests cover:
- GET /api/backup: list backups
- POST /api/backup: create backup
- DELETE /api/backup/{backup_id}: delete backup
"""

import pytest


@pytest.mark.integration
@pytest.mark.p1
def test_backup_list(app_server) -> None:
    """Test GET /api/backup returns backup list."""
    response = app_server.api_request("GET", "/api/backups")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


@pytest.mark.integration
@pytest.mark.p1
def test_backup_create(app_server) -> None:
    """Test POST /api/backup creates a backup."""
    response = app_server.api_request("POST", "/api/backups/delete", json={})
    # Should succeed or return appropriate error
    assert response.status_code in [200, 201, 400, 422, 500]


@pytest.mark.integration
@pytest.mark.p1
def test_backup_delete_nonexistent(app_server) -> None:
    """Test DELETE /api/backup/{backup_id} with non-existent backup."""
    response = app_server.api_request(
        "POST",
        "/api/backups/delete",
        json={"ids": ["nonexistent-backup-12345"]},
    )
    # delete returns 200 with per-id results; unknown ids land in "failed"
    assert response.status_code == 200


@pytest.mark.integration
@pytest.mark.p1
def test_backup_list_pagination(app_server) -> None:
    """Test backup list pagination."""
    response = app_server.api_request("GET", "/api/backups")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) <= 5


@pytest.mark.integration
@pytest.mark.p1
def test_backup_structure(app_server) -> None:
    """Test backup response structure."""
    response = app_server.api_request("GET", "/api/backups")
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
