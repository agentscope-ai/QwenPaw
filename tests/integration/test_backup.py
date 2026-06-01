# -*- coding: utf-8 -*-
"""Integration tests for backup APIs (list/get/restore/create/delete/
export/import).
"""
from __future__ import annotations

import io
import json
import zipfile

import pytest

_BACKUP_HTTP_TIMEOUT = 30.0


# --------------------------------------------------------------------------- #
# shared helpers for export / import cases
# --------------------------------------------------------------------------- #


_DEFAULT_BACKUP_PAYLOAD = {
    "scope": {
        "include_agents": False,
        "include_global_config": False,
        "include_secrets": False,
        "include_skill_pool": True,
    },
    "agents": [],
}


def _create_backup(app_server, *, name: str, description: str = "") -> str:
    """Create a minimal backup via stream and return its id."""
    payload = dict(_DEFAULT_BACKUP_PAYLOAD)
    payload["name"] = name
    payload["description"] = description or f"integration backup {name}"
    meta = _stream_create_backup(app_server, payload)
    backup_id = meta.get("id")
    assert isinstance(backup_id, str) and backup_id
    return backup_id


def _delete_backup(app_server, backup_id: str) -> None:
    """Best-effort backup delete used by finally blocks."""
    app_server.api_request(
        "POST",
        "/api/backups/delete",
        json={"ids": [backup_id]},
        timeout=_BACKUP_HTTP_TIMEOUT,
    )


