# -*- coding: utf-8 -*-
"""Loop mode discovery and custom-mode persistence APIs.

Covers ``app/routers/loops.py``, which had no integration coverage:
the built-in loop catalog, the gate catalog, per-session loop status,
and the full custom-mode lifecycle (create / list / update / duplicate /
delete) together with its conflict and validation branches — duplicate
id, duplicate slash command, duplicate name, id-change on update,
unknown id, and pipeline rules rejected by the compiler.

Each mutation is verified by reading the collection back, so a
regression that fails to persist (or fails to delete) is caught rather
than passing on a bare 201.

API endpoints:
  - GET    /api/loops
  - GET    /api/loops/status
  - GET    /api/loops/gates/catalog
  - GET    /api/loops/custom
  - POST   /api/loops/custom
  - PUT    /api/loops/custom/{mode_id}
  - POST   /api/loops/custom/{mode_id}/duplicate
  - DELETE /api/loops/custom/{mode_id}
"""
from __future__ import annotations

import pytest
from helpers import default_http_timeout

_HTTP_TIMEOUT = default_http_timeout(30.0)


def _mode(
    mode_id: str,
    *,
    slash: str | None = None,
    name: str | None = None,
    gate_type: str = "iteration",
    enabled: bool = True,
) -> dict:
    """Build a minimal valid custom loop mode payload."""
    return {
        "id": mode_id,
        "name": name or f"Mode {mode_id}",
        "description": "integration fixture mode",
        "slash_command": slash or mode_id,
        "enabled": enabled,
        "gates": [
            {
                "id": "g1",
                "type": gate_type,
                "enabled": True,
                "params": {},
            },
        ],
    }


def _list_custom(app_server) -> list[dict]:
    resp = app_server.api_request(
        "GET",
        "/api/loops/custom",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body, list), body
    return body


def _delete_custom(app_server, mode_id: str) -> None:
    try:
        app_server.api_request(
            "DELETE",
            f"/api/loops/custom/{mode_id}",
            timeout=_HTTP_TIMEOUT,
        )
    except Exception:  # noqa: BLE001 - cleanup must not mask failures
        pass


# =========================== A. read-only catalogs =========================


