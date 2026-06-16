# -*- coding: utf-8 -*-
"""Integration tests for memory, system-prompt-files, running-config,
and inbox event lifecycle.

Sprint 2.3 — Memory & Context.  All tests use the real ``qwenpaw app``
subprocess.  A/B classes are pure HTTP; C class covers inbox event
lifecycle driven entirely by Mock LLM heartbeat runs.

Existing CRUD roundtrip coverage (not duplicated here):
  - ``test_workspace_files.py``  — memory PUT/GET happy path
  - ``test_workspace_agent_settings.py``  — scoped memory + sys-prompt
  - ``test_workspace_running_config.py``  — running-config roundtrip
"""
from __future__ import annotations

import threading
import time
from http.server import HTTPServer
from pathlib import Path

import pytest

from helpers import (
    MOCK_LLM_PROVIDER_ID,
    MockLLMHandler,
    clean_inbox,
    create_agent,
    delete_agent_quietly,
    register_mock_provider,
    scoped,
    toggle_agent,
    unregister_mock_provider,
)

_HTTP_TIMEOUT = 15.0


@pytest.fixture(scope="module")
def mock_llm():
    """Start a module-scoped mock OpenAI server, yield (server, url)."""
    srv = HTTPServer(("127.0.0.1", 0), MockLLMHandler)
    srv.force_error = False
    srv.force_tool_call = False
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv, f"http://127.0.0.1:{port}/v1"
    srv.shutdown()


# ================================================================== #
#  A class — Memory file depth (6 tests)
# ================================================================== #


