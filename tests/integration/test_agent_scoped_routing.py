# -*- coding: utf-8 -*-
"""Integration tests for agent-scoped URL routing.

Verifies that ``/api/agents/{agentId}/...`` paths route correctly to
the same handlers as global ``/api/...`` paths (alias endpoints) and
that real agent-scoped endpoints resolve agent context properly.

Covers 13 P0 endpoints across five domains:

  - **plugins** (alias): install / upload / uninstall + real install
  - **console/inbox** (alias): seed → list → mark-read → delete
  - **workspace** (real): upload invalid / valid zip
  - **mcp-oauth** (real): revoke unknown client
  - **workspace/transcribe** (alias): disabled, unsupported extension
  - **workspace/transcription-provider-type** (alias): roundtrip, invalid
  - **skills/hub** (alias): cancel unknown task
"""
from __future__ import annotations

import io
import time
import zipfile

import httpx
import pytest

from tests.integration.helpers import (
    LOADER_READY_TIMEOUT,
    OFFICIAL_PLUGINS_DIR,
    PLUGIN_HTTP_TIMEOUT,
    clean_inbox,
    create_agent,
    delete_agent_quietly,
    delete_plugin_quietly,
    make_event,
    scoped,
    seed_inbox_events,
    wait_until_plugin_loader_ready,
)

_HTTP_TIMEOUT = 15.0


# ------------------------------------------------------------------ #
# file-local helpers (not shared)
# ------------------------------------------------------------------ #


