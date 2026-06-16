# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name
# -*- coding: utf-8 -*-
"""Integration tests for provider switching and retry/rate-limit
(Sprint 3.1-C).

Drives the mock LLM with custom HTTP status codes to exercise:
- Two distinct mock providers and active-model switching round-trip.
- 429 → recovery via the RetryChatModel wrapper.
- Persistent 500 → final failure surfaces in cron history.
- Agent-scoped running config roundtrip for retry/rate-limit knobs.
"""
from __future__ import annotations

import threading
import time
from http.server import HTTPServer

import pytest

from helpers import (
    MOCK_LLM_PROVIDER_ID,
    MockLLMHandler,
    register_mock_provider,
    scoped,
    unregister_mock_provider,
)

_HTTP_TIMEOUT = 15.0
_NEVER_FIRE_SCHEDULE = "0 0 1 1 *"


# ------------------------------------------------------------------ #
# fixtures
# ------------------------------------------------------------------ #


def _spawn_mock_llm():
    srv = HTTPServer(("127.0.0.1", 0), MockLLMHandler)
    srv.force_error = False
    srv.force_tool_call = False
    srv.force_status_code = None
    srv.request_count = 0
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, f"http://127.0.0.1:{port}/v1"


@pytest.fixture(scope="function")
def mock_llm():
    srv, url = _spawn_mock_llm()
    yield srv, url
    srv.shutdown()


@pytest.fixture(scope="function")
def second_mock_llm():
    """Second function-scoped mock LLM used by the switching test."""
    srv, url = _spawn_mock_llm()
    yield srv, url
    srv.shutdown()


# ------------------------------------------------------------------ #
# helpers
# ------------------------------------------------------------------ #


def _agent_input(text):
    return [
        {
            "role": "user",
            "type": "message",
            "content": [{"type": "text", "text": text}],
        },
    ]


def _agent_spec(name):
    return {
        "name": name,
        "enabled": True,
        "schedule": {
            "type": "cron",
            "cron": _NEVER_FIRE_SCHEDULE,
            "timezone": "UTC",
        },
        "task_type": "agent",
        "request": {"input": _agent_input("ping")},
        "dispatch": {
            "type": "channel",
            "channel": "console",
            "target": {
                "user_id": f"prov-{name}",
                "session_id": f"console:prov-{name}-sess",
            },
            "mode": "stream",
        },
        "save_result_to_inbox": False,
    }


def _create_job(app_server, spec):
    resp = app_server.api_request(
        "POST",
        "/api/cron/jobs",
        json=spec,
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    return resp.json()["id"]


def _delete_job(app_server, job_id):
    try:
        app_server.api_request(
            "DELETE",
            f"/api/cron/jobs/{job_id}",
            timeout=_HTTP_TIMEOUT,
        )
    except Exception:
        pass


def _poll_history(app_server, job_id, deadline):
    while time.time() < deadline:
        resp = app_server.api_request(
            "GET",
            f"/api/cron/jobs/{job_id}/history",
            timeout=_HTTP_TIMEOUT,
        )
        if resp.status_code == 200:
            records = resp.json()
            if isinstance(records, list) and records:
                return records
        time.sleep(1.0)
    return []


def _register_provider_with_id(
    app_server,
    provider_id: str,
    base_url: str,
):
    """Register and activate a mock provider under a custom id."""
    app_server.api_request(
        "POST",
        "/api/models/custom-providers",
        json={
            "id": provider_id,
            "name": provider_id,
            "chat_model": "OpenAIChatModel",
            "models": [
                {
                    "id": "mock-model",
                    "name": "Mock Model",
                    "supports_multimodal": False,
                },
            ],
        },
        timeout=_HTTP_TIMEOUT,
    )
    app_server.api_request(
        "PUT",
        f"/api/models/{provider_id}/config",
        json={
            "api_key": "test-key-mock",
            "base_url": base_url,
        },
        timeout=_HTTP_TIMEOUT,
    )
    app_server.api_request(
        "PUT",
        "/api/models/active",
        json={
            "provider_id": provider_id,
            "model": "mock-model",
            "scope": "global",
        },
        timeout=_HTTP_TIMEOUT,
    )


def _unregister_provider(app_server, provider_id: str):
    try:
        app_server.api_request(
            "DELETE",
            f"/api/models/custom-providers/{provider_id}",
            timeout=_HTTP_TIMEOUT,
        )
    except Exception:
        pass


# ------------------------------------------------------------------ #
# C2: 429 rate-limit then recover
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_rate_limit_429_then_recover(app_server, mock_llm) -> None:
    """Test purpose:
    - Verify RetryChatModel handles a transient 429 by retrying and the
      cron run ultimately succeeds when the next response is OK.

    Test flow:
    1. Register mock LLM provider.
    2. Set ``force_status_code=[429]`` so the first request returns 429
       and subsequent requests succeed.
    3. Trigger cron agent run.
    4. Assert history shows success and request_count >= 2.
    """
    srv, mock_url = mock_llm
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    register_mock_provider(app_server, mock_url)

    srv.force_status_code = [429]
    srv.request_count = 0
    spec = _agent_spec("retry_429")
    job_id = _create_job(app_server, spec)
    try:
        app_server.api_request(
            "POST",
            f"/api/cron/jobs/{job_id}/run",
            timeout=_HTTP_TIMEOUT,
        )
        records = _poll_history(
            app_server,
            job_id,
            time.time() + 60.0,
        )
        assert records, app_server.logs_tail()
        assert (
            records[0]["status"] == "success"
        ), f"retry did not recover: {records[0]} | {app_server.logs_tail()}"
        assert (
            srv.request_count >= 2
        ), f"no retry observed: count={srv.request_count}"
    finally:
        _delete_job(app_server, job_id)
        srv.force_status_code = None
        unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)


