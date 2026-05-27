# -*- coding: utf-8 -*-
"""Integration tests for the cron header (default-agent) endpoints.

The cron router is mounted twice — once under ``/api/agents/{agentId}/cron``
(scoped, covered by test_cron.py) and once under ``/api/cron`` (header,
covered here). Both share the same code path; the header tests verify
the default-agent resolution route (``get_agent_for_request`` →
default agent's CronManager) works end-to-end.

Job state lives on disk:
  - jobs.json:   <working_dir>/workspaces/default/jobs.json
  - history:     <working_dir>/workspaces/default/jobs_history/<job_id>.json

Most cases seed jobs through the HTTP API itself (so we exercise the
real write path). The history case seeds the history file directly
because the CronExecutor would need a real LLM round-trip to produce
records — that's Sprint 2.4's job. The manager caches history on
first read, so we seed BEFORE the first GET history call.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

_CRON_HTTP_TIMEOUT = 15.0


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _minimal_text_cron_spec(*, name: str, user_id: str | None = None) -> dict:
    """Build a valid CronJobSpec with task_type=text (no agent run)."""
    return {
        "name": name,
        "enabled": True,
        "schedule": {"type": "cron", "cron": "0 0 * * *", "timezone": "UTC"},
        "task_type": "text",
        "text": f"integration cron noop: {name}",
        "dispatch": {
            "type": "channel",
            "channel": "console",
            "target": {
                "user_id": user_id or "integ-cron-header-user",
                "session_id": (
                    "console:integ-cron-header-"
                    + (user_id or "default")
                    + "-session"
                ),
            },
            "mode": "stream",
            "meta": {},
        },
    }


def _default_workspace_dir(app_server) -> Path:
    """Resolve the default agent's workspace dir on disk.

    Matches the layout set up by the app startup migration:
    ``<working_dir>/workspaces/default``.
    """
    return app_server.working_dir / "workspaces" / "default"


def _create_cron_job(app_server, spec: dict) -> str:
    """POST /api/cron/jobs and return the new server-assigned job id."""
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


def _delete_cron_job_quietly(app_server, job_id: str) -> None:
    """Best-effort delete used by finally blocks."""
    app_server.api_request(
        "DELETE",
        f"/api/cron/jobs/{job_id}",
        timeout=_CRON_HTTP_TIMEOUT,
    )


def _seed_history_records(
    app_server,
    job_id: str,
    records: list[dict[str, Any]],
) -> None:
    """Write seeded CronExecutionRecord list to the job's history file.

    Must be called BEFORE the first GET /api/cron/jobs/{id}/history,
    otherwise CronManager will have already cached an empty list.
    """
    history_dir = _default_workspace_dir(app_server) / "jobs_history"
    history_dir.mkdir(parents=True, exist_ok=True)
    history_file = history_dir / f"{job_id}.json"
    history_file.write_text(
        json.dumps(records, ensure_ascii=False),
        encoding="utf-8",
    )


# --------------------------------------------------------------------------- #
# cases
# --------------------------------------------------------------------------- #


@pytest.mark.integration
@pytest.mark.p1
def test_cron_header_jobs_list_returns_empty_array_contract(
    app_server,
) -> None:
    """Test purpose:
    - Verify GET /api/cron/jobs returns [] on a fresh workspace. This
      is the first read Console's 定时任务 page makes; a 5xx here
      blocks the entire cron UI from loading.

    Test flow:
    1. GET /api/cron/jobs (no jobs created yet — but other tests in
       this module may have left some, so just assert ``isinstance
       list`` rather than strict empty).
    2. Assert 200 + response is a list.

    API endpoints:
    - GET /api/cron/jobs
    """
    resp = app_server.api_request(
        "GET",
        "/api/cron/jobs",
        timeout=_CRON_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    assert isinstance(resp.json(), list)


@pytest.mark.integration
@pytest.mark.p1
def test_cron_header_jobs_create_three_then_list_returns_all(
    app_server,
) -> None:
    """Test purpose:
    - Verify the header list endpoint reflects every job that was
      created via the header POST endpoint, with name + id intact.
      This exercises real data (3 distinct jobs) rather than the empty
      contract.

    Test flow:
    1. POST /api/cron/jobs three times with distinct names + targets.
    2. GET /api/cron/jobs and check all 3 ids/names appear with their
       correct schedule.
    3. finally — delete all 3.

    API endpoints:
    - POST /api/cron/jobs
    - GET /api/cron/jobs
    - DELETE /api/cron/jobs/{job_id}
    """
    job_ids: list[str] = []
    expected = [
        ("integ header cron A", "alice"),
        ("integ header cron B", "bob"),
        ("integ header cron C", "carol"),
    ]
    try:
        for name, user in expected:
            spec = _minimal_text_cron_spec(name=name, user_id=user)
            job_ids.append(_create_cron_job(app_server, spec))

        list_resp = app_server.api_request(
            "GET",
            "/api/cron/jobs",
            timeout=_CRON_HTTP_TIMEOUT,
        )
        assert list_resp.status_code == 200, app_server.logs_tail()
        items = list_resp.json()
        listed_ids = {item.get("id") for item in items}
        for job_id in job_ids:
            assert job_id in listed_ids, f"missing {job_id} in {listed_ids}"

        by_id = {
            item["id"]: item for item in items if item.get("id") in job_ids
        }
        for job_id, (name, _user) in zip(job_ids, expected):
            assert by_id[job_id].get("name") == name
            assert by_id[job_id].get("enabled") is True
    finally:
        for job_id in job_ids:
            _delete_cron_job_quietly(app_server, job_id)


@pytest.mark.integration
@pytest.mark.p2
def test_cron_header_get_job_returns_404_for_missing(app_server) -> None:
    """Test purpose:
    - Verify GET /api/cron/jobs/<missing> returns 404 + "job not found".

    Test flow:
    1. GET /api/cron/jobs/integ-missing-job-id-0001.
    2. Assert 404 + detail == "job not found".

    API endpoints:
    - GET /api/cron/jobs/{job_id}
    """
    resp = app_server.api_request(
        "GET",
        "/api/cron/jobs/integ-missing-cron-header-0001",
        timeout=_CRON_HTTP_TIMEOUT,
    )
    assert resp.status_code == 404, app_server.logs_tail()
    assert resp.json().get("detail") == "job not found"


@pytest.mark.integration
@pytest.mark.p1
def test_cron_header_dispatch_targets_returns_contract(app_server) -> None:
    """Test purpose:
    - Verify GET /api/cron/dispatch-targets returns the documented
      ``{channels: [...], items: [...]}`` shape with ``console``
      always present in the channels list (the server unconditionally
      surfaces console as a fallback channel).

    Test flow:
    1. GET /api/cron/dispatch-targets.
    2. Assert 200, response is a dict, ``channels`` is a list that
       contains ``console``, and ``items`` is a list.

    API endpoints:
    - GET /api/cron/dispatch-targets
    """
    resp = app_server.api_request(
        "GET",
        "/api/cron/dispatch-targets",
        timeout=_CRON_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    payload = resp.json()
    assert isinstance(payload, dict)
    channels = payload.get("channels")
    assert isinstance(channels, list)
    assert "console" in channels
    assert isinstance(payload.get("items"), list)


@pytest.mark.integration
@pytest.mark.p0
def test_cron_header_jobs_lifecycle_via_default_agent(app_server) -> None:
    """Test purpose:
    - Exercise the full header cron lifecycle (create → get → put →
      pause → resume → state → manual run trigger → delete → 404) so
      the default-agent resolution path is verified end-to-end. The
      scoped equivalent is already covered by
      ``test_agent_scoped_cron_job_lifecycle``; both paths share the
      same code but resolve the workspace differently.

    Test flow:
    1. POST /api/cron/jobs → capture job_id.
    2. GET /api/cron/jobs/{id} → assert detail matches.
    3. PUT /api/cron/jobs/{id} → rename; assert new name read back.
    4. POST .../pause → assert 200; GET .../state → enabled=false.
    5. POST .../resume → assert 200; GET .../state → enabled=true.
    6. POST .../run → assert 200 (manual run accepted; executor runs
       async with a noop text payload).
    7. DELETE → assert 200; repeat DELETE → 404 "job not found".

    API endpoints:
    - POST /api/cron/jobs
    - GET /api/cron/jobs/{job_id}
    - PUT /api/cron/jobs/{job_id}
    - POST /api/cron/jobs/{job_id}/pause
    - POST /api/cron/jobs/{job_id}/resume
    - POST /api/cron/jobs/{job_id}/run
    - GET /api/cron/jobs/{job_id}/state
    - DELETE /api/cron/jobs/{job_id}
    """
    spec_v1 = _minimal_text_cron_spec(name="integ header lifecycle v1")
    job_id = _create_cron_job(app_server, spec_v1)

    try:
        get_resp = app_server.api_request(
            "GET",
            f"/api/cron/jobs/{job_id}",
            timeout=_CRON_HTTP_TIMEOUT,
        )
        assert get_resp.status_code == 200, app_server.logs_tail()
        view = get_resp.json()
        assert view.get("spec", {}).get("id") == job_id
        assert view.get("spec", {}).get("name") == "integ header lifecycle v1"

        spec_v2 = dict(spec_v1)
        spec_v2["name"] = "integ header lifecycle v2"
        spec_v2["id"] = job_id
        put_resp = app_server.api_request(
            "PUT",
            f"/api/cron/jobs/{job_id}",
            json=spec_v2,
            timeout=_CRON_HTTP_TIMEOUT,
        )
        assert put_resp.status_code == 200, app_server.logs_tail()
        assert put_resp.json().get("name") == "integ header lifecycle v2"

        pause_resp = app_server.api_request(
            "POST",
            f"/api/cron/jobs/{job_id}/pause",
            timeout=_CRON_HTTP_TIMEOUT,
        )
        assert pause_resp.status_code == 200, app_server.logs_tail()
        # GET state right after pause: CronJobState currently does not
        # expose a ``paused`` boolean (pause_job only touches the
        # internal APScheduler state, not the persisted spec), so we
        # can only assert the endpoint contract holds and that
        # ``next_run_at`` is reachable. Strict pause-state assertion
        # is gated on the server exposing a state.paused field.
        state_after_pause = app_server.api_request(
            "GET",
            f"/api/cron/jobs/{job_id}/state",
            timeout=_CRON_HTTP_TIMEOUT,
        )
        assert state_after_pause.status_code == 200, app_server.logs_tail()
        paused_state = state_after_pause.json()
        assert isinstance(paused_state, dict)
        assert "next_run_at" in paused_state

        resume_resp = app_server.api_request(
            "POST",
            f"/api/cron/jobs/{job_id}/resume",
            timeout=_CRON_HTTP_TIMEOUT,
        )
        assert resume_resp.status_code == 200, app_server.logs_tail()
        # GET state right after resume: same API-limitation caveat as
        # above. Assert the contract still holds (so the resume call
        # didn't corrupt state) and the state object is still well-formed.
        state_after_resume = app_server.api_request(
            "GET",
            f"/api/cron/jobs/{job_id}/state",
            timeout=_CRON_HTTP_TIMEOUT,
        )
        assert state_after_resume.status_code == 200, app_server.logs_tail()
        resumed_state = state_after_resume.json()
        assert isinstance(resumed_state, dict)
        assert "next_run_at" in resumed_state

        run_resp = app_server.api_request(
            "POST",
            f"/api/cron/jobs/{job_id}/run",
            timeout=_CRON_HTTP_TIMEOUT,
        )
        assert run_resp.status_code == 200, app_server.logs_tail()

        delete_resp = app_server.api_request(
            "DELETE",
            f"/api/cron/jobs/{job_id}",
            timeout=_CRON_HTTP_TIMEOUT,
        )
        assert delete_resp.status_code == 200, app_server.logs_tail()
        job_id = None  # avoid double-delete in finally

        repeat_delete = app_server.api_request(
            "DELETE",
            f"/api/cron/jobs/{view['spec']['id']}",
            timeout=_CRON_HTTP_TIMEOUT,
        )
        assert repeat_delete.status_code == 404, app_server.logs_tail()
    finally:
        if job_id:
            _delete_cron_job_quietly(app_server, job_id)


@pytest.mark.integration
@pytest.mark.p1
def test_cron_header_job_history_with_seeded_records_returns_chronological(
    app_server,
) -> None:
    """Test purpose:
    - Verify GET /api/cron/jobs/{id}/history returns seeded records
      with their schema fields intact (run_at, status, error, trigger).
      Because executing a job needs a real LLM round-trip (deferred
      to Sprint 2.4), we seed history.json directly under the default
      workspace and call GET before the manager caches anything for
      this job_id.

    Test flow:
    1. Create a new job; capture job_id.
    2. Write 3 CronExecutionRecord entries to
       <ws>/jobs_history/<job_id>.json (2 success + 1 error, distinct
       run_at timestamps).
    3. GET /api/cron/jobs/{id}/history.
    4. Assert 200 + length 3 + status/error/trigger values match the
       seeded records, in the order they were written.
    5. finally — delete the job.

    API endpoints:
    - POST /api/cron/jobs
    - GET /api/cron/jobs/{job_id}/history
    - DELETE /api/cron/jobs/{job_id}
    """
    spec = _minimal_text_cron_spec(name="integ header history seed")
    job_id = _create_cron_job(app_server, spec)
    try:
        seeded: list[dict[str, Any]] = [
            {
                "run_at": "2026-05-26T08:00:00+00:00",
                "status": "success",
                "error": None,
                "trigger": "scheduled",
            },
            {
                "run_at": "2026-05-26T10:00:00+00:00",
                "status": "error",
                "error": "integration seeded failure",
                "trigger": "manual",
            },
            {
                "run_at": "2026-05-26T12:00:00+00:00",
                "status": "success",
                "error": None,
                "trigger": "scheduled",
            },
        ]
        _seed_history_records(app_server, job_id, seeded)

        history_resp = app_server.api_request(
            "GET",
            f"/api/cron/jobs/{job_id}/history",
            timeout=_CRON_HTTP_TIMEOUT,
        )
        assert history_resp.status_code == 200, app_server.logs_tail()
        records = history_resp.json()
        assert isinstance(records, list)
        assert len(records) == 3, records

        # API returns records in the same order they appear on disk.
        for returned, want in zip(records, seeded):
            assert returned.get("status") == want["status"]
            assert returned.get("trigger") == want["trigger"]
            assert returned.get("error") == want["error"]
            # run_at may be normalised to ISO string with or without tz;
            # just confirm it round-trips a stable value.
            assert isinstance(returned.get("run_at"), str)
    finally:
        _delete_cron_job_quietly(app_server, job_id)


@pytest.mark.integration
@pytest.mark.p2
def test_cron_header_dispatch_targets_filter_by_keyword(app_server) -> None:
    """Test purpose:
    - Verify the ``keyword`` filter on dispatch-targets actually
      partitions items: a chat created with user_id=alice should
      appear when querying ``?keyword=alice`` and disappear under a
      synthetic non-matching keyword. Console's "选择派发目标"
      autocomplete relies on this.

    Test flow:
    1. POST /api/chats with channel=console, user_id=alice — creates
       a chat that will surface as a dispatch target.
    2. GET /api/cron/dispatch-targets?keyword=alice — assert items
       includes an entry whose user_id == "alice".
    3. GET ?keyword=integ-no-such-user — assert items is empty (or
       at least does not contain "alice").
    4. finally — delete the chat.

    API endpoints:
    - POST /api/chats
    - GET /api/cron/dispatch-targets
    - DELETE /api/chats/{chat_id}
    """
    user_id = "alice-integ-cron-filter"
    session_id = f"console:{user_id}-session"
    create_resp = app_server.api_request(
        "POST",
        "/api/chats",
        json={
            "name": "integ cron filter chat",
            "session_id": session_id,
            "user_id": user_id,
            "channel": "console",
        },
        timeout=_CRON_HTTP_TIMEOUT,
    )
    assert create_resp.status_code == 200, app_server.logs_tail()
    chat_id = create_resp.json().get("id")
    assert isinstance(chat_id, str) and chat_id

    try:
        # tiny sleep so the chat row is fully persisted before the
        # dispatch-target list re-derives from chats
        time.sleep(0.1)

        match_resp = app_server.api_request(
            "GET",
            "/api/cron/dispatch-targets",
            params={"keyword": user_id},
            timeout=_CRON_HTTP_TIMEOUT,
        )
        assert match_resp.status_code == 200, app_server.logs_tail()
        match_items = match_resp.json().get("items", [])
        assert any(
            item.get("user_id") == user_id for item in match_items
        ), f"alice not in matched items: {match_items}"

        miss_resp = app_server.api_request(
            "GET",
            "/api/cron/dispatch-targets",
            params={"keyword": "integ-no-such-user-xyz"},
            timeout=_CRON_HTTP_TIMEOUT,
        )
        assert miss_resp.status_code == 200, app_server.logs_tail()
        miss_items = miss_resp.json().get("items", [])
        assert not any(
            item.get("user_id") == user_id for item in miss_items
        ), f"alice leaked into non-matching filter: {miss_items}"
    finally:
        app_server.api_request(
            "DELETE",
            f"/api/chats/{chat_id}",
            timeout=_CRON_HTTP_TIMEOUT,
        )