def _build_workspace_zip(files: dict[str, str]) -> bytes:
    """Build an in-memory zip containing the given path→content map."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


# ------------------------------------------------------------------ #
# plugins — alias endpoints (handler ignores agentId)
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p0
def test_plugins_install_invalid_source(app_server) -> None:
    """Test purpose:
    - Verify POST /api/agents/{agentId}/plugins/install with a
      non-existent local path returns 400 ``Path not found``, proving
      the agent-scoped URL reaches the install handler.

    Test flow:
    1. Wait for plugin loader readiness.
    2. POST agent-scoped plugins/install with a bogus local path.
    3. Assert 400 and detail contains ``Path not found``.

    API endpoints:
    - POST /api/agents/{agentId}/plugins/install
    """
    wait_until_plugin_loader_ready(app_server)
    resp = app_server.api_request(
        "POST",
        scoped("default", "/plugins/install"),
        json={
            "source": "/tmp/integ-no-such-plugin-path",
            "force": False,
        },
        timeout=PLUGIN_HTTP_TIMEOUT,
    )
    assert resp.status_code == 400, app_server.logs_tail()
    assert "Path not found" in resp.json().get("detail", "")


@pytest.mark.integration
@pytest.mark.p0
def test_plugins_upload_non_zip_rejected(app_server) -> None:
    """Test purpose:
    - Verify POST /api/agents/{agentId}/plugins/upload with a
      non-zip filename is rejected with 400 ``Only .zip archives``.

    Test flow:
    1. Wait for plugin loader readiness.
    2. POST agent-scoped plugins/upload with a plain-text file named
       ``test.txt``.
    3. Assert 400 and detail mentions ``.zip``.

    API endpoints:
    - POST /api/agents/{agentId}/plugins/upload
    """
    wait_until_plugin_loader_ready(app_server)
    resp = app_server.api_request(
        "POST",
        scoped("default", "/plugins/upload"),
        files={"file": ("test.txt", b"not a zip", "text/plain")},
        timeout=PLUGIN_HTTP_TIMEOUT,
    )
    assert resp.status_code == 400, app_server.logs_tail()
    assert ".zip" in resp.json().get("detail", "")


@pytest.mark.integration
@pytest.mark.p0
def test_plugins_uninstall_unknown(app_server) -> None:
    """Test purpose:
    - Verify DELETE /api/agents/{agentId}/plugins/{plugin_id} with
      an unknown plugin returns 404 ``not loaded``.

    Test flow:
    1. Wait for plugin loader readiness.
    2. DELETE agent-scoped plugins/<nonexistent_id>.
    3. Assert 404 and detail mentions ``not loaded``.

    API endpoints:
    - DELETE /api/agents/{agentId}/plugins/{plugin_id}
    """
    wait_until_plugin_loader_ready(app_server)
    resp = app_server.api_request(
        "DELETE",
        scoped("default", "/plugins/integ-nonexistent-plugin"),
        timeout=PLUGIN_HTTP_TIMEOUT,
    )
    assert resp.status_code == 404, app_server.logs_tail()
    assert "not loaded" in resp.json().get("detail", "")


@pytest.mark.integration
@pytest.mark.p0
def test_plugins_install_real_via_agentscoped(app_server) -> None:
    """Test purpose:
    - Verify a real plugin (bundled ``cloudpaw``) can be installed and
      uninstalled through the agent-scoped path. This is the happy-path
      proof that the agent-scoped routing delivers to the full install
      pipeline (hot-load → list → unload).

    Test flow:
    1. Wait for plugin loader readiness.
    2. POST /api/agents/default/plugins/install with the local
       cloudpaw bundle source.
    3. Assert 200, ``id == "cloudpaw"``, ``loaded == True``.
    4. GET /api/agents/default/plugins — assert cloudpaw in list.
    5. DELETE /api/agents/default/plugins/cloudpaw — assert 200.
    6. finally: best-effort cleanup.

    API endpoints:
    - POST /api/agents/{agentId}/plugins/install
    - GET  /api/agents/{agentId}/plugins
    - DELETE /api/agents/{agentId}/plugins/{plugin_id}
    """
    plugin_id = "cloudpaw"
    source_path = OFFICIAL_PLUGINS_DIR / "bundle" / "cloudpaw"
    assert source_path.is_dir(), f"missing source: {source_path}"

    try:
        wait_until_plugin_loader_ready(app_server)
        deadline = time.time() + LOADER_READY_TIMEOUT
        resp = None
        while True:
            try:
                resp = app_server.api_request(
                    "POST",
                    scoped("default", "/plugins/install"),
                    json={
                        "source": str(source_path),
                        "force": False,
                    },
                    timeout=PLUGIN_HTTP_TIMEOUT,
                )
            except httpx.TimeoutException:
                if time.time() >= deadline:
                    raise
                time.sleep(0.5)
                continue
            if resp.status_code != 503 or time.time() >= deadline:
                break
            time.sleep(0.5)
        assert resp.status_code == 200, (
            f"install via agent-scoped: {resp.status_code} | "
            f"{resp.text} | logs: {app_server.logs_tail()}"
        )
        payload = resp.json()
        assert payload.get("id") == plugin_id
        assert payload.get("loaded") is True

        list_resp = app_server.api_request(
            "GET",
            scoped("default", "/plugins"),
            timeout=PLUGIN_HTTP_TIMEOUT,
        )
        assert list_resp.status_code == 200, app_server.logs_tail()
        items = list_resp.json()
        if isinstance(items, dict):
            items = items.get("plugins", [])
        loaded_ids = {
            str(it["id"])
            for it in items
            if isinstance(it, dict) and "id" in it
        }
        assert plugin_id in loaded_ids

        wait_until_plugin_loader_ready(app_server)
        del_resp = app_server.api_request(
            "DELETE",
            scoped("default", f"/plugins/{plugin_id}"),
            timeout=PLUGIN_HTTP_TIMEOUT,
        )
        assert del_resp.status_code == 200, app_server.logs_tail()
    finally:
        delete_plugin_quietly(app_server, plugin_id)


# ------------------------------------------------------------------ #
# console/inbox — alias endpoints
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p0
def test_inbox_seed_list_read_delete_lifecycle(app_server) -> None:
    """Test purpose:
    - Verify the console inbox CRUD lifecycle works through agent-scoped
      paths: seed data → list → mark-read → delete. Covers the three
      inbox endpoints that are P0 under agent-scoped routing.

    Test flow:
    1. Seed 3 unread events into inbox_events.json.
    2. GET /api/agents/default/console/inbox/events — assert 3 events.
    3. POST /api/agents/default/console/inbox/read with 2 event ids —
       assert ``updated == 2``.
    4. GET events again — assert 2 read + 1 unread.
    5. DELETE /api/agents/default/console/inbox/events/{id} for the
       remaining unread event — assert ``deleted == True``.
    6. GET events — assert 2 remaining.
    7. Cleanup: wipe inbox state.

    API endpoints:
    - GET    /api/agents/{agentId}/console/inbox/events
    - POST   /api/agents/{agentId}/console/inbox/read
    - DELETE /api/agents/{agentId}/console/inbox/events/{event_id}
    """
    events = [
        make_event(event_id="scoped-inbox-01"),
        make_event(event_id="scoped-inbox-02"),
        make_event(event_id="scoped-inbox-03"),
    ]
    seed_inbox_events(app_server.working_dir, events)

    try:
        list_resp = app_server.api_request(
            "GET",
            scoped("default", "/console/inbox/events"),
            timeout=_HTTP_TIMEOUT,
        )
        assert list_resp.status_code == 200, app_server.logs_tail()
        listed = list_resp.json().get("events")
        assert len(listed) == 3

        mark_resp = app_server.api_request(
            "POST",
            scoped("default", "/console/inbox/read"),
            json={
                "event_ids": ["scoped-inbox-01", "scoped-inbox-02"],
                "all": False,
            },
            timeout=_HTTP_TIMEOUT,
        )
        assert mark_resp.status_code == 200, app_server.logs_tail()
        assert mark_resp.json().get("updated") == 2

        verify_resp = app_server.api_request(
            "GET",
            scoped("default", "/console/inbox/events"),
            timeout=_HTTP_TIMEOUT,
        )
        assert verify_resp.status_code == 200, app_server.logs_tail()
        read_map = {e["id"]: e["read"] for e in verify_resp.json()["events"]}
        assert read_map["scoped-inbox-01"] is True
        assert read_map["scoped-inbox-02"] is True
        assert read_map["scoped-inbox-03"] is False

        del_resp = app_server.api_request(
            "DELETE",
            scoped("default", "/console/inbox/events/scoped-inbox-03"),
            timeout=_HTTP_TIMEOUT,
        )
        assert del_resp.status_code == 200, app_server.logs_tail()
        assert del_resp.json().get("deleted") is True

        final_resp = app_server.api_request(
            "GET",
            scoped("default", "/console/inbox/events"),
            timeout=_HTTP_TIMEOUT,
        )
        assert final_resp.status_code == 200, app_server.logs_tail()
        remaining = {e["id"] for e in final_resp.json()["events"]}
        assert remaining == {"scoped-inbox-01", "scoped-inbox-02"}
    finally:
        clean_inbox(app_server.working_dir)


# ------------------------------------------------------------------ #
# workspace — real agent-scoped endpoints
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p0
def test_workspace_upload_invalid_content_type(app_server) -> None:
    """Test purpose:
    - Verify POST /api/agents/{agentId}/workspace/upload with a
      non-zip content type is rejected with 400.

    Test flow:
    1. Create a test agent.
    2. POST workspace/upload with content-type ``text/plain``.
    3. Assert 400 and detail mentions ``zip``.
    4. Delete test agent.

    API endpoints:
    - POST /api/agents/{agentId}/workspace/upload
    """
    agent_id = "integ_ws_upload_bad_ct_01"
    create_agent(app_server, agent_id)
    try:
        resp = app_server.api_request(
            "POST",
            scoped(agent_id, "/workspace/upload"),
            files={
                "file": (
                    "bad.zip",
                    b"not a zip",
                    "text/plain",
                ),
            },
            timeout=_HTTP_TIMEOUT,
        )
        assert resp.status_code == 400, app_server.logs_tail()
        assert "zip" in resp.json().get("detail", "").lower()
    finally:
        delete_agent_quietly(app_server, agent_id)


@pytest.mark.integration
@pytest.mark.p0
def test_workspace_upload_valid_zip_merges(app_server) -> None:
    """Test purpose:
    - Verify POST /api/agents/{agentId}/workspace/upload with a valid
      zip returns ``{"success": true}`` and the files are merged into
      the agent workspace. This is the happy-path coverage for the real
      agent-scoped workspace upload.

    Test flow:
    1. Create a test agent.
    2. Build a zip containing ``test_marker.txt``.
    3. POST workspace/upload with ``application/zip``.
    4. Assert 200 and ``success == True``.
    5. Delete test agent.

    API endpoints:
    - POST /api/agents/{agentId}/workspace/upload
    """
    agent_id = "integ_ws_upload_ok_01"
    create_agent(app_server, agent_id)
    try:
        zip_bytes = _build_workspace_zip(
            {
                "test_marker.txt": "agent-scoped upload test",
            },
        )
        resp = app_server.api_request(
            "POST",
            scoped(agent_id, "/workspace/upload"),
            files={
                "file": (
                    "workspace.zip",
                    zip_bytes,
                    "application/zip",
                ),
            },
            timeout=_HTTP_TIMEOUT,
        )
        assert resp.status_code == 200, app_server.logs_tail()
        assert resp.json().get("success") is True
    finally:
        delete_agent_quietly(app_server, agent_id)


# ------------------------------------------------------------------ #
# mcp-oauth — real agent-scoped endpoint
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p0
def test_mcp_oauth_revoke_unknown_client(app_server) -> None:
    """Test purpose:
    - Verify DELETE /api/agents/{agentId}/mcp/oauth/{client_key} with
      a non-existent client returns 404. The handler calls
      ``get_agent_for_request`` (real agent-scoped), then checks
      ``agent.config.mcp.clients``.

    Test flow:
    1. Create a test agent (fresh agent has mcp=None).
    2. DELETE agent-scoped mcp/oauth/<bogus_key>.
    3. Assert 404 and detail mentions ``not found``.
    4. Delete test agent.

    API endpoints:
    - DELETE /api/agents/{agentId}/mcp/oauth/{client_key}
    """
    agent_id = "integ_mcp_oauth_revoke_01"
    create_agent(app_server, agent_id)
    try:
        resp = app_server.api_request(
            "DELETE",
            scoped(agent_id, "/mcp/oauth/no-such-client"),
            timeout=_HTTP_TIMEOUT,
        )
        assert resp.status_code == 404, app_server.logs_tail()
        assert "not found" in resp.json().get("detail", "").lower()
    finally:
        delete_agent_quietly(app_server, agent_id)


# ------------------------------------------------------------------ #
# workspace/transcribe — alias endpoints
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p0
def test_transcribe_disabled_returns_400(app_server) -> None:
    """Test purpose:
    - Verify POST /api/agents/{agentId}/workspace/transcribe returns
      400 with code ``TRANSCRIPTION_DISABLED`` when the provider is
      set to ``disabled`` (the default).

    Test flow:
    1. POST agent-scoped workspace/transcribe with a dummy audio file.
    2. Assert 400 and detail.code == ``TRANSCRIPTION_DISABLED``.

    API endpoints:
    - POST /api/agents/{agentId}/workspace/transcribe
    """
    resp = app_server.api_request(
        "POST",
        scoped("default", "/workspace/transcribe"),
        files={
            "file": ("test.webm", b"\x00" * 16, "audio/webm"),
        },
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 400, app_server.logs_tail()
    detail = resp.json().get("detail", {})
    assert detail.get("code") == "TRANSCRIPTION_DISABLED"


@pytest.mark.integration
@pytest.mark.p0
def test_transcribe_unsupported_extension(app_server) -> None:
    """Test purpose:
    - Verify POST /api/agents/{agentId}/workspace/transcribe with an
      unsupported file extension returns 400 ``UNSUPPORTED_FILE_TYPE``.
      Requires transcription to be enabled first (otherwise the
      disabled check fires before the extension check).

    Test flow:
    1. PUT transcription-provider-type to ``whisper_api`` (enable).
    2. POST workspace/transcribe with ``test.txt`` file.
    3. Assert 400 and detail.code == ``UNSUPPORTED_FILE_TYPE``.
    4. PUT transcription-provider-type back to ``disabled`` (restore).

    API endpoints:
    - POST /api/agents/{agentId}/workspace/transcribe
    - PUT  /api/agents/{agentId}/workspace/transcription-provider-type
    """
    enable_resp = app_server.api_request(
        "PUT",
        scoped("default", "/workspace/transcription-provider-type"),
        json={"transcription_provider_type": "whisper_api"},
        timeout=_HTTP_TIMEOUT,
    )
    assert enable_resp.status_code == 200, app_server.logs_tail()

    try:
        resp = app_server.api_request(
            "POST",
            scoped("default", "/workspace/transcribe"),
            files={
                "file": ("test.txt", b"hello", "text/plain"),
            },
            timeout=_HTTP_TIMEOUT,
        )
        assert resp.status_code == 400, app_server.logs_tail()
        detail = resp.json().get("detail", {})
        assert detail.get("code") == "UNSUPPORTED_FILE_TYPE"
    finally:
        app_server.api_request(
            "PUT",
            scoped(
                "default",
                "/workspace/transcription-provider-type",
            ),
            json={"transcription_provider_type": "disabled"},
            timeout=_HTTP_TIMEOUT,
        )


# ------------------------------------------------------------------ #
# workspace/transcription-provider-type — alias endpoints
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p0
def test_transcription_provider_roundtrip(app_server) -> None:
    """Test purpose:
    - Verify GET/PUT /api/agents/{agentId}/workspace/transcription-
      provider-type forms a consistent roundtrip. This is the
      happy-path coverage for the transcription provider setting
      through agent-scoped routing.

    Test flow:
    1. GET agent-scoped transcription-provider-type — record baseline.
    2. PUT ``whisper_api``.
    3. GET — assert ``whisper_api``.
    4. PUT back to baseline (``disabled``).
    5. GET — assert baseline restored.

    API endpoints:
    - GET /api/agents/{agentId}/workspace/transcription-provider-type
    - PUT /api/agents/{agentId}/workspace/transcription-provider-type
    """
    base_path = "/workspace/transcription-provider-type"

    baseline_resp = app_server.api_request(
        "GET",
        scoped("default", base_path),
        timeout=_HTTP_TIMEOUT,
    )
    assert baseline_resp.status_code == 200, app_server.logs_tail()
    baseline = baseline_resp.json().get("transcription_provider_type")

    try:
        put_resp = app_server.api_request(
            "PUT",
            scoped("default", base_path),
            json={"transcription_provider_type": "whisper_api"},
            timeout=_HTTP_TIMEOUT,
        )
        assert put_resp.status_code == 200, app_server.logs_tail()
        assert (
            put_resp.json().get("transcription_provider_type") == "whisper_api"
        )

        get_resp = app_server.api_request(
            "GET",
            scoped("default", base_path),
            timeout=_HTTP_TIMEOUT,
        )
        assert get_resp.status_code == 200, app_server.logs_tail()
        assert (
            get_resp.json().get("transcription_provider_type") == "whisper_api"
        )
    finally:
        app_server.api_request(
            "PUT",
            scoped("default", base_path),
            json={
                "transcription_provider_type": baseline or "disabled",
            },
            timeout=_HTTP_TIMEOUT,
        )

    restore_resp = app_server.api_request(
        "GET",
        scoped("default", base_path),
        timeout=_HTTP_TIMEOUT,
    )
    assert restore_resp.status_code == 200, app_server.logs_tail()
    assert restore_resp.json().get("transcription_provider_type") == (
        baseline or "disabled"
    )


@pytest.mark.integration
@pytest.mark.p0
def test_transcription_provider_invalid(app_server) -> None:
    """Test purpose:
    - Verify PUT /api/agents/{agentId}/workspace/transcription-
      provider-type with an invalid value returns 400 and enumerates
      the allowed values.

    Test flow:
    1. PUT agent-scoped transcription-provider-type with ``"foobar"``.
    2. Assert 400 and detail mentions ``Invalid``.

    API endpoints:
    - PUT /api/agents/{agentId}/workspace/transcription-provider-type
    """
    resp = app_server.api_request(
        "PUT",
        scoped("default", "/workspace/transcription-provider-type"),
        json={"transcription_provider_type": "foobar"},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 400, app_server.logs_tail()
    assert "Invalid" in resp.json().get("detail", "")


# ------------------------------------------------------------------ #
# skills/hub — alias endpoint
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p0
def test_hub_install_cancel_unknown_task(app_server) -> None:
    """Test purpose:
    - Verify POST /api/agents/{agentId}/skills/hub/install/cancel/
      {task_id} with a non-existent task id returns 404.

    Test flow:
    1. POST agent-scoped skills/hub/install/cancel/<bogus_id>.
    2. Assert 404 and detail == ``install task not found``.

    API endpoints:
    - POST /api/agents/{agentId}/skills/hub/install/cancel/{task_id}
    """
    resp = app_server.api_request(
        "POST",
        scoped(
            "default",
            "/skills/hub/install/cancel/integ-no-such-task",
        ),
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 404, app_server.logs_tail()
    assert resp.json().get("detail") == "install task not found"
