# -*- coding: utf-8 -*-
"""Integration tests for cron job *execution* (text and agent types).

Sprint 2.1/2.2 covered cron CRUD lifecycle (create, pause, resume,
delete, history seeding).  This module covers the **execution** path:
POST /run triggers real ``CronExecutor.execute()`` and we verify
history records, inbox events, and channel delivery.

Agent-type tests use the shared Mock LLM (``helpers.MockLLMHandler``)
with tool_call support to validate the full pipeline:
  Mock LLM → tool_call(get_current_time) → Agent executes → Round 2
  → text response → history success.
"""
from __future__ import annotations

import threading
import time
from http.server import HTTPServer

import pytest

from helpers import (
    MOCK_LLM_PROVIDER_ID,
    MockLLMHandler,
    clean_inbox,
    register_mock_provider,
    unregister_mock_provider,
)

_CRON_HTTP_TIMEOUT = 15.0
_NEVER_FIRE_SCHEDULE = "0 0 1 1 *"


# ------------------------------------------------------------------ #
# fixtures
# ------------------------------------------------------------------ #


@pytest.fixture(scope="module")
def mock_llm():
    """Module-scoped mock OpenAI server with tool_call support."""
    srv = HTTPServer(("127.0.0.1", 0), MockLLMHandler)
    srv.force_error = False
    srv.force_tool_call = False
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv, f"http://127.0.0.1:{port}/v1"
    srv.shutdown()


# ------------------------------------------------------------------ #
# helpers
# ------------------------------------------------------------------ #


def _text_spec(name, *, text="Hello from cron", channel="console"):
    return {
        "name": name,
        "enabled": True,
        "schedule": {
            "type": "cron",
            "cron": _NEVER_FIRE_SCHEDULE,
            "timezone": "UTC",
        },
        "task_type": "text",
        "text": text,
        "dispatch": {
            "type": "channel",
            "channel": channel,
            "target": {
                "user_id": f"cron-exec-{name}",
                "session_id": f"console:cron-exec-{name}-sess",
            },
            "mode": "stream",
        },
    }


def _agent_input(text):
    """Build AgentRequest-compatible input list."""
    return [
        {
            "role": "user",
            "type": "message",
            "content": [{"type": "text", "text": text}],
        },
    ]


def _agent_spec(
    name,
    *,
    input_text="What time is it?",
    save_inbox=False,
):
    spec = {
        "name": name,
        "enabled": True,
        "schedule": {
            "type": "cron",
            "cron": _NEVER_FIRE_SCHEDULE,
            "timezone": "UTC",
        },
        "task_type": "agent",
        "request": {"input": _agent_input(input_text)},
        "dispatch": {
            "type": "channel",
            "channel": "console",
            "target": {
                "user_id": f"cron-exec-{name}",
                "session_id": f"console:cron-exec-{name}-sess",
            },
            "mode": "stream",
        },
    }
    if save_inbox:
        spec["save_result_to_inbox"] = True
    return spec