def _export_backup_bytes(app_server, backup_id: str) -> bytes:
    """Hit the export endpoint and return the raw zip bytes."""
    resp = app_server.api_request(
        "GET",
        f"/api/backups/{backup_id}/export",
        timeout=_BACKUP_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    assert "zip" in resp.headers.get("content-type", "").lower()
    return resp.content


def _list_backup_ids(app_server) -> set[str]:
    resp = app_server.api_request(
        "GET",
        "/api/backups",
        timeout=_BACKUP_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    return {item.get("id") for item in resp.json()}


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


# --------------------------------------------------------------------------- #
# Sprint 1.3 — export + import coverage
# --------------------------------------------------------------------------- #


@pytest.mark.integration
@pytest.mark.p1
def test_backup_export_returns_404_for_missing(app_server) -> None:
    """Test purpose:
    - Verify GET /api/backups/{backup_id}/export returns 404 when the
      backup id does not exist, so Console can tell a real export error
      apart from a silent failure.

    Test flow:
    1. GET /api/backups/<synthetic-missing>/export.
    2. Assert 404 + ``detail`` == "Backup not found".

    API endpoints:
    - GET /api/backups/{backup_id}/export
    """
    resp = app_server.api_request(
        "GET",
        "/api/backups/qwenpaw-missing-export-integ-0001/export",
        timeout=_BACKUP_HTTP_TIMEOUT,
    )
    assert resp.status_code == 404, app_server.logs_tail()
    assert resp.json().get("detail") == "Backup not found"


@pytest.mark.integration
@pytest.mark.p1
def test_backup_export_returns_valid_zip_with_manifest(app_server) -> None:
    """Test purpose:
    - Verify export returns a real zip stream whose archive contains
      the backup manifest. Console relies on the manifest entry to
      validate the archive client-side before triggering a restore.

    Test flow:
    1. Create a backup via stream; capture ``backup_id``.
    2. GET export and assert the response Content-Type is zip.
    3. Open response bytes with ``zipfile.ZipFile``; assert it parses
       and includes a backup.json / manifest.json file with the same
       ``backup_id``.
    4. finally — delete the backup.

    API endpoints:
    - POST /api/backups/stream
    - GET /api/backups/{backup_id}/export
    - POST /api/backups/delete
    """
    backup_id = _create_backup(app_server, name="integ-export-zip-01")
    try:
        zip_bytes = _export_backup_bytes(app_server, backup_id)
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            names = zf.namelist()
            # Manifest filename is implementation-defined; accept the
            # common shapes (backup.json / manifest.json) and verify the
            # backup_id appears somewhere in its contents.
            # Real archives store the manifest as ``meta.json`` at the
            # root; keep the alternatives accepted in case the layout
            # evolves (manifest.json / backup.json).
            manifest_name = next(
                (
                    n
                    for n in names
                    if n.endswith(
                        ("meta.json", "manifest.json", "backup.json"),
                    )
                ),
                None,
            )
            assert manifest_name is not None, f"no manifest in zip: {names}"
            manifest_text = zf.read(manifest_name).decode("utf-8")
            assert (
                backup_id in manifest_text
            ), f"backup_id missing from manifest: {manifest_text[:200]}"
    finally:
        _delete_backup(app_server, backup_id)


@pytest.mark.integration
@pytest.mark.p0
def test_backup_export_delete_import_restores_same_backup(app_server) -> None:
    """Test purpose:
    - Verify the disaster-recovery path: a user accidentally deletes a
      backup, then imports the previously-downloaded zip to recover it.
      The recovered backup keeps the same id (manifest-driven), so the
      restore flow afterwards behaves identically.

    Test flow:
    1. Create backup A; export it (zip bytes).
    2. Delete A; assert A is no longer in the list.
    3. POST /api/backups/import as multipart with the zip bytes.
    4. Assert 200 and the returned BackupMeta keeps id == A's id.
    5. GET /api/backups; assert A is back in the list.
    6. finally — delete A.

    API endpoints:
    - POST /api/backups/stream
    - GET /api/backups/{backup_id}/export
    - POST /api/backups/delete
    - POST /api/backups/import
    - GET /api/backups
    """
    backup_id = _create_backup(app_server, name="integ-recovery-01")
    try:
        zip_bytes = _export_backup_bytes(app_server, backup_id)

        _delete_backup(app_server, backup_id)
        assert backup_id not in _list_backup_ids(app_server)

        import_resp = app_server.api_request(
            "POST",
            "/api/backups/import",
            files={
                "file": (
                    f"{backup_id}.zip",
                    zip_bytes,
                    "application/zip",
                ),
            },
            timeout=_BACKUP_HTTP_TIMEOUT,
        )
        assert import_resp.status_code == 200, app_server.logs_tail()
        meta = import_resp.json()
        assert meta.get("id") == backup_id

        assert backup_id in _list_backup_ids(app_server)
    finally:
        _delete_backup(app_server, backup_id)


@pytest.mark.integration
@pytest.mark.p2
def test_backup_import_no_file_returns_400(app_server) -> None:
    """Test purpose:
    - Verify POST /api/backups/import with neither ``file`` nor
      ``pending_token`` returns 400, preventing silent no-op imports.

    Test flow:
    1. POST /api/backups/import with an empty multipart body
       (no file, no token).
    2. Assert 400 + ``detail`` == "file is required".

    API endpoints:
    - POST /api/backups/import
    """
    resp = app_server.api_request(
        "POST",
        "/api/backups/import",
        files={"_": ("placeholder", b"", "text/plain")},
        timeout=_BACKUP_HTTP_TIMEOUT,
    )
    # Some httpx builds collapse an entirely-empty multipart body, hence
    # the throwaway placeholder above. The server still sees no ``file``
    # form field and should reject.
    assert resp.status_code == 400, app_server.logs_tail()
    assert resp.json().get("detail") == "file is required"


@pytest.mark.integration
@pytest.mark.p2
def test_backup_import_non_zip_content_type_returns_400(app_server) -> None:
    """Test purpose:
    - Verify upload with a non-zip Content-Type is rejected with 400
      before the server tries to parse the archive, so a stray .txt
      upload doesn't waste cycles on extraction.

    Test flow:
    1. POST /api/backups/import multipart file with
       Content-Type=text/plain.
    2. Assert 400 + ``detail`` containing "Expected a zip file".

    API endpoints:
    - POST /api/backups/import
    """
    resp = app_server.api_request(
        "POST",
        "/api/backups/import",
        files={
            "file": (
                "not_a_backup.txt",
                b"this is plain text, not a zip",
                "text/plain",
            ),
        },
        timeout=_BACKUP_HTTP_TIMEOUT,
    )
    assert resp.status_code == 400, app_server.logs_tail()
    assert "Expected a zip file" in resp.json().get("detail", "")


@pytest.mark.integration
@pytest.mark.p2
def test_backup_import_corrupted_zip_returns_400(app_server) -> None:
    """Test purpose:
    - Verify a payload that *claims* to be a zip but is not parseable
      yields a 400 (via BackupValidationError) rather than a 500.

    Test flow:
    1. POST /api/backups/import with random bytes labelled
       ``application/zip`` and a .zip filename.
    2. Assert 400 (extraction / validation rejection).

    API endpoints:
    - POST /api/backups/import
    """
    resp = app_server.api_request(
        "POST",
        "/api/backups/import",
        files={
            "file": (
                "corrupted.zip",
                b"\x00\x01\x02 not a zip body \x03\x04\x05",
                "application/zip",
            ),
        },
        timeout=_BACKUP_HTTP_TIMEOUT,
    )
    assert resp.status_code == 400, app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_backup_import_conflict_returns_409_with_pending_token(
    app_server,
) -> None:
    """Test purpose:
    - Verify importing a zip whose backup_id is already present returns
      409 with a ``pending_token`` and the existing meta, so the client
      can prompt the user "overwrite?" without re-uploading the file.

    Test flow:
    1. Create backup A; export it (zip bytes).
    2. POST /api/backups/import the exported zip (A is still on the
       server).
    3. Assert 409, the response JSON contains ``pending_token`` and
       ``existing`` whose id matches A.
    4. finally — delete A. The temp pending upload may stay behind; the
       app's _cleanup_stale_uploads will eventually reap it.

    API endpoints:
    - POST /api/backups/stream
    - GET /api/backups/{backup_id}/export
    - POST /api/backups/import
    - POST /api/backups/delete
    """
    backup_id = _create_backup(app_server, name="integ-conflict-01")
    try:
        zip_bytes = _export_backup_bytes(app_server, backup_id)

        resp = app_server.api_request(
            "POST",
            "/api/backups/import",
            files={
                "file": (
                    f"{backup_id}.zip",
                    zip_bytes,
                    "application/zip",
                ),
            },
            timeout=_BACKUP_HTTP_TIMEOUT,
        )
        assert resp.status_code == 409, app_server.logs_tail()
        payload = resp.json()
        assert isinstance(payload.get("pending_token"), str)
        assert payload["pending_token"]
        existing = payload.get("existing") or {}
        assert existing.get("id") == backup_id
    finally:
        _delete_backup(app_server, backup_id)


@pytest.mark.integration
@pytest.mark.p1
def test_backup_import_with_pending_token_completes_overwrite(
    app_server,
) -> None:
    """Test purpose:
    - Verify the two-step overwrite flow: after a 409 the client can
      POST again with only the ``pending_token`` (no re-upload) to
      commit the overwrite. Console's "import and overwrite" button
      exercises this exact sequence.

    Test flow:
    1. Create backup A; export it (zip bytes).
    2. POST import — expect 409 and capture pending_token.
    3. POST import again as form-encoded body containing only
       ``pending_token`` (no ``file`` field).
    4. Assert 200, returned BackupMeta has id == A.
    5. GET /api/backups; assert A still present (overwrite, not delete).
    6. finally — delete A.

    API endpoints:
    - POST /api/backups/stream
    - GET /api/backups/{backup_id}/export
    - POST /api/backups/import (×2)
    - GET /api/backups
    - POST /api/backups/delete
    """
    backup_id = _create_backup(app_server, name="integ-overwrite-01")
    try:
        zip_bytes = _export_backup_bytes(app_server, backup_id)

        conflict_resp = app_server.api_request(
            "POST",
            "/api/backups/import",
            files={
                "file": (
                    f"{backup_id}.zip",
                    zip_bytes,
                    "application/zip",
                ),
            },
            timeout=_BACKUP_HTTP_TIMEOUT,
        )
        assert conflict_resp.status_code == 409, app_server.logs_tail()
        pending_token = conflict_resp.json().get("pending_token")
        assert isinstance(pending_token, str) and pending_token

        commit_resp = app_server.api_request(
            "POST",
            "/api/backups/import",
            data={"pending_token": pending_token},
            timeout=_BACKUP_HTTP_TIMEOUT,
        )
        assert commit_resp.status_code == 200, app_server.logs_tail()
        meta = commit_resp.json()
        assert meta.get("id") == backup_id

        assert backup_id in _list_backup_ids(app_server)
    finally:
        _delete_backup(app_server, backup_id)