@pytest.mark.integration
@pytest.mark.p1
def test_list_loops_includes_builtin_modes(app_server):
    """The loop list exposes the built-in modes.

    Test purpose:
      - Cover list_loops / _build_loop_catalog / _deduplicate: the
        response must name the built-ins rather than just be a list.
    """
    resp = app_server.api_request(
        "GET",
        "/api/loops",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, resp.text
    ids = {item["id"] for item in resp.json()}
    assert {"default", "goal", "mission"} <= ids, ids


@pytest.mark.integration
@pytest.mark.p1
def test_gate_catalog_describes_known_gates(app_server):
    """The gate catalog lists gate types with metadata.

    Test purpose:
      - Cover list_gate_catalog / GateCatalog.describe, which the mode
        builder UI needs to render available gates.
    """
    resp = app_server.api_request(
        "GET",
        "/api/loops/gates/catalog",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, resp.text
    entries = resp.json()
    assert isinstance(entries, list) and entries, entries
    types = {entry.get("type") for entry in entries}
    assert "iteration" in types, types
    first = entries[0]
    assert "title" in first and "category" in first, first


@pytest.mark.integration
@pytest.mark.p1
def test_loop_status_for_idle_session(app_server):
    """A session with no active loop reports idle.

    Test purpose:
      - Cover get_loop_status / _session_context_state on a session that
        has no persisted mode_state.
    """
    resp = app_server.api_request(
        "GET",
        "/api/loops/status",
        params={"session_id": "console:integ-loops-idle"},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("state") == "idle", body


# ======================= B. custom mode lifecycle ==========================


@pytest.mark.integration
@pytest.mark.p1
def test_custom_mode_create_list_delete(app_server):
    """A created custom mode appears in the list, then is removed.

    Test purpose:
      - Cover create_custom_mode (validation + persistence),
        list_custom_modes and delete_custom_mode, asserting the
        collection actually changes in both directions.

    Test flow:
      1. POST a new mode and assert 201 with the echoed id.
      2. GET the list and assert the mode is present.
      3. DELETE it and assert it is gone from the list.
    """
    mode_id = "integ-loop-crud"
    _delete_custom(app_server, mode_id)
    created = app_server.api_request(
        "POST",
        "/api/loops/custom",
        json=_mode(mode_id),
        timeout=_HTTP_TIMEOUT,
    )
    assert created.status_code == 201, created.text
    assert created.json()["id"] == mode_id, created.json()
    try:
        assert mode_id in {m["id"] for m in _list_custom(app_server)}
    finally:
        deleted = app_server.api_request(
            "DELETE",
            f"/api/loops/custom/{mode_id}",
            timeout=_HTTP_TIMEOUT,
        )
        assert deleted.status_code == 204, deleted.text
    assert mode_id not in {m["id"] for m in _list_custom(app_server)}


@pytest.mark.integration
@pytest.mark.p1
def test_custom_mode_update_replaces_fields(app_server):
    """Updating a mode persists the new description and gate.

    Test purpose:
      - Cover update_custom_mode's replace path plus _find_mode, and
        _validate_mode's ignored_mode handling that lets a mode keep its
        own slash command.
    """
    mode_id = "integ-loop-update"
    _delete_custom(app_server, mode_id)
    app_server.api_request(
        "POST",
        "/api/loops/custom",
        json=_mode(mode_id),
        timeout=_HTTP_TIMEOUT,
    )
    try:
        updated = _mode(mode_id, gate_type="timeout")
        updated["description"] = "updated description"
        put_resp = app_server.api_request(
            "PUT",
            f"/api/loops/custom/{mode_id}",
            json=updated,
            timeout=_HTTP_TIMEOUT,
        )
        assert put_resp.status_code == 200, put_resp.text
        stored = [m for m in _list_custom(app_server) if m["id"] == mode_id]
        assert stored, "mode disappeared after update"
        assert stored[0]["description"] == "updated description", stored[0]
        assert stored[0]["gates"][0]["type"] == "timeout", stored[0]
    finally:
        _delete_custom(app_server, mode_id)


@pytest.mark.integration
@pytest.mark.p1
def test_custom_mode_duplicate_gets_unique_identity(app_server):
    """Duplicating a mode yields a distinct id, name and command.

    Test purpose:
      - Cover duplicate_custom_mode / _unique_value: the copy must not
        collide with its source on any unique field.
    """
    mode_id = "integ-loop-dup"
    _delete_custom(app_server, mode_id)
    app_server.api_request(
        "POST",
        "/api/loops/custom",
        json=_mode(mode_id),
        timeout=_HTTP_TIMEOUT,
    )
    copy_id = None
    try:
        dup = app_server.api_request(
            "POST",
            f"/api/loops/custom/{mode_id}/duplicate",
            timeout=_HTTP_TIMEOUT,
        )
        assert dup.status_code == 201, dup.text
        body = dup.json()
        copy_id = body["id"]
        assert copy_id != mode_id, body
        assert body["slash_command"] != mode_id, body
        ids = {m["id"] for m in _list_custom(app_server)}
        assert {mode_id, copy_id} <= ids, ids
    finally:
        if copy_id:
            _delete_custom(app_server, copy_id)
        _delete_custom(app_server, mode_id)


# ==================== C. conflict / validation branches ====================


@pytest.mark.integration
@pytest.mark.p2
def test_duplicate_mode_id_returns_409(app_server):
    """Re-creating the same mode id is a conflict.

    Test purpose:
      - Cover create_custom_mode's id-collision guard.
    """
    mode_id = "integ-loop-dupid"
    _delete_custom(app_server, mode_id)
    first = app_server.api_request(
        "POST",
        "/api/loops/custom",
        json=_mode(mode_id),
        timeout=_HTTP_TIMEOUT,
    )
    assert first.status_code == 201, first.text
    try:
        again = app_server.api_request(
            "POST",
            "/api/loops/custom",
            json=_mode(mode_id),
            timeout=_HTTP_TIMEOUT,
        )
        assert again.status_code == 409, again.text
        assert "ID already exists" in again.text, again.text
    finally:
        _delete_custom(app_server, mode_id)


@pytest.mark.integration
@pytest.mark.p2
def test_duplicate_slash_command_returns_409(app_server):
    """Two modes cannot share a slash command.

    Test purpose:
      - Cover _validate_mode's slash-command collision branch, which is
        separate from the id check.
    """
    first_id = "integ-loop-slash-a"
    second_id = "integ-loop-slash-b"
    for mid in (first_id, second_id):
        _delete_custom(app_server, mid)
    created = app_server.api_request(
        "POST",
        "/api/loops/custom",
        json=_mode(first_id, slash="integ-shared-cmd"),
        timeout=_HTTP_TIMEOUT,
    )
    assert created.status_code == 201, created.text
    try:
        clash = app_server.api_request(
            "POST",
            "/api/loops/custom",
            json=_mode(second_id, slash="integ-shared-cmd"),
            timeout=_HTTP_TIMEOUT,
        )
        assert clash.status_code == 409, clash.text
        assert "Slash command exists" in clash.text, clash.text
    finally:
        _delete_custom(app_server, second_id)
        _delete_custom(app_server, first_id)


@pytest.mark.integration
@pytest.mark.p2
def test_duplicate_mode_name_returns_409(app_server):
    """Two modes cannot share a normalized display name.

    Test purpose:
      - Cover the normalize_custom_loop_mode_name comparison, which must
        catch case/spacing variants rather than exact strings only.
    """
    first_id = "integ-loop-name-a"
    second_id = "integ-loop-name-b"
    for mid in (first_id, second_id):
        _delete_custom(app_server, mid)
    created = app_server.api_request(
        "POST",
        "/api/loops/custom",
        json=_mode(first_id, name="Shared Mode Name"),
        timeout=_HTTP_TIMEOUT,
    )
    assert created.status_code == 201, created.text
    try:
        clash = app_server.api_request(
            "POST",
            "/api/loops/custom",
            json=_mode(second_id, name="  shared mode name  "),
            timeout=_HTTP_TIMEOUT,
        )
        assert clash.status_code == 409, clash.text
        assert "name exists" in clash.text.lower(), clash.text
    finally:
        _delete_custom(app_server, second_id)
        _delete_custom(app_server, first_id)


@pytest.mark.integration
@pytest.mark.p2
def test_update_with_changed_id_returns_422(app_server):
    """A mode's id cannot be changed through update.

    Test purpose:
      - Cover update_custom_mode's id-immutability guard, which runs
        before any workspace lookup.
    """
    mode_id = "integ-loop-idchange"
    _delete_custom(app_server, mode_id)
    app_server.api_request(
        "POST",
        "/api/loops/custom",
        json=_mode(mode_id),
        timeout=_HTTP_TIMEOUT,
    )
    try:
        resp = app_server.api_request(
            "PUT",
            f"/api/loops/custom/{mode_id}",
            json=_mode("integ-loop-renamed"),
            timeout=_HTTP_TIMEOUT,
        )
        assert resp.status_code == 422, resp.text
        assert "cannot change" in resp.text.lower(), resp.text
    finally:
        _delete_custom(app_server, mode_id)


@pytest.mark.integration
@pytest.mark.p2
def test_update_unknown_mode_returns_404(app_server):
    """Updating a non-existent mode is a 404.

    Test purpose:
      - Cover _find_mode's not-found branch reached from update.
    """
    resp = app_server.api_request(
        "PUT",
        "/api/loops/custom/integ-loop-absent",
        json=_mode("integ-loop-absent"),
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.integration
@pytest.mark.p2
def test_delete_unknown_mode_returns_404(app_server):
    """Deleting a non-existent mode is a 404.

    Test purpose:
      - Cover _find_mode reached from delete_custom_mode.
    """
    resp = app_server.api_request(
        "DELETE",
        "/api/loops/custom/integ-loop-absent-del",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.integration
@pytest.mark.p2
def test_duplicate_unknown_mode_returns_404(app_server):
    """Duplicating a non-existent mode is a 404.

    Test purpose:
      - Cover the duplicate route's lookup, distinct from update/delete.
    """
    resp = app_server.api_request(
        "POST",
        "/api/loops/custom/integ-loop-absent-dup/duplicate",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.integration
@pytest.mark.p2
def test_repeated_gate_type_rejected(app_server):
    """A mode repeating one gate type is rejected.

    Test purpose:
      - Cover CustomLoopModeConfig.validate_pipeline's duplicate-type
        rule, surfaced as a request validation error.
    """
    payload = _mode("integ-loop-badgates")
    payload["gates"] = [
        {"id": "g1", "type": "iteration", "enabled": True, "params": {}},
        {"id": "g2", "type": "iteration", "enabled": True, "params": {}},
    ]
    resp = app_server.api_request(
        "POST",
        "/api/loops/custom",
        json=payload,
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.integration
@pytest.mark.p2
def test_enabled_mode_without_enabled_gate_rejected(app_server):
    """An enabled mode with no enabled gate is rejected.

    Test purpose:
      - Cover validate_pipeline's "enabled modes require an enabled
        gate" rule.
    """
    payload = _mode("integ-loop-nogate")
    payload["enabled"] = True
    payload["gates"] = [
        {"id": "g1", "type": "iteration", "enabled": False, "params": {}},
    ]
    resp = app_server.api_request(
        "POST",
        "/api/loops/custom",
        json=payload,
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.integration
@pytest.mark.p2
def test_invalid_mode_id_pattern_rejected(app_server):
    """An id violating the slug pattern is rejected.

    Test purpose:
      - Cover the schema's id pattern constraint, which keeps ids safe
        for use in URLs and slash commands.
    """
    payload = _mode("integ-loop-ok")
    payload["id"] = "Invalid ID!"
    resp = app_server.api_request(
        "POST",
        "/api/loops/custom",
        json=payload,
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 422, resp.text
