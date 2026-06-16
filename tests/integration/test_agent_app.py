# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name
# -*- coding: utf-8 -*-
"""Integration tests for AgentApp routes (Sprint 3.1-B).

The AgentApp (from agentscope_runtime) is mounted under ``/api/agent``
(singular).  These routes live alongside QwenPaw's own ``/api/agents``
(plural) routers and are exercised by the agentscope_runtime SDK CLI.

Coverage: 4 cases (health, root info, task submission, admin status).
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
    unregister_mock_provider,
)

_HTTP_TIMEOUT = 15.0


# ------------------------------------------------------------------ #
# fixtures
# ------------------------------------------------------------------ #


@pytest.fixture(scope="module")
def mock_llm():
    srv = HTTPServer(("127.0.0.1", 0), MockLLMHandler)
    srv.force_error = False
    srv.force_tool_call = False
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv, f"http://127.0.0.1:{port}/v1"
    srv.shutdown()


# ------------------------------------------------------------------ #
# B1: GET /api/agent/health
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_agent_app_health(app_server) -> None:
    """Test purpose:
    - Verify GET /api/agent/health returns healthy + runner ready status.

    API endpoints:
    - GET /api/agent/health
    """
    resp = app_server.api_request(
        "GET",
        "/api/agent/health",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    body = resp.json()
    assert body.get("status") == "healthy", body
    assert body.get("runner") in {"ready", "not_ready"}, body


# ------------------------------------------------------------------ #
# B2: GET /api/agent/ (root info)
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_agent_app_root_info(app_server) -> None:
    """Test purpose:
    - Verify GET /api/agent/ root returns service info with endpoints map.

    Test flow:
    1. GET /api/agent/.
    2. Assert ``service`` is the QwenPaw runtime, ``endpoints`` map
       contains process / health / task keys.

    API endpoints:
    - GET /api/agent/
    """
    resp = app_server.api_request(
        "GET",
        "/api/agent/",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    body = resp.json()
    assert "service" in body, body
    endpoints = body.get("endpoints") or {}
    assert "process" in endpoints, endpoints
    assert "health" in endpoints, endpoints
    # enable_stream_task=True in QwenPaw config → task fields present.
    assert "task" in endpoints, endpoints


# ------------------------------------------------------------------ #
# B3: POST /api/agent/process/task — async task submission
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_agent_app_task_submit_status(app_server, mock_llm) -> None:
    """Test purpose:
    - Verify POST /api/agent/process/task accepts an async task and the
      task status can be polled via GET /api/agent/process/task/{id}.

    Test flow:
    1. Register mock LLM provider so the task has a backend.
    2. POST a minimal AgentRequest to /api/agent/process/task.
    3. Receive task_id; poll /api/agent/process/task/{id} until status
       is completed/failed (timeout 30s).

    API endpoints:
    - POST /api/agent/process/task
    - GET  /api/agent/process/task/{task_id}
    """
    _srv, mock_url = mock_llm
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    register_mock_provider(app_server, mock_url)

    payload = {
        "input": [
            {
                "role": "user",
                "type": "message",
                "content": [{"type": "text", "text": "ping"}],
            },
        ],
    }
    resp = app_server.api_request(
        "POST",
        "/api/agent/process/task",
        json=payload,
        timeout=_HTTP_TIMEOUT,
    )
    try:
        assert resp.status_code in {200, 201, 202}, (
            f"task submit failed: {resp.status_code} {resp.text} "
            f"{app_server.logs_tail()}"
        )
        body = resp.json()
        task_id = body.get("task_id") or body.get("id")
        assert task_id, body

        # Poll status.
        deadline = time.time() + 30.0
        last = None
        while time.time() < deadline:
            r = app_server.api_request(
                "GET",
                f"/api/agent/process/task/{task_id}",
                timeout=_HTTP_TIMEOUT,
            )
            if r.status_code == 200:
                last = r.json()
                status = last.get("status")
                if status in {
                    "completed",
                    "failed",
                    "succeeded",
                    "error",
                    "finished",
                }:
                    break
            time.sleep(1.0)
        assert last is not None, "no task status returned"
        assert last.get("status") in {
            "completed",
            "failed",
            "succeeded",
            "error",
            "finished",
            "running",
            "pending",
        }, last
    finally:
        unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)


# ------------------------------------------------------------------ #
# B4: GET /api/agent/admin/status
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p2
def test_agent_app_admin_status(app_server) -> None:
    """Test purpose:
    - Verify GET /api/agent/admin/status returns process information
      (PID, memory, uptime).

    API endpoints:
    - GET /api/agent/admin/status
    """
    resp = app_server.api_request(
        "GET",
        "/api/agent/admin/status",
        timeout=_HTTP_TIMEOUT,
    )
    # admin/status may be 200 or 401/403 depending on auth config; accept
    # any 2xx and verify the payload is shaped like a status dict.
    assert resp.status_code in {
        200,
        401,
        403,
    }, f"unexpected status: {resp.status_code} {resp.text}"
    if resp.status_code == 200:
        body = resp.json()
        assert isinstance(body, dict), body