@pytest.mark.integration
@pytest.mark.p2
def test_memory_file_get_nonexistent_returns_404(
    app_server,
) -> None:
    """GET a memory file that does not exist → 404."""
    resp = app_server.api_request(
        "GET",
        scoped("default", "/workspace/memory/nonexistent_integ.md"),
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 404, app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p0
def test_memory_file_cross_agent_isolated(app_server) -> None:
    """A memory file written to agent_a is not visible to agent_b."""
    agent_a = "integ_mc_iso_a"
    agent_b = "integ_mc_iso_b"
    create_agent(app_server, agent_a)
    create_agent(app_server, agent_b)
    try:
        put_resp = app_server.api_request(
            "PUT",
            scoped(agent_a, "/workspace/memory/isolated_note.md"),
            json={"content": "agent_a private data"},
            timeout=_HTTP_TIMEOUT,
        )
        assert put_resp.status_code == 200, app_server.logs_tail()

        get_b = app_server.api_request(
            "GET",
            scoped(agent_b, "/workspace/memory/isolated_note.md"),
            timeout=_HTTP_TIMEOUT,
        )
        assert (
            get_b.status_code == 404
        ), "agent_b must not see agent_a's memory file"

        get_a = app_server.api_request(
            "GET",
            scoped(agent_a, "/workspace/memory/isolated_note.md"),
            timeout=_HTTP_TIMEOUT,
        )
        assert get_a.status_code == 200
        assert "agent_a private data" in get_a.json()["content"]
    finally:
        delete_agent_quietly(app_server, agent_a)
        delete_agent_quietly(app_server, agent_b)


@pytest.mark.integration
@pytest.mark.p1
def test_memory_file_unicode_content_roundtrip(app_server) -> None:
    """Chinese + emoji content survives PUT → GET roundtrip."""
    content = "你好世界 Hello 🌍 — 测试内容"
    resp = app_server.api_request(
        "PUT",
        scoped("default", "/workspace/memory/unicode_test.md"),
        json={"content": content},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()

    get_resp = app_server.api_request(
        "GET",
        scoped("default", "/workspace/memory/unicode_test.md"),
        timeout=_HTTP_TIMEOUT,
    )
    assert get_resp.status_code == 200
    assert get_resp.json()["content"].strip() == content


@pytest.mark.integration
@pytest.mark.p1
def test_memory_file_persists_after_agent_disable_enable(
    app_server,
) -> None:
    """Memory file survives a disable → re-enable cycle."""
    agent_id = "integ_mc_persist"
    create_agent(app_server, agent_id)
    try:
        app_server.api_request(
            "PUT",
            scoped(agent_id, "/workspace/memory/persist_check.md"),
            json={"content": "persist me"},
            timeout=_HTTP_TIMEOUT,
        )

        toggle_agent(app_server, agent_id, False)
        toggle_agent(app_server, agent_id, True)

        get_resp = app_server.api_request(
            "GET",
            scoped(agent_id, "/workspace/memory/persist_check.md"),
            timeout=_HTTP_TIMEOUT,
        )
        assert get_resp.status_code == 200
        assert get_resp.json()["content"].strip() == "persist me"
    finally:
        delete_agent_quietly(app_server, agent_id)


@pytest.mark.integration
@pytest.mark.p1
def test_memory_file_overwrite_preserves_sibling_files(
    app_server,
) -> None:
    """Overwriting one memory file does not affect siblings."""
    app_server.api_request(
        "PUT",
        scoped("default", "/workspace/memory/sibling_a.md"),
        json={"content": "aaa"},
        timeout=_HTTP_TIMEOUT,
    )
    app_server.api_request(
        "PUT",
        scoped("default", "/workspace/memory/sibling_b.md"),
        json={"content": "bbb"},
        timeout=_HTTP_TIMEOUT,
    )

    app_server.api_request(
        "PUT",
        scoped("default", "/workspace/memory/sibling_a.md"),
        json={"content": "aaa_updated"},
        timeout=_HTTP_TIMEOUT,
    )

    get_b = app_server.api_request(
        "GET",
        scoped("default", "/workspace/memory/sibling_b.md"),
        timeout=_HTTP_TIMEOUT,
    )
    assert get_b.status_code == 200
    assert get_b.json()["content"].strip() == "bbb"


@pytest.mark.integration
@pytest.mark.p2
def test_memory_file_list_metadata_fields_complete(
    app_server,
) -> None:
    """MdFileInfo contains all five documented fields with valid types."""
    app_server.api_request(
        "PUT",
        scoped("default", "/workspace/memory/meta_probe.md"),
        json={"content": "metadata test"},
        timeout=_HTTP_TIMEOUT,
    )

    list_resp = app_server.api_request(
        "GET",
        scoped("default", "/workspace/memory"),
        timeout=_HTTP_TIMEOUT,
    )
    assert list_resp.status_code == 200
    files = list_resp.json()
    assert isinstance(files, list)

    target = [f for f in files if f.get("filename") == "meta_probe.md"]
    assert len(target) == 1, f"meta_probe.md not in list: {files}"
    info = target[0]

    assert isinstance(info["filename"], str)
    assert isinstance(info["path"], str)
    assert isinstance(info["size"], int) and info["size"] > 0
    assert isinstance(info["created_time"], str) and info["created_time"]
    assert isinstance(info["modified_time"], str) and info["modified_time"]


# ================================================================== #
#  B class — System-prompt-files + context config depth (5 tests)
# ================================================================== #


@pytest.mark.integration
@pytest.mark.p1
def test_system_prompt_files_global_put_get_roundtrip(
    app_server,
) -> None:
    """PUT/GET system-prompt-files via X-Agent-Id header route."""
    get_before = app_server.api_request(
        "GET",
        "/api/workspace/system-prompt-files",
        headers={"X-Agent-Id": "default"},
        timeout=_HTTP_TIMEOUT,
    )
    assert get_before.status_code == 200, app_server.logs_tail()
    before = get_before.json()
    assert isinstance(before, list)

    reversed_list = list(reversed(before))
    try:
        put_resp = app_server.api_request(
            "PUT",
            "/api/workspace/system-prompt-files",
            json=reversed_list,
            headers={"X-Agent-Id": "default"},
            timeout=_HTTP_TIMEOUT,
        )
        assert put_resp.status_code == 200

        get_after = app_server.api_request(
            "GET",
            "/api/workspace/system-prompt-files",
            headers={"X-Agent-Id": "default"},
            timeout=_HTTP_TIMEOUT,
        )
        assert get_after.status_code == 200
        assert get_after.json() == reversed_list
    finally:
        app_server.api_request(
            "PUT",
            "/api/workspace/system-prompt-files",
            json=before,
            headers={"X-Agent-Id": "default"},
            timeout=_HTTP_TIMEOUT,
        )


@pytest.mark.integration
@pytest.mark.p0
def test_system_prompt_files_cross_agent_isolated(
    app_server,
) -> None:
    """Modifying agent_a's prompt-files list does not change agent_b."""
    agent_a = "integ_mc_spf_a"
    agent_b = "integ_mc_spf_b"
    create_agent(app_server, agent_a)
    create_agent(app_server, agent_b)
    try:
        base_a = app_server.api_request(
            "GET",
            scoped(agent_a, "/workspace/system-prompt-files"),
            timeout=_HTTP_TIMEOUT,
        ).json()

        base_b = app_server.api_request(
            "GET",
            scoped(agent_b, "/workspace/system-prompt-files"),
            timeout=_HTTP_TIMEOUT,
        ).json()

        modified = list(base_a) + ["CUSTOM_INTEG.md"]
        app_server.api_request(
            "PUT",
            scoped(agent_a, "/workspace/system-prompt-files"),
            json=modified,
            timeout=_HTTP_TIMEOUT,
        )

        after_b = app_server.api_request(
            "GET",
            scoped(agent_b, "/workspace/system-prompt-files"),
            timeout=_HTTP_TIMEOUT,
        ).json()

        assert (
            after_b == base_b
        ), "agent_b prompt-files changed after agent_a modification"

        after_a = app_server.api_request(
            "GET",
            scoped(agent_a, "/workspace/system-prompt-files"),
            timeout=_HTTP_TIMEOUT,
        ).json()
        assert "CUSTOM_INTEG.md" in after_a
    finally:
        app_server.api_request(
            "PUT",
            scoped(agent_a, "/workspace/system-prompt-files"),
            json=base_a,
            timeout=_HTTP_TIMEOUT,
        )
        delete_agent_quietly(app_server, agent_a)
        delete_agent_quietly(app_server, agent_b)


@pytest.mark.integration
@pytest.mark.p1
def test_running_config_approval_level_writeback_to_profile(
    app_server,
) -> None:
    """PUT running-config with approval_level writes it back to the
    agent profile (workspace.py:932-933)."""
    get_before = app_server.api_request(
        "GET",
        scoped("default", "/workspace/running-config"),
        timeout=_HTTP_TIMEOUT,
    )
    assert get_before.status_code == 200
    before = get_before.json()
    original_level = before.get("approval_level", "AUTO")

    try:
        updated = dict(before)
        updated["approval_level"] = "CONFIRM"
        put_resp = app_server.api_request(
            "PUT",
            scoped("default", "/workspace/running-config"),
            json=updated,
            timeout=_HTTP_TIMEOUT,
        )
        assert put_resp.status_code == 200

        profile_resp = app_server.api_request(
            "GET",
            "/api/agents/default",
            timeout=_HTTP_TIMEOUT,
        )
        assert profile_resp.status_code == 200
        profile = profile_resp.json()
        assert (
            profile.get("approval_level") == "CONFIRM"
        ), "approval_level not written back to agent profile"
    finally:
        restore = dict(before)
        restore["approval_level"] = original_level
        app_server.api_request(
            "PUT",
            scoped("default", "/workspace/running-config"),
            json=restore,
            timeout=_HTTP_TIMEOUT,
        )


@pytest.mark.integration
@pytest.mark.p1
def test_running_config_context_compact_fields_roundtrip(
    app_server,
) -> None:
    """Modify light_context_config.context_compact_config fields and
    verify they persist on readback."""
    get_before = app_server.api_request(
        "GET",
        scoped("default", "/workspace/running-config"),
        timeout=_HTTP_TIMEOUT,
    )
    assert get_before.status_code == 200
    before = get_before.json()

    try:
        updated = dict(before)
        lcc = dict(updated.get("light_context_config") or {})
        ccc = dict(lcc.get("context_compact_config") or {})
        ccc["compact_threshold_ratio"] = 0.5
        lcc["context_compact_config"] = ccc
        updated["light_context_config"] = lcc

        put_resp = app_server.api_request(
            "PUT",
            scoped("default", "/workspace/running-config"),
            json=updated,
            timeout=_HTTP_TIMEOUT,
        )
        assert put_resp.status_code == 200

        get_after = app_server.api_request(
            "GET",
            scoped("default", "/workspace/running-config"),
            timeout=_HTTP_TIMEOUT,
        )
        assert get_after.status_code == 200
        after = get_after.json()
        after_ccc = after.get("light_context_config", {}).get(
            "context_compact_config",
            {},
        )
        assert after_ccc.get("compact_threshold_ratio") == 0.5
    finally:
        app_server.api_request(
            "PUT",
            scoped("default", "/workspace/running-config"),
            json=before,
            timeout=_HTTP_TIMEOUT,
        )


@pytest.mark.integration
@pytest.mark.p2
def test_running_config_extra_fields_ignored(
    app_server,
) -> None:
    """PUT with unknown fields succeeds but they are not persisted
    (AgentsRunningConfig uses extra='ignore')."""
    get_before = app_server.api_request(
        "GET",
        scoped("default", "/workspace/running-config"),
        timeout=_HTTP_TIMEOUT,
    )
    assert get_before.status_code == 200
    before = get_before.json()

    try:
        updated = dict(before)
        updated["bogus_field_xyz_integ"] = 42
        put_resp = app_server.api_request(
            "PUT",
            scoped("default", "/workspace/running-config"),
            json=updated,
            timeout=_HTTP_TIMEOUT,
        )
        assert put_resp.status_code == 200

        get_after = app_server.api_request(
            "GET",
            scoped("default", "/workspace/running-config"),
            timeout=_HTTP_TIMEOUT,
        )
        assert get_after.status_code == 200
        assert "bogus_field_xyz_integ" not in get_after.json()
    finally:
        app_server.api_request(
            "PUT",
            scoped("default", "/workspace/running-config"),
            json=before,
            timeout=_HTTP_TIMEOUT,
        )


# ================================================================== #
#  C class — Inbox event lifecycle (5 tests)
# ================================================================== #


def _register_mock_provider(app_server, mock_llm_url):
    return register_mock_provider(app_server, mock_llm_url)


def _unregister_mock_provider(app_server, provider_id):
    unregister_mock_provider(app_server, provider_id)


def _poll_inbox_heartbeat(
    app_server,
    deadline,
    event_type=None,
):
    """Poll inbox until a heartbeat event appears or deadline."""
    while time.time() < deadline:
        resp = app_server.api_request(
            "GET",
            "/api/console/inbox/events",
            params={"source_type": "heartbeat"},
            timeout=_HTTP_TIMEOUT,
        )
        if resp.status_code == 200:
            body = resp.json()
            events = body.get(
                "events",
                body if isinstance(body, list) else [],
            )
            if event_type:
                events = [
                    e for e in events if e.get("event_type") == event_type
                ]
            if events:
                return events
        time.sleep(1.0)
    return []


def _setup_heartbeat(app_server, mock_url):
    """Register provider + write HEARTBEAT.md + configure inbox."""
    working_dir = app_server.working_dir
    clean_inbox(working_dir)
    _unregister_mock_provider(app_server, "integ-mock-llm")

    provider_id = _register_mock_provider(app_server, mock_url)

    hb_before = app_server.api_request(
        "GET",
        scoped("default", "/config/heartbeat"),
        timeout=_HTTP_TIMEOUT,
    ).json()

    ws_dir = Path(working_dir) / "workspaces" / "default"
    hb_file = ws_dir / "HEARTBEAT.md"
    ws_dir.mkdir(parents=True, exist_ok=True)
    hb_original = hb_file.read_text("utf-8") if hb_file.exists() else None

    hb_file.write_text(
        "Integration test heartbeat query",
        encoding="utf-8",
    )

    app_server.api_request(
        "PUT",
        scoped("default", "/config/heartbeat"),
        json={
            "enabled": True,
            "target": "inbox",
            "every": "24h",
        },
        timeout=_HTTP_TIMEOUT,
    )

    return {
        "provider_id": provider_id,
        "hb_before": hb_before,
        "hb_file": hb_file,
        "hb_original": hb_original,
        "working_dir": working_dir,
    }


def _teardown_heartbeat(app_server, ctx):
    """Restore heartbeat config + HEARTBEAT.md + provider + inbox."""
    clean_inbox(ctx["working_dir"])
    hb_file = ctx["hb_file"]
    if ctx["hb_original"] is not None:
        hb_file.write_text(
            ctx["hb_original"],
            encoding="utf-8",
        )
    elif hb_file.exists():
        hb_file.unlink()
    app_server.api_request(
        "PUT",
        scoped("default", "/config/heartbeat"),
        json=ctx["hb_before"],
        timeout=_HTTP_TIMEOUT,
    )
    _unregister_mock_provider(app_server, ctx["provider_id"])


@pytest.mark.integration
@pytest.mark.p0
def test_heartbeat_inbox_end_to_end(  # pylint: disable=redefined-outer-name
    app_server,
    mock_llm,
) -> None:
    """Mock LLM → heartbeat run → inbox event + trace created."""
    srv, mock_url = mock_llm
    srv.force_error = False
    ctx = _setup_heartbeat(app_server, mock_url)
    try:
        run_resp = app_server.api_request(
            "POST",
            scoped("default", "/config/heartbeat/run"),
            timeout=_HTTP_TIMEOUT,
        )
        assert run_resp.status_code == 200
        assert run_resp.json().get("started") is True

        events = _poll_inbox_heartbeat(
            app_server,
            time.time() + 30.0,
            event_type="heartbeat_result",
        )
        assert len(events) >= 1, (
            "No heartbeat inbox event after 30s: " f"{app_server.logs_tail()}"
        )

        event = events[0]
        assert event["source_type"] == "heartbeat"
        assert event["event_type"] == "heartbeat_result"
        assert event["status"] == "success"
        assert event["severity"] == "info"
        assert event["agent_id"] == "default"
        assert isinstance(event.get("payload"), dict)
        assert "run_id" in event["payload"]

        for field in (
            "id",
            "agent_id",
            "source_type",
            "event_type",
            "status",
            "severity",
            "title",
            "read",
            "created_at",
        ):
            assert field in event, f"missing field: {field}"

        run_id = event["payload"]["run_id"]
        trace_resp = app_server.api_request(
            "GET",
            f"/api/console/inbox/traces/{run_id}",
            timeout=_HTTP_TIMEOUT,
        )
        assert trace_resp.status_code == 200
    finally:
        _teardown_heartbeat(app_server, ctx)


@pytest.mark.integration
@pytest.mark.p1
def test_heartbeat_inbox_event_body_contains_response(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
) -> None:
    """Heartbeat event body contains the mock LLM response text."""
    srv, mock_url = mock_llm
    srv.force_error = False
    ctx = _setup_heartbeat(app_server, mock_url)
    try:
        run_resp = app_server.api_request(
            "POST",
            scoped("default", "/config/heartbeat/run"),
            timeout=_HTTP_TIMEOUT,
        )
        assert run_resp.status_code == 200

        events = _poll_inbox_heartbeat(
            app_server,
            time.time() + 30.0,
            event_type="heartbeat_result",
        )
        assert len(events) >= 1, app_server.logs_tail()

        event = events[0]
        assert event["body"], "event body should not be empty"
    finally:
        _teardown_heartbeat(app_server, ctx)


@pytest.mark.integration
@pytest.mark.p1
def test_heartbeat_run_twice_creates_two_events(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
) -> None:
    """Two heartbeat runs produce two distinct inbox events."""
    srv, mock_url = mock_llm
    srv.force_error = False
    ctx = _setup_heartbeat(app_server, mock_url)
    try:
        for _ in range(2):
            run_resp = app_server.api_request(
                "POST",
                scoped("default", "/config/heartbeat/run"),
                timeout=_HTTP_TIMEOUT,
            )
            assert run_resp.status_code == 200
            time.sleep(3.0)

        events = _poll_inbox_heartbeat(
            app_server,
            time.time() + 30.0,
            event_type="heartbeat_result",
        )
        assert len(events) >= 2, (
            f"Expected >=2 events, got {len(events)}: "
            f"{app_server.logs_tail()}"
        )

        ids = {e["id"] for e in events}
        run_ids = {
            e["payload"]["run_id"]
            for e in events
            if "run_id" in e.get("payload", {})
        }
        assert len(ids) >= 2, "events must have unique ids"
        assert len(run_ids) >= 2, "events must have unique run_ids"
    finally:
        _teardown_heartbeat(app_server, ctx)


@pytest.mark.integration
@pytest.mark.p1
def test_heartbeat_inbox_mark_read_via_api(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
) -> None:
    """Heartbeat event → mark read → unread_only excludes it."""
    srv, mock_url = mock_llm
    srv.force_error = False
    ctx = _setup_heartbeat(app_server, mock_url)
    try:
        run_resp = app_server.api_request(
            "POST",
            scoped("default", "/config/heartbeat/run"),
            timeout=_HTTP_TIMEOUT,
        )
        assert run_resp.status_code == 200

        events = _poll_inbox_heartbeat(
            app_server,
            time.time() + 30.0,
            event_type="heartbeat_result",
        )
        assert len(events) >= 1, app_server.logs_tail()
        event = events[0]

        mark_resp = app_server.api_request(
            "POST",
            "/api/console/inbox/read",
            json={"event_ids": [event["id"]], "all": False},
            timeout=_HTTP_TIMEOUT,
        )
        assert mark_resp.status_code == 200
        assert mark_resp.json().get("updated") == 1

        unread_resp = app_server.api_request(
            "GET",
            "/api/console/inbox/events",
            params={
                "unread_only": "true",
                "source_type": "heartbeat",
            },
            timeout=_HTTP_TIMEOUT,
        )
        assert unread_resp.status_code == 200
        body = unread_resp.json()
        unread = body.get(
            "events",
            body if isinstance(body, list) else [],
        )
        unread_ids = {e["id"] for e in unread}
        assert event["id"] not in unread_ids
    finally:
        _teardown_heartbeat(app_server, ctx)


@pytest.mark.integration
@pytest.mark.p1
def test_heartbeat_inbox_delete_cleans_trace(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
) -> None:
    """Heartbeat event+trace → DELETE event → trace also removed."""
    srv, mock_url = mock_llm
    srv.force_error = False
    ctx = _setup_heartbeat(app_server, mock_url)
    try:
        run_resp = app_server.api_request(
            "POST",
            scoped("default", "/config/heartbeat/run"),
            timeout=_HTTP_TIMEOUT,
        )
        assert run_resp.status_code == 200

        events = _poll_inbox_heartbeat(
            app_server,
            time.time() + 30.0,
            event_type="heartbeat_result",
        )
        assert len(events) >= 1, app_server.logs_tail()
        event = events[0]
        run_id = event["payload"]["run_id"]

        del_resp = app_server.api_request(
            "DELETE",
            f"/api/console/inbox/events/{event['id']}",
            timeout=_HTTP_TIMEOUT,
        )
        assert del_resp.status_code == 200
        del_body = del_resp.json()
        assert del_body.get("deleted") is True
        assert del_body.get("trace_deleted") is True

        trace_resp = app_server.api_request(
            "GET",
            f"/api/console/inbox/traces/{run_id}",
            timeout=_HTTP_TIMEOUT,
        )
        assert trace_resp.status_code == 404
    finally:
        _teardown_heartbeat(app_server, ctx)


@pytest.mark.integration
@pytest.mark.p1
def test_heartbeat_resilient_to_llm_error(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
) -> None:
    """Test purpose:
    - Verify that a heartbeat run against a failing LLM (422) does
      not crash and still creates a heartbeat_result inbox event.
      Runner.stream_query() swallows LLM errors internally, so the
      heartbeat completes normally even when the LLM returns errors.

    Test flow:
    1. Set mock LLM to force 422 errors.
    2. Setup heartbeat with mock provider.
    3. POST heartbeat/run.
    4. Poll inbox for heartbeat_result event.
    5. Assert the event was created (heartbeat did not crash).
    6. Restore mock LLM to normal.

    API endpoints:
    - POST /api/agents/{agentId}/config/heartbeat/run
    - GET /api/console/inbox/events
    """
    srv, mock_url = mock_llm
    srv.force_error = False
    ctx = _setup_heartbeat(app_server, mock_url)
    srv.force_error = True
    try:
        run_resp = app_server.api_request(
            "POST",
            scoped("default", "/config/heartbeat/run"),
            timeout=_HTTP_TIMEOUT,
        )
        assert run_resp.status_code == 200

        events = _poll_inbox_heartbeat(
            app_server,
            time.time() + 30.0,
            event_type="heartbeat_result",
        )
        assert len(events) >= 1, (
            "Heartbeat should complete even with LLM errors: "
            f"{app_server.logs_tail()}"
        )

        event = events[0]
        assert event["source_type"] == "heartbeat"
        assert event["event_type"] == "heartbeat_result"
    finally:
        srv.force_error = False
        _teardown_heartbeat(app_server, ctx)


@pytest.mark.integration
@pytest.mark.p2
def test_heartbeat_auto_schedule_fires(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
) -> None:
    """Test purpose:
    - Verify that a heartbeat configured with every=60s fires
      automatically via the scheduler without a manual POST run.

    Test flow:
    1. Setup heartbeat with every=60s.
    2. Wait ~70s for the scheduler to fire.
    3. Poll inbox for heartbeat_result event.
    4. Assert event was created by the scheduler.

    API endpoints:
    - PUT /api/agents/{agentId}/config/heartbeat
    - GET /api/console/inbox/events
    """
    srv, mock_url = mock_llm
    srv.force_error = False
    working_dir = app_server.working_dir
    clean_inbox(working_dir)
    unregister_mock_provider(
        app_server,
        MOCK_LLM_PROVIDER_ID,
    )

    provider_id = register_mock_provider(app_server, mock_url)

    hb_before = app_server.api_request(
        "GET",
        scoped("default", "/config/heartbeat"),
        timeout=_HTTP_TIMEOUT,
    ).json()

    ws_dir = Path(working_dir) / "workspaces" / "default"
    hb_file = ws_dir / "HEARTBEAT.md"
    ws_dir.mkdir(parents=True, exist_ok=True)
    hb_original = hb_file.read_text("utf-8") if hb_file.exists() else None
    hb_file.write_text(
        "Auto-schedule heartbeat test query",
        encoding="utf-8",
    )

    app_server.api_request(
        "PUT",
        scoped("default", "/config/heartbeat"),
        json={
            "enabled": True,
            "target": "inbox",
            "every": "60s",
        },
        timeout=_HTTP_TIMEOUT,
    )

    try:
        events = _poll_inbox_heartbeat(
            app_server,
            time.time() + 80.0,
            event_type="heartbeat_result",
        )
        assert len(events) >= 1, (
            "No auto-scheduled heartbeat event after 80s: "
            f"{app_server.logs_tail()}"
        )
        event = events[0]
        assert event["source_type"] == "heartbeat"
        assert event["event_type"] == "heartbeat_result"
    finally:
        clean_inbox(working_dir)
        if hb_original is not None:
            hb_file.write_text(hb_original, encoding="utf-8")
        elif hb_file.exists():
            hb_file.unlink()
        app_server.api_request(
            "PUT",
            scoped("default", "/config/heartbeat"),
            json=hb_before,
            timeout=_HTTP_TIMEOUT,
        )
        unregister_mock_provider(app_server, provider_id)