def _create_job(app_server, spec):
    resp = app_server.api_request(
        "POST",
        "/api/cron/jobs",
        json=spec,
        timeout=_CRON_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    job_id = resp.json().get("id")
    assert isinstance(job_id, str) and job_id
    return job_id


def _delete_job(app_server, job_id):
    try:
        app_server.api_request(
            "DELETE",
            f"/api/cron/jobs/{job_id}",
            timeout=_CRON_HTTP_TIMEOUT,
        )
    except Exception:
        pass


def _poll_history(app_server, job_id, deadline, *, min_count=1):
    """Poll GET history until min_count records appear."""
    while time.time() < deadline:
        resp = app_server.api_request(
            "GET",
            f"/api/cron/jobs/{job_id}/history",
            timeout=_CRON_HTTP_TIMEOUT,
        )
        if resp.status_code == 200:
            records = resp.json()
            if isinstance(records, list) and len(records) >= min_count:
                return records
        time.sleep(1.0)
    return []


def _poll_inbox_cron(app_server, deadline, *, event_type=None):
    """Poll inbox for cron-sourced events."""
    while time.time() < deadline:
        resp = app_server.api_request(
            "GET",
            "/api/console/inbox/events",
            params={"source_type": "cron"},
            timeout=_CRON_HTTP_TIMEOUT,
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


# ------------------------------------------------------------------ #
# A1: text-type manual run → history record
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p0
def test_cron_text_manual_run_creates_history(app_server) -> None:
    """Test purpose:
    - Verify POST /run on a text-type cron job creates a history
      record with trigger=manual and status=success.

    Test flow:
    1. POST create text-type cron job (never-fire schedule).
    2. POST run (manual trigger).
    3. Poll GET history until a record appears.
    4. Assert record fields: trigger=manual, status=success.
    5. Cleanup: DELETE job.

    API endpoints:
    - POST /api/cron/jobs
    - POST /api/cron/jobs/{job_id}/run
    - GET /api/cron/jobs/{job_id}/history
    - DELETE /api/cron/jobs/{job_id}
    """
    spec = _text_spec("integ_text_hist")
    job_id = _create_job(app_server, spec)
    try:
        run_resp = app_server.api_request(
            "POST",
            f"/api/cron/jobs/{job_id}/run",
            timeout=_CRON_HTTP_TIMEOUT,
        )
        assert run_resp.status_code == 200
        assert run_resp.json().get("started") is True

        records = _poll_history(
            app_server,
            job_id,
            time.time() + 15.0,
        )
        assert (
            len(records) >= 1
        ), f"No history record after 15s: {app_server.logs_tail()}"

        rec = records[0]
        assert rec["trigger"] == "manual"
        assert rec["status"] == "success"
        assert "run_at" in rec
    finally:
        _delete_job(app_server, job_id)


# ------------------------------------------------------------------ #
# A2: agent-type manual run with Mock LLM (text only, no tool_call)
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p0
def test_cron_agent_manual_run_with_mock_llm(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
) -> None:
    """Test purpose:
    - Verify POST /run on an agent-type cron job with Mock LLM
      produces a successful history record.

    Test flow:
    1. Register mock LLM provider.
    2. POST create agent-type cron job.
    3. POST run (manual trigger).
    4. Poll history until success record appears.
    5. Cleanup.

    API endpoints:
    - POST /api/cron/jobs
    - POST /api/cron/jobs/{job_id}/run
    - GET /api/cron/jobs/{job_id}/history
    - DELETE /api/cron/jobs/{job_id}
    """
    srv, mock_url = mock_llm
    srv.force_error = False
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    spec = _agent_spec("integ_agent_hist", input_text="Hello")
    job_id = _create_job(app_server, spec)
    try:
        run_resp = app_server.api_request(
            "POST",
            f"/api/cron/jobs/{job_id}/run",
            timeout=_CRON_HTTP_TIMEOUT,
        )
        assert run_resp.status_code == 200
        assert run_resp.json().get("started") is True

        records = _poll_history(
            app_server,
            job_id,
            time.time() + 30.0,
        )
        assert (
            len(records) >= 1
        ), f"No history record after 30s: {app_server.logs_tail()}"

        rec = records[0]
        assert rec["trigger"] == "manual"
        assert rec["status"] == "success"
    finally:
        _delete_job(app_server, job_id)
        unregister_mock_provider(app_server, provider_id)


# ------------------------------------------------------------------ #
# A3: agent-type with tool_call (get_current_time) — full pipeline
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p0
def test_cron_agent_tool_call_execution(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
) -> None:
    """Test purpose:
    - Verify Mock LLM tool_call round-trip: the agent receives a
      tool_call for get_current_time, executes it, sends the result
      back, and the second LLM round produces a text summary.

    Test flow:
    1. Register mock LLM provider.
    2. POST create agent-type cron job with save_result_to_inbox=true.
    3. POST run.
    4. Poll history → status=success.
    5. Poll inbox → cron_result event body contains time info.
    6. Cleanup.

    API endpoints:
    - POST /api/cron/jobs
    - POST /api/cron/jobs/{job_id}/run
    - GET /api/cron/jobs/{job_id}/history
    - GET /api/console/inbox/events
    - DELETE /api/cron/jobs/{job_id}
    """
    srv, mock_url = mock_llm
    srv.force_error = False
    srv.force_tool_call = True
    clean_inbox(app_server.working_dir)
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    spec = _agent_spec(
        "integ_tool_call",
        input_text="What time is it?",
        save_inbox=True,
    )
    job_id = _create_job(app_server, spec)
    try:
        run_resp = app_server.api_request(
            "POST",
            f"/api/cron/jobs/{job_id}/run",
            timeout=_CRON_HTTP_TIMEOUT,
        )
        assert run_resp.status_code == 200

        records = _poll_history(
            app_server,
            job_id,
            time.time() + 30.0,
        )
        assert (
            len(records) >= 1
        ), f"No history after 30s: {app_server.logs_tail()}"
        assert records[0]["status"] == "success"

        events = _poll_inbox_cron(
            app_server,
            time.time() + 10.0,
            event_type="cron_result",
        )
        assert (
            len(events) >= 1
        ), f"No cron_result event: {app_server.logs_tail()}"
        event = events[0]
        assert event["source_type"] == "cron"
        assert event.get("body"), "event body should not be empty"
    finally:
        srv.force_tool_call = False
        _delete_job(app_server, job_id)
        clean_inbox(app_server.working_dir)
        unregister_mock_provider(app_server, provider_id)


# ------------------------------------------------------------------ #
# A4: agent run → inbox event
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_cron_agent_run_creates_inbox_event(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
) -> None:
    """Test purpose:
    - Verify an agent-type cron run with save_result_to_inbox
      creates a cron_result inbox event with correct metadata.

    Test flow:
    1. Register mock LLM provider.
    2. POST create agent-type job with save_result_to_inbox=true.
    3. POST run.
    4. Poll inbox for cron_result event.
    5. Assert event fields: source_type, event_type, agent_id.
    6. Cleanup.

    API endpoints:
    - POST /api/cron/jobs
    - POST /api/cron/jobs/{job_id}/run
    - GET /api/console/inbox/events
    - DELETE /api/cron/jobs/{job_id}
    """
    srv, mock_url = mock_llm
    srv.force_error = False
    clean_inbox(app_server.working_dir)
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    spec = _agent_spec(
        "integ_inbox_event",
        input_text="Say hello",
        save_inbox=True,
    )
    job_id = _create_job(app_server, spec)
    try:
        app_server.api_request(
            "POST",
            f"/api/cron/jobs/{job_id}/run",
            timeout=_CRON_HTTP_TIMEOUT,
        )

        events = _poll_inbox_cron(
            app_server,
            time.time() + 30.0,
            event_type="cron_result",
        )
        assert (
            len(events) >= 1
        ), f"No cron_result inbox event: {app_server.logs_tail()}"

        event = events[0]
        assert event["source_type"] == "cron"
        assert event["event_type"] == "cron_result"
        assert event["agent_id"] == "default"
        assert event["status"] == "success"
        assert event["severity"] == "info"
    finally:
        _delete_job(app_server, job_id)
        clean_inbox(app_server.working_dir)
        unregister_mock_provider(app_server, provider_id)


# ------------------------------------------------------------------ #
# A5: text delivery to custom channel
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_cron_text_delivery_to_custom_channel(
    app_server,
    channel_callback_server,
) -> None:
    """Test purpose:
    - Verify a text-type cron job dispatched to the test_echo custom
      channel delivers the text to the callback server.

    Test flow:
    1. Enable test_echo channel.
    2. POST create text-type job dispatched to test_echo.
    3. POST run.
    4. Poll callback server recorded payloads.
    5. Assert the text arrives at the callback.
    6. Cleanup.

    API endpoints:
    - PUT /api/config/channels/test_echo
    - POST /api/cron/jobs
    - POST /api/cron/jobs/{job_id}/run
    - DELETE /api/cron/jobs/{job_id}
    """
    server = channel_callback_server
    server.recorded.clear()

    app_server.api_request(
        "PUT",
        "/api/config/channels/test_echo",
        json={"enabled": True},
        timeout=_CRON_HTTP_TIMEOUT,
    )
    time.sleep(1.0)

    cron_text = "cron-delivery-test-payload"
    spec = _text_spec(
        "integ_text_channel",
        text=cron_text,
        channel="test_echo",
    )
    job_id = _create_job(app_server, spec)
    try:
        run_resp = app_server.api_request(
            "POST",
            f"/api/cron/jobs/{job_id}/run",
            timeout=_CRON_HTTP_TIMEOUT,
        )
        assert run_resp.status_code == 200

        deadline = time.time() + 10.0
        while time.time() < deadline and not server.recorded:
            time.sleep(0.5)

        assert (
            len(server.recorded) >= 1
        ), "callback server did not receive cron text"
        assert server.recorded[0].get("text") == cron_text
    finally:
        _delete_job(app_server, job_id)


# ------------------------------------------------------------------ #
# A6: agent run error → error history record
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_cron_delivery_error_creates_error_record(
    app_server,
) -> None:
    """Test purpose:
    - Verify that a cron job whose channel delivery fails creates
      a history record with status=error and a descriptive error.
      Dispatches to a non-existent channel to trigger KeyError
      in channel_manager.send_text().

    Test flow:
    1. POST create text-type job dispatched to non-existent channel.
    2. POST run.
    3. Poll history → status=error record with delivery error.
    4. Cleanup.

    API endpoints:
    - POST /api/cron/jobs
    - POST /api/cron/jobs/{job_id}/run
    - GET /api/cron/jobs/{job_id}/history
    - DELETE /api/cron/jobs/{job_id}
    """
    spec = _text_spec(
        "integ_delivery_error",
        channel="nonexistent_integ_xyz",
    )
    job_id = _create_job(app_server, spec)
    try:
        app_server.api_request(
            "POST",
            f"/api/cron/jobs/{job_id}/run",
            timeout=_CRON_HTTP_TIMEOUT,
        )

        records = _poll_history(
            app_server,
            job_id,
            time.time() + 15.0,
        )
        assert (
            len(records) >= 1
        ), f"No history record after 15s: {app_server.logs_tail()}"
        assert records[0]["status"] == "error"
        assert records[0].get("error")
    finally:
        _delete_job(app_server, job_id)


# ------------------------------------------------------------------ #
# A7: scheduler fires on schedule (P2 — nightly only, ~70s wait)
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p2
def test_cron_scheduler_fires_on_schedule(app_server) -> None:
    """Test purpose:
    - Verify a cron job with ``* * * * *`` schedule fires
      automatically via the APScheduler within ~70 seconds.

    Test flow:
    1. POST create text-type job with ``* * * * *``.
    2. Wait up to 80s.
    3. Poll history → at least 1 record with trigger=scheduled.
    4. Cleanup.

    API endpoints:
    - POST /api/cron/jobs
    - GET /api/cron/jobs/{job_id}/history
    - DELETE /api/cron/jobs/{job_id}
    """
    spec = _text_spec("integ_sched_fire")
    spec["schedule"]["cron"] = "* * * * *"
    job_id = _create_job(app_server, spec)
    try:
        records = _poll_history(
            app_server,
            job_id,
            time.time() + 80.0,
        )
        assert len(records) >= 1, (
            f"No scheduled record after 80s: " f"{app_server.logs_tail()}"
        )
        scheduled = [r for r in records if r.get("trigger") == "scheduled"]
        assert len(scheduled) >= 1, f"No trigger=scheduled record: {records}"
    finally:
        _delete_job(app_server, job_id)


# ------------------------------------------------------------------ #
# A8: paused job not fired by scheduler (P2 — nightly only, ~70s)
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p2
def test_cron_paused_job_not_fired_by_scheduler(
    app_server,
) -> None:
    """Test purpose:
    - Verify a paused cron job with ``* * * * *`` does NOT fire
      automatically even after waiting past its schedule.

    Test flow:
    1. POST create text-type job with ``* * * * *``.
    2. POST pause the job.
    3. Wait 70s.
    4. GET history → should be empty (no scheduled runs).
    5. Cleanup.

    API endpoints:
    - POST /api/cron/jobs
    - POST /api/cron/jobs/{job_id}/pause
    - GET /api/cron/jobs/{job_id}/history
    - DELETE /api/cron/jobs/{job_id}
    """
    spec = _text_spec("integ_paused_no_fire")
    spec["schedule"]["cron"] = "* * * * *"
    job_id = _create_job(app_server, spec)
    try:
        pause_resp = app_server.api_request(
            "POST",
            f"/api/cron/jobs/{job_id}/pause",
            timeout=_CRON_HTTP_TIMEOUT,
        )
        assert pause_resp.status_code == 200

        time.sleep(70.0)

        hist_resp = app_server.api_request(
            "GET",
            f"/api/cron/jobs/{job_id}/history",
            timeout=_CRON_HTTP_TIMEOUT,
        )
        assert hist_resp.status_code == 200
        records = hist_resp.json()
        assert isinstance(records, list)
        assert len(records) == 0, f"paused job should not fire, got: {records}"
    finally:
        _delete_job(app_server, job_id)


# ------------------------------------------------------------------ #
# A9: validation — text job without text field → 422
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p2
def test_cron_create_text_without_text_rejected(
    app_server,
) -> None:
    """Test purpose:
    - Verify POST create with task_type=text but no text field
      returns 422 (Pydantic validation).

    Test flow:
    1. POST /api/cron/jobs with task_type=text, text omitted.
    2. Assert 422.

    API endpoints:
    - POST /api/cron/jobs
    """
    spec = {
        "name": "integ_bad_text_job",
        "enabled": True,
        "schedule": {
            "type": "cron",
            "cron": "0 0 * * *",
        },
        "task_type": "text",
        "dispatch": {
            "type": "channel",
            "channel": "console",
            "target": {
                "user_id": "cron-bad",
                "session_id": "console:cron-bad-sess",
            },
        },
    }
    resp = app_server.api_request(
        "POST",
        "/api/cron/jobs",
        json=spec,
        timeout=_CRON_HTTP_TIMEOUT,
    )
    assert (
        resp.status_code == 422
    ), f"expected 422, got {resp.status_code}: {resp.text}"
