# -*- coding: utf-8 -*-
"""Integration tests for agent-scoped cron job APIs."""
from __future__ import annotations

import copy

import pytest

_CRON_HTTP_TIMEOUT = 30.0


def _minimal_text_cron_spec(*, name: str) -> dict:
    """Build a valid CronJobSpec with task_type=text (no agent request)."""
    return {
        "name": name,
        "enabled": True,
        "schedule": {"type": "cron", "cron": "0 0 * * *", "timezone": "UTC"},
        "task_type": "text",
        "text": "integration cron noop",
        "dispatch": {
            "type": "channel",
            "channel": "console",
            "target": {
                "user_id": "integ-cron-user",
                "session_id": "console:integ-cron-session",
            },
            "mode": "stream",
            "meta": {},
        },
    }


@pytest.mark.integration
@pytest.mark.p0
# pylint: disable-next=too-many-statements
def test_agent_scoped_cron_job_lifecycle(
    app_server,
) -> None:
    """Test purpose:
    - Verify agent-scoped cron endpoints support create, list, detail, replace,
      pause, resume, manual run trigger, runtime state read, and delete.

    Test flow:
    1. Create a dedicated test agent.
    2. POST a minimal text cron job and capture server-assigned ``id``.
    3. GET job list and single job view; assert job is present.
    4. PUT replace job (rename) and read back via GET view.
    5. POST pause and resume; assert success flags.
    6. POST run (fire-and-forget) and GET job state payload.
    7. DELETE job and assert repeat DELETE returns 404.
    8. Delete test agent.

    API endpoints:
    - POST /api/agents
    - POST /api/agents/{agentId}/cron/jobs
    - GET /api/agents/{agentId}/cron/jobs
    - GET /api/agents/{agentId}/cron/jobs/{job_id}
    - PUT /api/agents/{agentId}/cron/jobs/{job_id}
    - POST /api/agents/{agentId}/cron/jobs/{job_id}/pause
    - POST /api/agents/{agentId}/cron/jobs/{job_id}/resume
    - POST /api/agents/{agentId}/cron/jobs/{job_id}/run
    - GET /api/agents/{agentId}/cron/jobs/{job_id}/state
    - DELETE /api/agents/{agentId}/cron/jobs/{job_id}
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_cron_lifecycle_01"
    base = f"/api/agents/{agent_id}/cron"
    job_id: str | None = None

    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={
            "id": agent_id,
            "name": "Cron lifecycle agent",
            "description": "",
        },
        timeout=_CRON_HTTP_TIMEOUT,
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    try:
        create_job = app_server.api_request(
            "POST",
            f"{base}/jobs",
            json=_minimal_text_cron_spec(name="integration cron job v1"),
            timeout=_CRON_HTTP_TIMEOUT,
        )
        assert create_job.status_code == 200, app_server.logs_tail()
        created = create_job.json()
        job_id = created.get("id")
        assert isinstance(job_id, str) and job_id
        assert created.get("name") == "integration cron job v1"

        list_resp = app_server.api_request(
            "GET",
            f"{base}/jobs",
            timeout=_CRON_HTTP_TIMEOUT,
        )
        assert list_resp.status_code == 200, app_server.logs_tail()
        listed_ids = {j.get("id") for j in list_resp.json()}
        assert job_id in listed_ids

        get_view = app_server.api_request(
            "GET",
            f"{base}/jobs/{job_id}",
            timeout=_CRON_HTTP_TIMEOUT,
        )
        assert get_view.status_code == 200, app_server.logs_tail()
        view_payload = get_view.json()
        assert view_payload.get("spec", {}).get("id") == job_id
        assert "state" in view_payload

        spec_for_put = copy.deepcopy(view_payload["spec"])
        spec_for_put["name"] = "integration cron job v2"
        put_replace = app_server.api_request(
            "PUT",
            f"{base}/jobs/{job_id}",
            json=spec_for_put,
            timeout=_CRON_HTTP_TIMEOUT,
        )
        assert put_replace.status_code == 200, app_server.logs_tail()
        assert put_replace.json().get("name") == "integration cron job v2"

        get_after_put = app_server.api_request(
            "GET",
            f"{base}/jobs/{job_id}",
            timeout=_CRON_HTTP_TIMEOUT,
        )
        assert get_after_put.status_code == 200, app_server.logs_tail()
        assert (
            get_after_put.json()["spec"]["name"] == "integration cron job v2"
        )

        pause_resp = app_server.api_request(
            "POST",
            f"{base}/jobs/{job_id}/pause",
            timeout=_CRON_HTTP_TIMEOUT,
        )
        assert pause_resp.status_code == 200, app_server.logs_tail()
        assert pause_resp.json().get("paused") is True

        resume_resp = app_server.api_request(
            "POST",
            f"{base}/jobs/{job_id}/resume",
            timeout=_CRON_HTTP_TIMEOUT,
        )
        assert resume_resp.status_code == 200, app_server.logs_tail()
        assert resume_resp.json().get("resumed") is True

        run_resp = app_server.api_request(
            "POST",
            f"{base}/jobs/{job_id}/run",
            timeout=_CRON_HTTP_TIMEOUT,
        )
        assert run_resp.status_code == 200, app_server.logs_tail()
        assert run_resp.json().get("started") is True

        state_resp = app_server.api_request(
            "GET",
            f"{base}/jobs/{job_id}/state",
            timeout=_CRON_HTTP_TIMEOUT,
        )
        assert state_resp.status_code == 200, app_server.logs_tail()
        state_body = state_resp.json()
        assert isinstance(state_body, dict)

        del_ok = app_server.api_request(
            "DELETE",
            f"{base}/jobs/{job_id}",
            timeout=_CRON_HTTP_TIMEOUT,
        )
        assert del_ok.status_code == 200, app_server.logs_tail()
        assert del_ok.json().get("deleted") is True

        del_again = app_server.api_request(
            "DELETE",
            f"{base}/jobs/{job_id}",
            timeout=_CRON_HTTP_TIMEOUT,
        )
        assert del_again.status_code == 404, app_server.logs_tail()
        job_id = None
    finally:
        if job_id is not None:
            app_server.api_request(
                "DELETE",
                f"{base}/jobs/{job_id}",
                timeout=_CRON_HTTP_TIMEOUT,
            )
        app_server.api_request(
            "DELETE",
            f"/api/agents/{agent_id}",
            timeout=_CRON_HTTP_TIMEOUT,
        )