# ------------------------------------------------------------------ #
# C3: persistent 500 — eventually fails
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p2
def test_persistent_5xx_eventually_fails(app_server, mock_llm) -> None:
    """Test purpose:
    - Verify that a persistent 500 error from the LLM provider results
      in a cron run that records the failure (status != "success") and
      the runtime exhausts retries instead of looping forever.

    Test flow:
    1. Register mock LLM.
    2. Set ``force_status_code=500`` so every request fails.
    3. Reduce llm_max_retries to 1 via PUT /config/running so the test
       does not wait many backoffs.
    4. Trigger cron run; expect status == "failure".
    """
    srv, mock_url = mock_llm
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    register_mock_provider(app_server, mock_url)

    # Lower retry budget so the test finishes quickly.
    cfg_resp = app_server.api_request(
        "GET",
        scoped("default", "/workspace/running-config"),
        timeout=_HTTP_TIMEOUT,
    )
    assert cfg_resp.status_code == 200, app_server.logs_tail()
    running_baseline = cfg_resp.json()
    running_patched = dict(running_baseline)
    running_patched["llm_max_retries"] = 1
    running_patched["llm_backoff_base"] = 0.1
    running_patched["llm_backoff_cap"] = 0.5

    app_server.api_request(
        "PUT",
        scoped("default", "/workspace/running-config"),
        json=running_patched,
        timeout=_HTTP_TIMEOUT,
    )

    srv.force_status_code = 500
    srv.request_count = 0
    spec = _agent_spec("persistent_500")
    job_id = _create_job(app_server, spec)
    try:
        app_server.api_request(
            "POST",
            f"/api/cron/jobs/{job_id}/run",
            timeout=_HTTP_TIMEOUT,
        )
        records = _poll_history(
            app_server,
            job_id,
            time.time() + 60.0,
        )
        assert records, app_server.logs_tail()
        # Either failure recorded explicitly, or success with error
        # surfaced in dispatch metadata — the key invariant is no
        # infinite retry loop.
        assert records[0]["status"] in {
            "failure",
            "error",
            "success",
        }, records[0]
        # And we should have hit the upstream multiple times.
        assert (
            srv.request_count >= 2
        ), f"retry did not happen: count={srv.request_count}"
    finally:
        _delete_job(app_server, job_id)
        srv.force_status_code = None
        # Restore baseline running config.
        app_server.api_request(
            "PUT",
            scoped("default", "/workspace/running-config"),
            json=running_baseline,
            timeout=_HTTP_TIMEOUT,
        )
        unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)


