# -*- coding: utf-8 -*-
"""Integration tests for backup APIs (list/get/restore/create/delete)."""
from __future__ import annotations

import json

import pytest

_BACKUP_HTTP_TIMEOUT = 30.0


def _stream_create_backup(app_server, payload: dict) -> dict:
    """POST /api/backups/stream and return the 'meta' dict from the final
    ``done`` event.

    The endpoint emits ``data: {...}\\n\\n`` SSE frames; we walk them until
    a ``done`` event arrives, raising AssertionError on ``error`` events.
    """
    url = f"{app_server.base_url}/api/backups/stream"
    with app_server.client.stream(
        "POST",
        url,
        json=payload,
        timeout=_BACKUP_HTTP_TIMEOUT,
    ) as resp:
        assert resp.status_code == 200, (
            f"create stream returned {resp.status_code}; "
            f"logs: {app_server.logs_tail()}"
        )
        meta: dict | None = None
        for line in resp.iter_lines():
            if not line or not line.startswith("data:"):
                continue
            event = json.loads(line[len("data:") :].strip())
            if event.get("type") == "error":
                raise AssertionError(
                    f"backup create errored: {event} | "
                    f"logs: {app_server.logs_tail()}",
                )
            if event.get("type") == "done":
                meta = event["meta"]
                break
        assert meta is not None, (
            "backup stream ended without a 'done' event; "
            f"logs: {app_server.logs_tail()}"
        )
        return meta


@pytest.mark.integration
@pytest.mark.p0
def test_backup_get_detail_returns_404_for_missing(app_server) -> None:
    """Test purpose:
    - Verify GET /api/backups/{backup_id} returns 404 when the backup id
      is not present, so the console reliably distinguishes missing vs
      malformed backups.

    Test flow:
    1. GET /api/backups/{nonexistent_id}.
    2. Assert 404 status and ``detail`` == ``Backup not found``.

    API endpoints:
    - GET /api/backups/{backup_id}
    """
    resp = app_server.api_request(
        "GET",
        "/api/backups/qwenpaw-missing-integ-0001",
        timeout=_BACKUP_HTTP_TIMEOUT,
    )
    assert resp.status_code == 404, app_server.logs_tail()
    assert resp.json().get("detail") == "Backup not found"


@pytest.mark.integration
@pytest.mark.p0
def test_backup_restore_returns_404_for_missing(app_server) -> None:
    """Test purpose:
    - Verify POST /api/backups/{backup_id}/restore returns 404 when the
      backup id does not exist, preventing silent no-op restores.

    Test flow:
    1. POST /api/backups/{nonexistent_id}/restore with a minimal restore
       body (no agents, no secrets).
    2. Assert 404 status and ``detail`` == ``Backup not found``.

    API endpoints:
    - POST /api/backups/{backup_id}/restore
    """
    resp = app_server.api_request(
        "POST",
        "/api/backups/qwenpaw-missing-integ-0002/restore",
        json={
            "include_agents": False,
            "agent_ids": [],
            "include_global_config": False,
            "include_secrets": False,
            "include_skill_pool": False,
            "mode": "custom",
        },
        timeout=_BACKUP_HTTP_TIMEOUT,
    )
    assert resp.status_code == 404, app_server.logs_tail()
    assert resp.json().get("detail") == "Backup not found"


@pytest.mark.integration
@pytest.mark.p0
def test_backup_create_stream_and_restore_lifecycle(app_server) -> None:
    """Test purpose:
    - Verify the full backup CRUD lifecycle: create via SSE stream, list,
      detail, restore, delete. A regression on any step makes the
      backup/restore feature unusable, so the lifecycle is P0.

    Test flow:
    1. POST /api/backups/stream with a minimal scope (no agents/secrets,
       skill_pool only) and consume SSE events until ``done`` arrives.
    2. Capture ``backup_id`` from the final ``done`` event meta.
    3. GET /api/backups and assert the new id is present in the listing.
    4. GET /api/backups/{backup_id} and assert detail matches the id.
    5. POST /api/backups/{backup_id}/restore with a no-op restore body
       (no agents, no secrets, no global config); assert 200 and
       ``ok`` == True.
    6. POST /api/backups/delete with the id; assert it is reported in
       ``deleted``.
    7. GET /api/backups and assert the id is no longer present.

    API endpoints:
    - POST /api/backups/stream
    - GET /api/backups
    - GET /api/backups/{backup_id}
    - POST /api/backups/{backup_id}/restore
    - POST /api/backups/delete
    """
    create_payload = {
        "name": "integ-backup-lifecycle-01",
        "description": "integration backup lifecycle",
        "scope": {
            "include_agents": False,
            "include_global_config": False,
            "include_secrets": False,
            "include_skill_pool": True,
        },
        "agents": [],
    }
    meta = _stream_create_backup(app_server, create_payload)
    backup_id = meta.get("id")
    assert isinstance(backup_id, str) and backup_id
    assert meta.get("name") == "integ-backup-lifecycle-01"

    try:
        list_resp = app_server.api_request(
            "GET",
            "/api/backups",
            timeout=_BACKUP_HTTP_TIMEOUT,
        )
        assert list_resp.status_code == 200, app_server.logs_tail()
        listed_ids = {item.get("id") for item in list_resp.json()}
        assert backup_id in listed_ids

        detail_resp = app_server.api_request(
            "GET",
            f"/api/backups/{backup_id}",
            timeout=_BACKUP_HTTP_TIMEOUT,
        )
        assert detail_resp.status_code == 200, app_server.logs_tail()
        assert detail_resp.json().get("id") == backup_id

        restore_resp = app_server.api_request(
            "POST",
            f"/api/backups/{backup_id}/restore",
            json={
                "include_agents": False,
                "agent_ids": [],
                "include_global_config": False,
                "include_secrets": False,
                "include_skill_pool": False,
                "mode": "custom",
            },
            timeout=_BACKUP_HTTP_TIMEOUT,
        )
        assert restore_resp.status_code == 200, app_server.logs_tail()
        assert restore_resp.json().get("ok") is True
    finally:
        delete_resp = app_server.api_request(
            "POST",
            "/api/backups/delete",
            json={"ids": [backup_id]},
            timeout=_BACKUP_HTTP_TIMEOUT,
        )
        assert delete_resp.status_code == 200, app_server.logs_tail()
        deleted_payload = delete_resp.json()
        assert backup_id in deleted_payload.get("deleted", [])

        list_after = app_server.api_request(
            "GET",
            "/api/backups",
            timeout=_BACKUP_HTTP_TIMEOUT,
        )
        assert list_after.status_code == 200, app_server.logs_tail()
        remaining = {item.get("id") for item in list_after.json()}
        assert backup_id not in remaining