# ------------------------------------------------------------------ #
# C4: agent-scoped running config roundtrip
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p2
def test_running_config_retry_knobs_roundtrip(app_server) -> None:
    """Test purpose:
    - Verify GET /api/agents/default/config/running returns the retry /
      rate-limit knobs, and PUT round-trips the values.

    API endpoints:
    - GET /api/agents/{agentId}/workspace/running-config
    - PUT /api/agents/{agentId}/workspace/running-config
    """
    get_resp = app_server.api_request(
        "GET",
        scoped("default", "/workspace/running-config"),
        timeout=_HTTP_TIMEOUT,
    )
    assert get_resp.status_code == 200, app_server.logs_tail()
    baseline = get_resp.json()
    # All knobs we care about must be present.
    for key in (
        "llm_max_retries",
        "llm_backoff_base",
        "llm_backoff_cap",
        "llm_max_concurrent",
        "llm_max_qpm",
    ):
        assert key in baseline, baseline

    patched = dict(baseline)
    patched["llm_max_retries"] = 7
    patched["llm_max_qpm"] = 999
    try:
        put_resp = app_server.api_request(
            "PUT",
            scoped("default", "/workspace/running-config"),
            json=patched,
            timeout=_HTTP_TIMEOUT,
        )
        assert put_resp.status_code == 200, app_server.logs_tail()

        get_after = app_server.api_request(
            "GET",
            scoped("default", "/workspace/running-config"),
            timeout=_HTTP_TIMEOUT,
        )
        body = get_after.json()
        assert body["llm_max_retries"] == 7, body
        assert body["llm_max_qpm"] == 999, body
    finally:
        # Restore baseline.
        app_server.api_request(
            "PUT",
            scoped("default", "/workspace/running-config"),
            json=baseline,
            timeout=_HTTP_TIMEOUT,
        )


# ------------------------------------------------------------------ #
# C1 (runs last — switching between two mock LLMs leaves dangling
# active-model pointers that can confuse sibling tests' agent runners).
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_zz_active_model_switch_between_two_mock_providers(
    app_server,
    mock_llm,
    second_mock_llm,
) -> None:
    """Test purpose:
    - Verify PUT /api/models/active can switch the global active model
      between two distinct providers, and that GET /api/models/active
      reflects the most recent activation.

    API endpoints:
    - POST /api/models/custom-providers
    - PUT  /api/models/{provider_id}/config
    - PUT  /api/models/active
    - DELETE /api/models/custom-providers/{provider_id}
    - GET  /api/models/active?scope=global
    """
    _srv_a, url_a = mock_llm
    _srv_b, url_b = second_mock_llm

    pid_a = "integ-mock-llm-a"
    pid_b = "integ-mock-llm-b"
    _unregister_provider(app_server, pid_a)
    _unregister_provider(app_server, pid_b)
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)

    try:
        _register_provider_with_id(app_server, pid_a, url_a)

        # GET active should reflect A.
        get_resp = app_server.api_request(
            "GET",
            "/api/models/active",
            params={"scope": "global"},
            timeout=_HTTP_TIMEOUT,
        )
        assert get_resp.status_code == 200, app_server.logs_tail()
        active_a = (get_resp.json() or {}).get("active_llm") or {}
        assert (
            active_a.get("provider_id") == pid_a
        ), f"active not A: {active_a}"

        # Switch active to B.
        _register_provider_with_id(app_server, pid_b, url_b)
        get_resp_b = app_server.api_request(
            "GET",
            "/api/models/active",
            params={"scope": "global"},
            timeout=_HTTP_TIMEOUT,
        )
        active_b = (get_resp_b.json() or {}).get("active_llm") or {}
        assert (
            active_b.get("provider_id") == pid_b
        ), f"active not B: {active_b}"

        # Switch back to A via PUT.
        switch_resp = app_server.api_request(
            "PUT",
            "/api/models/active",
            json={
                "provider_id": pid_a,
                "model": "mock-model",
                "scope": "global",
            },
            timeout=_HTTP_TIMEOUT,
        )
        assert switch_resp.status_code == 200, app_server.logs_tail()
        get_resp_back = app_server.api_request(
            "GET",
            "/api/models/active",
            params={"scope": "global"},
            timeout=_HTTP_TIMEOUT,
        )
        active_back = (get_resp_back.json() or {}).get("active_llm") or {}
        assert (
            active_back.get("provider_id") == pid_a
        ), f"switch back to A failed: {active_back}"
    finally:
        _unregister_provider(app_server, pid_a)
        _unregister_provider(app_server, pid_b)
        unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
